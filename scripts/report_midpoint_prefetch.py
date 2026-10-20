"""Preserve the failed order audit and independently report the rejected experiment."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import re
import statistics

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output)
    assert not output.exists(), 'Preserve earlier audits'
    evidence = {}

    def read(relative):
        path = ROOT / relative
        evidence[relative] = digest(path)
        return json.loads(path.read_text(encoding='utf-8'))

    prefix = 'artifacts/verification/aster-midpoint-prefetch-'
    plan_path = 'artifacts/research/aster-midpoint-prefetch-plan-v1.json'
    build_path = 'artifacts/research/aster-midpoint-prefetch-build-v1.json'
    plan, build = read(plan_path), read(build_path)
    correct, timing = read(prefix + 'correctness-v1.json'), read(prefix + 'timing-v1.json')
    assert build['plan_sha256'] == digest(ROOT / plan_path)
    assert correct['passed'] and len(correct['steps']) == 29 and correct['active_step'] is None
    assert correct['build_report_sha256'] == timing['build_report_sha256'] == digest(ROOT / build_path)
    assert timing['correctness_report_sha256'] == digest(ROOT / (prefix + 'correctness-v1.json'))
    assert timing['checker_sha256'] == digest(ROOT / 'scripts/benchmark_midpoint_prefetch.py')
    native = {}
    for step in correct['steps']:
        assert step['exit_code'] == 0 and digest(step['log']) == step['log_sha256']
        if step['label'] in ['feature-release', 'feature-debug', 'default-release', 'default-debug']:
            rows = re.findall(r'test result: (\w+)\. (\d+) passed; (\d+) failed', Path(step['log']).read_text(encoding='utf-8'))
            assert rows and all(kind == 'ok' and failed == '0' for kind, _, failed in rows)
            native[step['label']] = sum(int(passed) for _, passed, _ in rows)
            assert native[step['label']] >= 159
    for binary in build['binaries'].values():
        assert digest(binary['path']) == binary['sha256']
    for role, folder in [('control', 'aster-midpoint-prefetch-control-source-v1'), ('candidate', 'aster-midpoint-prefetch-source-v1')]:
        source = ROOT / 'artifacts/research' / folder
        manifest = read('artifacts/research/' + folder + '/manifest.json')
        assert manifest['binary_sha256'] == build['binaries'][role]['sha256']
        for file in manifest['source_files']:
            assert digest(source / file['path']) == file['sha256']
    parent = read(plan['validation']['parent'])['openings']
    assert len(parent) == 80
    for mode in ['auto', 'avx2', 'scalar']:
        exact = read(prefix + 'equivalence-' + mode + '-v1.json')
        assert exact['passed'] and exact['positions'] == exact['identical'] == 80
        for suite in plan['validation']['tactics_suites']:
            tactical = read(f'artifacts/tactics/aster-midpoint-prefetch-{mode}-{suite}.json')
            assert tactical['reference_match'] and tactical['binary_sha256'] == build['binaries']['candidate']['sha256']
    for check in ['runtime', 'rules', 'edges', 'play', 'proofs']:
        result = read(prefix + check + '-v1.json')
        assert result.get('passed') or result.get('status') == 'passed', check
    assert timing['status'] == 'completed' and timing['complete'] and timing['identical_behavior']
    assert timing['active_query'] is None and timing['plan_sha256'] == digest(ROOT / plan_path)
    assert timing['prior_suite_root_overlap'] == 0 and len(timing['warmups']) == 6
    observed = timing['observations']
    assert [{k: o[k] for k in ['mode', 'batch', 'root', 'roles']} for o in observed] == plan['timing']['schedule']
    first_slots = Counter()
    last_end = 0
    for item in observed:
        assert list(item['runs']) == item['roles']
        for role in item['roles']:
            run = item['runs'][role]
            assert run['began_ns'] >= last_end and run['ended_ns'] > run['began_ns']
            assert run['elapsed_ns'] == run['ended_ns'] - run['began_ns']
            last_end = run['ended_ns']
        assert item['runs']['baseline']['behavior'] == item['runs']['candidate']['behavior']
        first_slots[item['mode'], item['root'], item['roles'][0]] += 1
    decisions = {}
    root_balanced = True
    slot_counts = []
    for mode, repetitions in plan['timing']['replicates'].items():
        for root in range(16):
            counts = {role: first_slots[mode, root, role] for role in ['baseline', 'candidate']}
            slot_counts.append(dict(mode=mode, root=root, first_slots=counts))
            root_balanced &= counts['baseline'] == counts['candidate'] == repetitions // 2
        ratios = []
        for batch in range(repetitions):
            rows = [o for o in observed if o['mode'] == mode and o['batch'] == batch]
            assert len(rows) == 16
            assert Counter(o['roles'][0] for o in rows) == {'baseline': 8, 'candidate': 8}
            totals = {role: sum(o['runs'][role]['elapsed_ns'] for o in rows) for role in ['baseline', 'candidate']}
            ratio = totals['candidate'] / totals['baseline']
            assert timing['modes'][mode]['batches'][batch] == dict(index=batch, total_ns=totals, ratio=ratio)
            ratios.append(ratio)
        rng = random.Random(plan['timing']['seed'])
        samples = sorted(statistics.median(rng.choices(ratios, k=repetitions)) for _ in range(20000))
        median, interval = statistics.median(ratios), [samples[500], samples[19499]]
        prefix_mode = 'auto' if mode == 'auto' else 'other'
        passed = median <= plan['timing'][prefix_mode + '_max_median_ratio'] and interval[1] <= plan['timing'][prefix_mode + '_max_upper95_ratio']
        assert timing['modes'][mode]['median_ratio'] == median and timing['modes'][mode]['interval95'] == interval
        assert timing['modes'][mode]['passed'] == passed
        decisions[mode] = dict(median_ratio=median, interval95=interval, passed=passed)
    eligible = all(m['passed'] for m in decisions.values())
    assert timing['passed'] == eligible
    if not eligible:
        assert not list((ROOT / 'artifacts/matches').glob('aster-midpoint-prefetch-*'))
    prior_failure = ROOT / 'artifacts/verification/aster-midpoint-prefetch-first-audit-failure-v1.log'
    assert prior_failure.is_file() and not root_balanced
    evidence[prior_failure.relative_to(ROOT).as_posix()] = digest(prior_failure)
    evidence['scripts/audit_midpoint_prefetch_timing.py'] = digest(ROOT / 'scripts/audit_midpoint_prefetch_timing.py')
    report = dict(status='evidence_verified_experiment_rejected', created_utc=datetime.now(timezone.utc).isoformat(),
                  checker_sha256=digest(__file__), evidence_sha256=evidence,
                  timing=decisions, actual_order_matches_plan=True, matched_root_pairs=len(observed),
                  root_first_slot_balance=root_balanced, first_slot_counts=slot_counts,
                  timing_passed=eligible, protocol_conformant=False,
                  protocol_failure='The explicit schedule was followed, with8AB/8BA per batch, but reversing roots and using (batch+ordinal)%2 cancels the intended per-root first-slot rotation. Each root always ran the same role first. The plan prose incorrectly claimed per-root balance. Preserve every result; no corrected rerun or variant.',
                  native_tests_including_compile_fail=native, eligible_for_conditional_matches=False,
                  conditional_pairs_unused=64 if not eligible else None, adopted=False,
                  interpretation='Audited engineering gates only; no playing-strength, absolute/public Elo or reference-superiority claim.')
    output.write_bytes((json.dumps(report, indent=2) + '\n').encode('utf-8'))
    print(json.dumps({k: report[k] for k in ['status', 'eligible_for_conditional_matches', 'root_first_slot_balance', 'timing']}))


if __name__ == '__main__':
    main()
