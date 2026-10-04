"""Run reproducible, color-swapped UCI engine matches and save PGN plus a JSON report."""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import pathlib
import platform
import time

import chess
import chess.engine
import chess.pgn

from uci_client import DEFAULT_ENGINE, ROOT, engine_command

# Balanced opening sampling is still needed for serious strength testing. These
# eight ordinary opening lines provide a deterministic initial smoke-test suite.
OPENINGS = [
    "e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 b5a4 g8f6",
    "e2e4 c7c5 g1f3 d7d6 d2d4 c5d4 f3d4 g8f6",
    "d2d4 d7d5 c2c4 e7e6 b1c3 g8f6 c1g5 f8e7",
    "d2d4 g8f6 c2c4 g7g6 b1c3 f8g7 e2e4 d7d6",
    "e2e4 e7e6 d2d4 d7d5 b1c3 g8f6 c1g5 f8e7",
    "e2e4 c7c6 d2d4 d7d5 b1c3 d5e4 c3e4 c8f5",
    "d2d4 d7d5 c2c4 c7c6 g1f3 g8f6 b1c3 e7e6",
    "e2e4 e7e5 g1f3 b8c6 f1c4 g8f6 d2d3 f8c5",
]


def configure(engine: chess.engine.SimpleEngine, hash_mb: int, eval_file: str | None = None) -> dict[str, int | str]:
    settings = {name: value for name, value in {"Hash": hash_mb, "Threads": 1, "Move Overhead": 0}.items()
                if name in engine.options}
    if eval_file:
        if "EvalFile" not in engine.options:
            raise ValueError("Selected engine does not support EvalFile")
        settings["EvalFile"] = str(pathlib.Path(eval_file).resolve())
    engine.configure(settings)
    return settings


