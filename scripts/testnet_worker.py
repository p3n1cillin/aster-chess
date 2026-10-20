"""Aster testing-network worker: build two engine versions and play paired games.

Any Linux machine with git, a C++ compiler, Python 3 and network access can run
this. It prepares pinned tools (fastchess, the UHO opening book, the network
files, and optionally the upstream engine built from source), builds the base
and candidate engines from Git refs with the requested cargo features, checks
their bench signatures, then plays color-swapped pairs in batches. After every
batch it prints one line

    TESTNET_RESULT {json}

with the batch pentanomial [LL, LD, DD, WD, WW] from the candidate's view, so
a coordinator can aggregate results from many workers (scripts/testnet_sprt.py).

Development tools are never runtime dependencies of Aster.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'tools'
WORK = ROOT / 'testnet' / 'work'

FASTCHESS_URL = 'https://github.com/Disservin/fastchess.git'
FASTCHESS_TAG = 'v1.4.0-alpha'
BOOKS_URL = 'https://github.com/official-stockfish/books.git'
BOOK_NAME = 'UHO_Lichess_4852_v1.epd'
BOOK_SHA256 = '7a7f6470615a69c6cf23d565417701d38732876f480af90d67b42abade35644a'
UPSTREAM_URL = 'https://github.com/official-stockfish/Stockfish.git'
UPSTREAM_COMMIT = 'effdc3fd3f6de6e75fe1374a51a7a7eed66f880b'
UPSTREAM_NET = 'nn-c9e480e92425.nnue'


def run(cmd, cwd=None, env=None, quiet=True):
    result = subprocess.run(cmd, cwd=cwd, env=env, text=True,
                            stdout=subprocess.PIPE if quiet else None,
                            stderr=subprocess.STDOUT if quiet else None)
    if result.returncode != 0:
        tail = (result.stdout or '')[-3000:]
        raise RuntimeError(f'command failed ({result.returncode}): {" ".join(map(str, cmd))}\n{tail}')
    return result.stdout or ''


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def log(msg):
    print(f'[testnet {time.strftime("%H:%M:%S")}] {msg}', flush=True)


def ensure_fastchess() -> pathlib.Path:
    src = TOOLS / 'fastchess' / 'src'
    exe = src / 'fastchess'
    if not exe.exists():
        log('building fastchess')
        if not src.exists():
            run(['git', 'clone', '-q', '--depth', '1', '--branch', FASTCHESS_TAG, FASTCHESS_URL, str(src)])
        run(['make', '-j', str(os.cpu_count() or 2)], cwd=src)
    return exe


def ensure_book() -> pathlib.Path:
    book = TOOLS / 'books' / BOOK_NAME
    if not book.exists():
        log('fetching opening book')
        repo = TOOLS / 'books' / 'repo'
        if not repo.exists():
            run(['git', 'clone', '-q', '--depth', '1', '--filter=blob:none', '--no-checkout', BOOKS_URL, str(repo)])
        run(['git', 'checkout', '-q', 'HEAD', '--', BOOK_NAME + '.zip'], cwd=repo)
        import zipfile
        zipfile.ZipFile(repo / (BOOK_NAME + '.zip')).extractall(book.parent)
    if sha256(book) != BOOK_SHA256:
        raise RuntimeError('opening book checksum mismatch')
    return book


def ensure_networks():
    run([sys.executable, 'scripts/fetch_aster_network.py'], cwd=ROOT)
    run([sys.executable, 'scripts/fetch_rust_network.py'], cwd=ROOT)


def ensure_upstream() -> pathlib.Path:
    """The upstream development commit built from source (gcc PGO), as a reference opponent."""
    exe = TOOLS / 'stockfish' / f'upstream-{UPSTREAM_COMMIT[:10]}'
    if exe.exists():
        return exe
    log('building upstream reference opponent')
    src = TOOLS / 'stockfish' / f'src-{UPSTREAM_COMMIT[:10]}'
    if not (src / 'src' / 'Makefile').exists():
        src.mkdir(parents=True, exist_ok=True)
        run(['git', 'init', '-q'], cwd=src)
        run(['git', 'fetch', '-q', '--depth', '1', UPSTREAM_URL, UPSTREAM_COMMIT], cwd=src)
        run(['git', 'checkout', '-q', 'FETCH_HEAD'], cwd=src)
    shutil.copy(ROOT / 'crates' / 'aster-core' / UPSTREAM_NET, src / 'src' / UPSTREAM_NET)
    flags = open('/proc/cpuinfo').read()
    arch = 'x86-64-avx512icl' if 'avx512_vnni' in flags and 'avx512vbmi2' in flags else 'x86-64-bmi2'
    run(['make', '-j', str(os.cpu_count() or 2), 'profile-build', f'ARCH={arch}', 'COMP=gcc'], cwd=src / 'src')
    shutil.copy(src / 'src' / 'stockfish', exe)
    return exe


def build_aster(ref: str, features: list[str]) -> pathlib.Path:
    """Build aster-core at a Git ref with features; cached by (commit, features)."""
    commit = run(['git', 'rev-parse', ref], cwd=ROOT).strip()
    tag = commit[:12] + ('-' + '+'.join(sorted(features)) if features else '')
    exe = WORK / 'bin' / f'aster-core-{tag}'
    if exe.exists():
        return exe
    log(f'building aster-core {tag}')
    tree = WORK / 'trees' / commit[:12]
    if not tree.exists():
        tree.parent.mkdir(parents=True, exist_ok=True)
        run(['git', 'worktree', 'add', '--detach', str(tree), commit], cwd=ROOT)
    net = ROOT / 'crates' / 'aster-core' / UPSTREAM_NET
    if not (tree / 'crates' / 'aster-core' / UPSTREAM_NET).exists():
        shutil.copy(net, tree / 'crates' / 'aster-core' / UPSTREAM_NET)
    cmd = ['cargo', 'build', '--release', '--locked', '-p', 'aster-core',
           '--target-dir', str(WORK / 'target')]
    if features:
        cmd += ['--features', ','.join(features)]
    run(cmd, cwd=tree)
    exe.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(WORK / 'target' / 'release' / 'aster-core', exe)
    return exe


def bench_nodes(exe: pathlib.Path) -> int:
    out = subprocess.run([str(exe), 'bench'], capture_output=True, text=True, timeout=600)
    found = re.search(r'Nodes searched\s*:\s*(\d+)', out.stderr)
    if not found:
        raise RuntimeError(f'no bench output from {exe}')
    return int(found[1])


def engine_binary(side: dict) -> pathlib.Path:
    if side.get('engine') == 'upstream':
        return ensure_upstream()
    return build_aster(side['ref'], side.get('features', []))


def play_batch(fastchess, book, cand, base, spec, seed, pairs, concurrency, pgn):
    each = [f'option.Hash={spec.get("hash", 16)}', f'option.Threads={spec.get("threads", 1)}']
    if 'nodes' in spec:
        each = ['tc=inf', f'nodes={spec["nodes"]}'] + each
    else:
        each = [f'tc={spec["tc"]}'] + each
    cmd = [str(fastchess),
           '-engine', f'cmd={cand}', 'name=candidate', *[f'option.{k}={v}' for k, v in spec['candidate'].get('options', {}).items()],
           '-engine', f'cmd={base}', 'name=base', *[f'option.{k}={v}' for k, v in spec['base'].get('options', {}).items()],
           '-each', *each,
           '-openings', f'file={book}', 'format=epd', 'order=random', '-srand', str(seed),
           '-rounds', str(pairs), '-games', '2', '-repeat', '-concurrency', str(concurrency),
           '-report', 'penta=true', '-ratinginterval', '0', '-pgnout', f'file={pgn}']
    out = run(cmd, cwd=WORK)
    found = re.findall(r'Ptnml\(0-2\):\s*\[(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\]', out)
    if not found:
        raise RuntimeError('no pentanomial in fastchess output:\n' + out[-2000:])
    games = re.findall(r'Games:\s*(\d+), Wins:\s*(\d+), Losses:\s*(\d+), Draws:\s*(\d+)', out)
    problems = re.findall(r'(?i)(disconnect|illegal move|crash|loses on time|stall)', out)
    return [int(x) for x in found[-1]], [int(x) for x in games[-1]] if games else None, len(problems)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--spec', required=True, help='test spec JSON (testnet/specs/*.json)')
    parser.add_argument('--worker', default=socket.gethostname())
    parser.add_argument('--seed', type=int, required=True, help='distinct per worker; batches add 1, 2, ...')
    parser.add_argument('--batches', type=int, default=1000, help='stop after this many batches')
    parser.add_argument('--batch-pairs', type=int, default=100)
    parser.add_argument('--concurrency', type=int, default=os.cpu_count() or 1)
    parser.add_argument('--hours', type=float, default=1e9, help='stop starting batches after this long')
    parser.add_argument('--deadline', type=float, default=0, help='Unix time after which no batch starts')
    parser.add_argument('--resume', help='log of an earlier run: skip batches it already reported')
    args = parser.parse_args()

    spec_path = pathlib.Path(args.spec)
    spec = json.loads(spec_path.read_text())
    WORK.mkdir(parents=True, exist_ok=True)
    ensure_networks()
    fastchess, book = ensure_fastchess(), ensure_book()
    cand, base = engine_binary(spec['candidate']), engine_binary(spec['base'])
    info = {'test': spec['name'], 'worker': args.worker,
            'candidate_sha256': sha256(cand), 'base_sha256': sha256(base)}
    for label, exe, side in [('candidate', cand, spec['candidate']), ('base', base, spec['base'])]:
        if side.get('engine') != 'upstream':
            info[f'{label}_bench'] = bench_nodes(exe)
            if 'bench' in side and info[f'{label}_bench'] != side['bench']:
                raise RuntimeError(f'{label} bench {info[label + "_bench"]} != spec {side["bench"]}')
    print('TESTNET_READY ' + json.dumps(info), flush=True)

    done = set()
    if args.resume and pathlib.Path(args.resume).exists():
        for line in pathlib.Path(args.resume).read_text(errors='replace').splitlines():
            if line.startswith('TESTNET_RESULT '):
                r = json.loads(line[len('TESTNET_RESULT '):])
                if (r['test'], r['worker']) == (spec['name'], args.worker):
                    done.add(r['batch'])
    started = time.time()
    for k in range(1, args.batches + 1):
        if k in done:
            continue
        if time.time() - started > args.hours * 3600 or (args.deadline and time.time() > args.deadline):
            break
        seed = args.seed * 100000 + k
        pgn = WORK / f'{spec["name"]}-{args.worker}-{seed}.pgn'
        penta, games, problems = play_batch(fastchess, book, cand, base, spec, seed,
                                            args.batch_pairs, args.concurrency, pgn)
        result = dict(info, batch=k, seed=seed, pairs=sum(penta), pentanomial=penta,
                      games_w_l_d=games[1:] if games else None, problems=problems)
        print('TESTNET_RESULT ' + json.dumps(result), flush=True)
    print('TESTNET_DONE', flush=True)


if __name__ == '__main__':
    main()
