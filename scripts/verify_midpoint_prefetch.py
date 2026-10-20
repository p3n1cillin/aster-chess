"""Run the declared pre-timing gates once against a frozen prefetch candidate."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-report', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    assert not output.exists(), 'Preserve prior gate attempts'
    build = json.loads(Path(args.build_report).read_text(encoding='utf-8'))
    assert build['status'] == 'built_unqualified'
    plan = json.loads((ROOT / 'artifacts/research/aster-midpoint-prefetch-plan-v1.json').read_text(encoding='utf-8'))
    assert build['plan_sha256'] == digest(ROOT / 'artifacts/research/aster-midpoint-prefetch-plan-v1.json')
    for role, folder in [('control', 'aster-midpoint-prefetch-control-source-v1'), ('candidate', 'aster-midpoint-prefetch-source-v1')]:
        binary = build['binaries'][role]
        assert digest(binary['path']) == binary['sha256']
        source = ROOT / 'artifacts/research' / folder
        manifest = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
        assert manifest['binary_sha256'] == binary['sha256']
        for entry in manifest['source_files']:
            assert digest(source / entry['path']) == entry['sha256']
    logs = output.with_suffix('')
    logs.mkdir()
    report = dict(status='running', passed=False, created_utc=datetime.now(timezone.utc).isoformat(),
                  pid=os.getpid(), build_report_sha256=digest(args.build_report),
                  checker_sha256=digest(__file__), steps=[], active_step=None)

    def save():
        output.write_bytes((json.dumps(report, indent=2) + '\n').encode('utf-8'))

    env = os.environ.copy()
    for key in ['ASTER_SIMD', 'RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'LLVM_PROFILE_FILE', 'CARGO_PROFILE_RELEASE_DEBUG', 'CARGO_PROFILE_RELEASE_STRIP']:
        env.pop(key, None)
    env['CARGO_TARGET_DIR'] = str(ROOT / '.aster-local/midpoint-prefetch-v1/target')

    def run(label, command, mode='auto', timeout=900):
        local = env.copy()
        if mode != 'auto':
            local['ASTER_SIMD'] = mode
        log = logs / (label + '.log')
        report['active_step'] = dict(label=label, command=command, mode=mode)
        save()
        with log.open('xb') as stream:
            result = subprocess.run(command, cwd=ROOT, env=local, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=timeout)
        report['steps'].append(dict(label=label, command=command, mode=mode,
                                    exit_code=result.returncode, log=str(log), log_sha256=digest(log)))
        save()
        assert result.returncode == 0, label
        print(json.dumps(dict(completed=label)), flush=True)

    python, cargo = sys.executable, str(Path.home() / '.cargo/bin/cargo.exe')
    candidate, control = [build['binaries'][r]['path'] for r in ['candidate', 'control']]
    prefix = 'artifacts/verification/aster-midpoint-prefetch-'
    save()
    try:
        for script in ['verify_source_names', 'fetch_rust_network', 'fetch_aster_network']:
            run(script, [python, 'scripts/' + script + '.py'])
        run('format', [cargo, 'fmt', '--all', '--check'])
        for feature in [True, False]:
            for release in [True, False]:
                command = [cargo, 'test', '--workspace', '--locked']
                if release:
                    command.append('--release')
                if feature:
                    command += ['--features', 'midpoint-prefetch']
                run(('feature' if feature else 'default') + ('-release' if release else '-debug'), command)
        run('runtime', [python, 'scripts/verify_fused_input_runtime.py', '--build-report', args.build_report,
                        '--output', prefix + 'runtime-v1.json'])
        for mode in ['auto', 'avx2', 'scalar']:
            run('equivalence-' + mode, [python, 'scripts/verify_rust_equivalence.py', '--candidate', candidate,
                                       '--baseline', control, '--suite', plan['validation']['parent'],
                                       '--output', prefix + 'equivalence-' + mode + '-v1.json'], mode)
        for suite in plan['validation']['tactics_suites']:
            baseline = f'artifacts/tactics/aster-midpoint-prefetch-control-{suite}.json'
            run('tactics-control-' + suite, [python, 'scripts/tactics.py', 'tests/fixtures/' + suite + '.json',
                                           '--engine', control, '--nodes', '20000', '--output', baseline])
            for mode in ['auto', 'avx2', 'scalar']:
                run('tactics-' + mode + '-' + suite, [python, 'scripts/tactics.py', 'tests/fixtures/' + suite + '.json',
                    '--engine', candidate, '--nodes', '20000', '--reference-report', baseline,
                    '--output', f'artifacts/tactics/aster-midpoint-prefetch-{mode}-{suite}.json'], mode)
        for name, script, extra in [('rules', 'verify.py', ['--setups', '1000']),
                                     ('edges', 'verify_rust_legal_edges.py', []),
                                     ('play', 'smoke_rust_play.py', []),
                                     ('proofs', 'smoke_mate_proof.py', [])]:
            run(name, [python, 'scripts/' + script, '--engine', candidate, '--output', prefix + name + '-v1.json', *extra])
        run('bench7', [candidate, 'bench', '7'])
        for binary in build['binaries'].values():
            assert digest(binary['path']) == binary['sha256']
        report.update(status='passed', passed=True, active_step=None,
                      completed_utc=datetime.now(timezone.utc).isoformat())
        save()
    except BaseException as error:
        report.update(status='failed', error=str(error), failed_utc=datetime.now(timezone.utc).isoformat())
        save()
        raise


if __name__ == '__main__':
    main()
