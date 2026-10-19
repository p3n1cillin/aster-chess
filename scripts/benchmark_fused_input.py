"""Counterbalanced same-work fusion timing on fresh roots."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import re
import statistics
import time

import chess
import chess.engine

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True)
    parser.add_argument('--build-report', required=True)
    parser.add_argument('--suite', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise ValueError('Preserve earlier timing attempts')
    plan = json.loads(Path(args.plan).read_text(encoding='utf-8'))
    build = json.loads(Path(args.build_report).read_text(encoding='utf-8'))
    assert build['status'] == 'built_unqualified' and build['plan_sha256'] == digest(args.plan)
    binaries = {role: build['binaries'][label] for role, label in [('baseline', 'control'), ('candidate', 'candidate')]}
    for binary in binaries.values():
        assert digest(binary['path']) == binary['sha256']
    entries = json.loads(Path(args.suite).read_text(encoding='utf-8'))['openings']
    assert len(entries) == 16
    canonical = lambda fen: ' '.join(chess.Board(fen).fen().split()[:4])
    excluded = set()
    for prior in plan['generation']['excluded_suites']:
        path = ROOT / prior['path']
        assert digest(path) == prior['sha256']
        excluded.update(canonical(e['fen']) for e in json.loads(path.read_text(encoding='utf-8'))['openings'])
    parent = json.loads((ROOT / plan['validation']['parent']).read_text(encoding='utf-8'))['openings']
    assert len(parent) == 64 and len({canonical(e['fen']) for e in parent}) == 64
    assert not any(canonical(e['fen']) in excluded for e in parent)
    assert entries == parent[:16]
    report = {'complete': False, 'passed': False, 'plan_sha256': digest(args.plan),
              'build_report_sha256': digest(args.build_report), 'suite_sha256': digest(args.suite),
              'checker_sha256': digest(__file__), 'binaries': binaries, 'prior_suite_root_overlap': 0,
              'timing': plan['timing'], 'modes': {},
              'limits': 'Held-out roots; desktop wall time includes protocol/reset, without affinity/isolation. Ratios do not establish Elo or reference superiority.'}
    save = lambda: output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    save()
    reference = {}
    for mode in plan['timing']['replicates']:
        env = os.environ.copy()
        env.pop('ASTER_SIMD', None)
        if mode != 'auto':
            env['ASTER_SIMD'] = mode
        engines = {}
        try:
            for role, binary in binaries.items():
                engine = chess.engine.SimpleEngine.popen_uci([binary['path']], env=env, timeout=120)
                engines[role] = engine
                engine.configure({'Threads': 1, 'Hash': 64})
                engine.play(chess.Board(), chess.engine.Limit(depth=8), game=object())
            detail = {'batches': []}
            report['modes'][mode] = detail
            for repetition in range(plan['timing']['replicates'][mode]):
                order = ['baseline', 'candidate'] if repetition % 2 == 0 else ['candidate', 'baseline']
                indices = list(range(16)) if repetition % 2 == 0 else list(reversed(range(16)))
                batch = {'index': repetition, 'order': order, 'total_ns': {'baseline': 0, 'candidate': 0}, 'positions': []}
                for index in indices:
                    board = chess.Board()
                    for move in entries[index]['moves'].split():
                        board.push_uci(move)
                    observation = {'index': index, 'runs': {}}
                    for role in order:
                        start = time.perf_counter_ns()
                        result = engines[role].play(board, chess.engine.Limit(depth=plan['timing']['depth']), game=object(), info=chess.engine.INFO_ALL)
                        elapsed = time.perf_counter_ns() - start
                        assert result.move in board.legal_moves
                        score = result.info['score'].white()
                        behavior = {'bestmove': result.move.uci(), 'cp': score.score(), 'mate': score.mate(),
                                    'nodes': result.info['nodes'], 'depth': result.info['depth'],
                                    'pv': [m.uci() for m in result.info.get('pv', [])]}
                        replay = board.copy()
                        for move in result.info.get('pv', []):
                            assert move in replay.legal_moves
                            replay.push(move)
                        assert behavior['depth'] == plan['timing']['depth']
                        reference.setdefault(index, behavior)
                        assert behavior == reference[index], (mode, role, index)
                        observation['runs'][role] = {'elapsed_ns': elapsed, 'behavior': behavior}
                        batch['total_ns'][role] += elapsed
                    batch['positions'].append(observation)
                batch['ratio'] = batch['total_ns']['candidate'] / batch['total_ns']['baseline']
                detail['batches'].append(batch)
                save()
            ratios = [b['ratio'] for b in detail['batches']]
            rng = random.Random(plan['timing']['seed'])
            samples = sorted(statistics.median(rng.choices(ratios, k=len(ratios))) for _ in range(plan['timing']['bootstrap_samples']))
            detail.update(median_ratio=statistics.median(ratios), interval95=[samples[500], samples[19499]])
            prefix = 'auto' if mode == 'auto' else 'other'
            detail['passed'] = (detail['median_ratio'] <= plan['timing'][prefix + '_max_median_ratio']
                                and detail['interval95'][1] <= plan['timing'][prefix + '_max_upper95_ratio'])
            save()
            print(json.dumps({'mode': mode, 'median_ratio': detail['median_ratio'], 'interval95': detail['interval95'], 'passed': detail['passed']}), flush=True)
        finally:
            for engine in engines.values():
                engine.quit()
    report.update(complete=True, passed=all(m['passed'] for m in report['modes'].values()), identical_behavior=True)
    save()
    print(json.dumps({'complete': True, 'passed': report['passed']}))


if __name__ == '__main__':
    main()
