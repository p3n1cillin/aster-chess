"""Freeze diverse legal opening positions using a pinned development teacher."""
from __future__ import annotations
from research_reference import research_text

import argparse
import hashlib
import json
import pathlib
import random

import chess
import chess.engine

from uci_client import ROOT, engine_command


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--positions", type=int, default=64)
    parser.add_argument("--attempts", type=int, default=512)
    parser.add_argument("--plies", type=int, default=16)
    parser.add_argument("--seed", type=int, default=20261006)
    parser.add_argument("--nodes", type=int, default=2048)
    parser.add_argument("--verify-nodes", type=int, default=20000)
    parser.add_argument("--max-cp", type=int, default=80)
    parser.add_argument("--exclude", action="append", default=[], help="Training JSONL whose canonical positions must be excluded; repeatable")
    parser.add_argument("--exclude-suite", action="append", default=[], help="Prior opening fixture to exclude; may be repeated")
    parser.add_argument("--output", default="tests/fixtures/openings-v1.json")
    args = parser.parse_args()
    if min(args.positions, args.attempts, args.nodes, args.verify_nodes, args.max_cp) < 1 or not 8 <= args.plies <= 40:
        parser.error("Positive budgets required; plies must be 8..40")
    output = pathlib.Path(args.output)
    if output.exists(): parser.error("Do not replace frozen suites")
    excluded = set()
    exclusions = []
    for name in args.exclude:
        path = pathlib.Path(name)
        positions_to_exclude = {" ".join(chess.Board(json.loads(line)["fen"]).fen().split()[:4])
                               for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}
        excluded.update(positions_to_exclude)
        exclusions.append({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "positions": len(positions_to_exclude)})
    prior_suites = []
    for name in args.exclude_suite:
        path = pathlib.Path(name)
        prior = json.loads(path.read_text(encoding="utf-8"))
        for entry in prior["openings"]:
            excluded.add(" ".join(chess.Board(entry["fen"]).fen().split()[:4]))
        prior_suites.append({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "positions": len(prior["openings"])})
    manifest = json.loads((ROOT / research_text('opponent_manifest')).read_text(encoding="utf-8"))
    teacher_path = ROOT / manifest["executable"]
    if hashlib.sha256(teacher_path.read_bytes()).hexdigest() != manifest["executable_sha256"]:
        raise ValueError("Teacher binary does not match its pinned manifest")
    rng = random.Random(args.seed)
    positions = []
    with chess.engine.SimpleEngine.popen_uci(engine_command(ROOT / manifest["executable"]), timeout=30) as teacher:
        teacher.configure({"Threads": 1, "Hash": 64})
        for attempt in range(args.attempts):
            board = chess.Board(); game = object(); moves = []
            for _ in range(args.plies):
                if board.outcome(claim_draw=True) is not None: break
                infos = teacher.analyse(board, chess.engine.Limit(nodes=args.nodes), multipv=min(4, board.legal_moves.count()), game=game)
                best = infos[0]["score"].pov(board.turn).score()
                if best is None: break
                # Sample near-best moves, not random blunders, from the start.
                options = [info["pv"][0] for info in infos if info.get("pv") and info["score"].pov(board.turn).score() is not None
                           and best - info["score"].pov(board.turn).score() <= 60]
                selected = rng.choice(options); moves.append(selected.uci()); board.push(selected)
            canonical = " ".join(board.fen().split()[:4])
            if len(moves) != args.plies or canonical in excluded or board.outcome(claim_draw=True) is not None: continue
            # Clear history/cache before the stronger balance check.
            checked = teacher.analyse(board, chess.engine.Limit(nodes=args.verify_nodes), game=object())
            score = checked["score"].white().score()
            if score is None or abs(score) > args.max_cp: continue
            positions.append({"id": f"opening-{len(positions) + 1:03}", "moves": " ".join(moves),
                              "fen": board.fen(), "teacher_white_cp": score, "teacher_depth": checked.get("depth"), "attempt": attempt})
            excluded.add(canonical)
            if len(positions) == args.positions: break
    if len(positions) < args.positions: raise RuntimeError("Budget exhausted before requested suite size")
    rng.shuffle(positions)
    data = {"schema": 1, "seed": args.seed, "plies": args.plies, "selection_nodes": args.nodes,
            "verification_nodes": args.verify_nodes, "max_abs_teacher_cp": args.max_cp,
            "teacher": manifest, "training_exclusion": exclusions[0] if len(exclusions) == 1 else None,
            "training_exclusions": exclusions, "prior_suites_excluded": prior_suites, "attempts_used": attempt + 1,
            "teacher_options": {"Threads": 1, "Hash": 64},
            "generator_sha256": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
            "interpretation": "Seeded near-best MultiPV continuations from the start, distinct final positions, balanced under a bounded teacher check. Teacher scores do not prove equality; this is a regression suite, not an independent final superiority test.",
            "openings": positions}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"positions": len(positions), "attempts": attempt + 1, "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}))


if __name__ == "__main__": main()
