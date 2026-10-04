"""Audit complete KPK games and identify theoretical losses versus conversion failures."""
import argparse
import collections
import hashlib
import json
import pathlib

import chess
import chess.pgn
import chess.syzygy


def digest(path): return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prefix")
    parser.add_argument("--oracle", default="tools/syzygy-development-v1")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(); output = pathlib.Path(args.output)
    if output.exists(): parser.error("Preserve previous diagnostics")
    path = pathlib.Path(args.prefix + ".json"); pgn = pathlib.Path(args.prefix + ".pgn")
    report = json.loads(path.read_text()); suite = json.loads(pathlib.Path(report["opening_suite"]["path"]).read_text())
    counters = {name: collections.Counter() for name in ("candidate", "opponent")}; rows = []
    with chess.syzygy.open_tablebase(args.oracle) as oracle, pgn.open() as source:
        for detail in report["games"]:
            game = chess.pgn.read_game(source); assert game is not None and not game.errors
            board = game.board(); setup = suite["openings"][detail["pair"] - 1]
            assert board.fen() == setup["start_fen"] == detail["initial_fen"]
            pawn_color = chess.WHITE if board.pieces(chess.PAWN, chess.WHITE) else chess.BLACK
            candidate_color = detail["candidate_color"] == "white"
            pawn_role = "candidate" if pawn_color == candidate_color else "opponent"
            defender_role = "opponent" if pawn_role == "candidate" else "candidate"
            won = setup["oracle_wdl"] != 0; initial = oracle.probe_wdl(board)
            assert initial == setup["oracle_wdl"]
            promotions = []; degradations = []
            for ply, move in enumerate(game.mainline_moves(), 1):
                before = oracle.probe_wdl(board); role = "candidate" if board.turn == candidate_color else "opponent"
                board.push(move)
                after = -oracle.probe_wdl(board)
                if after < before:
                    degradations.append({"ply": ply, "role": role, "move": move.uci(), "from_wdl": before, "to_wdl": after, "fen_after": board.fen()})
                    counters[role]["theoretical_wdl_degradations"] += 1
                if move.promotion:
                    promotions.append({"ply": ply, "role": role, "move": move.uci(), "safe_win": after > 0})
            actual = board.outcome(claim_draw=True)
            assert actual is not None and actual.result() == detail["result"]
            if won:
                counters[pawn_role]["initial_wins_as_pawn_side"] += 1
                counters[pawn_role]["converted_to_checkmate"] += actual.winner == pawn_color
                counters[pawn_role]["safe_promotions"] += any(p["role"] == pawn_role and p["safe_win"] for p in promotions)
                counters[pawn_role]["post_promotion_draws"] += actual.winner is None and any(p["role"] == pawn_role and p["safe_win"] for p in promotions)
            else:
                counters[defender_role]["initial_draws_as_defender"] += 1
                counters[defender_role]["draws_held_as_defender"] += actual.winner is None
            rows.append({"pair": detail["pair"], "candidate_color": detail["candidate_color"], "stratum": setup["stratum"],
                         "pawn_role": pawn_role, "initially_won": won, "result": detail["result"], "termination": detail["termination"],
                         "promotions": promotions, "theoretical_wdl_degradations": degradations})
        assert chess.pgn.read_game(source) is None
    result = {"complete": True, "games": len(rows), "roles": {k: dict(v) for k, v in counters.items()}, "details": rows,
              "report_sha256": digest(path), "pgn_sha256": digest(pgn), "suite_sha256": digest(report["opening_suite"]["path"]),
              "oracle_manifest_sha256": digest(pathlib.Path(args.oracle) / "manifest.json"), "script_sha256": digest(__file__),
              "interpretation": "WDL edges ignore clock/history; actual completed outcomes use retained history and claimable game rules. A safe promotion is not counted as a completed win."}
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"games": len(rows), "roles": result["roles"]}))


if __name__ == "__main__": main()
