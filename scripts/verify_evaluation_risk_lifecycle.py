"""Verify research-state reset, SMP budget bounds and responsive cancellation."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import time

import chess

from uci_client import UciClient
from verify import validate_pv


def telemetry(lines):
    match = re.search(r'Aster evaluation risk samples (\d+) deferred (\d+) max_per_thread (\d+)', '\n'.join(lines))
    assert match and int(match[3]) == 64
    return {'samples': int(match[1]), 'deferred': int(match[2])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise ValueError('Preserve prior results')
    cases = []
    root = chess.Board()
    with UciClient(args.engine) as client:
        for threads in [1, 2, 4]:
            client.send(f'setoption name Threads value {threads}')
            client.send('setoption name Hash value 3')
            for enabled in [False, True]:
                client.send('setoption name Aster Evaluation Risk value ' + str(enabled).lower())
                client.send('ucinewgame')
                client.send('position startpos')
                client.ready()
                client.send('go infinite')
                time.sleep(0.2)
                start = time.perf_counter()
                client.ready()
                ready_seconds = time.perf_counter() - start
                assert ready_seconds < 2
                client.send('stop')
                lines = client.until('bestmove', timeout=3)
                validate_pv(root, lines)
                assert chess.Move.from_uci(lines[-1].split()[1]) in root.legal_moves
                stats = telemetry(lines) if enabled else {'samples': 0, 'deferred': 0}
                assert stats['deferred'] <= 64 * threads
                actual = client.command('d', 'info string fen ').removeprefix('info string fen ')
                assert actual == root.fen()
                cases.append({'threads': threads, 'enabled': enabled, 'ready_seconds': ready_seconds,
                              'root_restored': True, **stats})
        client.send('setoption name Threads value 1')
        client.send('setoption name Hash value 64')
        client.send('setoption name Aster Evaluation Risk value true')
        resets = []
        for command in ['ucinewgame', 'ucinewgame', 'setoption name Clear Hash']:
            client.send(command)
            client.send('position startpos')
            client.ready()
            client.send('go depth 12')
            lines = client.until('bestmove', timeout=30)
            validate_pv(root, lines)
            info = [line for line in lines if line.startswith('info depth ') and ' pv ' in line][-1]
            normalized = re.sub(r'\b(time|nps) \d+', r'\1 <timing>', info)
            resets.append({'reset': command, 'result': {'last_info': normalized, 'bestmove': lines[-1], **telemetry(lines)}})
        assert all(r['result'] == resets[0]['result'] for r in resets)
    report = {'passed': True, 'binary_sha256': hashlib.sha256(Path(args.engine).read_bytes()).hexdigest(),
              'checker_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'cases': cases, 'deterministic_resets': resets,
              'checks': 'Threads1/2/4,3MiB hash, enabled/disabled ready during search, stop, legal PV/bestmove, root restored; repeated game/clear-hash reset reproduces complete final info and activity.'}
    with output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(json.dumps({'passed': True, 'cases': len(cases), 'deterministic_resets': len(resets)}))


if __name__ == '__main__':
    main()
