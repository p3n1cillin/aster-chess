"""Fixed paired timing and exact-work check for indexed accumulator updates."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import re
import statistics
import subprocess


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def normalized(stdout):
    return [re.sub(r'\b(nps|time) \d+', r'\1 <timing>', line.strip())
            for line in stdout.splitlines()
            if line.startswith(('info depth ', 'bestmove '))]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--plan', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise ValueError('Preserve previous timing attempts')
    plan = json.loads(Path(args.plan).read_text(encoding='utf-8'))
    timing = plan['gates']['timing']
    binaries = {role: str(Path(getattr(args, role)).resolve()) for role in ['baseline', 'candidate']}
    assert digest(binaries['baseline']) == plan['baseline_sha256']
    report = {'complete': False, 'passed': False, 'plan_sha256': digest(args.plan),
              'checker_sha256': digest(__file__),
              'binaries': {r: {'path': p, 'sha256': digest(p)} for r, p in binaries.items()},
              'modes': {}, 'interpretation': timing['interpretation']}

    def save():
        output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')

    save()
    reference = None

    def bench(mode, role, label):
        nonlocal reference
        env = os.environ.copy()
        env.pop('ASTER_SIMD', None)
        if mode != 'auto':
            env['ASTER_SIMD'] = mode
        result = subprocess.run([binaries[role], 'core', 'bench'], capture_output=True,
                                encoding='utf-8', env=env, timeout=180)
        raw = {}
        for stream in ['stdout', 'stderr']:
            path = output.with_name(output.stem + f'-{mode}-{role}-{label}.{stream}.txt')
            with path.open('x', encoding='utf-8') as handle:
                handle.write(getattr(result, stream))
            raw[stream] = {'path': str(path), 'sha256': digest(path)}
        trace = normalized(result.stdout)
        if reference is None:
            reference = trace
            report['normalized_reference'] = trace
        signature = re.search(r'Nodes searched\s*:\s*(\d+)', result.stderr)
        elapsed = re.search(r'Total time \(ms\)\s*:\s*(\d+)', result.stderr)
        observed = {'exit_code': result.returncode, 'raw': raw,
                    'nodes': int(signature[1]) if signature else None,
                    'elapsed_ms': int(elapsed[1]) if elapsed else None,
                    'exact_reference': trace == reference,
                    'searches': sum(line.startswith('bestmove ') for line in trace)}
        report.setdefault('runs', []).append({'mode': mode, 'role': role, 'label': label, **observed})
        save()
        if not (result.returncode == 0 and observed['nodes'] == 1559611
                and observed['searches'] == 51 and observed['exact_reference'] and observed['elapsed_ms'] > 0):
            raise ValueError(f'Canonical work changed: {mode} {role} {label}')
        return observed['elapsed_ms']

    for mode, pairs in timing['pairs'].items():
        bench(mode, 'baseline', 'warm')
        bench(mode, 'candidate', 'warm')
        detail = {'pairs': []}
        report['modes'][mode] = detail
        for index in range(pairs):
            order = ['baseline', 'candidate'] if index % 2 == 0 else ['candidate', 'baseline']
            elapsed = {role: bench(mode, role, f'{index:02}') for role in order}
            detail['pairs'].append({'index': index, 'order': order, 'elapsed_ms': elapsed,
                                    'ratio': elapsed['candidate'] / elapsed['baseline']})
            save()
        ratios = [p['ratio'] for p in detail['pairs']]
        rng = random.Random(timing['seed'])
        samples = sorted(statistics.median(rng.choices(ratios, k=len(ratios)))
                         for _ in range(timing['bootstrap_samples']))
        low = int(0.025 * len(samples))
        high = int(0.975 * len(samples)) - 1
        detail.update(median_ratio=statistics.median(ratios), interval95=[samples[low], samples[high]])
        prefix = 'avx2' if mode == 'avx2' else 'other'
        detail['passed'] = (detail['median_ratio'] <= timing[prefix + '_max_median_ratio']
                            and detail['interval95'][1] <= timing[prefix + '_max_upper95_ratio'])
        save()
        print(json.dumps({'mode': mode, 'median_ratio': detail['median_ratio'],
                          'interval95': detail['interval95'], 'passed': detail['passed']}), flush=True)
    report.update(complete=True, passed=all(m['passed'] for m in report['modes'].values()))
    save()
    print(json.dumps({'complete': True, 'passed': report['passed']}))


if __name__ == '__main__':
    main()
