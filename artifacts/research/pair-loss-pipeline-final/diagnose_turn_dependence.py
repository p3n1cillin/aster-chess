"""Measure a position-only network's limitation on paired side-to-move labels."""
import argparse
import hashlib
import json
import pathlib
import random
import statistics

import chess
import chess.engine

from neural_format import QuantizedModel
from uci_client import ROOT, engine_command


def digest(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data")
    parser.add_argument("model")
    parser.add_argument("--pairs", type=int, default=128)
    parser.add_argument("--nodes", type=int, default=8192)
    parser.add_argument("--seed", type=int, default=20261018)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if min(args.pairs, args.nodes) < 1:
        parser.error("Pair and node budgets must be positive")
    output = pathlib.Path(args.output)
    if output.exists():
        parser.error("Preserve earlier diagnostics; use a new output path")
    training = json.loads(pathlib.Path(args.model).with_name("training.json").read_text())
    data_hash = digest(args.data)
    if data_hash != training["dataset_sha256"] or digest(args.model) != training["model_sha256"]:
        raise ValueError("Data/model fingerprints do not match the training report")
    validation_games = set(training["validation_games"])
    rows = [json.loads(line) for line in pathlib.Path(args.data).read_text().splitlines() if line.strip()]
    rows = [row for row in rows if row["game"] in validation_games]
    random.Random(args.seed).shuffle(rows)
    model = QuantizedModel(args.model)
    teacher_manifest = json.loads((ROOT / "tools/stockfish/manifest.json").read_text())
    teacher_path = ROOT / teacher_manifest["executable"]
    if digest(teacher_path) != teacher_manifest["executable_sha256"]:
        raise ValueError("Teacher binary differs from its pinned manifest")
    pairs = []
    examined = 0
    with chess.engine.SimpleEngine.popen_uci(engine_command(teacher_path), timeout=30) as teacher:
        teacher.configure({"Threads": 1, "Hash": 64})
        for row in rows:
            examined += 1
            original = chess.Board(row["fen"])
            if original.ep_square is not None:
                continue
            white = original.copy(stack=False); white.turn = chess.WHITE
            black = original.copy(stack=False); black.turn = chess.BLACK
            if any(not b.is_valid() or b.is_check() or b.outcome(claim_draw=True) is not None for b in (white, black)):
                continue
            labels = {}
            order = [white, black] if len(pairs) % 2 == 0 else [black, white]
            for board in order:
                info = teacher.analyse(board, chess.engine.Limit(nodes=args.nodes), game=object())
                labels[board.turn] = {"white_cp": info["score"].white().score(), "nodes": info.get("nodes"), "depth": info.get("depth")}
            if any(label["white_cp"] is None for label in labels.values()):
                continue
            raw_white, raw_black = model.white_score(white), model.white_score(black)
            if not model.turn_output:
                assert raw_white == raw_black, "Expected a position-only model"
            if model.classical_base:
                static = row["classical_white_cp"] - (12 if original.turn else -12)
                value_white = static + max(-250, min(250, raw_white))
                value_black = static + max(-250, min(250, raw_black))
            else:
                value_white, value_black = raw_white, raw_black
            teacher_delta = labels[chess.WHITE]["white_cp"] - labels[chess.BLACK]["white_cp"]
            pairs.append({"source_fen": row["fen"], "source_game": row["game"], "white_to_move": labels[chess.WHITE],
                          "black_to_move": labels[chess.BLACK], "teacher_turn_delta_cp": teacher_delta,
                          "model_white_to_move_cp": value_white + 12, "model_black_to_move_cp": value_black - 12,
                          "model_turn_delta_cp": value_white - value_black + 24,
                          "model_pair_mae_cp": (abs(value_white + 12 - labels[chess.WHITE]["white_cp"])
                              + abs(value_black - 12 - labels[chess.BLACK]["white_cp"])) / 2,
                          "position_only_pair_mae_lower_bound_cp": abs(teacher_delta - 24) / 2})
            if len(pairs) == args.pairs:
                break
    if len(pairs) != args.pairs:
        raise ValueError("Held-out sample exhausted before the requested pair count")
    report = {"pairs": pairs, "positions_examined": examined, "arguments": vars(args), "teacher": teacher_manifest,
              "teacher_options": {"Threads": 1, "Hash": 64}, "data_sha256": data_hash, "model_sha256": digest(args.model),
              "source_sha256": digest(__file__), "mean_abs_teacher_turn_delta_cp": statistics.mean(abs(p["teacher_turn_delta_cp"]) for p in pairs),
              "mean_position_only_mae_lower_bound_cp": statistics.mean(p["position_only_pair_mae_lower_bound_cp"] for p in pairs),
              "median_position_only_mae_lower_bound_cp": statistics.median(p["position_only_pair_mae_lower_bound_cp"] for p in pairs),
              "mean_model_pair_mae_cp": statistics.mean(p["model_pair_mae_cp"] for p in pairs),
              "turn_output": model.turn_output,
              "interpretation": "Counterfactual structurally legal FEN pairs, without game history. Bounded teacher-label representational diagnostic, not a strength test or general MAE lower bound on the original dataset."}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("mean_abs_teacher_turn_delta_cp", "mean_position_only_mae_lower_bound_cp", "median_position_only_mae_lower_bound_cp")}))


if __name__ == "__main__":
    main()
