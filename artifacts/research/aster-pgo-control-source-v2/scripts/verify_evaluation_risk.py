"""Check legal search, activity bounds, cost or disabled exactness on fresh roots."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import statistics
import time

import chess
import chess.engine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--baseline', required=True)
    parser.add_argument('--suite', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--disabled', action='store_true')
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise ValueError('Preserve earlier reports')
    suite = Path(args.suite)
    positions = json.loads(suite.read_text(encoding='utf-8'))['openings']
    engines = {}
    observations = []
    try:
        for role in ['baseline', 'candidate']:
            engines[role] = chess.engine.SimpleEngine.popen_uci([str(Path(getattr(args, role)).resolve())], timeout=60)
            engines[role].configure({'Threads': 1, 'Hash': 64})
        if args.disabled:
            engines['candidate'].configure({'Aster Evaluation Risk': False})
        for index, entry in enumerate(positions):
            board = chess.Board()
            for move in entry['moves'].split():
                board.push_uci(move)
            cases = {}
            for role in (['baseline', 'candidate'] if index % 2 == 0 else ['candidate', 'baseline']):
                started = time.perf_counter()
                limit = chess.engine.Limit(depth=9) if args.disabled else chess.engine.Limit(nodes=20000)
                result = engines[role].play(board, limit, game=object(), info=chess.engine.INFO_ALL)
                elapsed = time.perf_counter() - started
                assert result.move in board.legal_moves
                replay = board.copy()
                for move in result.info.get('pv', []):
                    assert move in replay.legal_moves
                    replay.push(move)
                activity = re.search(r'Aster evaluation risk samples (\d+) deferred (\d+) max_per_thread (\d+)', result.info.get('string', ''))
                if role == 'candidate' and not args.disabled:
                    assert activity and int(activity[3]) == 64 and int(activity[2]) <= 64
                elif role == 'candidate':
                    assert activity is None
                score = result.info['score'].white()
                cases[role] = {'bestmove': result.move.uci(), 'cp': score.score(), 'mate': score.mate(),
                               'depth': result.info.get('depth'), 'nodes': result.info['nodes'],
                               'pv': [m.uci() for m in result.info.get('pv', [])], 'wall_seconds': elapsed,
                               'samples': int(activity[1]) if activity else 0,
                               'deferred': int(activity[2]) if activity else 0}
            keys = ['bestmove', 'cp', 'mate', 'depth', 'nodes', 'pv']
            exact = all(cases['baseline'][key] == cases['candidate'][key] for key in keys)
            base, candidate = cases['baseline'], cases['candidate']
            throughput = (candidate['nodes'] / candidate['wall_seconds']) / (base['nodes'] / base['wall_seconds'])
            observations.append({'index': index, 'fen': board.fen(), 'results': cases,
                                 'exact': exact, 'throughput_ratio': throughput})
    finally:
        for engine in engines.values():
            engine.quit()
    deferred = sum(o['results']['candidate']['deferred'] for o in observations)
    samples = sum(o['results']['candidate']['samples'] for o in observations)
    throughput = statistics.median(o['throughput_ratio'] for o in observations)
    passed = all(o['exact'] for o in observations) if args.disabled else deferred > 0 and samples > 0 and throughput >= 0.90
    report = {'passed': passed, 'disabled': args.disabled, 'positions': len(observations),
              'candidate_sha256': hashlib.sha256(Path(args.candidate).read_bytes()).hexdigest(),
              'baseline_sha256': hashlib.sha256(Path(args.baseline).read_bytes()).hexdigest(),
              'suite_sha256': hashlib.sha256(suite.read_bytes()).hexdigest(),
              'checker_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'limit': {'depth': 9} if args.disabled else {'nodes': 20000},
              'samples': samples, 'deferred': deferred, 'median_throughput_ratio': throughput,
              'observations': observations, 'limits': 'Desktop cost includes protocol/reset; heuristic risk is not probability, a proof or playing strength.'}
    with output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(json.dumps({k: report[k] for k in ['passed', 'disabled', 'positions', 'samples', 'deferred', 'median_throughput_ratio']}))
    if not passed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
