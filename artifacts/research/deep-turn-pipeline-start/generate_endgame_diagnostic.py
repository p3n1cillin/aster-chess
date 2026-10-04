"""Preserve fresh played endgames, native teacher labels and source outcomes."""
import argparse
import collections
import hashlib
import json
import pathlib
import random
import re
import time

import chess
import chess.engine
import chess.pgn

from match import OPENINGS
from uci_client import ROOT, UciClient, engine_command


def digest(path): return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def key(board): return " ".join(board.fen().split()[:4])


def phase(board):
    return sum(len(board.pieces(kind, color)) * weight for color in (chess.WHITE, chess.BLACK)
               for kind, weight in ((chess.KNIGHT, 1), (chess.BISHOP, 1), (chess.ROOK, 2), (chess.QUEEN, 4)))


def labels(teacher, board, nodes):
    infos = teacher.analyse(board.copy(stack=False), chess.engine.Limit(nodes=nodes), multipv=2, game=object())
    result = []
    for info in infos:
        score = info["score"].white()
        result.append({"white_cp": score.score(), "white_mate": score.mate(), "depth": info.get("depth"),
                       "reported_nodes": info.get("nodes"), "pv": [m.uci() for m in info.get("pv", [])]})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--positions", type=int, default=512)
    parser.add_argument("--games", type=int, default=512)
    parser.add_argument("--max-plies", type=int, default=240)
    parser.add_argument("--per-game", type=int, default=4)
    parser.add_argument("--play-nodes", type=int, default=512)
    parser.add_argument("--sample-nodes", type=int, default=8192)
    parser.add_argument("--verify-nodes", type=int, default=65536)
    parser.add_argument("--seed", type=int, default=20261023)
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--exclude-suite", action="append", default=[])
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if min(args.positions, args.games, args.max_plies, args.per_game, args.play_nodes, args.sample_nodes, args.verify_nodes) < 1:
        parser.error("Positive bounded budgets required")
    output = pathlib.Path(args.output)
    manifest_path = pathlib.Path(str(output) + ".manifest.json")
    pgn_path = pathlib.Path(str(output) + ".source.pgn")
    if any(path.exists() for path in (output, manifest_path, pgn_path)): parser.error("Preserve previous diagnostics")
    exclusions, excluded = [], set()
    for name in args.exclude:
        path = pathlib.Path(name)
        excluded.update(key(chess.Board(json.loads(line)["fen"])) for line in path.read_text().splitlines() if line.strip())
        exclusions.append({"path": str(path), "sha256": digest(path), "kind": "data"})
    for name in args.exclude_suite:
        path = pathlib.Path(name); suite = json.loads(path.read_text())
        excluded.update(key(chess.Board(e["fen"])) for e in suite.get("openings", suite.get("positions", [])))
        exclusions.append({"path": str(path), "sha256": digest(path), "kind": "suite"})
    teacher_manifest = json.loads((ROOT / "tools/stockfish/manifest.json").read_text())
    teacher_path = ROOT / teacher_manifest["executable"]
    if digest(teacher_path) != teacher_manifest["executable_sha256"]: raise ValueError("Changed teacher")
    output.parent.mkdir(parents=True, exist_ok=True)
    metadata = {"schema": 1, "complete": False, "parameters": vars(args), "teacher": teacher_manifest,
                "teacher_options": {"Threads": 1, "Hash": 64}, "exclusions": exclusions,
                "generator_sha256": digest(__file__), "positions_written": 0,
                "search_context": "Each label starts from FEN without played history; full source history and result are retained separately.",
                "interpretation": "Fresh source games, static and bounded search labels. Played results are descriptive, not oracle labels or strength claims."}
    manifest_path.write_text(json.dumps(metadata, indent=2) + "\n")
    rng = random.Random(args.seed); rows, games, seen = [], [], set()
    started = time.monotonic()
    with chess.engine.SimpleEngine.popen_uci(engine_command(teacher_path), timeout=30) as player, pgn_path.open("w", encoding="utf-8") as pgn:
        player.configure({"Threads": 1, "Hash": 64})
        for game_id in range(args.games):
            board = chess.Board(); opening_index = rng.randrange(len(OPENINGS))
            for text in OPENINGS[opening_index].split(): board.push_uci(text)
            token = object(); pending = []
            while len(board.move_stack) < args.max_plies and board.outcome(claim_draw=True) is None:
                ply = len(board.move_stack); canonical = key(board)
                if (len(rows) + len(pending) < args.positions and len(pending) < args.per_game and ply >= 40 and ply % 4 == 0
                    and phase(board) <= 8 and len(board.piece_map()) <= 12 and board.halfmove_clock < 90
                    and not board.is_check() and canonical not in excluded and canonical not in seen):
                    pending.append({"fen": board.fen(en_passant="fen"), "game": game_id, "ply": ply,
                                    "phase": phase(board), "pieces": len(board.piece_map()), "opening_index": opening_index,
                                    "history_uci": [move.uci() for move in board.move_stack]})
                    seen.add(canonical)
                if rng.random() < .03:
                    selected = rng.choice(list(board.legal_moves))
                else:
                    selected = player.play(board, chess.engine.Limit(nodes=args.play_nodes), game=token).move
                if selected not in board.legal_moves: raise ValueError("Illegal source-game move")
                board.push(selected)
            outcome = board.outcome(claim_draw=True)
            result = outcome.result() if outcome else "*"
            termination = outcome.termination.name.lower() if outcome else "maximum_plies_unresolved"
            game = chess.pgn.Game.from_board(board)
            game.headers.update(Event="Aster fresh endgame diagnostic", Site="local", Date="????.??.??", Round=str(game_id + 1),
                                White=player.id.get("name", "teacher"), Black=player.id.get("name", "teacher"), Result=result,
                                Termination=termination, SourceGame=str(game_id), PlayNodes=str(args.play_nodes), RandomProbability="0.03")
            pgn.write(str(game) + "\n\n"); pgn.flush()
            games.append({"game": game_id, "result": result, "termination": termination, "plies": len(board.move_stack), "positions": len(pending)})
            for row in pending:
                row.update(source_result=result, source_termination=termination)
            rows.extend(pending)
            if game_id % 25 == 0:
                print(json.dumps({"stage": "source_games", "games": len(games), "positions": len(rows), "seconds": round(time.monotonic() - started, 2)}), flush=True)
            if len(rows) == args.positions: break
    metadata.update(source_games=games, source_pgn_sha256=digest(pgn_path),
                    source_unresolved=sum(g["result"] == "*" for g in games))
    with chess.engine.SimpleEngine.popen_uci(engine_command(teacher_path), timeout=30) as teacher, UciClient(teacher_path) as static, output.open("w", encoding="utf-8") as destination:
        teacher.configure({"Threads": 1, "Hash": 64})
        static.send("setoption name Threads value 1"); static.send("setoption name Hash value 64"); static.ready()
        for i, row in enumerate(rows):
            board = chess.Board(row["fen"])
            static.send("position fen " + row["fen"])
            trace = static.command("eval", "Final evaluation", timeout=10)
            match = re.search(r"Final evaluation\s+([+-]\d+\.\d+)\s+\(white side\)", trace)
            if not match: raise ValueError("Unexpected static trace: " + trace)
            row["static_white_cp"] = int(round(float(match.group(1)) * 100))
            row["sample"] = labels(teacher, board, args.sample_nodes)
            row["verified"] = labels(teacher, board, args.verify_nodes)
            row["id"] = f"endgame-{i + 1:04}"
            destination.write(json.dumps(row, separators=(",", ":")) + "\n")
            if (i + 1) % 64 == 0:
                destination.flush()
                print(json.dumps({"stage": "labels", "positions": i + 1, "seconds": round(time.monotonic() - started, 2)}), flush=True)
    for entry in exclusions:
        if digest(entry["path"]) != entry["sha256"]: raise ValueError("Exclusion changed during generation")
    metadata.update(complete=len(rows) == args.positions, positions_written=len(rows), data_sha256=digest(output),
                    seconds=round(time.monotonic() - started, 3), source_outcomes=dict(collections.Counter(g["result"] for g in games)))
    manifest_path.write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps({k: metadata[k] for k in ("complete", "positions_written", "source_unresolved", "source_outcomes", "seconds")}))
    if not metadata["complete"]: raise ValueError("Game budget exhausted; partial artifacts preserved")


if __name__ == "__main__": main()
