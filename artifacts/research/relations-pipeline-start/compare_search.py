"""Compare fixed-depth search behavior and work across a frozen opening suite."""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import pathlib
import time

import chess
import chess.engine

from match import configure
from uci_client import DEFAULT_ENGINE, engine_command


def fingerprint(path: pathlib.Path) -> str:
    with path.open("rb") as source: return hashlib.file_digest(source, "sha256").hexdigest()


def run(engine: chess.engine.SimpleEngine, board: chess.Board, depth: int) -> dict:
    started = time.monotonic()
    result = engine.play(board, chess.engine.Limit(depth=depth), game=object(), info=chess.engine.INFO_ALL)
    if result.move not in board.legal_moves: raise RuntimeError("Search produced an illegal best move")
    replay = board.copy()
    for move in result.info.get("pv", []):
        if move not in replay.legal_moves: raise RuntimeError("Search produced an illegal PV")
        replay.push(move)
    score = result.info.get("score")
    return {"move": result.move.uci(), "white_cp": score.white().score() if score else None,
            "white_mate": score.white().mate() if score else None, "depth": result.info.get("depth"),
            "nodes": result.info.get("nodes"), "reported_seconds": result.info.get("time"),
            "elapsed_seconds": round(time.monotonic() - started, 6)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", default=str(DEFAULT_ENGINE))
    parser.add_argument("--opponent", required=True)
    parser.add_argument("--suite", default="tests/fixtures/openings-v1.json")
    parser.add_argument("--depth", type=int, default=6)
    parser.add_argument("--hash", type=int, default=64)
    parser.add_argument("--eval-file")
    parser.add_argument("--opponent-eval-file")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not 1 <= args.depth <= 126 or not 1 <= args.hash <= 1024: parser.error("Invalid depth or Hash")
    paths = [pathlib.Path(args.engine).resolve(), pathlib.Path(args.opponent).resolve()]
    suite_path = pathlib.Path(args.suite).resolve()
    suite = json.loads(suite_path.read_text(encoding="utf-8")); positions = []
    with chess.engine.SimpleEngine.popen_uci(engine_command(paths[0]), timeout=120) as candidate, \
            chess.engine.SimpleEngine.popen_uci(engine_command(paths[1]), timeout=120) as opponent:
        options = [configure(engine, args.hash, model) for engine, model in
                   zip((candidate, opponent), (args.eval_file, args.opponent_eval_file), strict=True)]
        names = [engine.id.get("name") for engine in (candidate, opponent)]
        for entry in suite["openings"]:
            board = chess.Board()
            for move in entry["moves"].split(): board.push_uci(move)
            if board.fen() != entry["fen"] or board.outcome(claim_draw=True) is not None: raise ValueError("Invalid opening fixture")
            compared = {"id": entry["id"], "fen": board.fen()}
            # Alternate process order to reduce systematic timing order effects.
            engines = [("candidate", candidate), ("opponent", opponent)]
            if len(positions) % 2: engines.reverse()
            for role, engine in engines: compared[role] = run(engine, board, args.depth)
            compared["same_move"] = compared["candidate"]["move"] == compared["opponent"]["move"]
            compared["same_score"] = all(compared["candidate"][key] == compared["opponent"][key] for key in ("white_cp", "white_mate"))
            positions.append(compared)
    summary = {"positions": len(positions), "same_move": sum(entry["same_move"] for entry in positions),
               "same_score": sum(entry["same_score"] for entry in positions)}
    for role in ("candidate", "opponent"):
        summary[role + "_nodes"] = sum(entry[role]["nodes"] or 0 for entry in positions)
        summary[role + "_elapsed_seconds"] = round(sum(entry[role]["elapsed_seconds"] for entry in positions), 3)
    report = {"timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "engines": [{"path": str(path), "sha256": fingerprint(path), "name": name, "options": option}
                          for path, name, option in zip(paths, names, options, strict=True)],
              "suite": str(suite_path), "suite_sha256": fingerprint(suite_path), "depth": args.depth,
              "summary": summary, "positions": positions,
              "interpretation": "Fixed-depth work and behavior comparison with legal PV checks, not a strength test. Selective search and ordering can change scores; timing is affected by JIT and machine load."}
    for engine, model in zip(report["engines"], (args.eval_file, args.opponent_eval_file), strict=True):
        if model:
            path = pathlib.Path(model).resolve()
            engine["model"] = str(path); engine["model_sha256"] = fingerprint(path)
    output = pathlib.Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__": main()
