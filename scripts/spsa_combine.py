"""Average the latest SPSA_STATE of independent SPSA chains (weighted by games)."""
import argparse
import json
from collections import defaultdict


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('files', nargs='+')
    ap.add_argument('--label')
    args = ap.parse_args()
    latest = {}
    for f in args.files:
        for line in open(f, encoding='utf-8', errors='replace'):
            at = line.find('SPSA_STATE ')
            if at < 0:
                continue
            try:
                s = json.loads(line[at + len('SPSA_STATE '):].strip().rstrip('"').replace('\\"', '"'))
            except json.JSONDecodeError:
                continue
            if args.label and s['label'] != args.label:
                continue
            key = (s['label'], s['worker'], s['seed'])
            if key not in latest or s['iteration'] > latest[key]['iteration']:
                latest[key] = s
    total = sum(s['games'] for s in latest.values())
    values = defaultdict(float)
    for s in latest.values():
        for name, v in s['values'].items():
            values[name] += v * s['games'] / total
    print(json.dumps({'chains': len(latest), 'games': total,
                      'values': {k: round(v) for k, v in sorted(values.items())},
                      'raw': {k: round(v, 2) for k, v in sorted(values.items())}}))


if __name__ == '__main__':
    main()
