"""Create a bounded tactical regression suite from fresh, teacher-verified games."""
from research_reference import research_text
import argparse
import hashlib
import json
import pathlib
import random

import chess
import chess.engine

from match import OPENINGS
from uci_client import ROOT, engine_command


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--positions", type=int, default=32)
    parser.add_argument("--games", type=int, default=64)
    parser.add_argument("--seed", type=int, default=20261005)
    parser.add_argument("--exclude", action="append", default=[], help="Dataset whose positions must not enter this suite; repeatable")
    parser.add_argument("--exclude-suite", action="append", default=[], help="Earlier tactical/opening fixtures to exclude")
    parser.add_argument("--quiet-only", action="store_true", help="Require a non-capture, non-promotion, non-checking best move")
    parser.add_argument("--output", default="tests/fixtures/tactics-v1.json")
    args = parser.parse_args()
    if min(args.positions, args.games) < 1:
        parser.error("Position and game budgets must be positive")
    output = pathlib.Path(args.output)
    if output.exists():
        parser.error("Suite already exists; do not silently replace frozen regression fixtures")
    excluded = set()
    exclusions = []
    for name in args.exclude:
        path = pathlib.Path(name)
        with path.open(encoding="utf-8") as data:
            excluded.update(" ".join(chess.Board(json.loads(line)["fen"]).fen().split()[:4]) for line in data if line.strip())
        exclusions.append({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    for name in args.exclude_suite:
        path = pathlib.Path(name)
        suite = json.loads(path.read_text(encoding="utf-8"))
        for entry in suite.get("positions", suite.get("openings", [])):
            excluded.add(" ".join(chess.Board(entry["fen"]).fen().split()[:4]))
        exclusions.append({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    manifest = json.loads((ROOT / research_text('opponent_manifest')).read_text(encoding="utf-8"))
    teacher_path = ROOT / manifest["executable"]
    if hashlib.sha256(teacher_path.read_bytes()).hexdigest() != manifest["executable_sha256"]:
        raise ValueError("Teacher binary does not match its pinned manifest")
    rng = random.Random(args.seed); positions = []
    with chess.engine.SimpleEngine.popen_uci(engine_command(ROOT / manifest["executable"]), timeout=30) as teacher:
        teacher.configure({"Threads": 1, "Hash": 64})
        for game_id in range(args.games):
            board = chess.Board()
            for text in OPENINGS[rng.randrange(len(OPENINGS))].split(): board.push_uci(text)
            game = object()
            for ply in range(8, 140):
                if board.outcome(claim_draw=True) is not None: break
                selected = None
                canonical = " ".join(board.fen().split()[:4])
                if ply >= 12 and ply % 5 == 0 and canonical not in excluded and board.legal_moves.count() > 1:
                    infos = teacher.analyse(board, chess.engine.Limit(nodes=5000), multipv=2, game=game)
                    first, second = infos[0], infos[1]
                    score = first["score"].pov(board.turn).score(mate_score=30000)
                    alternative = second["score"].pov(board.turn).score(mate_score=30000)
                    if first.get("pv"): selected = first["pv"][0]
                    eligible = selected is not None and (not args.quiet_only
                        or (not board.is_capture(selected) and not selected.promotion and not board.gives_check(selected)))
                    if eligible and score is not None and alternative is not None and score - alternative >= 180:
                        verified = teacher.analyse(board, chess.engine.Limit(nodes=50000), multipv=2, game=game)
                        vfirst, vsecond = verified[0], verified[1]
                        sv = vfirst["score"].pov(board.turn).score(mate_score=30000)
                        av = vsecond["score"].pov(board.turn).score(mate_score=30000)
                        if vfirst["pv"][0] == selected and sv is not None and av is not None and sv - av >= 120:
                            positions.append({"id": f"tactic-{len(positions) + 1:03}", "fen": board.fen(en_passant="fen"),
                                              "best_moves": [selected.uci()], "teacher_depth": vfirst.get("depth"),
                                              "teacher_nodes": vfirst.get("nodes"), "score_gap_cp": sv - av, "source_game": game_id})
                            excluded.add(canonical)
                            if len(positions) >= args.positions: break
                if rng.random() < .1: selected = rng.choice(list(board.legal_moves))
                elif selected is None: selected = teacher.play(board, chess.engine.Limit(nodes=256), game=game).move
                board.push(selected)
            if len(positions) >= args.positions: break
    if len(positions) < args.positions:
        raise RuntimeError("Fixture budget exhausted; increase --games or reduce --positions")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"schema": 2, "seed": args.seed, "teacher": manifest, "positions": positions,
                                 "quiet_only": args.quiet_only, "exclusions": exclusions, "games_budget": args.games,
                                 "games_used": game_id + 1, "sample_nodes": 5000, "verification_nodes": 50000,
                                 "teacher_options": {"Threads": 1, "Hash": 64},
                                 "generator_sha256": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
                                 "interpretation": "Fresh generated games, excluded from specified training data; stable unique move under two teacher budgets. Not an exhaustive proof of optimality."}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"positions": len(positions), "games": game_id + 1, "output": str(output)}))


if __name__ == "__main__":
    main()
