"""Concurrent color-swapped paired match with pentanomial statistics.

Each opening from a frozen suite is played twice with colors swapped. Pairs are
scored as units (pentanomial model), so dependence between the two games of an
opening is accounted for. Games run concurrently, one engine thread each.
Writes a PGN and a JSON report (binaries, options, openings, time control,
every game). Results are a measurement, not a strength claim unless the
interval excludes 50%.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import hashlib
import json
import math
import pathlib
import threading
import time

import chess
import chess.engine
import chess.pgn

ROOT = pathlib.Path(__file__).resolve().parents[1]


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def elo_from_score(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return -400 * math.log10(1 / p - 1)


def pentanomial(pair_scores: list[float]) -> dict:
    """Mean pair score (0..1 per game) with a normal 95% interval over pairs."""
    n = len(pair_scores)
    if n == 0:
        return {}
    xs = [s / 2 for s in pair_scores]  # pair score as a fraction of 2 games
    mean = sum(xs) / n
    var = sum((x - mean) ** 2 for x in xs) / max(n - 1, 1)
    se = math.sqrt(var / n) if n > 1 else 0.5
    lo, hi = mean - 1.96 * se, mean + 1.96 * se
    counts = {k: sum(1 for s in pair_scores if s == k) for k in (0, 0.5, 1, 1.5, 2)}
    return {"pairs": n, "score": mean, "score_95": [lo, hi], "elo": elo_from_score(mean),
            "elo_95": [elo_from_score(lo), elo_from_score(hi)],
            "pentanomial_LL_LD_DD_WD_WW": [counts[0], counts[0.5], counts[1], counts[1.5], counts[2]]}


class EnginePool:
    """One engine process per worker thread (engines are not shared between games)."""

    def __init__(self, path: pathlib.Path, options: dict):
        self.path, self.options = path, options
        self.local = threading.local()
        self.all = []
        self.lock = threading.Lock()

    def get(self) -> chess.engine.SimpleEngine:
        e = getattr(self.local, "engine", None)
        if e is None:
            e = chess.engine.SimpleEngine.popen_uci([str(self.path)])
            # Ponder is managed by python-chess (always off here) and cannot be configured.
            e.configure({k: v for k, v in self.options.items() if k in e.options and k != "Ponder"})
            self.local.engine = e
            with self.lock:
                self.all.append(e)
        return e

    def close(self):
        for e in self.all:
            try:
                e.quit()
            except Exception:
                pass


def play_game(cand: EnginePool, base: EnginePool, opening: dict, cand_white: bool, tc: tuple[float, float], max_plies: int, game_id: str):
    board = chess.Board(opening.get("start_fen", chess.STARTING_FEN))
    for uci in opening["moves"].split():
        board.push_uci(uci)
    engines = {chess.WHITE: cand.get() if cand_white else base.get(), chess.BLACK: base.get() if cand_white else cand.get()}
    clocks = {chess.WHITE: tc[0], chess.BLACK: tc[0]}
    termination, result = None, "*"
    while True:
        outcome = board.outcome(claim_draw=True)
        if outcome:
            result, termination = outcome.result(), outcome.termination.name.lower()
            break
        if board.ply() >= max_plies:
            termination = "unresolved_max_plies"
            break
        side = board.turn
        limit = chess.engine.Limit(white_clock=clocks[chess.WHITE], black_clock=clocks[chess.BLACK], white_inc=tc[1], black_inc=tc[1])
        start = time.monotonic()
        res = engines[side].play(board, limit, game=game_id)
        clocks[side] -= time.monotonic() - start
        if clocks[side] < 0:
            result, termination = ("0-1" if side == chess.WHITE else "1-0"), "time_forfeit"
            break
        clocks[side] += tc[1]
        if res.move is None or not board.is_legal(res.move):
            result, termination = ("0-1" if side == chess.WHITE else "1-0"), "illegal_move"
            break
        board.push(res.move)
    return board, result, termination


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--openings", default=str(ROOT / "tests" / "fixtures" / "openings-v4.json"))
    ap.add_argument("--pairs", type=int, default=64)
    ap.add_argument("--tc", default="8+0.08", help="BASE+INC seconds per side")
    ap.add_argument("--concurrency", type=int, default=5)
    ap.add_argument("--hash", type=int, default=16)
    ap.add_argument("--max-plies", type=int, default=600)
    ap.add_argument("--output", required=True, help="Output prefix for .pgn/.json")
    args = ap.parse_args()

    cand_path, base_path = pathlib.Path(args.candidate).resolve(), pathlib.Path(args.baseline).resolve()
    opening_path = pathlib.Path(args.openings).resolve()
    openings = json.loads(opening_path.read_text())["openings"]
    base_s, inc_s = (float(x) for x in args.tc.split("+"))
    options = {"Hash": args.hash, "Threads": 1, "Ponder": False}
    cand, base = EnginePool(cand_path, options), EnginePool(base_path, options)
    out = pathlib.Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    pgn_path, json_path = out.parent / (out.name + ".pgn"), out.parent / (out.name + ".json")

    probe_c, probe_b = cand.get(), base.get()
    report = {"kind": "paired match", "started": datetime.datetime.now().isoformat(timespec="seconds"),
              "candidate": {"name": probe_c.id.get("name"), "path": str(cand_path), "sha256": sha256(cand_path)},
              "baseline": {"name": probe_b.id.get("name"), "path": str(base_path), "sha256": sha256(base_path)},
              "options": options, "time_control": {"base_s": base_s, "increment_s": inc_s},
              "concurrency": args.concurrency, "openings": {"path": str(opening_path), "sha256": sha256(opening_path)},
              "max_plies": args.max_plies, "games": []}
    lock = threading.Lock()
    pair_points: dict[int, list] = {}

    def job(pair: int, cand_white: bool):
        opening = openings[pair % len(openings)]
        board, result, termination = play_game(cand, base, opening, cand_white, (base_s, inc_s), args.max_plies, f"{pair}-{cand_white}")
        cand_name, base_name = report["candidate"]["name"], report["baseline"]["name"]
        game = chess.pgn.Game.from_board(board)
        game.headers.update({"Event": "paired match", "Round": f"{pair + 1}.{1 if cand_white else 2}",
                             "White": cand_name if cand_white else base_name, "Black": base_name if cand_white else cand_name,
                             "Result": result, "Opening": opening.get("id", str(pair)), "TimeControl": f"{base_s:g}+{inc_s:g}",
                             "Termination": termination or ""})
        pts = None
        if result != "*":
            w = {"1-0": 1.0, "0-1": 0.0, "1/2-1/2": 0.5}[result]
            pts = w if cand_white else 1 - w
        with lock:
            with pgn_path.open("a", encoding="utf-8") as f:
                print(game, file=f, end="\n\n")
            report["games"].append({"pair": pair, "opening": opening.get("id"), "candidate_white": cand_white, "result": result,
                                    "termination": termination, "plies": board.ply(), "candidate_points": pts})
            pair_points.setdefault(pair, []).append(pts)
            done = [p for p, v in pair_points.items() if len(v) == 2 and None not in v]
            stats = pentanomial([sum(pair_points[p]) for p in done])
            report["pentanomial"] = stats
            tmp = json_path.parent / (json_path.name + ".tmp")
            tmp.write_text(json.dumps(report, indent=2) + "\n")
            # Another process (e.g. a scanner on a network share) can briefly
            # hold the report open; retry rather than abort the match.
            for attempt in range(20):
                try:
                    tmp.replace(json_path)
                    break
                except PermissionError:
                    time.sleep(0.25 * (attempt + 1))
            n = len(report["games"])
            if stats:
                print(f"[{n}/{2 * args.pairs}] pairs {stats['pairs']} score {100 * stats['score']:.1f}% "
                      f"Elo {stats['elo']:+.1f} [{stats['elo_95'][0]:+.1f}, {stats['elo_95'][1]:+.1f}] penta {stats['pentanomial_LL_LD_DD_WD_WW']}", flush=True)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as ex:
            futures = [ex.submit(job, pair, cw) for pair in range(args.pairs) for cw in (True, False)]
            for f in futures:
                f.result()
    finally:
        cand.close()
        base.close()
    report["finished"] = datetime.datetime.now().isoformat(timespec="seconds")
    unresolved = sum(1 for g in report["games"] if g["candidate_points"] is None)
    report["unresolved_games"] = unresolved
    json_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report.get("pentanomial", {})), "unresolved", unresolved)


if __name__ == "__main__":
    main()
