"""Aggregate testing-network results and compute a pentanomial SPRT.

Reads TESTNET_RESULT lines (from worker logs, transcripts or stdin), sums the
pentanomial counts per test, and reports score, logistic Elo with a 95%
interval, and the generalized SPRT log-likelihood ratio for logistic Elo bounds
[elo0, elo1] (normal approximation over game pairs, as fishtest's GSPRT).
"""
import argparse
import json
import math
import sys
from collections import defaultdict

SCORES = [0.0, 0.25, 0.5, 0.75, 1.0]


def elo(score):
    score = min(max(score, 1e-9), 1 - 1e-9)
    return -400 * math.log10(1 / score - 1)


def score_of(e):
    return 1 / (1 + 10 ** (-e / 400))


def analyse(penta, elo0, elo1, alpha=0.05, beta=0.05):
    n = sum(penta)
    if n < 2:
        return {'pairs': n}
    mean = sum(s * c for s, c in zip(SCORES, penta)) / n
    var = sum(c * (s - mean) ** 2 for s, c in zip(SCORES, penta)) / n
    var = max(var, 1e-6)
    se = math.sqrt(var / n)
    s0, s1 = score_of(elo0), score_of(elo1)
    llr = n * (s1 - s0) * (2 * mean - s0 - s1) / (2 * var)
    lower, upper = math.log(beta / (1 - alpha)), math.log((1 - beta) / alpha)
    state = 'accepted' if llr >= upper else 'rejected' if llr <= lower else 'running'
    return {'pairs': n, 'games': 2 * n, 'pentanomial': penta, 'score': mean,
            'elo': elo(mean), 'elo_95': [elo(mean - 1.96 * se), elo(mean + 1.96 * se)],
            'llr': llr, 'bounds': [lower, upper], 'elo0': elo0, 'elo1': elo1, 'state': state}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', nargs='*', help='logs containing TESTNET_RESULT lines (default stdin)')
    parser.add_argument('--elo0', type=float, default=0.0)
    parser.add_argument('--elo1', type=float, default=2.0)
    args = parser.parse_args()
    totals = defaultdict(lambda: [0] * 5)
    seen = set()
    streams = [open(f, encoding='utf-8', errors='replace') for f in args.files] or [sys.stdin]
    for stream in streams:
        for line in stream:
            at = line.find('TESTNET_RESULT ')
            if at < 0:
                continue
            try:
                r = json.loads(line[at + len('TESTNET_RESULT '):].strip().rstrip('"').replace('\\"', '"'))
            except json.JSONDecodeError:
                continue
            key = (r['test'], r['worker'], r['seed'])
            if key in seen:  # the same batch may appear in several transcripts
                continue
            seen.add(key)
            for i, c in enumerate(r['pentanomial']):
                totals[r['test']][i] += c
    for test, penta in sorted(totals.items()):
        print(json.dumps({'test': test, **analyse(penta, args.elo0, args.elo1)}))


if __name__ == '__main__':
    main()
