"""Independently check counterfactual pairs and preservation of source game groups."""
import argparse
import hashlib
import json
import pathlib

import chess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("augmented")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    source = pathlib.Path(args.source)
    augmented = pathlib.Path(args.augmented)
    originals = [json.loads(line) for line in source.read_text().splitlines() if line.strip()]
    rows = [json.loads(line) for line in augmented.read_text().splitlines() if line.strip()]
    if rows[:len(originals)] != originals:
        raise ValueError("Original rows changed or reordered")
    parents = {row["fen"]: row for row in originals}
    extras = rows[len(originals):]
    if not extras:
        raise ValueError("No paired examples")
    for row in extras:
        parent = parents[row["source_fen"]]
        if row.get("counterfactual_turn") is not True or row["game"] != parent["game"]:
            raise ValueError("Pair lacks marker or crosses game groups")
        before, after = chess.Board(parent["fen"]), chess.Board(row["fen"])
        if before.ep_square is not None or after.ep_square is not None:
            raise ValueError("En passant turn pair")
        before.turn = not before.turn
        if before.fen(en_passant="fen") != after.fen(en_passant="fen"):
            raise ValueError("Pair changed fields other than side to move")
        if not after.is_valid() or after.is_check() or after.outcome(claim_draw=True) is not None:
            raise ValueError("Invalid, checked or terminal counterfactual")
        if "ply" in row or row.get("source_ply") != parent.get("ply"):
            raise ValueError("Counterfactual wrongly claims played history")
    report = {"status": "passed", "source_positions": len(originals), "paired_positions": len(extras),
              "original_rows_preserved": True, "cross_game_pairs": 0,
              "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "augmented_sha256": hashlib.sha256(augmented.read_bytes()).hexdigest(),
              "auditor_sha256": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
              "interpretation": "Opposite-turn FEN labels without histories; parent groups are preserved for game-level splits."}
    pathlib.Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
