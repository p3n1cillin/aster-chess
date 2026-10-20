"""Execute the committed per-root timing order once, preserving every observation."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
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
    parser.add_argument('--correctness-report', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output)
    assert not output.exists(), 'Never replace a previous attempt'
    plan = json.loads(Path(args.plan).read_text(encoding='utf-8'))
    build = json.loads(Path(args.build_report).read_text(encoding='utf-8'))
    correctness = json.loads(Path(args.correctness_report).read_text(encoding='utf-8'))
    assert build['status'] == 'built_unqualified' and build['plan_sha256'] == digest(args.plan)
    assert correctness['passed'] and correctness['build_report_sha256'] == digest(args.build_report)
    for check in correctness['steps']:
        assert digest(check['log']) == check['log_sha256'] and check['exit_code'] == 0
    parent_path = ROOT / plan['validation']['parent']
    parent = json.loads(parent_path.read_text(encoding='utf-8'))['openings']
    start, stop = plan['validation']['timing_range']
    entries = parent[start:stop]
    assert len(parent) == 80 and len(entries) == 16
    canonical = lambda fen: ' '.join(chess.Board(fen).fen().split()[:4])
    excluded = set()
    for prior in plan['generation']['excluded_suites']:
        assert digest(ROOT / prior['path']) == prior['sha256']
        excluded.update(canonical(e['fen']) for e in json.loads((ROOT / prior['path']).read_text(encoding='utf-8-sig'))['openings'])
    assert len({canonical(e['fen']) for e in parent}) == 80
    assert not any(canonical(e['fen']) in excluded for e in parent)
    binaries = {role: build['binaries'][label] for role, label in [('baseline', 'control'), ('candidate', 'candidate')]}
    for role, binary in binaries.items():
        assert digest(binary['path']) == binary['sha256']
        folder = 'aster-midpoint-prefetch-' + ('control-source-v1' if role == 'baseline' else 'source-v1')
        frozen = ROOT / 'artifacts/research' / folder
        manifest = json.loads((frozen / 'manifest.json').read_text(encoding='utf-8'))
        assert manifest['binary_sha256'] == binary['sha256']
        for file in manifest['source_files']:
            assert digest(frozen / file['path']) == file['sha256']
    # Verify the explicit schedule independently before any timed search.
    expected = []
    for mode in plan['timing']['mode_order']:
        for batch in range(plan['timing']['replicates'][mode]):
            roots = list(range(16)) if batch % 2 == 0 else list(range(15, -1, -1))
            for ordinal, root in enumerate(roots):
                roles = ['baseline', 'candidate'] if (batch + ordinal) % 2 == 0 else ['candidate', 'baseline']
                expected.append(dict(mode=mode, batch=batch, root=root, roles=roles))
    assert expected == plan['timing']['schedule']
    report = dict(status='running', complete=False, passed=False, pid=os.getpid(),
                  created_utc=datetime.now(timezone.utc).isoformat(), checker_sha256=digest(__file__),
                  plan_sha256=digest(args.plan), build_report_sha256=digest(args.build_report),
                  correctness_report_sha256=digest(args.correctness_report), parent_sha256=digest(parent_path),
                  binaries=binaries, observations=[], warmups=[], modes={}, active_query=None,
                  limits=plan['timing']['metric'])

    def save():
        output.write_bytes((json.dumps(report, indent=2) + '\n').encode('utf-8'))

    save()
    reference = {}
    try:
        for mode in plan['timing']['mode_order']:
            env = os.environ.copy()
            env.pop('ASTER_SIMD', None)
            if mode != 'auto':
                env['ASTER_SIMD'] = mode
            engines = {}
            try:
                for role in ['baseline', 'candidate']:
                    engine = chess.engine.SimpleEngine.popen_uci([binaries[role]['path']], env=env, timeout=120)
                    engines[role] = engine
                    engine.configure({'Threads': 1, 'Hash': 64})
                    report['active_query'] = dict(mode=mode, role=role, warmup=True)
                    save()
                    result = engine.play(chess.Board(), chess.engine.Limit(depth=8), game=object(), info=chess.engine.INFO_ALL)
                    report['warmups'].append(dict(mode=mode, role=role, bestmove=result.move.uci(), nodes=result.info['nodes']))
                for specification in [s for s in expected if s['mode'] == mode]:
                    board = chess.Board()
                    for move in entries[specification['root']]['moves'].split():
                        board.push_uci(move)
                    observation = dict(specification, runs={})
                    for role in specification['roles']:
                        report['active_query'] = dict(specification, role=role)
                        save()
                        began = time.perf_counter_ns()
                        result = engines[role].play(board, chess.engine.Limit(depth=plan['timing']['depth']), game=object(), info=chess.engine.INFO_ALL)
                        elapsed = time.perf_counter_ns() - began
                        assert result.move in board.legal_moves
                        score = result.info['score'].white()
                        behavior = dict(bestmove=result.move.uci(), cp=score.score(), mate=score.mate(),
                                        nodes=result.info['nodes'], depth=result.info['depth'],
                                        pv=[m.uci() for m in result.info.get('pv', [])])
                        replay = board.copy()
                        for move in behavior['pv']:
                            replay.push_uci(move)
                        assert behavior['depth'] == plan['timing']['depth']
                        reference.setdefault(specification['root'], behavior)
                        assert behavior == reference[specification['root']], (mode, role, specification['root'])
                        observation['runs'][role] = dict(elapsed_ns=elapsed, behavior=behavior)
                        report['active_query'] = None
                    report['observations'].append(observation)
                    save()
                batches = []
                for batch in range(plan['timing']['replicates'][mode]):
                    observations = [o for o in report['observations'] if o['mode'] == mode and o['batch'] == batch]
                    assert len(observations) == 16
                    totals = {r: sum(o['runs'][r]['elapsed_ns'] for o in observations) for r in binaries}
                    batches.append(dict(index=batch, total_ns=totals, ratio=totals['candidate']/totals['baseline']))
                ratios = [b['ratio'] for b in batches]
                rng = random.Random(plan['timing']['seed'])
                resampled = sorted(statistics.median(rng.choices(ratios, k=len(ratios))) for _ in range(plan['timing']['bootstrap_samples']))
                median, interval = statistics.median(ratios), [resampled[500], resampled[19499]]
                prefix = 'auto' if mode == 'auto' else 'other'
                passed = median <= plan['timing'][prefix+'_max_median_ratio'] and interval[1] <= plan['timing'][prefix+'_max_upper95_ratio']
                report['modes'][mode] = dict(batches=batches, median_ratio=median, interval95=interval, passed=passed)
                save()
                print(json.dumps(dict(mode=mode, median_ratio=median, interval95=interval, passed=passed)), flush=True)
            finally:
                for engine in engines.values():
                    engine.quit()
        executed = [{k: o[k] for k in ['mode', 'batch', 'root', 'roles']} for o in report['observations']]
        assert executed == expected
        report.update(status='completed', complete=True, passed=all(m['passed'] for m in report['modes'].values()),
                      schedule_exact=True, identical_behavior=True, prior_suite_root_overlap=0,
                      completed_utc=datetime.now(timezone.utc).isoformat())
        save()
    except BaseException as error:
        report.update(status='failed', error=str(error), failed_utc=datetime.now(timezone.utc).isoformat())
        save()
        raise


if __name__ == '__main__':
    main()
