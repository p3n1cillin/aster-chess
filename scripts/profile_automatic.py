"""Collect the fixed unchanged-engine diagnostic; never optimize or repeat runs."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pe_metadata(path):
    data = Path(path).read_bytes()
    header = struct.unpack_from('<I', data, 0x3c)[0]
    optional = header + 24
    assert data[header:header + 4] == b'PE\0\0'
    assert struct.unpack_from('<H', data, optional)[0] == 0x20b
    base = struct.unpack_from('<Q', data, optional + 24)[0]
    size = struct.unpack_from('<I', data, optional + 56)[0]
    count = struct.unpack_from('<H', data, header + 6)[0]
    opt_size = struct.unpack_from('<H', data, header + 20)[0]
    sections = []
    for index in range(count):
        at = optional + opt_size + index * 40
        virtual_size, rva, raw_size, offset = struct.unpack_from('<IIII', data, at + 8)
        sections.append({'name': data[at:at + 8].rstrip(b'\0').decode('ascii'),
                         'rva': rva, 'virtual_size': virtual_size, 'raw_size': raw_size, 'offset': offset})
    debug_rva, debug_size = struct.unpack_from('<II', data, optional + 112 + 6 * 8)
    codeview = None
    for section in sections:
        if section['rva'] <= debug_rva < section['rva'] + max(section['virtual_size'], section['raw_size']):
            start = section['offset'] + debug_rva - section['rva']
            for at in range(start, start + debug_size, 28):
                kind = struct.unpack_from('<I', data, at + 12)[0]
                length, _, pointer = struct.unpack_from('<III', data, at + 16)
                if kind == 2 and data[pointer:pointer + 4] == b'RSDS':
                    codeview = {'guid': str(uuid.UUID(bytes_le=data[pointer + 4:pointer + 20])),
                                'age': struct.unpack_from('<I', data, pointer + 20)[0],
                                'pdb': data[pointer + 24:pointer + length].split(b'\0')[0].decode('utf-8')}
    return {'preferred_base': base, 'image_size': size, 'sections': sections, 'codeview': codeview}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True)
    parser.add_argument('--directory', required=True)
    parser.add_argument('--runs-directory', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    plan_path, stage, runs, output = [Path(p).resolve() for p in
                                    [args.plan, args.directory, args.runs_directory, args.output]]
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    if stage.exists() or runs.exists() or output.exists():
        raise ValueError('Preserve prior attempts; use fresh declared collection paths')
    for entry in plan['playing_inputs']:
        assert digest(ROOT / entry['path']) == entry['sha256'], entry['path']
    for workload in plan['workloads'].values():
        if 'input' in workload:
            assert digest(ROOT / workload['input']) == workload['input_sha256']
            assert digest(ROOT / workload['parent']) == workload['parent_sha256']
    for tool in plan['tools'].values():
        assert digest(tool['path']) == tool['sha256']
    cargo = shutil.which('cargo') or str(Path.home() / '.cargo/bin/cargo.exe')
    rustc = shutil.which('rustc') or str(Path.home() / '.cargo/bin/rustc.exe')
    compiler = subprocess.check_output([rustc, '-Vv'], cwd=ROOT, encoding='utf-8').strip()
    assert compiler.startswith('rustc ' + plan['build']['rust'] + ' ')
    assert '\nhost: ' + plan['build']['host'] in compiler
    production = ROOT / 'target/release/aster.exe'
    assert digest(production) == plan['production_sha256']
    stage.mkdir(parents=True)
    runs.mkdir(parents=True)
    report = {'status': 'building', 'created_utc': datetime.now(timezone.utc).isoformat(),
              'pid': os.getpid(), 'plan': str(plan_path), 'plan_sha256': digest(plan_path),
              'collector_sha256': digest(__file__), 'compiler': compiler,
              'binaries': {'production': {'path': str(production), 'sha256': digest(production)}},
              'builds': [], 'runs': [], 'normalized_reference': {}}

    def save():
        output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')

    def execute(argv, directory, env, stdout, stderr, timeout):
        start = time.perf_counter_ns()
        with stdout.open('x', encoding='utf-8') as out, stderr.open('x', encoding='utf-8') as err:
            process = subprocess.Popen(argv, cwd=directory, env=env, stdout=out, stderr=err)
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
                process.wait(timeout=15)
                raise
        elapsed = time.perf_counter_ns() - start
        if code:
            raise RuntimeError(f'Process exited {code}; inspect {stdout} and {stderr}')
        return elapsed

    env = os.environ.copy()
    for name in ['ASTER_SIMD', 'RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'LLVM_PROFILE_FILE']:
        env.pop(name, None)
    save()
    try:
        for role, features in plan['build']['features'].items():
            folder = stage / role
            folder.mkdir()
            map_file = folder / 'link.map'
            build_env = env.copy()
            build_env.update(plan['build']['environment'])
            build_env['CARGO_TARGET_DIR'] = str(stage / 'target')
            build_env['CARGO_ENCODED_RUSTFLAGS'] = '\x1f'.join(plan['build']['flags'] + ['-C', 'link-arg=/MAP:' + str(map_file)])
            command = [cargo, *plan['build']['cargo'], '--features', ','.join(features)]
            stdout, stderr = folder / 'build.stdout.txt', folder / 'build.stderr.txt'
            execute(command, ROOT, build_env, stdout, stderr, plan['resources']['build_timeout_seconds'])
            release = stage / 'target' / plan['build']['host'] / 'release'
            binary = folder / 'aster-core.exe'
            shutil.copy2(release / binary.name, binary)
            metadata = pe_metadata(binary)
            cv = metadata['codeview']
            assert cv, 'No CodeView/PDB metadata; preserve this attempt'
            pdb_source = Path(cv['pdb'])
            if not pdb_source.is_file():
                choices = [release / pdb_source.name, release / 'deps' / pdb_source.name]
                pdb_source = next((p for p in choices if p.is_file()), pdb_source)
            assert pdb_source.is_file(), cv
            pdb = folder / pdb_source.name
            shutil.copy2(pdb_source, pdb)
            summary = subprocess.check_output([plan['tools']['llvm-pdbutil']['path'], 'dump', '--summary', str(pdb)], encoding='utf-8')
            (folder / 'pdb-summary.txt').write_text(summary, encoding='utf-8')
            assert cv['guid'].lower() in summary.lower(), 'PDB GUID mismatch'
            assert map_file.is_file()
            report['binaries'][role] = {'path': str(binary), 'sha256': digest(binary), 'features': features,
                'pdb': str(pdb), 'pdb_sha256': digest(pdb), 'map': str(map_file), 'map_sha256': digest(map_file), 'pe': metadata}
            report['builds'].append({'role': role, 'command': command,
                'environment': {k: build_env[k] for k in ['CARGO_TARGET_DIR', 'CARGO_ENCODED_RUSTFLAGS', *plan['build']['environment']]},
                'stdout_sha256': digest(stdout), 'stderr_sha256': digest(stderr)})
            save()
            print(json.dumps({'built': role, 'sha256': digest(binary)}), flush=True)
        report['status'] = 'collecting'
        save()
        for ordinal, specification in enumerate(plan['schedule']):
            role, workload_name = specification['role'], specification['workload']
            workload = plan['workloads'][workload_name]
            folder = runs / f'{ordinal:02}-{workload_name}-r{specification["repetition"]}-{role}'
            folder.mkdir()
            command = [report['binaries'][role]['path']]
            if role == 'production':
                command.append('core')
            command += workload['args']
            stdout, stderr = folder / 'stdout.txt', folder / 'stderr.txt'
            elapsed = execute(command, folder, env, stdout, stderr, plan['resources']['per_process_timeout_seconds'])
            out, err = stdout.read_text(encoding='utf-8'), stderr.read_text(encoding='utf-8')
            normalized = [re.sub(r'\b(nps|time) \d+', r'\1 <timing>', line) for line in out.splitlines()
                          if line.startswith(('info depth ', 'bestmove '))]
            reference = report['normalized_reference'].setdefault(workload_name, normalized)
            nodes = int(re.search(r'Nodes searched\s*:\s*(\d+)', err)[1])
            bench_ms = int(re.search(r'Total time \(ms\)\s*:\s*(\d+)', err)[1])
            detail = dict(specification, ordinal=ordinal, command=command, wall_ns=elapsed, bench_ms=bench_ms,
                          nodes=nodes, exact=normalized == reference, folder=str(folder),
                          stdout_sha256=digest(stdout), stderr_sha256=digest(stderr))
            report['runs'].append(detail)
            save()
            assert detail['exact'] and bench_ms > 0
            assert sum(line.startswith('bestmove ') for line in normalized) == workload['searches']
            if 'expected_nodes' in workload:
                assert nodes == workload['expected_nodes']
            if role == 'counters':
                detail['counters'] = {name: {'ticks': int(ticks), 'calls': int(calls)} for name, ticks, calls in
                    re.findall(r'^\s*([\w+]+):\s+(\d+) cycles\s+(\d+) calls', err, re.M)}
                assert len(detail['counters']) == 11 and detail['counters']['total_eval']['calls'] > 0
            if role == 'sampler':
                for name in ['samples.txt', 'callers.txt']:
                    path = folder / name
                    assert path.is_file()
                    detail[name] = {'path': str(path), 'sha256': digest(path)}
                detail['outside_samples'] = int(re.search(r'sampler: (\d+) samples outside the executable', err)[1])
                detail['raw_pc_samples'] = sum(bool(line.strip()) for line in (folder / 'samples.txt').read_text().splitlines())
                assert detail['raw_pc_samples'] >= 100
            save()
            print(json.dumps({'collected': ordinal + 1, 'of': len(plan['schedule']), 'role': role, 'workload': workload_name}), flush=True)
        assert [{k: run[k] for k in ['workload', 'repetition', 'role']} for run in report['runs']] == plan['schedule']
        assert digest(production) == plan['production_sha256']
        report.update(status='collected', completed_utc=datetime.now(timezone.utc).isoformat(),
                      production_unchanged=True, limits=plan['gates']['limits'])
        save()
    except BaseException as error:
        report.update(status='failed', error=str(error), failed_utc=datetime.now(timezone.utc).isoformat())
        save()
        raise


if __name__ == '__main__':
    main()
