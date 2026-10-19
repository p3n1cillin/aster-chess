"""Counterbalanced same-work timing screen; never infer Elo from search speed."""
import argparse
import hashlib
import json
import pathlib
import re
import statistics
import time

from uci_client import UciClient


def digest(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def search(client, moves, depth):
    client.send('ucinewgame')
    client.send('position startpos moves ' + moves)
    client.ready()
    started = time.perf_counter_ns()
    client.send(f'go depth {depth}')
    lines = client.until('bestmove', timeout=60)
    elapsed = time.perf_counter_ns() - started
    exact = [line for line in lines if line.startswith('info depth ')
             and ' pv ' in line and ' lowerbound ' not in line and ' upperbound ' not in line][-1]
    result = {
        'depth': int(exact.split()[2]),
        'nodes': int(re.search(r'\bnodes (\d+)', exact)[1]),
        'score': re.search(r'\bscore (cp|mate) (-?\d+)', exact)[0],
        'pv': exact.split(' pv ', 1)[1],
        'bestmove': lines[-1],
    }
    assert result['depth'] == depth, result
    return elapsed, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--suite', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = pathlib.Path(args.output)
    if output.exists():
        raise ValueError('Preserve earlier timing attempts')
    entries = json.loads(pathlib.Path(args.suite).read_text(encoding='utf-8'))['openings']
    assert len(entries) == 16
    report = {
        'complete': False, 'depth': 12, 'replicates_requested': 8,
        'suite_sha256': digest(args.suite), 'checker_sha256': digest(__file__),
        'baseline_sha256': digest(args.baseline), 'candidate_sha256': digest(args.candidate),
        'plan_sha256': digest('artifacts/research/rust-legal-probe-plan-v1.json'),
        'options': {'Hash': 64, 'Threads': 1}, 'replicates': [],
        'interpretation': 'Counterbalanced local wall-clock screen with identical work. '
                          'No CPU affinity or desktop isolation; no Elo or strength inferred.',
    }

    def save():
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes((json.dumps(report, indent=2) + '\n').encode())

    save()
    with UciClient(args.baseline) as baseline, UciClient(args.candidate) as candidate:
        clients = {'baseline': baseline, 'candidate': candidate}
        for client in clients.values():
            client.send('setoption name Hash value 64')
            client.send('setoption name Threads value 1')
            client.ready()
            search(client, '', 8)  # Discard weight/page/process warmup.
        reference = {}
        for repetition in range(8):
            order = ['baseline', 'candidate'] if repetition % 2 == 0 else ['candidate', 'baseline']
            indices = list(range(16)) if repetition % 2 == 0 else list(reversed(range(16)))
            batch = {'index': repetition, 'engine_order': order, 'positions': [],
                     'total_ns': {'baseline': 0, 'candidate': 0}}
            for index in indices:
                detail = {'position': index, 'runs': {}}
                for role in order:
                    elapsed, behavior = search(clients[role], entries[index]['moves'], 12)
                    reference.setdefault(index, behavior)
                    assert reference[index] == behavior, (index, role, reference[index], behavior)
                    batch['total_ns'][role] += elapsed
                    detail['runs'][role] = {'wall_ns': elapsed, 'behavior': behavior}
                batch['positions'].append(detail)
            batch['baseline_over_candidate_time'] = batch['total_ns']['baseline'] / batch['total_ns']['candidate']
            report['replicates'].append(batch)
            save()
            print(json.dumps({'replicate': repetition, 'time_ratio': batch['baseline_over_candidate_time']}), flush=True)
    ratios = [batch['baseline_over_candidate_time'] for batch in report['replicates']]
    report.update(complete=True, identical_behavior=True,
                  median_time_ratio=statistics.median(ratios),
                  candidate_faster_replicates=sum(ratio > 1 for ratio in ratios))
    report['timing_gate_passed'] = report['median_time_ratio'] >= 1.03 and report['candidate_faster_replicates'] >= 6
    save()
    print(json.dumps({key: report[key] for key in ['complete', 'identical_behavior', 'median_time_ratio',
                                                 'candidate_faster_replicates', 'timing_gate_passed']}))


if __name__ == '__main__':
    main()
