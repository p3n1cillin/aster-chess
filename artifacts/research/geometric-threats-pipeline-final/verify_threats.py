"""Differentially check geometric threat features and scoring against python-chess."""
import argparse
import hashlib
import json
import pathlib
import random

import chess

from fit_threats import features
from uci_client import UciClient
from verify import SPECIAL_FENS


def digest(path): return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--fit", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = pathlib.Path(args.output)
    if output.exists(): parser.error("Preserve prior checks")
    fit_path = pathlib.Path(args.fit)
    fit = json.loads(fit_path.read_text())
    data = pathlib.Path(fit["arguments"]["data"])
    if digest(data) != fit["data_sha256"]: raise ValueError("Changed fit dataset")
    baseline_provenance = json.loads(pathlib.Path(str(data) + ".classical.json").read_text())
    if baseline_provenance["output_sha256"] != digest(data) or baseline_provenance["classical_binary_sha256"] != digest(args.baseline):
        raise ValueError("Baseline differs from fit provenance")
    for entry in fit["source_files"]:
        if digest(fit_path.parent / "source" / entry["name"]) != entry["sha256"]:
            raise ValueError("Changed preserved fitter source")
    mg, eg = fit["mg_weights_cp"], fit["eg_weights_cp"]
    rng = random.Random(20261021)
    rows = [json.loads(line) for line in data.read_text().splitlines() if line.strip()]
    heldout = set(fit["validation_games"])
    selected = rng.sample([row for row in rows if row["game"] in heldout and not row.get("counterfactual_turn")], 1000)
    checked, altered = 0, 0
    with UciClient(args.engine) as candidate, UciClient(args.baseline) as baseline:
        def check(board):
            nonlocal checked, altered
            fen = board.fen(en_passant="fen")
            f, phase = features(board)
            numerator = sum(a * b for a, b in zip(f, mg)) * phase + sum(a * b for a, b in zip(f, eg)) * (24 - phase)
            expected = (1 if numerator >= 0 else -1) * (abs(numerator) // 24)
            candidate.send("position fen " + fen)
            actual = list(map(int, candidate.command("threats", "info string threats ").split()[3:]))
            assert actual == f + [expected], (fen, f, expected, actual)
            # Candidate features must neither mutate board state nor depend on caches.
            assert candidate.command("d", "info string fen ") == "info string fen " + fen
            baseline.send("position fen " + fen)
            original = int(baseline.command("eval", "info string eval ").split()[-1])
            corrected = max(-28000, min(28000, original + (expected if board.turn else -expected)))
            score = int(candidate.command("eval", "info string eval ").split()[-1])
            assert score == corrected, (fen, original, corrected, score)
            assert candidate.command("eval", "info string eval ").split()[-1] == str(score)
            checked += 1; altered += score != original
        for row in selected: check(chess.Board(row["fen"]))
        for fen in SPECIAL_FENS:
            board = chess.Board(fen)
            for _ in range(100):
                check(board)
                moves = list(board.legal_moves)
                if not moves: break
                board.push(rng.choice(moves))
    report = {"passed": True, "positions": checked, "changed_evaluations": altered,
              "engine_sha256": digest(args.engine), "baseline_sha256": digest(args.baseline), "fit_sha256": digest(fit_path),
              "data_sha256": digest(data), "source_sha256": digest(__file__),
              "interpretation": "Python geometric attack masks versus independent C# bitboards, integer correction and baseline score. Not strength."}
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__": main()
