"""Compare quantized inference with the C# runtime and score held-out teacher data."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import random

import chess
import numpy as np

from neural_format import QuantizedModel
from uci_client import DEFAULT_ENGINE, UciClient
from verify import SPECIAL_FENS


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model")
    parser.add_argument("--engine", default=str(DEFAULT_ENGINE))
    parser.add_argument("--data", help="Teacher dataset used by the adjacent training.json report")
    parser.add_argument("--output", help="Optional JSON verification report")
    args = parser.parse_args()
    model_path = pathlib.Path(args.model).resolve()
    reference = QuantizedModel(model_path)
    rng = random.Random(20261003)
    checked = 0
    with UciClient(args.engine) as client, UciClient(args.engine) as baseline_client:
        def expected_score(board: chess.Board) -> int:
            base = None
            if reference.classical_base:
                baseline_client.send("position fen " + board.fen(en_passant="fen"))
                base = int(baseline_client.command("eval", "info string eval ").split()[-1])
            return reference.side_score(board, base)
        client.send("setoption name EvalFile value " + str(model_path)); client.ready()
        for fen in SPECIAL_FENS:
            board = chess.Board(fen)
            for _ in range(40):
                client.send("position fen " + board.fen(en_passant="fen"))
                actual = int(client.command("eval", "info string eval ").split()[-1])
                expected = expected_score(board)
                assert actual == expected, (board.fen(), expected, actual)
                rebuild = client.command("nncheck", "info string nncheck ").split()
                assert rebuild[-1] == rebuild[-2], rebuild
                checked += 1
                moves = list(board.legal_moves)
                if not moves:
                    break
                board.push(rng.choice(moves))
        # A complete history exercises incremental moves rather than FEN refresh.
        board = chess.Board(); history = []
        for _ in range(160):
            client.send("position startpos moves " + " ".join(history))
            actual = int(client.command("eval", "info string eval ").split()[-1])
            assert actual == expected_score(board), (history, actual, expected_score(board))
            checked += 1
            moves = list(board.legal_moves)
            if not moves:
                break
            move = rng.choice(moves); history.append(move.uci()); board.push(move)
        # New games retain the selected model; failed loads retain the old model.
        client.send("ucinewgame"); client.ready()
        assert int(client.command("eval", "info string eval ").split()[-1]) == expected_score(chess.Board())
        client.send("setoption name EvalFile value missing-network-file.ann")
        client.until("info string error:")
        assert int(client.command("eval", "info string eval ").split()[-1]) == expected_score(chess.Board())
        client.send("setoption name EvalFile value <classical>"); client.ready()
        assert client.command("nncheck", "info string nncheck ") == "info string nncheck classical"

        evaluation_report = None
        if args.data:
            training = json.loads(model_path.with_name("training.json").read_text(encoding="utf-8"))
            if hashlib.sha256(model_path.read_bytes()).hexdigest() != training["model_sha256"]:
                raise ValueError("Model differs from its training report")
            validation_games = set(training["validation_games"])
            rows = [json.loads(line) for line in pathlib.Path(args.data).read_text(encoding="utf-8").splitlines() if line.strip()]
            rows = [row for row in rows if row["game"] in validation_games]
            if not rows:
                raise ValueError("Evaluation dataset has no held-out game positions")
            classical, neural, target = [], [], []
            for row in rows:
                board = chess.Board(row["fen"])
                client.send("position fen " + row["fen"])
                actual = int(client.command("eval", "info string eval ").split()[-1])
                classical.append(actual if board.turn else -actual)
                raw = reference.white_score(board)
                neural.append(max(-250, min(250, raw)) + (actual if board.turn else -actual) if reference.classical_base
                              else raw + (12 if board.turn else -12))
                target.append(row["score_white_cp"])
            y = np.array(target)
            evaluation_report = {"held_out_positions": len(rows), "classical_mae_cp": float(np.abs(np.array(classical) - y).mean()),
                                 "neural_mae_cp": float(np.abs(np.array(neural) - y).mean()),
                                 "data": str(pathlib.Path(args.data).resolve()),
                                 "data_sha256": hashlib.sha256(pathlib.Path(args.data).read_bytes()).hexdigest(),
                                 "training_data_sha256": training["dataset_sha256"],
                                 "validation_games": sorted(validation_games)}
    report = {"status": "passed", "model": str(model_path), "exact_inference_positions": checked,
              "held_out_evaluation": evaluation_report, "interpretation": "Inference agreement and teacher fit, not measured playing strength."}
    for name, path in (("engine", args.engine), ("model", model_path)):
        with pathlib.Path(path).open("rb") as source:
            report[name + "_sha256"] = hashlib.file_digest(source, "sha256").hexdigest()
    report["engine"] = str(pathlib.Path(args.engine).resolve())
    if args.output:
        pathlib.Path(args.output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
