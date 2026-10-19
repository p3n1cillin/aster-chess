"""Build one fixed Rust PGO experiment, preserving controls, profiles and logs."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import chess
import chess.engine

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True)
    parser.add_argument('--directory', required=True)
    parser.add_argument('--profile-directory', required=True)
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    plan_path = Path(args.plan).resolve()
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    stage, profiles, report_path = map(lambda p: Path(p).resolve(),
                                      [args.directory, args.profile_directory, args.report])
    if stage.exists() or profiles.exists() or report_path.exists():
        raise ValueError('Use fresh staging, profile and report paths; preserve previous evidence')
    cargo = shutil.which('cargo') or str(Path.home() / '.cargo/bin/cargo.exe')
    rustc = shutil.which('rustc') or str(Path.home() / '.cargo/bin/rustc.exe')
    compiler = subprocess.check_output([rustc, '-Vv'], cwd=ROOT, encoding='utf-8').strip()
    host = re.search(r'^host: (.+)$', compiler, re.M)[1]
    if host != plan['build']['host'] or not compiler.startswith('rustc ' + plan['build']['toolchain'] + ' '):
        raise ValueError('This experiment is pinned to its declared compiler and host')
    sysroot = Path(subprocess.check_output([rustc, '--print', 'sysroot'], cwd=ROOT, encoding='utf-8').strip())
    extension = '.exe' if os.name == 'nt' else ''
    profdata = sysroot / 'lib/rustlib' / host / ('bin/llvm-profdata' + extension)
    if not profdata.is_file():
        raise FileNotFoundError('Install the matching Rust llvm-tools component first')
    for entry in plan['playing_inputs']:
        if digest(ROOT / entry['path']) != entry['sha256']:
            raise ValueError('Playing/build input changed: ' + entry['path'])
    training = ROOT / plan['training']['suite']
    if digest(training) != plan['training']['suite_sha256']:
        raise ValueError('Frozen training suite changed')
    stage.mkdir(parents=True)
    profiles.mkdir(parents=True)
    raw = profiles / 'raw'
    raw.mkdir()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {'status': 'running', 'created_utc': datetime.now(timezone.utc).isoformat(),
              'plan': str(plan_path), 'plan_sha256': digest(plan_path), 'compiler': compiler,
              'llvm_profdata': str(profdata), 'llvm_profdata_sha256': digest(profdata),
              'builder_sha256': digest(__file__), 'stage': str(stage), 'steps': [], 'binaries': {}}

    def save():
        report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')

    save()
    env = os.environ.copy()
    for name in ['RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'LLVM_PROFILE_FILE', 'ASTER_SIMD']:
        env.pop(name, None)
    env['CARGO_TARGET_DIR'] = str(stage / 'target')
    base_flags = plan['build']['flags']
    target = plan['build']['target']

    def step(label, argv, child_env):
        log = report_path.with_name(report_path.stem + '-' + label + '.log')
        detail = {'label': label, 'argv': [str(a) for a in argv], 'log': str(log),
                  'environment': {key: child_env[key] for key in ['CARGO_TARGET_DIR', 'CARGO_ENCODED_RUSTFLAGS', 'LLVM_PROFILE_FILE', 'ASTER_SIMD'] if key in child_env}}
        report['steps'].append(detail)
        save()
        with log.open('x', encoding='utf-8') as stream:
            result = subprocess.run(argv, cwd=ROOT, env=child_env, stdout=stream, stderr=subprocess.STDOUT)
        detail.update(exit_code=result.returncode, log_sha256=digest(log))
        save()
        if result.returncode:
            raise RuntimeError(f'{label} failed ({result.returncode}); see {log}')
        print(json.dumps({'completed': label}), flush=True)
        return log

    def build(label, extra):
        child_env = env.copy()
        flags = base_flags + extra
        child_env['CARGO_ENCODED_RUSTFLAGS'] = '\x1f'.join(flags)
        step('build-' + label, [cargo, *plan['build']['cargo']], child_env)
        folder = stage / label
        folder.mkdir()
        for binary in ['aster', 'aster-core', 'aster-pgo-trainer']:
            shutil.copy2(stage / 'target' / target / 'release' / (binary + extension), folder / (binary + extension))
        binary = folder / ('aster' + extension)
        report['binaries'][label] = {'path': str(binary), 'sha256': digest(binary), 'rustflags': flags}
        driver = folder / ('aster-pgo-trainer' + extension)
        report['binaries'][label]['training_driver'] = {'path': str(driver), 'sha256': digest(driver)}
        save()
        return binary, child_env

    try:
        control, _ = build('control', [])
        log = step('control-signature', [str(control), 'core', 'bench'], env)
        assert re.search(r'Nodes searched\s*:\s*1559611\b', log.read_text(encoding='utf-8'))
        instrumented, instrument_env = build('instrumented', ['-C', 'profile-generate=' + str(raw)])
        driver = Path(report['binaries']['instrumented']['training_driver']['path'])
        instrument_env['LLVM_PROFILE_FILE'] = str(raw / '%p-%m.profraw')
        for mode, repeats in plan['training']['bench_repeats'].items():
            child_env = instrument_env.copy()
            if mode != 'auto':
                child_env['ASTER_SIMD'] = mode
            for index in range(repeats):
                log = step(f'train-bench-{mode}-{index}', [str(driver), 'core', 'bench'], child_env)
                assert re.search(r'Nodes searched\s*:\s*1559611\b', log.read_text(encoding='utf-8'))
        positions = json.loads(training.read_text(encoding='utf-8'))['openings']
        assert len(positions) == plan['training']['roots']
        observations = []
        with chess.engine.SimpleEngine.popen_uci([str(driver)], env=instrument_env, timeout=120) as engine:
            engine.configure({'Threads': plan['training']['threads'], 'Hash': plan['training']['hash_mib']})
            for entry in positions:
                board = chess.Board()
                for move in entry['moves'].split():
                    board.push_uci(move)
                result = engine.play(board, chess.engine.Limit(depth=plan['training']['depth']), game=object(), info=chess.engine.INFO_ALL)
                assert result.move in board.legal_moves
                replay = board.copy()
                for move in result.info.get('pv', []):
                    assert move in replay.legal_moves
                    replay.push(move)
                observations.append({'id': entry['id'], 'bestmove': result.move.uci(), 'nodes': result.info['nodes'],
                                     'depth': result.info['depth'], 'pv': [m.uci() for m in result.info.get('pv', [])]})
        report['training_roots'] = observations
        save()
        for script in plan['training']['auxiliary']:
            name = Path(script).stem
            step('train-' + name, [sys.executable, script, '--engine', str(instrumented), '--output',
                                  str(report_path.with_name(report_path.stem + '-train-' + name + '.json'))], instrument_env)
        files = sorted(raw.glob('*.profraw'))
        if not files:
            raise ValueError('Instrumented workloads produced no raw profiles')
        report['raw_profiles'] = [{'path': str(p), 'bytes': p.stat().st_size, 'sha256': digest(p)} for p in files]
        merged = profiles / 'merged.profdata'
        step('merge-profile', [str(profdata), 'merge', '-o', str(merged), *map(str, files)], env)
        report['merged_profile'] = {'path': str(merged), 'bytes': merged.stat().st_size, 'sha256': digest(merged)}
        coverage_log = step('profile-coverage', [str(profdata), 'show', '--all-functions', '--counts', str(merged)], env)
        categories = {'main_search': '6Worker6search', 'quiescence': '6Worker7qsearch', 'evaluation': '7Network8evaluate'}
        coverage = {category: 0 for category in categories}
        for block in re.split(r'(?m)^  (?=\S)', coverage_log.read_text(encoding='utf-8')):
            name = block.splitlines()[0] if block.splitlines() else ''
            counts = re.search(r'Block counts: \[([^\]]*)\]', block)
            if '10aster_core' not in name or not counts:
                continue
            maximum = max((int(v.strip()) for v in counts[1].split(',') if v.strip()), default=0)
            for category, marker in categories.items():
                if marker in name:
                    coverage[category] = max(coverage[category], maximum)
        report['search_profile_coverage'] = coverage
        save()
        if not all(value > 0 for value in coverage.values()):
            raise ValueError('Profile is missing actual search/evaluation counters; do not compile an optimized candidate')
        optimized, optimized_env = build('optimized', ['-C', 'profile-use=' + str(merged), '-C', 'llvm-args=-pgo-warn-missing-function'])
        report.update(status='built_unqualified', completed_utc=datetime.now(timezone.utc).isoformat(),
                      optimized_build_command=[cargo, *plan['build']['cargo']],
                      optimized_build_environment={key: optimized_env[key] for key in ['CARGO_TARGET_DIR', 'CARGO_ENCODED_RUSTFLAGS']},
                      binary_sha256=digest(optimized),
                      interpretation='Build/training completed, not an adoption or speed/strength result. Test only on the separately frozen fresh roots. Ordinary builds remain available.')
        save()
        print(json.dumps({'status': report['status'], 'control': report['binaries']['control'],
                          'optimized': report['binaries']['optimized'], 'raw_profiles': len(files)}), flush=True)
    except BaseException as error:
        report.update(status='failed', error=str(error))
        save()
        raise


if __name__ == '__main__':
    main()
