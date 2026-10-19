"""CI checks current-build mate exports with the independent rules verifier."""
import argparse
import json
import pathlib
import subprocess
import tempfile

import chess

from uci_client import DEFAULT_ENGINE, engine_command
from verify_mate_proof import verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", default=str(DEFAULT_ENGINE))
    parser.add_argument("--output")
    args = parser.parse_args()
    cases = ["8/8/4K3/1k6/8/1p6/8/Q1R5 w - - 0 1", "k7/p1P5/2K5/8/8/8/8/8 w - - 0 1",
        "5B2/7B/6P1/R4pPk/8/7K/8/8 w - f6 0 1", "7k/6Q1/6K1/8/8/8/8/8 b - - 150 1"]
    checked = nodes = 0
    with tempfile.TemporaryDirectory(prefix="aster-mate-proof-") as temporary:
        for fen in cases:
            for mirrored in (False, True):
                board = chess.Board(fen); board = board.mirror() if mirrored else board
                strong = not board.turn if board.is_checkmate() else board.turn
                output = pathlib.Path(temporary) / f"proof-{checked}.json"
                result = subprocess.run([*engine_command(args.engine), "certify-mate", str(output), "7", "white" if strong else "black", board.fen(en_passant="fen")], capture_output=True, text=True)
                if result.returncode: raise AssertionError(result.stdout + result.stderr)
                report = verify(json.loads(output.read_text())); nodes += report["positions"]; checked += 1
        absent = pathlib.Path(temporary) / "unproved.json"
        result = subprocess.run([*engine_command(args.engine), "certify-mate", str(absent), "0", "white", chess.STARTING_FEN], capture_output=True, text=True)
        assert result.returncode == 2 and not absent.exists()
    report = {"passed": True, "independent_certificates": checked, "positions": nodes, "incomplete_export_refused": True}
    if args.output:
        with pathlib.Path(args.output).open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
    print(json.dumps(report))


if __name__ == "__main__": main()
