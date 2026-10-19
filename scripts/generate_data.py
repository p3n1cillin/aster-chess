'Generate bounded, deduplicated legal positions and reference engine teacher labels.'
from __future__ import annotations
from research_reference import research_text

import argparse
import datetime
import hashlib
import json
import pathlib
import random
import time

import chess
import chess.engine

from match import OPENINGS
from uci_client import ROOT, engine_command


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--positions", type=int, default=20000)
    parser.add_argument("--label-nodes", type=int, default=2048)
    parser.add_argument("--play-nodes", type=int, default=128)
    parser.add_argument("--max-games", type=int, default=3000)
    parser.add_argument("--max-plies", type=int, default=160)
    parser.add_argument("--seed", type=int, default=20261003)
    parser.add_argument("--random-probability", type=float, default=.08)
    parser.add_argument("--max-abs-cp", type=int, default=1500)
    parser.add_argument("--openings", help="Frozen opening suite for diverse training starts")
    parser.add_argument("--exclude-suite", action="append", default=[], help="Exclude canonical positions from a regression opening suite")
    parser.add_argument("--output", default="artifacts/data/teacher-20k.jsonl")
    args = parser.parse_args()
    if min(args.positions, args.label_nodes, args.play_nodes, args.max_games, args.max_plies) < 1:
        parser.error("Generation budgets must be positive")
    if not 0 <= args.random_probability <= 1 or args.max_abs_cp < 1:
        parser.error("Invalid sampling parameters")
    output = pathlib.Path(args.output).resolve()
    if output.exists():
        parser.error("Output already exists; use a new path to preserve the previous dataset")
    manifest = json.loads((ROOT / research_text('opponent_manifest')).read_text(encoding="utf-8"))
    teacher_path = ROOT / manifest["executable"]
    if hashlib.sha256(teacher_path.read_bytes()).hexdigest() != manifest["executable_sha256"]:
        raise ValueError("Teacher binary differs from the pinned manifest")
    openings = OPENINGS
    opening_manifest = None
    if args.openings:
        path = pathlib.Path(args.openings)
        fixture = json.loads(path.read_text(encoding="utf-8"))
        openings = [entry["moves"] for entry in fixture["openings"]]
        for entry, line in zip(fixture["openings"], openings, strict=True):
            board = chess.Board()
            for move in line.split(): board.push_uci(move)
            if board.fen() != entry["fen"] or board.outcome(claim_draw=True) is not None:
                raise ValueError("Invalid training opening")
        if not openings: raise ValueError("Empty training opening suite")
        opening_manifest = {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "positions": len(openings)}
    exclusions = []; excluded = set()
    for name in args.exclude_suite:
        path = pathlib.Path(name); fixture = json.loads(path.read_text(encoding="utf-8"))
        excluded.update(" ".join(chess.Board(entry["fen"]).fen().split()[:4]) for entry in fixture["openings"])
        exclusions.append({"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "positions": len(fixture["openings"])})
    output.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    seen: set[str] = set()
    count = 0
    started = time.monotonic()
    metadata = {"schema": 1, "purpose": "teacher-distillation prototype, not outcome-based self-play learning",
                "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "teacher": manifest,
                "teacher_options": {"Threads": 1, "Hash": 64}, "parameters": vars(args),
                "sampling": f"every third ply; skip checks, terminal/claimable draws, rule-50 proximity and abs(score)>{args.max_abs_cp}cp",
                "play_policy": f"teacher PV at sampled positions, low-node teacher otherwise; {args.random_probability:.1%} random legal moves",
                "training_openings": opening_manifest, "regression_exclusions": exclusions,
                "deduplication": "FEN first four fields with legally available en passant; duplicates removed globally before game-level splitting"}
    metadata_path = pathlib.Path(str(output) + ".manifest.json")
    with chess.engine.SimpleEngine.popen_uci(engine_command(teacher_path), timeout=20) as teacher, output.open("w", encoding="utf-8") as data:
        teacher.configure({"Threads": 1, "Hash": 64})
        for game_id in range(args.max_games):
            board = chess.Board()
            opening_index = rng.randrange(len(openings))
            for text in openings[opening_index].split():
                board.push_uci(text)
            game_token = object()
            for ply in range(len(board.move_stack), args.max_plies):
                if board.outcome(claim_draw=True) is not None:
                    break
                selected = None
                fen = board.fen(en_passant="fen")
                canonical = " ".join(board.fen().split()[:4])
                if ply % 3 == 0 and not board.is_check() and board.halfmove_clock < 60 and canonical not in seen and canonical not in excluded:
                    info = teacher.analyse(board, chess.engine.Limit(nodes=args.label_nodes), game=game_token,
                                           info=chess.engine.INFO_SCORE | chess.engine.INFO_PV | chess.engine.INFO_BASIC)
                    score = info["score"].white().score()
                    if info.get("pv"):
                        selected = info["pv"][0]
                    if score is not None and abs(score) <= args.max_abs_cp:
                        row = {"fen": fen, "score_white_cp": score, "game": game_id, "ply": ply,
                               "depth": info.get("depth"), "nodes": info.get("nodes"), "opening_index": opening_index}
                        data.write(json.dumps(row, separators=(",", ":")) + "\n")
                        seen.add(canonical); count += 1
                        if count % 1000 == 0:
                            data.flush()
                            print(json.dumps({"positions": count, "games": game_id + 1, "seconds": round(time.monotonic() - started, 2)}), flush=True)
                        if count >= args.positions:
                            break
                if rng.random() < args.random_probability:
                    selected = rng.choice(list(board.legal_moves))
                elif selected is None:
                    selected = teacher.play(board, chess.engine.Limit(nodes=args.play_nodes), game=game_token).move
                if selected not in board.legal_moves:
                    raise RuntimeError(f"Teacher selected an illegal move at {fen}: {selected}")
                board.push(selected)
            if count >= args.positions:
                break
        metadata["games_generated"] = game_id + 1
    with output.open("rb") as file:
        metadata["data_sha256"] = hashlib.file_digest(file, "sha256").hexdigest()
    metadata["positions_written"] = count
    metadata["seconds"] = round(time.monotonic() - started, 3)
    metadata["complete"] = count == args.positions
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"positions": count, "games": metadata["games_generated"], "complete": metadata["complete"], "seconds": metadata["seconds"]}), flush=True)
    if not metadata["complete"]:
        raise RuntimeError("Maximum game budget exhausted; partial dataset and manifest have been preserved")


if __name__ == "__main__":
    main()
