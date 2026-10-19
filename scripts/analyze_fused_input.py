"""Apply the frozen fusion gates, including the prospective timing stop."""
import argparse
import hashlib
import json
from pathlib import Path
import re

from analyze_disagreement import control_report

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'artifacts/verification/aster-fused-input-'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = ROOT / args.output
    if output.exists():
        raise ValueError('Preserve earlier decisions')
    evidence = {}

    def digest(path):
        return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()

    def read(path):
        evidence[path] = digest(path)
        return json.loads((ROOT / path).read_text(encoding='utf-8-sig'))

    plan_path = 'artifacts/research/aster-fused-input-plan-v1.json'
    plan = read(plan_path)
    build = read('artifacts/research/aster-fused-input-build-v1.json')
    assert build['plan_sha256'] == digest(plan_path)
    binaries = build['binaries']
    for binary in binaries.values():
        assert digest(binary['path']) == binary['sha256']
    assert binaries['control']['sha256'] == plan['baseline_sha256']
    for role, folder in [('control', 'aster-fused-input-control-source-v1'), ('candidate', 'aster-fused-input-source-v1')]:
        folder = 'artifacts/research/' + folder
        manifest = read(folder + '/manifest.json')
        assert manifest['binary_sha256'] == binaries[role]['sha256']
        for entry in manifest['source_files']:
            assert digest(folder + '/' + entry['path']) == entry['sha256']
    timing = read(PREFIX + 'timing-v1.json')
    assert timing['complete'] and timing['identical_behavior'] and timing['prior_suite_root_overlap'] == 0
    assert timing['plan_sha256'] == digest(plan_path)
    assert timing['build_report_sha256'] == digest('artifacts/research/aster-fused-input-build-v1.json')
    assert timing['binaries']['baseline']['sha256'] == binaries['control']['sha256']
    assert timing['binaries']['candidate']['sha256'] == binaries['candidate']['sha256']
    parent = read(plan['validation']['parent'])['openings']
    assert len(parent) == 64
    suite_path = 'tests/fixtures/aster-fused-input-timing-v1.json'
    assert read(suite_path)['openings'] == parent[:16]
    assert timing['suite_sha256'] == digest(suite_path)
    for mode, repetitions in plan['timing']['replicates'].items():
        observed = timing['modes'][mode]
        assert len(observed['batches']) == repetitions
        for batch in observed['batches']:
            order = ['baseline', 'candidate'] if batch['index'] % 2 == 0 else ['candidate', 'baseline']
            assert batch['order'] == order and len(batch['positions']) == 16
        threshold = 'auto' if mode == 'auto' else 'other'
        passed = (observed['median_ratio'] <= plan['timing'][threshold + '_max_median_ratio']
                  and observed['interval95'][1] <= plan['timing'][threshold + '_max_upper95_ratio'])
        assert observed['passed'] == passed
        exact = read(PREFIX + f'equivalence-{mode}-v1.json')
        assert exact['passed'] and exact['positions'] == exact['identical'] == 64
        for suite in plan['validation']['tactics_suites']:
            tactical = read(f'artifacts/tactics/aster-fused-input-{mode}-candidate-{suite}-v1.json')
            assert tactical['reference_match'] and tactical['binary_sha256'] == binaries['candidate']['sha256']
    assert timing['passed'] == all(m['passed'] for m in timing['modes'].values())
    for profile, count in [('feature-release', 162), ('feature-debug', 162), ('default-release', 159), ('default-debug', 159)]:
        path = PREFIX + profile + '-tests-v1.log'
        evidence[path] = digest(path)
        rows = re.findall(r'test result: (\w+)\. (\d+) passed; (\d+) failed', (ROOT / path).read_text(encoding='utf-8-sig'))
        assert sum(int(row[1]) for row in rows) == count and all(row[0] == 'ok' and row[2] == '0' for row in rows)
    for check in ['runtime', 'rules', 'edges', 'play', 'proofs', 'final-source-names']:
        result = read(PREFIX + check + '-v1.json')
        assert result.get('passed') or result.get('status') == 'passed', check
    assert all(read(PREFIX + 'cpu-v1.json').values())
    ci = read(PREFIX + 'ci-jobs-v1.json')
    assert len(ci['jobs']) == 2 and all(job['conclusion'] == 'success' for job in ci['jobs'])
    controls = {}
    if timing['passed']:
        for name, seconds in [('30ms', 0.03), ('100ms', 0.1)]:
            path = f'artifacts/matches/aster-fused-input-{name}-v1.json'
            raw = read(path)
            assert raw['candidate_binary_sha256'] == binaries['candidate']['sha256']
            assert raw['opponent_binary_sha256'] == binaries['control']['sha256']
            first, last = plan['validation'][name + '_range']
            assert read(f'tests/fixtures/aster-fused-input-{name}-v1.json')['openings'] == parent[first:last]
            control = control_report(ROOT / path, 32, seconds)
            interval = control.get('opening_family_95_percent_interval')
            control['passes_engineering_nonregression'] = bool(control['resolved_pairs'] == 32
                and control['unresolved_pairs'] == control['forfeits'] == 0 and interval and interval[1] >= 0.5)
            controls[name] = control
            for kind in ['pgn', 'journal']:
                audit = read(PREFIX + f'{name}-{kind}-audit-v1.json')
                assert audit['status'] == 'passed' and audit['games'] == 64
    else:
        assert not list((ROOT / 'artifacts/matches').glob('aster-fused-input-*-v1.*'))
    protocol = {'adoption_conformant': False,
                'deviation': 'The plan can be read as alternating AB/BA per root within batches. The checker alternated between whole batches, applying one order to every root in each batch. Counts and reverse-root order are unchanged; all raw results remain. Conservatively ineligible for adoption, without rerunning or replacing outcomes.'}
    adopted = timing['passed'] and protocol['adoption_conformant'] and all(c['passes_engineering_nonregression'] for c in controls.values())
    report = {'adopted': adopted, 'timing_passed': timing['passed'], 'controls': controls,
              'conditional_matches_started': bool(controls), 'conditional_pairs_unused': 64 if not controls else 0,
              'reason': 'Timing gate failed; conditional matches prospectively skipped.' if not timing['passed'] else 'All fixed gates evaluated.',
              'timing_order_protocol': protocol,
              'candidate_sha256': binaries['candidate']['sha256'], 'baseline_sha256': binaries['control']['sha256'],
              'evidence_sha256': evidence, 'analyzer_sha256': digest('scripts/analyze_fused_input.py'),
              'interpretation': 'Engineering trial only. No absolute/public Elo, novelty or reference superiority. Failed outcomes are not retuned.'}
    with output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(json.dumps({k: report[k] for k in ['adopted', 'timing_passed', 'conditional_matches_started', 'conditional_pairs_unused']}))


if __name__ == '__main__':
    main()
