"""Record KPK positions actually reached in a saved, complete paired match."""
import argparse
import hashlib
import json
import pathlib

import chess
import chess.pgn


def digest(path): return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prefix")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = pathlib.Path(args.output)
    if output.exists(): parser.error("Preserve previous coverage")
    pgn = pathlib.Path(args.prefix + ".pgn"); report_path = pathlib.Path(args.prefix + ".json")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    rows = []; count = 0
    with pgn.open(encoding="utf-8") as source:
        while (game := chess.pgn.read_game(source)) is not None:
            assert not game.errors
            board = game.board(); positions = []
            for move in game.mainline_moves():
                board.push(move)
                if len(board.piece_map()) == 3 and (board.pawns & board.occupied).bit_count() == 1:
                    positions.append({"ply": len(board.move_stack), "fen": board.fen()})
            if positions: rows.append({"round": game.headers["Round"], "result": game.headers["Result"], "positions": positions})
            count += 1
    assert count == len(report["games"]) == 2 * report["pairs_requested"]
    result = {"complete": True, "games": count, "games_reaching_kpk": len(rows),
              "kpk_positions": sum(len(row["positions"]) for row in rows), "details": rows,
              "pgn_sha256": digest(pgn), "report_sha256": digest(report_path), "script_sha256": digest(__file__),
              "interpretation": "Observed mainline coverage only. Does not count KPK in searched variations or attribute match outcomes to this feature."}
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("games", "games_reaching_kpk", "kpk_positions")}))


if __name__ == "__main__": main()
