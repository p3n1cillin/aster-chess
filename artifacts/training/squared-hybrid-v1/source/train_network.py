"""Train and export a small original Aster position network on game-separated data."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import pathlib
import random
import shutil
import time

import chess
import numpy as np
import torch
from torch import nn

from neural_format import FEATURES, CONTEXT_FEATURES, QuantizedModel, feature_indices, save_model


def initial_linear() -> torch.Tensor:
    values = torch.zeros(FEATURES + 1, 1)
    material = [1.0, 3.2, 3.35, 5.0, 9.5, 0.0]
    for piece in range(12):
        for square in range(64):
            color, kind = divmod(piece, 6)
            file, raw_rank = square % 8, square // 8
            rank = raw_rank if color == 0 else 7 - raw_rank
            center = 7 - (abs(2 * file - 7) + abs(2 * rank - 7)) // 2
            bonus = [rank * .07 + center * .03, center * .12, center * .06, rank * .02,
                     center * .03, -center * .10 - rank * .08][kind]
            values[piece * 64 + square, 0] = (material[kind] + bonus) * (1 if color == 0 else -1)
    return values


class PositionNetwork(nn.Module):
    def __init__(self, hidden: int, classical_base: bool = False, king_context: bool = False, activation_bias: float = .5, turn_output: bool = False, squared_activation: bool = False):
        super().__init__()
        self.features = CONTEXT_FEATURES if king_context else FEATURES
        self.linear = nn.Embedding(self.features + 1, 1, padding_idx=self.features)
        self.transformer = nn.Embedding(self.features + 1, hidden, padding_idx=self.features)
        self.bias = nn.Parameter(torch.full((hidden,), activation_bias))
        self.output = nn.Parameter(torch.empty(hidden * (2 if turn_output else 1)))
        self.classical_base = classical_base
        self.turn_output = turn_output
        self.squared_activation = squared_activation
        with torch.no_grad():
            self.linear.weight.zero_()
            if not classical_base: self.linear.weight[:FEATURES].copy_(initial_linear()[:FEATURES])
            self.transformer.weight.normal_(0, .02)
            if king_context: self.transformer.weight[FEATURES:].zero_()
            self.transformer.weight[self.features].zero_()
            self.output.normal_(0, .02)
            if turn_output: self.output[hidden:].copy_(-self.output[:hidden])

    def forward(self, white: torch.Tensor, black: torch.Tensor, tempo: torch.Tensor, turn: torch.Tensor | None = None) -> torch.Tensor:
        aw = torch.clamp(self.transformer(white).sum(dim=1) + self.bias, 0, 1)
        ab = torch.clamp(self.transformer(black).sum(dim=1) + self.bias, 0, 1)
        if self.squared_activation:
            aw, ab = aw.square(), ab.square()
        linear = (self.linear(white).sum(dim=1) - self.linear(black).sum(dim=1)).squeeze(1) / 2
        if self.turn_output:
            if turn is None: raise ValueError("Turn-aware output requires explicit side-to-move inputs")
            own = torch.where(turn[:, None] > 0, aw, ab)
            other = torch.where(turn[:, None] > 0, ab, aw)
            value = linear + (own @ self.output[:aw.shape[1]] + other @ self.output[aw.shape[1]:]) * turn
        else:
            value = linear + (aw - ab) @ self.output
        if self.classical_base:
            value = torch.clamp(value, -2.5, 2.5)
        return value + tempo


def objective(prediction: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    # Mix value calibration near equal positions with a small robust cp term.
    return nn.functional.mse_loss(torch.sigmoid(prediction / 4), torch.sigmoid(target / 4)) \
        + .01 * nn.functional.smooth_l1_loss(prediction, target, beta=1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data")
    parser.add_argument("--output", default="artifacts/training/prototype-v1")
    parser.add_argument("--hidden", type=int, default=128)
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--learning-rate", type=float, default=.002)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20261003)
    parser.add_argument("--classical-base", action="store_true", help="Learn bounded corrections on the frozen classical evaluator")
    parser.add_argument("--king-context", action="store_true", help="Add own-king-region conditioned piece features")
    parser.add_argument("--turn-output", action="store_true", help="Learn separate moving/opponent perspective output weights; requires king context")
    parser.add_argument("--squared-activation", action="store_true", help="Square clipped hidden values; requires turn output")
    parser.add_argument("--activation-bias", type=float, default=.5, help="Initial clipped-ReLU bias; zero starts at its nonlinear boundary")
    args = parser.parse_args()
    if not 8 <= args.hidden <= 256 or args.hidden % 8 or min(args.epochs, args.batch_size, args.threads) <= 0 or args.learning_rate <= 0:
        parser.error("Invalid training budget or hidden size")
    if not np.isfinite(args.activation_bias) or not -16 <= args.activation_bias <= 16:
        parser.error("Invalid activation bias")
    if args.turn_output and not args.king_context:
        parser.error("Turn-aware formats require --king-context")
    if args.squared_activation and not args.turn_output:
        parser.error("Squared activation requires --turn-output")
    output = pathlib.Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "model.ann").exists():
        parser.error("Output already contains a model; use a new directory to retain the previous experiment")
    source_directory = output / "source"
    source_directory.mkdir(exist_ok=True)
    source_manifest = []
    for name in ("train_network.py", "neural_format.py"):
        path = pathlib.Path(__file__).with_name(name)
        shutil.copy2(path, source_directory / name)
        source_manifest.append({"name": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    initial_data_digest = hashlib.sha256(pathlib.Path(args.data).read_bytes()).hexdigest()
    torch.set_num_threads(args.threads)
    torch.manual_seed(args.seed); np.random.seed(args.seed); random.seed(args.seed)
    torch.use_deterministic_algorithms(True)
    started = time.monotonic()
    rows = [json.loads(line) for line in pathlib.Path(args.data).read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise ValueError("Empty training dataset")
    features = CONTEXT_FEATURES if args.king_context else FEATURES
    max_active = 64 if args.king_context else 32
    white = torch.full((len(rows), max_active), features, dtype=torch.long)
    black = torch.full_like(white, features)
    target = torch.tensor([row["score_white_cp"] / 100 for row in rows], dtype=torch.float32)
    turn = torch.tensor([1.0 if row["fen"].split()[1] == "w" else -1.0 for row in rows])
    if args.classical_base and any("classical_white_cp" not in row for row in rows):
        raise ValueError("Hybrid training requires classical_white_cp; run add_classical_scores.py first")
    classical_provenance = None
    baseline_path = pathlib.Path(str(args.data) + ".classical.json")
    if args.classical_base and baseline_path.exists():
        classical_provenance = json.loads(baseline_path.read_text(encoding="utf-8"))
        if "output_sha256" in classical_provenance and classical_provenance["output_sha256"] != hashlib.sha256(pathlib.Path(args.data).read_bytes()).hexdigest():
            raise ValueError("Classical score provenance does not match the training dataset")
    tempo = torch.tensor([row["classical_white_cp"] / 100 if args.classical_base
                          else (.12 if row["fen"].split()[1] == "w" else -.12) for row in rows])
    games = sorted({row["game"] for row in rows})
    rng = random.Random(args.seed)
    validation_games = set(rng.sample(games, max(1, len(games) // 10)))
    validation_indices, training_indices = [], []
    canonical: set[str] = set()
    for i, row in enumerate(rows):
        board = chess.Board(row["fen"])
        if not board.is_valid():
            raise ValueError("Invalid training FEN")
        key = " ".join(board.fen().split()[:4])
        if key in canonical:
            raise ValueError("Duplicate position in dataset; deduplicate before splitting")
        canonical.add(key)
        fw, fb = feature_indices(board, chess.WHITE, args.king_context), feature_indices(board, chess.BLACK, args.king_context)
        if len(fw) > max_active:
            raise ValueError("Training position has more than 32 pieces")
        white[i, :len(fw)] = torch.tensor(fw); black[i, :len(fb)] = torch.tensor(fb)
        (validation_indices if row["game"] in validation_games else training_indices).append(i)
    if not training_indices or not validation_indices:
        raise ValueError("Dataset needs multiple games for a held-out game split")
    training = torch.tensor(training_indices); validation = torch.tensor(validation_indices)
    model = PositionNetwork(args.hidden, args.classical_base, args.king_context, args.activation_bias, args.turn_output, args.squared_activation)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=1e-5)

    def evaluate(indices: torch.Tensor) -> dict:
        with torch.no_grad():
            predictions = torch.cat([model(white[batch], black[batch], tempo[batch], turn[batch]) for batch in indices.split(args.batch_size)])
            actual = target[indices]
            return {"loss": float(objective(predictions, actual)), "mae_cp": float((predictions - actual).abs().mean() * 100),
                    "rmse_cp": float((predictions - actual).square().mean().sqrt() * 100)}

    initial = evaluate(validation)
    def activation_stats() -> dict:
        # A fixed held-out diagnostic sample; never used as a strength gate.
        sample = validation[:1024]
        with torch.no_grad():
            pre = torch.cat([model.transformer(white[sample]).sum(dim=1) + model.bias,
                             model.transformer(black[sample]).sum(dim=1) + model.bias])
            return {"positions": len(sample), "outside_linear_fraction": float(((pre <= 0) | (pre >= 1)).float().mean())}
    initial_activation = activation_stats()
    best_loss = initial["loss"]
    best_weights = copy.deepcopy(model.state_dict())
    best_epoch = 0
    history = []
    print(json.dumps({"initial_validation": initial, "initial_activation": initial_activation, "training_positions": len(training), "validation_positions": len(validation)}), flush=True)
    for epoch in range(1, args.epochs + 1):
        shuffled = training[torch.randperm(len(training))]
        for batch in shuffled.split(args.batch_size):
            optimizer.zero_grad(set_to_none=True)
            prediction = model(white[batch], black[batch], tempo[batch], turn[batch])
            loss = objective(prediction, target[batch])
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1)
            optimizer.step()
            with torch.no_grad():
                model.output.clamp_(-1.25, 1.25)
                model.transformer.weight.clamp_(-8, 8)
                model.bias.clamp_(-16, 16)
                model.linear.weight.clamp_(-100, 100)
                model.linear.weight[features].zero_(); model.transformer.weight[features].zero_()
        metrics = evaluate(validation)
        history.append({"epoch": epoch, **metrics})
        if metrics["loss"] < best_loss:
            best_loss = metrics["loss"]; best_weights = copy.deepcopy(model.state_dict()); best_epoch = epoch
        if epoch % 5 == 0 or epoch == args.epochs:
            print(json.dumps({"epoch": epoch, "best_epoch": best_epoch, **metrics, "seconds": round(time.monotonic() - started, 2)}), flush=True)
    model.load_state_dict(best_weights)
    model.eval()
    torch.save({"schema": 1, "hidden": args.hidden, "state_dict": model.state_dict(), "arguments": vars(args)}, output / "checkpoint.pt")
    with torch.no_grad():
        save_model(output / "model.ann", model.linear.weight[:features, 0].numpy(), model.bias.numpy(),
                   model.transformer.weight[:features].numpy(), model.output.numpy(), args.classical_base, args.king_context, args.turn_output, args.squared_activation)
        float_predictions = model(white[validation], black[validation], tempo[validation], turn[validation]).numpy() * 100
    quantized = QuantizedModel(output / "model.ann")
    quantized_predictions = []
    for index in validation_indices:
        board = chess.Board(rows[index]["fen"])
        raw = quantized.white_score(board)
        quantized_predictions.append(max(-250, min(250, raw)) + rows[index]["classical_white_cp"] if args.classical_base
                                     else raw + (12 if board.turn else -12))
    qp = np.array(quantized_predictions)
    yt = np.array([rows[index]["score_white_cp"] for index in validation_indices])
    with pathlib.Path(args.data).open("rb") as source:
        data_digest = hashlib.file_digest(source, "sha256").hexdigest()
    if data_digest != initial_data_digest:
        raise ValueError("Dataset changed during training")
    with (output / "model.ann").open("rb") as source:
        model_digest = hashlib.file_digest(source, "sha256").hexdigest()
    report = {"schema": 1, "arguments": vars(args), "torch_version": torch.__version__, "numpy_version": np.__version__,
              "dataset_sha256": data_digest, "model_sha256": model_digest, "source_files": source_manifest,
              "architecture": f"shared {features}->H clipped ReLU with linear term; king_context={args.king_context}; turn_output={args.turn_output}; squared_activation={args.squared_activation}",
              "training_positions": len(training), "validation_positions": len(validation), "training_games": len(games) - len(validation_games),
              "validation_games": sorted(validation_games), "initial_validation": initial, "selected_validation": evaluate(validation),
              "selected_epoch": best_epoch, "epochs": history, "quantized_validation_mae_cp": float(np.abs(qp - yt).mean()),
              "quantization_mae_cp": float(np.abs(qp - float_predictions).mean()), "quantization_max_error_cp": float(np.abs(qp - float_predictions).max()),
              "seconds": round(time.monotonic() - started, 3), "interpretation": "Teacher fit on held-out games, not playing strength or evidence of surpassing Stockfish."}
    report["initial_activation"] = initial_activation
    report["selected_activation"] = activation_stats()
    report["classical_base"] = args.classical_base
    if classical_provenance is not None:
        if classical_provenance.get("output_sha256", data_digest) != data_digest:
            raise ValueError("Classical score provenance does not match the training dataset")
        report["classical_score_provenance"] = classical_provenance
    report["king_context"] = args.king_context
    report["turn_output"] = args.turn_output
    report["squared_activation"] = args.squared_activation
    report["features"] = features
    report["residual_cap_cp"] = 250 if args.classical_base else None
    (output / "training.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("selected_epoch", "quantized_validation_mae_cp", "quantization_mae_cp", "seconds")}), flush=True)


if __name__ == "__main__":
    main()
