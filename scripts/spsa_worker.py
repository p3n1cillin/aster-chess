"""SPSA tuning worker for Aster's tunable search parameters (src/tune.rs).

Runs one SPSA chain (the fishtest schedule: c_k = c / k^0.101,
a_k = a / (A + k)^0.602, A = 0.1 N, per-parameter c_end and r_end) using a
`tune` build of aster-core at a Git ref. Every step draws a random sign vector
d, plays `--pairs` color-swapped game pairs between theta + c_k d and
theta - c_k d with fastchess, and updates
theta += (a_k / c_k) * (wins - losses) * d, per parameter. Progress is printed
as `SPSA_STATE {json}` lines; independent chains from several workers are
averaged by the coordinator (scripts/spsa_combine.py).
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import random
import re
import socket
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import testnet_worker as tw  # noqa: E402


def load_params(binary, names, overrides):
    spec = subprocess.run([str(binary)], input='tune-spec\nquit\n', capture_output=True,
                          text=True, timeout=120).stdout
    params = {}
    for line in spec.splitlines():
        parts = line.strip().split(',')
        if len(parts) != 7 or parts[1] != 'int':
            continue
        name = parts[0]
        value, lo, hi, c_end, r_end = map(float, parts[2:7])
        if names and name not in names:
            continue
        params[name] = dict(value=float(value), min=lo, max=hi, c_end=c_end, r_end=r_end)
    for name, value in overrides.items():
        if name in params:
            params[name]['value'] = float(value)
    if not params:
        raise RuntimeError('no tunable parameters selected')
    return params


def play(fastchess, book, binary, plus, minus, spec, seed, pairs, concurrency, workdir):
    each = [f'option.Hash={spec.get("hash", 16)}', 'option.Threads=1']
    each = (['tc=inf', f'nodes={spec["nodes"]}'] if 'nodes' in spec else [f'tc={spec["tc"]}']) + each
    cmd = [str(fastchess),
           '-engine', f'cmd={binary}', 'name=plus', *[f'option.{k}={v}' for k, v in plus.items()],
           '-engine', f'cmd={binary}', 'name=minus', *[f'option.{k}={v}' for k, v in minus.items()],
           '-each', *each,
           '-openings', f'file={book}', 'format=epd', 'order=random', '-srand', str(seed),
           '-rounds', str(pairs), '-games', '2', '-repeat', '-concurrency', str(concurrency),
           '-report', 'penta=true', '-ratinginterval', '0']
    out = tw.run(cmd, cwd=workdir)
    found = re.findall(r'Games:\s*(\d+), Wins:\s*(\d+), Losses:\s*(\d+), Draws:\s*(\d+)', out)
    if not found:
        raise RuntimeError('no result in fastchess output:\n' + out[-2000:])
    games, wins, losses, draws = map(int, found[-1])
    return wins, losses, draws


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--ref', required=True, help='Git ref of the engine to tune')
    ap.add_argument('--params', default='', help='comma-separated subset (default: all)')
    ap.add_argument('--start', default='{}', help='JSON of starting values (e.g. a combined state)')
    ap.add_argument('--tc', default='10+0.1')
    ap.add_argument('--nodes', type=int)
    ap.add_argument('--iterations', type=int, default=2000, help='planned steps N (sets the schedule)')
    ap.add_argument('--pairs', type=int, default=4, help='game pairs per step')
    ap.add_argument('--concurrency', type=int, default=os.cpu_count() or 1)
    ap.add_argument('--seed', type=int, required=True)
    ap.add_argument('--hours', type=float, default=1e9)
    ap.add_argument('--worker', default=socket.gethostname())
    ap.add_argument('--label', default='spsa')
    ap.add_argument('--resume', help='log of an earlier run of this chain: continue after its last SPSA_STATE')
    ap.add_argument('--deadline', type=float, default=0, help='Unix time after which no step starts')
    args = ap.parse_args()

    tw.WORK.mkdir(parents=True, exist_ok=True)
    tw.ensure_networks()
    fastchess, book = tw.ensure_fastchess(), tw.ensure_book()
    binary = tw.build_aster(args.ref, ['tune'])
    names = [n for n in args.params.split(',') if n]
    params = load_params(binary, names, json.loads(args.start))
    spec = {'nodes': args.nodes} if args.nodes else {'tc': args.tc}

    n = args.iterations
    big_a, alpha, gamma = 0.1 * n, 0.602, 0.101
    for p in params.values():
        p['c'] = p['c_end'] * n ** gamma
        p['a'] = p['r_end'] * p['c_end'] ** 2 * (big_a + n) ** alpha
    started = time.time()
    totals = [0, 0, 0]
    first = 1
    last = resume_state(args) if args.resume else None
    if last:
        first = last['iteration'] + 1
        totals = last['plus_w_l_d']
        for name, v in last['values'].items():
            if name in params:
                params[name]['value'] = float(v)
        print(f'SPSA_RESUME from iteration {last["iteration"]}', flush=True)
    for k in range(first, n + 1):
        if time.time() - started > args.hours * 3600 or (args.deadline and time.time() > args.deadline):
            break
        # Seeded per step, so a resumed chain draws the same directions.
        rng = random.Random(args.seed * 7919 + k)
        delta = {name: rng.choice((-1, 1)) for name in params}
        plus, minus = {}, {}
        for name, p in params.items():
            ck = p['c'] / k ** gamma
            plus[name] = round(min(p['max'], max(p['min'], p['value'] + ck * delta[name])))
            minus[name] = round(min(p['max'], max(p['min'], p['value'] - ck * delta[name])))
        wins, losses, draws = play(fastchess, book, binary, plus, minus, spec,
                                   args.seed * 1000003 + k, args.pairs, args.concurrency, tw.WORK)
        totals = [totals[0] + wins, totals[1] + losses, totals[2] + draws]
        result = wins - losses
        for name, p in params.items():
            ak, ck = p['a'] / (big_a + k) ** alpha, p['c'] / k ** gamma
            p['value'] = min(p['max'], max(p['min'], p['value'] + ak / ck * result * delta[name]))
        state = {'label': args.label, 'worker': args.worker, 'seed': args.seed, 'ref': args.ref,
                 'iteration': k, 'planned': n, 'games': 2 * args.pairs * k,
                 'plus_w_l_d': totals, 'tc': spec,
                 'values': {name: round(p['value'], 2) for name, p in params.items()}}
        print('SPSA_STATE ' + json.dumps(state), flush=True)
    else:
        print('SPSA_DONE', flush=True)
        return
    print('SPSA_DONE (time budget)', flush=True)


def resume_state(args):
    """Last SPSA_STATE of this chain in an earlier log, if any."""
    path = pathlib.Path(args.resume)
    if not path.exists():
        return None
    last = None
    for line in path.read_text(errors='replace').splitlines():
        if line.startswith('SPSA_STATE '):
            try:
                s = json.loads(line[len('SPSA_STATE '):])
            except json.JSONDecodeError:
                continue
            if (s['label'], s['worker'], s['seed']) == (args.label, args.worker, args.seed):
                last = s
    return last


if __name__ == '__main__':
    main()
