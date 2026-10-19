"""Compare the Rust core's Syzygy WDL (and DTZ when available) probes with python-chess.

python-chess's tablebase reader is an independent implementation; this checks
random legal positions for every material signature whose table exists.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import subprocess

import chess
import chess.syzygy

ROOT = pathlib.Path(__file__).resolve().parents[1]


def random_position(rng: random.Random, white: str, black: str) -> chess.Board | None:
    pieces = [(chess.Piece.from_symbol(c), chess.WHITE) for c in white] + [(chess.Piece.from_symbol(c.lower()), chess.BLACK) for c in black]
    for _ in range(200):
        board = chess.Board(None)
        board.turn = rng.choice([chess.WHITE, chess.BLACK])
        squares = rng.sample(range(64), len(pieces))
        ok = True
        for (piece, _), sq in zip(pieces, squares):
            if piece.piece_type == chess.PAWN and chess.square_rank(sq) in (0, 7):
                ok = False
                break
            board.set_piece_at(sq, piece)
        if ok and board.is_valid():
            return board
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--engine", required=True)
    ap.add_argument("--tables", default=str(ROOT / "tools" / "syzygy-development-v1"))
    ap.add_argument("--positions", type=int, default=400, help="Random positions per table")
    ap.add_argument("--seed", type=int, default=20261019)
    ap.add_argument("--output")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    tables = sorted(p.stem for p in pathlib.Path(args.tables).glob("*.rtbw"))
    has_dtz = {p.stem for p in pathlib.Path(args.tables).glob("*.rtbz")}
    reference = chess.syzygy.open_tablebase(args.tables)
    engine = subprocess.Popen([args.engine], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)

    def ask(cmd: str, prefix: str) -> str:
        engine.stdin.write(cmd + "\n")
        engine.stdin.flush()
        while True:
            line = engine.stdout.readline()
            if not line:
                raise RuntimeError("engine exited")
            if line.startswith(prefix):
                return line.strip()

    ask("uci", "uciok")
    found = ask(f"setoption name SyzygyPath value {args.tables}", "info string Found")
    checked = 0
    mismatches = []
    per_table = {}
    for name in tables:
        white, black = name.split("v")
        n = 0
        for _ in range(args.positions):
            # Either side may own the stronger material (exercises color flipping).
            board = random_position(rng, white, black) if rng.random() < 0.5 else random_position(rng, black, white)
            if board is None:
                continue
            ref_wdl = reference.probe_wdl(board)
            ref_dtz = reference.probe_dtz(board) if name in has_dtz else None
            line = ask(f"position fen {board.fen()}\ntbprobe", "info string tbprobe")
            parts = line.split()
            wdl, wdl_state, dtz, dtz_state = int(parts[4]), parts[5], int(parts[7]), parts[8]
            ok = wdl_state != "Fail" and wdl == ref_wdl
            if ref_dtz is not None:
                ok = ok and dtz_state != "Fail" and dtz == ref_dtz
            if not ok:
                mismatches.append({"fen": board.fen(), "engine": line, "wdl": ref_wdl, "dtz": ref_dtz})
            checked += 1
            n += 1
        per_table[name] = n
    engine.stdin.write("quit\n")
    engine.stdin.flush()
    engine.wait(timeout=10)
    report = {"passed": not mismatches, "engine_tables": found, "positions": checked, "per_table": per_table,
              "dtz_checked": sorted(has_dtz), "mismatches": mismatches[:20]}
    if args.output:
        pathlib.Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("passed", "engine_tables", "positions", "per_table", "dtz_checked")}))
    if mismatches:
        print(json.dumps(mismatches[:5], indent=1))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
