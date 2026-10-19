"""Apply the predeclared evaluation-risk trial gates without adaptive tuning."""
import argparse
import hashlib
import json
from pathlib import Path

from analyze_disagreement import control_report

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise ValueError('Preserve earlier decisions')
    read = lambda p: json.loads((ROOT / p).read_text(encoding='utf-8-sig'))
    prefix = 'artifacts/verification/aster-evaluation-risk-'
    controls = {name: control_report(ROOT / f'artifacts/matches/aster-evaluation-risk-{name}-v1.json', 64, seconds)
                for name, seconds in [('30ms', 0.03), ('100ms', 0.1)]}
    activity = read(prefix + 'activity-v1.json')
    audits = {}
    for name, control in controls.items():
        assert (control['candidate_sha256'], control['baseline_sha256']) == (activity['candidate_sha256'], activity['baseline_sha256'])
        for kind in ['pgn', 'journal']:
            path = prefix + f'{name}-{kind}-audit-v1.json'
            audit = read(path)
            assert audit['status'] == 'passed' and audit['games'] == 128
            audits[path] = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
    tactics = []
    for suite in ['tactics-v1', 'tactics-quiet-v1', 'endgames-v1']:
        baseline = read(f'artifacts/tactics/aster-evaluation-risk-control-{suite}.json')
        candidate = read(f'artifacts/tactics/aster-evaluation-risk-candidate-{suite}.json')
        assert baseline['limit'] == candidate['limit'] == {'nodes': 20000}
        assert baseline['total'] == candidate['total']
        assert (baseline['binary_sha256'], candidate['binary_sha256']) == (activity['baseline_sha256'], activity['candidate_sha256'])
        tactics.append({'suite': suite, 'baseline': baseline['solved'], 'candidate': candidate['solved'],
                        'passed': candidate['solved'] >= baseline['solved'],
                        'changed_positions': [{'id': b['id'], 'baseline': b['bestmove'], 'candidate': c['bestmove']}
                                              for b, c in zip(baseline['positions'], candidate['positions'], strict=True)
                                              if b['bestmove'] != c['bestmove']]})
    eligible = activity['passed'] and all(c['passes_strength_gate'] for c in controls.values()) and all(t['passed'] for t in tactics)
    result = {'eligible_for_confirmation': eligible, 'production_enabled': False, 'controls': controls,
              'tactics': tactics, 'activity_passed': activity['passed'], 'audits_sha256': audits,
              'analyzer_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'bootstrap_implementation_sha256': hashlib.sha256((ROOT / 'scripts/analyze_disagreement.py').read_bytes()).hexdigest(),
              'interpretation': 'Both strict 95% whole-opening-family score lower bounds must exceed 50%; fixed 20000 samples/20261019 seed. Eligibility still needs all correctness/CI gates and a separately declared reference confirmation. No Elo, calibrated probability, novelty or superiority claim.'}
    with output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps({'eligible_for_confirmation': eligible, 'controls': controls}))


if __name__ == '__main__':
    main()
