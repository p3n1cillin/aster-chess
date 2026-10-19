"""Check a core binary's `bench` node signature against crates/aster-core/BENCH.json."""
import argparse
import json
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, help='aster-core executable')
    parser.add_argument('--key', choices=['aster', 'upstream_reference'], required=True)
    args = parser.parse_args()
    expected = json.loads((ROOT / 'crates/aster-core/BENCH.json').read_text(encoding='utf-8'))[args.key]
    result = subprocess.run([args.binary, 'bench'], capture_output=True, text=True, timeout=300, check=True)
    found = re.search(r'Nodes searched\s*:\s*(\d+)', result.stderr)
    nodes = int(found[1]) if found else None
    print(json.dumps({'passed': nodes == expected, 'key': args.key, 'expected': expected, 'nodes': nodes}))
    if nodes != expected:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
