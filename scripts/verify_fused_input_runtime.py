"""Check complete canonical traces across kernels and cancellation on feature-gated fusion binaries."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

import chess
from uci_client import UciClient
from verify import validate_pv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-report', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise ValueError('Preserve previous results')
    build = json.loads(Path(args.build_report).read_text(encoding='utf-8'))
    assert build['status'] == 'built_unqualified'
    observations = []
    reference = None
    for mode in ['auto', 'avx2', 'scalar']:
        env = os.environ.copy()
        env.pop('ASTER_SIMD', None)
        if mode != 'auto':
            env['ASTER_SIMD'] = mode
        for role in ['control', 'candidate']:
            info = build['binaries'][role]
            assert hashlib.sha256(Path(info['path']).read_bytes()).hexdigest() == info['sha256']
            result = subprocess.run([info['path'], 'core', 'bench'], env=env, capture_output=True, encoding='utf-8', timeout=180, check=True)
            raw = {}
            for stream in ['stdout', 'stderr']:
                path = output.with_name(output.stem + f'-{mode}-{role}.{stream}.txt')
                with path.open('x', encoding='utf-8') as handle:
                    handle.write(getattr(result, stream))
                raw[stream] = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            lines = [re.sub(r'\b(nps|time) \d+', r'\1 <timing>', line) for line in result.stdout.splitlines()
                     if line.startswith(('info depth ', 'bestmove '))]
            assert re.search(r'Nodes searched\s*:\s*1559611\b', result.stderr)
            assert sum(line.startswith('bestmove ') for line in lines) == 51
            if reference is None:
                reference = lines
            assert lines == reference, (mode, role)
            observations.append({'mode': mode, 'role': role, 'sha256': info['sha256'], 'exact': True, 'raw': raw})
    root = chess.Board()
    lifecycle = []
    for threads in [1, 2, 4]:
        with UciClient(build['binaries']['candidate']['path']) as client:
            client.send(f'setoption name Threads value {threads}')
            client.send('setoption name Hash value 3')
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
            assert client.command('d', 'info string fen ').removeprefix('info string fen ') == root.fen()
            lifecycle.append({'threads': threads, 'hash_mib': 3, 'ready_seconds': ready_seconds, 'root_restored': True})
    report = {'passed': True, 'signature': 1559611, 'searches_per_run': 51,
              'normalized_reference': reference, 'observations': observations, 'lifecycle': lifecycle,
              'build_report_sha256': hashlib.sha256(Path(args.build_report).read_bytes()).hexdigest(),
              'checker_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    with output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(json.dumps({'passed': True, 'exact_runs': 6, 'lifecycle': len(lifecycle)}))


if __name__ == '__main__':
    main()
