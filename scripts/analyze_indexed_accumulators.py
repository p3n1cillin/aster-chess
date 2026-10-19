"""Apply the fixed engineering adoption gates; never derive Elo from timing."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import re
import statistics

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'artifacts/verification/aster-indexed-accumulators-'


def digest(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise ValueError('Preserve previous decisions')
    evidence = {}

    def read(path):
        evidence[path] = digest(path)
        return json.loads((ROOT / path).read_text(encoding='utf-8-sig'))

    plan_path = 'artifacts/research/aster-indexed-accumulators-plan-v1.json'
    plan = read(plan_path)
    execution = read('artifacts/research/aster-indexed-accumulators-execution-v1.json')
    assert execution['plan_sha256'] == digest(plan_path)
    timing = read(PREFIX + 'timing-v1.json')
    assert timing['complete'] and timing['plan_sha256'] == digest(plan_path)
    assert timing['checker_sha256'] == digest('scripts/benchmark_indexed_accumulators.py')
    for role in ['baseline', 'candidate']:
        assert timing['binaries'][role]['sha256'] == execution[role + '_sha256']
    assert len(timing['runs']) == 86
    assert all(r['exact_reference'] and r['nodes'] == 1559611 and r['exit_code'] == 0 for r in timing['runs'])
    for mode, pairs in plan['gates']['timing']['pairs'].items():
        assert len(timing['modes'][mode]['pairs']) == pairs
    controls = {}
    for mode in ['auto', 'avx2']:
        path = f'artifacts/matches/aster-indexed-accumulators-{mode}-v1.json'
        report = read(path)
        assert len(report['games']) == 64 and report['pairs_requested'] == 32
        assert report['limit'] == {'seconds_per_move': 0.03}
        for role, field in [('candidate', 'candidate'), ('opponent', 'baseline')]:
            assert report[role + '_binary_sha256'] == execution[field + '_sha256']
            assert report[role + '_options']['Threads'] == 1 and report[role + '_options']['Hash'] == 64
        for kind in ['pgn', 'journal']:
            audit = read(PREFIX + f'{mode}-{kind}-audit-v1.json')
            assert audit['status'] == 'passed' and audit['games'] == 64
            if kind == 'journal':
                assert audit['source_sha256']['report'] == digest(path)
        scores = []
        for pair in range(1, 33):
            games = [g for g in report['games'] if g['pair'] == pair]
            assert len(games) == 2 and {g['candidate_color'] for g in games} == {'white', 'black'}
            assert games[0]['opening'] == games[1]['opening']
            assert games[0]['starting_fen'] == games[1]['starting_fen']
            points = 0
            for game in games:
                assert game['result'] in ['1-0', '0-1', '1/2-1/2']
                points += (0.5 if game['result'] == '1/2-1/2' else
                           float((game['result'] == '1-0') == (game['candidate_color'] == 'white')))
            scores.append(points / 2)
        rng = random.Random(20261019)
        samples = sorted(statistics.mean(rng.choices(scores, k=32)) for _ in range(20000))
        interval = [samples[500], samples[19499]]
        controls[mode] = {'games': 64, 'wins': report['wins'], 'draws': report['draws'],
                          'losses': report['losses'], 'score': statistics.mean(scores),
                          'pair_bootstrap95': interval,
                          'passed': report['forfeits'] == 0 and report['unresolved'] == 0 and interval[1] >= 0.5}
    for mode in ['auto', 'avx2', 'scalar']:
        equivalence = read(PREFIX + f'equivalence-{mode}-v1.json')
        assert equivalence['passed'] and equivalence['identical'] == equivalence['positions'] == 64
        assert read(PREFIX + f'{mode}-rules-v1.json')['passed']
        if mode != 'scalar':
            for check in ['edges', 'play', 'proofs']:
                result = read(PREFIX + f'{mode}-{check}-v1.json')
                assert result.get('passed') or result.get('status') == 'passed'
        for suite in ['tactics-v1', 'tactics-quiet-v1', 'endgames-v1']:
            tactical = read(f'artifacts/tactics/aster-indexed-accumulators-{mode}-candidate-{suite}.json')
            assert tactical['reference_match'] and tactical['binary_sha256'] == execution['candidate_sha256']
    for profile in ['release', 'debug']:
        path = PREFIX + profile + '-tests-v1.log'
        evidence[path] = digest(path)
        results = re.findall(r'test result: (\w+)\. (\d+) passed; (\d+) failed', (ROOT / path).read_text(encoding='utf-8-sig'))
        assert sum(int(r[1]) for r in results) == 155 and all(r[0] == 'ok' and r[2] == '0' for r in results)
    ci = read(PREFIX + 'ci-jobs-v1.json')
    assert ci['code_commit'] == execution['code_commit']
    assert len(ci['jobs']) == 2 and all(j['conclusion'] == 'success' for j in ci['jobs'])
    adopted = timing['passed'] and all(c['passed'] for c in controls.values())
    result = {'adopted': adopted, 'timing_passed': timing['passed'], 'controls': controls,
              'bootstrap_samples': 20000, 'bootstrap_seed': 20261019,
              'analyzer_sha256': digest('scripts/analyze_indexed_accumulators.py'),
              'evidence_sha256': evidence,
              'interpretation': 'Engineering speed/nonregression decision. Pair bootstrap does not model correlated opening families. No absolute Elo, playing-strength gain, novelty or reference superiority established.'}
    with output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps({'adopted': adopted, 'controls': controls}))


if __name__ == '__main__':
    main()
