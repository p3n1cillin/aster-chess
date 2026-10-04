"""Score preserved counterfactual teacher pairs without regenerating their labels."""
import argparse
import hashlib
import json
import pathlib
import statistics

import chess

from neural_format import QuantizedModel


def digest(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("diagnostic")
    parser.add_argument("data")
    parser.add_argument("model")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = pathlib.Path(args.output)
    if output.exists():
        parser.error("Preserve prior diagnostics; choose another output")
    diagnostic = json.loads(pathlib.Path(args.diagnostic).read_text())
    if digest(args.data) != diagnostic["data_sha256"]:
        raise ValueError("Diagnostic source data fingerprint differs")
    training = json.loads(pathlib.Path(args.model).with_name("training.json").read_text())
    if digest(args.model) != training["model_sha256"]:
        raise ValueError("Model fingerprint differs")
    heldout = set(training["validation_games"])
    source = {row["fen"]: row for row in
              (json.loads(line) for line in pathlib.Path(args.data).read_text().splitlines() if line.strip())}
    model = QuantizedModel(args.model)
    pairs = []
    for pair in diagnostic["pairs"]:
        row = source[pair["source_fen"]]
        if row["game"] != pair["source_game"] or row["game"] not in heldout:
            raise ValueError("Diagnostic pair outside model's held-out groups")
        original = chess.Board(row["fen"])
        predictions = []
        for side in (chess.WHITE, chess.BLACK):
            board = original.copy(stack=False); board.turn = side
            raw = model.white_score(board)
            if model.classical_base:
                base = row["classical_white_cp"] - (12 if original.turn else -12)
                value = base + max(-250, min(250, raw))
            else:
                value = raw
            predictions.append(value + (12 if side else -12))
        error = (abs(predictions[0] - pair["white_to_move"]["white_cp"])
                 + abs(predictions[1] - pair["black_to_move"]["white_cp"])) / 2
        pairs.append({"source_fen": row["fen"], "white_to_move_cp": predictions[0],
                      "black_to_move_cp": predictions[1], "turn_delta_cp": predictions[0] - predictions[1],
                      "pair_mae_cp": error})
    report = {"status": "passed", "pairs": pairs, "mean_model_pair_mae_cp": statistics.mean(p["pair_mae_cp"] for p in pairs),
              "mean_model_turn_delta_cp": statistics.mean(p["turn_delta_cp"] for p in pairs),
              "mean_abs_model_turn_delta_cp": statistics.mean(abs(p["turn_delta_cp"]) for p in pairs),
              "diagnostic_sha256": digest(args.diagnostic), "data_sha256": digest(args.data),
              "model_sha256": digest(args.model), "source_sha256": digest(__file__),
              "interpretation": "Scores exactly the preserved held-out counterfactual sample; teacher fit, not playing strength."}
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "pairs"}))


if __name__ == "__main__":
    main()
