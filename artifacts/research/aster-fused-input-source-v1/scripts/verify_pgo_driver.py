"""Compare the development-only native profiling entry with the ordinary engine."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', required=True)
    parser.add_argument('--driver', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise ValueError('Preserve prior evidence')
    observations = []
    for role in ['engine', 'driver']:
        binary = str(Path(getattr(args, role)).resolve())
        handshake = subprocess.run([binary], input='uci\nisready\nquit\n', capture_output=True, encoding='utf-8', timeout=30, check=True)
        assert 'uciok' in handshake.stdout and 'readyok' in handshake.stdout
        bench = subprocess.run([binary, 'core', 'bench'], capture_output=True, encoding='utf-8', timeout=180, check=True)
        raw = {}
        for stream in ['stdout', 'stderr']:
            path = output.with_name(output.stem + '-' + role + '.' + stream + '.txt')
            with path.open('x', encoding='utf-8') as handle:
                handle.write(getattr(bench, stream))
            raw[stream] = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        assert re.search(r'Nodes searched\s*:\s*1559611\b', bench.stderr)
        lines = [re.sub(r'\b(nps|time) \d+', r'\1 <timing>', line) for line in bench.stdout.splitlines()
                 if line.startswith(('info depth ', 'bestmove '))]
        assert sum(line.startswith('bestmove ') for line in lines) == 51
        observations.append({'role': role, 'sha256': hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
                             'handshake': handshake.stdout, 'normalized_lines': lines, 'raw': raw})
    assert observations[0]['handshake'] == observations[1]['handshake']
    assert observations[0]['normalized_lines'] == observations[1]['normalized_lines']
    report = {'passed': True, 'signature': 1559611, 'searches': 51, 'observations': observations,
              'checker_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    with output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(json.dumps({'passed': True, 'signature': 1559611, 'searches': 51}))


if __name__ == '__main__':
    main()
