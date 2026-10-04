"""Score held-out marked turn pairs using their retained teacher labels."""
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
    parser.add_argument("data")
    parser.add_argument("models", nargs="+")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = pathlib.Path(args.output)
    if output.exists(): parser.error("Preserve earlier diagnostics")
    rows = [json.loads(line) for line in pathlib.Path(args.data).read_text().splitlines() if line.strip()]
    parents = {row["fen"]: row for row in rows if not row.get("counterfactual_turn")}
    results = []
    shared_groups = None
    for model_path in args.models:
        training = json.loads(pathlib.Path(model_path).with_name("training.json").read_text())
        if digest(model_path) != training["model_sha256"]: raise ValueError("Model differs from training report")
        groups = set(training["validation_games"])
        if shared_groups is not None and groups != shared_groups: raise ValueError("Model game splits differ")
        shared_groups = groups
        model = QuantizedModel(model_path)
        teacher, predicted, errors = [], [], []
        for row in rows:
            if not row.get("counterfactual_turn") or row["game"] not in groups: continue
            parent = parents[row["source_fen"]]
            if parent["game"] != row["game"]: raise ValueError("Pair crosses source-game groups")
            white, black = (row, parent) if row["fen"].split()[1] == "w" else (parent, row)
            predictions = []
            for value in (white, black):
                board = chess.Board(value["fen"])
                raw = model.white_score(board)
                score = max(-250, min(250, raw)) + value["classical_white_cp"] if model.classical_base else raw + (12 if board.turn else -12)
                predictions.append(max(-28000, min(28000, score)))
            teacher.append(white["score_white_cp"] - black["score_white_cp"])
            predicted.append(predictions[0] - predictions[1])
            errors.extend([abs(predictions[0] - white["score_white_cp"]), abs(predictions[1] - black["score_white_cp"])])
        if not teacher: raise ValueError("No held-out pairs")
        results.append({"model": str(pathlib.Path(model_path).resolve()), "model_sha256": digest(model_path),
                        "pairs": len(teacher), "teacher_turn_mean_cp": statistics.mean(teacher),
                        "teacher_turn_std_cp": statistics.pstdev(teacher), "predicted_turn_mean_cp": statistics.mean(predicted),
                        "predicted_turn_std_cp": statistics.pstdev(predicted), "pair_mae_cp": statistics.mean(errors)})
    report = {"data_sha256": digest(args.data), "models": results, "source_sha256": digest(__file__),
              "interpretation": "Marked held-out pairs with retained source-game groups; descriptive teacher fit, not playing strength."}
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