def source_fingerprint() -> str:
    hasher = hashlib.sha256()
    for source in sorted((ROOT / "src/Engine").glob("*.cs")):
        hasher.update(source.name.encode()); hasher.update(b"\0"); hasher.update(source.read_bytes())
    return hasher.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", default=str(DEFAULT_ENGINE))
    parser.add_argument("--opponent", help="Opponent executable or .dll; defaults to the fetched Stockfish")
    parser.add_argument("--pairs", type=int, default=4)
    parser.add_argument("--movetime", type=float, default=0.1, help="Seconds per move, equally for both engines")
    parser.add_argument("--nodes", type=int, help="Use equal node limits instead of equal move time (not a wall-clock strength comparison)")
    parser.add_argument("--max-plies", type=int, default=400, help="Unfinished games remain unresolved, never counted as draws")
    parser.add_argument("--hash", type=int, default=64)
    parser.add_argument("--eval-file", help="Candidate EvalFile option")
    parser.add_argument("--opponent-eval-file", help="Opponent EvalFile option")
    parser.add_argument("--openings", help="Frozen JSON suite with legal UCI opening lines; each pair uses a distinct entry")
    parser.add_argument("--output", default="artifacts/matches/baseline")
    args = parser.parse_args()
    if args.pairs < 1 or args.movetime <= 0 or args.max_plies < 1 or (args.nodes is not None and args.nodes < 1) or not 1 <= args.hash <= 1024:
        parser.error("Pairs, time, nodes and maximum plies must be positive; Hash must be 1..1024 MiB")
    openings = OPENINGS
    opening_manifest = None
    if args.openings:
        opening_path = pathlib.Path(args.openings).resolve()
        opening_manifest = json.loads(opening_path.read_text(encoding="utf-8"))
        openings = [entry["moves"] for entry in opening_manifest["openings"]]
        if args.pairs > len(openings):
            parser.error("Requested more pairs than distinct suite entries")
        positions = set()
        for entry, line in zip(opening_manifest["openings"], openings, strict=True):
            board = chess.Board()
            for move in line.split(): board.push_uci(move)
            if entry.get("fen", board.fen()) != board.fen():
                parser.error("Opening suite FEN disagrees with its legal move history")
            if board.outcome(claim_draw=True) is not None:
                parser.error("Opening suite contains a terminal position")
            canonical = " ".join(board.fen().split()[:4])
            if canonical in positions:
                parser.error("Opening suite contains transposed duplicate positions")
            positions.add(canonical)
        opening_manifest = {"path": str(opening_path), "sha256": hashlib.sha256(opening_path.read_bytes()).hexdigest(),
                            "metadata": {key: value for key, value in opening_manifest.items() if key != "openings"}}
    stockfish_manifest = None
    if args.opponent:
        opponent_path = pathlib.Path(args.opponent).resolve()
    else:
        manifest_path = ROOT / "tools/stockfish/manifest.json"
        if not manifest_path.exists():
            parser.error("Run scripts/fetch_stockfish.py first, or provide --opponent")
        stockfish_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        opponent_path = ROOT / stockfish_manifest["executable"]
    candidate_path = pathlib.Path(args.engine).resolve()
    for model_path in (args.eval_file, args.opponent_eval_file):
        if model_path and not pathlib.Path(model_path).is_file():
            parser.error("Evaluator file does not exist: " + model_path)
    output = pathlib.Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    pgn_path = pathlib.Path(str(output) + ".pgn")
    report_path = pathlib.Path(str(output) + ".json")
    summary: dict = {
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "candidate": str(candidate_path), "opponent": str(opponent_path),
        "candidate_binary_sha256": hashlib.file_digest(candidate_path.open("rb"), "sha256").hexdigest(),
        "opponent_binary_sha256": hashlib.file_digest(opponent_path.open("rb"), "sha256").hexdigest(),
        "candidate_source_sha256": source_fingerprint() if candidate_path == DEFAULT_ENGINE else None,
        "stockfish_release": stockfish_manifest, "platform": platform.platform(),
        "hardware": {"processor": platform.processor(), "logical_processors": os.cpu_count()},
        "python_version": platform.python_version(),
        "opening_suite": opening_manifest,
        "pairs_requested": args.pairs, "limit": {"nodes": args.nodes} if args.nodes else {"seconds_per_move": args.movetime},
        "max_plies": args.max_plies, "wins": 0, "draws": 0, "losses": 0, "unresolved": 0,
        "forfeits": 0, "games": [], "interpretation": "Smoke-test sample; does not establish an Elo rating or superiority.",
    }
    for role, model_path in (("candidate", args.eval_file), ("opponent", args.opponent_eval_file)):
        if model_path:
            with pathlib.Path(model_path).open("rb") as source:
                summary[role + "_model_sha256"] = hashlib.file_digest(source, "sha256").hexdigest()
    started = time.monotonic()
    candidate = chess.engine.SimpleEngine.popen_uci(engine_command(candidate_path), timeout=15)
    try:
        opponent = chess.engine.SimpleEngine.popen_uci(engine_command(opponent_path), timeout=15)
        try:
            summary["candidate_name"] = candidate.id.get("name")
            summary["opponent_name"] = opponent.id.get("name")
            summary["candidate_options"] = configure(candidate, args.hash, args.eval_file)
            summary["opponent_options"] = configure(opponent, args.hash, args.opponent_eval_file)
            with pgn_path.open("w", encoding="utf-8") as pgn_file:
                for pair in range(args.pairs):
                    opening = openings[pair % len(openings)]
                    for candidate_white in (True, False):
                        board = chess.Board()
                        for text in opening.split():
                            board.push_uci(text)
                        initial_fen = board.fen()
                        game = chess.pgn.Game.from_board(board)
                        game.headers["Event"] = "Aster paired engine benchmark"
                        game.headers["Date"] = summary["timestamp_utc"][:10].replace("-", ".")
                        game.headers["Round"] = f"{pair + 1}.{1 if candidate_white else 2}"
                        game.headers["White"] = str(summary["candidate_name"] if candidate_white else summary["opponent_name"])
                        game.headers["Black"] = str(summary["opponent_name"] if candidate_white else summary["candidate_name"])
                        game.headers["TimeControl"] = "-"
                        game.headers["TimeLimit"] = f"{args.nodes} nodes/move" if args.nodes else f"{args.movetime}s/move"
                        node = game.end()
                        game_token = object()
                        termination = "maximum plies reached"
                        winner: bool | None = None
                        result = "*"
                        game_started = time.monotonic()
                        searches = []
                        for _ in range(args.max_plies):
                            outcome = board.outcome(claim_draw=True)
                            if outcome is not None:
                                result = outcome.result(); winner = outcome.winner
                                termination = outcome.termination.name.lower(); break
                            playing_candidate = board.turn == candidate_white
                            engine = candidate if playing_candidate else opponent
                            try:
                                limit = chess.engine.Limit(nodes=args.nodes) if args.nodes else chess.engine.Limit(time=args.movetime)
                                move_started = time.monotonic()
                                response = engine.play(board, limit, game=game_token, info=chess.engine.INFO_BASIC | chess.engine.INFO_SCORE)
                                if response.move not in board.legal_moves:
                                    raise chess.engine.EngineError(f"Illegal move: {response.move}")
                                score = response.info.get("score")
                                searches.append({"ply": len(board.move_stack) + 1,
                                                 "role": "candidate" if playing_candidate else "opponent",
                                                 "move": response.move.uci(), "depth": response.info.get("depth"),
                                                 "nodes": response.info.get("nodes"), "reported_seconds": response.info.get("time"),
                                                 "elapsed_seconds": round(time.monotonic() - move_started, 6),
                                                 "white_cp": score.white().score() if score else None,
                                                 "white_mate": score.white().mate() if score else None})
                                board.push(response.move); node = node.add_variation(response.move)
                            except (chess.engine.EngineError, TimeoutError) as error:
                                winner = not board.turn; result = "1-0" if winner else "0-1"
                                termination = "engine forfeit: " + str(error)
                                summary["forfeits"] += 1; break
                        else:
                            outcome = board.outcome(claim_draw=True)
                            if outcome is not None:
                                result = outcome.result(); winner = outcome.winner
                                termination = outcome.termination.name.lower()
                        game.headers["Result"] = result
                        game.headers["Termination"] = termination
                        if result == "*": summary["unresolved"] += 1
                        elif winner is None: summary["draws"] += 1
                        elif winner == candidate_white: summary["wins"] += 1
                        else: summary["losses"] += 1
                        detail = {"pair": pair + 1, "candidate_color": "white" if candidate_white else "black", "opening": opening,
                                  "initial_fen": initial_fen, "result": result, "termination": termination,
                                  "plies": len(board.move_stack), "seconds": round(time.monotonic() - game_started, 3), "searches": searches}
                        summary["games"].append(detail)
                        pgn_file.write(str(game) + "\n\n"); pgn_file.flush()
                        summary["seconds"] = round(time.monotonic() - started, 3)
                        report_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
                        print(json.dumps({key: value for key, value in detail.items() if key != "searches"}), flush=True)
                        if summary["forfeits"]:
                            raise RuntimeError("Engine forfeit; inspect the saved report. Match stopped because process state may be invalid.")
        finally:
            opponent.quit()
    finally:
        candidate.quit()
    print(json.dumps({key: summary[key] for key in ("wins", "draws", "losses", "unresolved", "forfeits", "seconds")}), flush=True)


if __name__ == "__main__":
    main()
