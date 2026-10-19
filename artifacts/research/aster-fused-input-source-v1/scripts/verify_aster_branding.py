"""Check Aster identity, deterministic core behavior and counterbalanced bench time."""
from research_reference import research_text
import argparse
import hashlib
import json
import os
import pathlib
import re
import statistics
import subprocess
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXE = '.exe' if os.name == 'nt' else ''


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bench(binary, output, label):
    started = time.perf_counter()
    result = subprocess.run([str(binary), 'core', 'bench'], capture_output=True,
                            text=True, encoding='utf-8', timeout=120, check=True)
    elapsed = time.perf_counter() - started
    # Preserve transcripts before checking anything, including failed runs.
    output.with_name(output.stem + '-' + label + '.stdout.txt').write_bytes(result.stdout.encode())
    output.with_name(output.stem + '-' + label + '.stderr.txt').write_bytes(result.stderr.encode())
    signature = re.search(r'Nodes searched\s*:\s*(\d+)', result.stderr)
    assert signature and int(signature[1]) == 1559611, result.stderr[-1000:]
    lines = [re.sub(r'\b(time|nps) \d+', r'\1 <timing>', line)
             for line in result.stdout.splitlines()
             if line.startswith(('info depth ', 'bestmove '))]
    assert sum(line.startswith('bestmove ') for line in lines) == 51
    return dict(seconds=elapsed, signature=int(signature[1]), deterministic_lines=lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', default=str(ROOT / f'target/release/aster{EXE}'))
    parser.add_argument('--core', default=str(ROOT / f'target/release/aster-core{EXE}'))
    parser.add_argument('--baseline')
    parser.add_argument('--rounds', type=int, default=8)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = pathlib.Path(args.output)
    if output.exists() or args.rounds < 1:
        raise ValueError('Use a fresh output and a positive round count')
    output.parent.mkdir(parents=True, exist_ok=True)
    engine, core = pathlib.Path(args.engine).resolve(), pathlib.Path(args.core).resolve()
    identities = []
    for binary in [engine, core]:
        result = subprocess.run([str(binary)], input='uci\nlicense\nisready\nquit\n',
                                capture_output=True, text=True, encoding='utf-8', check=True, timeout=30)
        assert 'id name Aster 1.0.0' in result.stdout
        assert 'id author Aster contributors' in result.stdout
        assert 'uciok' in result.stdout and 'readyok' in result.stdout
        assert 'GNU General Public License' in result.stdout
        assert not re.search(research_text('forbidden_identity_pattern'), result.stdout, re.I), result.stdout
        identities.append(dict(binary=str(binary), sha256=digest(binary), transcript=result.stdout))
    candidate = bench(engine, output, 'candidate-warm')
    report = dict(passed=True, identities=identities, signature=candidate['signature'],
                  bench_bestmoves=51, verifier_sha256=digest(pathlib.Path(__file__)),
                  timing_scope='Local desktop, no affinity or isolation. Timing samples do not prove '
                               'exactly identical speed, Elo or superiority to any reference engine.')
    if args.baseline:
        baseline = pathlib.Path(args.baseline).resolve()
        original = bench(baseline, output, 'baseline-warm')
        assert candidate['deterministic_lines'] == original['deterministic_lines']
        pairs = []
        for index in range(args.rounds):
            runs = {}
            for role in (['baseline', 'candidate'] if index % 2 == 0 else ['candidate', 'baseline']):
                runs[role] = bench(baseline if role == 'baseline' else engine,
                                   output, f'{index}-{role}')
                assert runs[role]['deterministic_lines'] == original['deterministic_lines']
            pairs.append(dict(order=['baseline', 'candidate'] if index % 2 == 0 else ['candidate', 'baseline'],
                              baseline_seconds=runs['baseline']['seconds'],
                              candidate_seconds=runs['candidate']['seconds'],
                              candidate_over_baseline=runs['candidate']['seconds'] / runs['baseline']['seconds']))
        report.update(baseline_sha256=digest(baseline), pairs=pairs,
                      deterministic_lines=original['deterministic_lines'],
                      median_candidate_over_baseline=statistics.median(p['candidate_over_baseline'] for p in pairs))
    output.write_bytes((json.dumps(report, indent=2) + '\n').encode())
    print(json.dumps({key: report[key] for key in ['passed', 'signature', 'bench_bestmoves',
                     'median_candidate_over_baseline'] if key in report}))


if __name__ == '__main__':
    main()
