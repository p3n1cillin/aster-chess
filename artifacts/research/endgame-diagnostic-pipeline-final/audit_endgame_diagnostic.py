"""Audit source PGNs, played histories, exclusions and native endgame labels."""
import argparse
import collections
import json
import pathlib

import chess
import chess.pgn

from generate_endgame_diagnostic import digest, key, phase
from uci_client import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = pathlib.Path(args.output)
    if output.exists(): parser.error("Preserve prior audit")
    data = pathlib.Path(args.data)
    manifest = json.loads(pathlib.Path(str(data) + ".manifest.json").read_text())
    rows = [json.loads(line) for line in data.read_text().splitlines() if line.strip()]
    assert manifest["complete"] and manifest["data_sha256"] == digest(data)
    assert manifest["positions_written"] == len(rows) == manifest["parameters"]["positions"]
    teacher = manifest["teacher"]
    assert digest(ROOT / teacher["executable"]) == teacher["executable_sha256"]
    excluded = set()
    for entry in manifest["exclusions"]:
        path = pathlib.Path(entry["path"]); assert digest(path) == entry["sha256"]
        if entry["kind"] == "data": values = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
        else:
            suite = json.loads(path.read_text()); values = suite.get("openings", suite.get("positions", []))
        excluded.update(key(chess.Board(value["fen"])) for value in values)
    pgn_path = pathlib.Path(str(data) + ".source.pgn")
    assert digest(pgn_path) == manifest["source_pgn_sha256"]
    games = []
    with pgn_path.open() as source:
        while (game := chess.pgn.read_game(source)) is not None:
            assert not game.errors
            games.append(game)
    assert len(games) == len(manifest["source_games"])
    for i, (game, detail) in enumerate(zip(games, manifest["source_games"])):
        assert detail["game"] == i and game.headers["SourceGame"] == str(i)
        end = game.end().board()
        assert len(end.move_stack) == detail["plies"]
        outcome = end.outcome(claim_draw=True)
        assert (outcome.result() if outcome else "*") == detail["result"] == game.headers["Result"]
        assert (outcome.termination.name.lower() if outcome else "maximum_plies_unresolved") == detail["termination"]
        assert game.headers["Termination"] == detail["termination"]
        if outcome is None: assert len(end.move_stack) == manifest["parameters"]["max_plies"]
    seen = set(); counts = collections.Counter(); native_mates = 0
    for row in rows:
        board = chess.Board()
        source_moves = list(games[row["game"]].mainline_moves())
        assert row["history_uci"] == [m.uci() for m in source_moves[:row["ply"]]]
        for text in row["history_uci"]: board.push_uci(text)
        assert len(board.move_stack) == row["ply"] and board.fen(en_passant="fen") == row["fen"]
        assert board.is_valid() and not board.is_check() and board.outcome(claim_draw=True) is None
        assert row["phase"] == phase(board) <= 8 and row["pieces"] == len(board.piece_map()) <= 12
        canonical = key(board)
        assert canonical not in excluded and canonical not in seen
        seen.add(canonical); counts[row["game"]] += 1
        detail = manifest["source_games"][row["game"]]
        assert row["source_result"] == detail["result"] and row["source_termination"] == detail["termination"]
        for tier in ("sample", "verified"):
            assert 1 <= len(row[tier]) <= 2
            first_moves = []
            for label in row[tier]:
                assert (label["white_cp"] is None) != (label["white_mate"] is None)
                replay = chess.Board(row["fen"])
                assert label["pv"]
                for text in label["pv"]: replay.push_uci(text)
                first_moves.append(label["pv"][0])
            assert len(set(first_moves)) == len(first_moves)
        native_mates += row["verified"][0]["white_mate"] is not None
    assert all(count <= manifest["parameters"]["per_game"] for count in counts.values())
    assert all(counts[g["game"]] == g["positions"] for g in manifest["source_games"])
    unresolved = sum(g["result"] == "*" for g in manifest["source_games"])
    assert unresolved == manifest["source_unresolved"]
    report = {"passed": True, "positions": len(rows), "source_games": len(games), "source_games_with_positions": len(counts),
              "source_unresolved": unresolved, "native_mate_labels": native_mates, "exact_overlaps": 0,
              "data_sha256": digest(data), "source_pgn_sha256": digest(pgn_path), "auditor_sha256": digest(__file__),
              "interpretation": "Independent full-history/PGN, native label/PV and exclusion checks. No oracle outcomes or strength inference."}
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__": main()
