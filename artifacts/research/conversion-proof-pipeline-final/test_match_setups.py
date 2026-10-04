"""Regression tests for legal FEN starts, PGN origins and black-turn auditing."""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

import chess
import chess.pgn

from match import OPENINGS, validate_openings


class SetupTests(unittest.TestCase):
    def test_legacy_lines(self):
        entries = validate_openings([{"moves": line} for line in OPENINGS])
        self.assertEqual(len(entries), 8)
        self.assertTrue(all(e["start_fen"] == chess.STARTING_FEN for e in entries))

    def test_black_start_retains_clock_and_fullmove(self):
        fen = "8/8/8/8/8/4q3/5k2/7K b - - 7 42"
        result = validate_openings([{"start_fen": fen, "moves": ""}])
        self.assertEqual(result[0]["fen"], fen)

    def test_invalid_terminal_and_duplicate_starts(self):
        for entries in ([], [{"start_fen": "8/8/8/8/8/8/8/8 w - - 0 1", "moves": ""}],
                        [{"start_fen": "7k/8/8/8/8/8/8/K7 w - - 0 1", "moves": ""}],
                        [{"moves": "e2e5"}], [{"moves": "e2e4", "fen": chess.STARTING_FEN}],
                        [{"moves": "e2e4"}, {"moves": "e2e4"}]):
            with self.subTest(entries=entries), self.assertRaises(ValueError): validate_openings(entries)

    def test_black_turn_pgn_audit_and_role_corruption(self):
        fen = "8/8/8/8/8/4q3/5k2/7K b - - 7 42"
        with tempfile.TemporaryDirectory() as temp:
            prefix = pathlib.Path(temp) / "black"
            games, details = [], []
            for color in ("white", "black"):
                board = chess.Board(fen); game = chess.pgn.Game.from_board(board)
                move = chess.Move.from_uci("e3h3"); board.push(move); game.add_variation(move)
                self.assertTrue(board.is_checkmate())
                game.headers["Result"] = "0-1"; game.headers["Termination"] = "checkmate"
                self.assertEqual(game.headers["SetUp"], "1"); self.assertEqual(game.headers["FEN"], fen)
                games.append(str(game))
                details.append({"candidate_color": color, "starting_fen": fen, "opening": "", "initial_fen": fen,
                                "result": "0-1", "termination": "checkmate", "plies": 1,
                                "searches": [{"ply": 1, "role": "candidate" if color == "black" else "opponent", "move": "e3h3"}]})
            report = {"pairs_requested": 1, "games": details, "forfeits": 0, "unresolved": 0, "wins": 1, "draws": 0, "losses": 1}
            pathlib.Path(str(prefix) + ".pgn").write_text("\n\n".join(games) + "\n\n")
            path = pathlib.Path(str(prefix) + ".json"); path.write_text(json.dumps(report))
            cmd = [sys.executable, str(pathlib.Path(__file__).with_name("audit_match.py")), str(prefix)]
            result = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            details[0]["searches"][0]["role"] = "candidate"; path.write_text(json.dumps(report))
            self.assertNotEqual(subprocess.run(cmd, capture_output=True).returncode, 0)


if __name__ == "__main__": unittest.main()
