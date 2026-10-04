"""Independently audit saved match PGNs against their JSON report."""
import argparse
import json
import pathlib

import chess.pgn


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prefix", help="Path prefix without .pgn or .json")
    args = parser.parse_args()
    report = json.loads(pathlib.Path(args.prefix + ".json").read_text(encoding="utf-8"))
    counts = dict(wins=0, draws=0, losses=0, unresolved=0)
    games = []
    with pathlib.Path(args.prefix + ".pgn").open(encoding="utf-8") as source:
        while (game := chess.pgn.read_game(source)) is not None:
            assert not game.errors, game.errors
            games.append(game)
    assert len(games) == len(report["games"])
    assert len(games) == 2 * report["pairs_requested"], "Match did not finish all requested pairs"
    assert sum(detail["termination"].startswith("engine forfeit") for detail in report["games"]) == report["forfeits"]
    for game, detail in zip(games, report["games"], strict=True):
        opening = game.board()
        for move in detail["opening"].split(): opening.push_uci(move)
        assert opening.fen() == detail["initial_fen"]
        moves = list(game.mainline_moves())
        assert [move.uci() for move in moves[:len(detail["opening"].split())]] == detail["opening"].split()
        if "searches" in detail:
            assert [search["move"] for search in detail["searches"]] == [move.uci() for move in moves[len(detail["opening"].split()):]]
            for index, search in enumerate(detail["searches"], len(detail["opening"].split()) + 1):
                assert search["ply"] == index
                candidate_turn = (index % 2 == 1) == (detail["candidate_color"] == "white")
                assert search["role"] == ("candidate" if candidate_turn else "opponent")
        board = game.end().board()
        assert game.headers["Result"] == detail["result"]
        assert len(board.move_stack) == detail["plies"]
        assert game.headers["Termination"] == detail["termination"]
        if detail["termination"].startswith("engine forfeit"):
            pass
        elif detail["result"] == "*":
            assert board.outcome(claim_draw=True) is None
        else:
            outcome = board.outcome(claim_draw=True)
            assert outcome is not None
            assert outcome.result() == detail["result"]
            assert outcome.termination.name.lower() == detail["termination"]
        candidate_white = detail["candidate_color"] == "white"
        if detail["result"] == "*": counts["unresolved"] += 1
        elif detail["result"] == "1/2-1/2": counts["draws"] += 1
        elif (detail["result"] == "1-0") == candidate_white: counts["wins"] += 1
        else: counts["losses"] += 1
    for key, value in counts.items():
        assert value == report[key], (key, value, report[key])
    print(json.dumps({"status": "passed", "games": len(games), **counts}))


if __name__ == "__main__":
    main()
