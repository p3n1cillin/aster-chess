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

from neural_format import FEATURES, CONTEXT_FEATURES, RELATION_FEATURES, QuantizedModel, feature_indices, material_phase, save_model


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
    def __init__(self, hidden: int, classical_base: bool = False, king_context: bool = False, activation_bias: float = .5, turn_output: bool = False, squared_activation: bool = False, transformer_std: float = .02, phase_output: bool = False, attack_features: bool = False):
        super().__init__()
        if phase_output and (not turn_output or not king_context or squared_activation):
            raise ValueError("Phase output requires clipped turn-aware king-context features")
        if attack_features and (not phase_output or not turn_output or not king_context or squared_activation):
            raise ValueError("Relation features require clipped phase/turn/king-context output")
        self.features = RELATION_FEATURES if attack_features else CONTEXT_FEATURES if king_context else FEATURES
        self.king_context = king_context
        self.attack_features = attack_features
        self.linear = nn.Embedding(self.features + 1, 1, padding_idx=self.features)
        self.transformer = nn.Embedding(self.features + 1, hidden, padding_idx=self.features)
        self.bias = nn.Parameter(torch.full((hidden,), activation_bias))
        self.output = nn.Parameter(torch.empty(hidden * (2 if turn_output else 1)))
        self.classical_base = classical_base
        self.turn_output = turn_output
        self.squared_activation = squared_activation
        self.phase_output = phase_output
        with torch.no_grad():
            self.linear.weight.zero_()
            if not classical_base: self.linear.weight[:FEATURES].copy_(initial_linear()[:FEATURES])
            self.transformer.weight.normal_(0, transformer_std)
            if king_context: self.transformer.weight[FEATURES:].zero_()
            self.transformer.weight[self.features].zero_()
            self.output.normal_(0, .02)
            if turn_output: self.output[hidden:].copy_(-self.output[:hidden])
            # Consume exactly the control's random stream. Identical cloned heads
            # initially predict the same value at every phase.
            if phase_output: self.output = nn.Parameter(torch.cat([self.output, self.output]))

    def forward(self, white: torch.Tensor, black: torch.Tensor, tempo: torch.Tensor, turn: torch.Tensor | None = None, phase: torch.Tensor | None = None) -> torch.Tensor:
        aw = torch.clamp(self.transformer(white).sum(dim=1) + self.bias, 0, 1)
        ab = torch.clamp(self.transformer(black).sum(dim=1) + self.bias, 0, 1)
        if self.squared_activation:
            aw, ab = aw.square(), ab.square()
        linear = (self.linear(white).sum(dim=1) - self.linear(black).sum(dim=1)).squeeze(1) / 2
        if self.turn_output:
            if turn is None: raise ValueError("Turn-aware output requires explicit side-to-move inputs")
            own = torch.where(turn[:, None] > 0, aw, ab)
            other = torch.where(turn[:, None] > 0, ab, aw)
            hidden = aw.shape[1]
            residual = own @ self.output[:hidden] + other @ self.output[hidden:2*hidden]
            if self.phase_output:
                if phase is None: raise ValueError("Phase output requires explicit material phase")
                endgame = own @ self.output[2*hidden:3*hidden] + other @ self.output[3*hidden:]
                weight = torch.clamp(phase, 0, 24) / 24
                residual = residual * weight + endgame * (1 - weight)
            value = linear + residual * turn
        else:
            value = linear + (aw - ab) @ self.output
        if self.classical_base:
            value = torch.clamp(value, -2.5, 2.5)
        return value + tempo


def objective(prediction: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    # Mix value calibration near equal positions with a small robust cp term.
    return nn.functional.mse_loss(torch.sigmoid(prediction / 4), torch.sigmoid(target / 4)) \
        + .01 * nn.functional.smooth_l1_loss(prediction, target, beta=1)


def validation_split(games: list[int], seed: int, path: str | None) -> tuple[set[int], dict | None]:
    if path is None:
        return set(random.Random(seed).sample(games, max(1, len(games) // 10))), None
    source = pathlib.Path(path)
    raw = json.loads(source.read_text(encoding="utf-8"))
    selected = raw.get("validation_games") if isinstance(raw, dict) else raw
    if not isinstance(selected, list) or not selected or any(type(game) is not int for game in selected):
        raise ValueError("Fixed validation games must be a nonempty list of integer IDs")
    if len(set(selected)) != len(selected) or not set(selected) < set(games):
        raise ValueError("Fixed validation IDs must be unique, present, and leave training games")
    return set(selected), {"path": str(source.resolve()), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}


def turn_pairs(rows: list[dict], validation_games: set) -> tuple[list, list]:
    """Return white/black row pairs, retaining the original whole-game split."""
    parents = {row["fen"]: i for i, row in enumerate(rows) if not row.get("counterfactual_turn")}
    training, validation, used = [], [], set()
    for i, row in enumerate(rows):
        if not row.get("counterfactual_turn"):
            continue
        parent_index = parents.get(row.get("source_fen"))
        if parent_index is None:
            raise ValueError("Turn pair has no original parent")
        parent = rows[parent_index]
        a, b = parent["fen"].split(), row["fen"].split()
        if parent["game"] != row["game"] or a[1] == b[1] or a[:1] + a[2:] != b[:1] + b[2:]:
            raise ValueError("Turn pair changes source group or fields besides the moving side")
        if parent_index in used:
            raise ValueError("Duplicate turn-pair parent")
        used.add(parent_index)
        pair = (parent_index, i) if a[1] == "w" else (i, parent_index)
        (validation if row["game"] in validation_games else training).append(pair)
    return training, validation


def pair_partitions(rows: list[dict], validation_games: set) -> dict[str,list]:
    """Keep old static and explicitly marked fresh deep pairs in separate streams."""
    for row in rows:
        flag = row.get("fresh_deep_pair",False)
        if type(flag) is not bool or (flag and not row.get("counterfactual_turn")):
            raise ValueError("Fresh pair marker must be boolean and belong to a counterfactual row")
    training,validation = turn_pairs(rows,validation_games)
    result = {"old_training":[],"old_validation":[],"fresh_training":[],"fresh_validation":[]}
    for partition,pairs in (("training",training),("validation",validation)):
        for pair in pairs:
            fresh = any(rows[index].get("fresh_deep_pair",False) for index in pair)
            result[("fresh_" if fresh else "old_")+partition].append(pair)
    return result


def load_initial_checkpoint(model: PositionNetwork, path: str) -> dict:
    """Load an explicit initial function and training RNG, never optimizer state."""
    source = pathlib.Path(path)
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    checkpoint = torch.load(source,map_location="cpu",weights_only=True)
    architecture = {"hidden":model.bias.numel(),"classical_base":model.classical_base,
        "king_context":model.king_context,"turn_output":model.turn_output,
        "phase_output":model.phase_output,"squared_activation":model.squared_activation}
    if model.attack_features: architecture["attack_features"] = True
    if checkpoint.get("schema") != 1 or checkpoint.get("kind") != "aster_initial_state" or checkpoint.get("architecture") != architecture:
        raise ValueError("Initial checkpoint architecture mismatch")
    state = checkpoint.get("state_dict",{})
    expected = model.state_dict()
    if set(state) != set(expected): raise ValueError("Initial checkpoint parameter mismatch")
    for key,value in state.items():
        if not isinstance(value,torch.Tensor) or value.dtype != torch.float32 or value.shape != expected[key].shape or not torch.isfinite(value).all():
            raise ValueError("Invalid initial tensor: "+key)
        bound = {"linear.weight":100,"transformer.weight":8,"bias":16,"output":1.25}[key]
        if (value.abs()>bound).any(): raise ValueError("Initial tensor exceeds training bound: "+key)
    if state["linear.weight"][-1].count_nonzero() or state["transformer.weight"][-1].count_nonzero():
        raise ValueError("Initial padding features must be zero")
    rng = checkpoint.get("training_rng_state")
    if not isinstance(rng,torch.Tensor) or rng.dtype != torch.uint8 or rng.shape != torch.get_rng_state().shape:
        raise ValueError("Invalid initial training RNG")
    try: torch.Generator().set_state(rng)
    except RuntimeError as error: raise ValueError("Invalid initial training RNG payload") from error
    model.load_state_dict(state,strict=True); torch.set_rng_state(rng)
    return {"path":str(source.resolve()),"sha256":checksum,"architecture":architecture,
        "scope":"Explicit model initialization and post-initialization batch RNG; no optimizer or trained checkpoint resume."}


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
    parser.add_argument("--validation-games", help="Frozen JSON list or object with validation_games; whole-game split")
    parser.add_argument("--initial-checkpoint", help="Explicit aster_initial_state weights and batch RNG; dimensions and padding validated")
    parser.add_argument("--classical-base", action="store_true", help="Learn bounded corrections on the frozen classical evaluator")
    parser.add_argument("--king-context", action="store_true", help="Add own-king-region conditioned piece features")
    parser.add_argument("--turn-output", action="store_true", help="Learn separate moving/opponent perspective output weights; requires king context")
    parser.add_argument("--squared-activation", action="store_true", help="Square clipped hidden values; requires turn output")
    parser.add_argument("--phase-output", action="store_true", help="Interpolate separate middlegame/endgame outputs; requires clipped turn-aware king context")
    parser.add_argument("--attack-features", action="store_true", help="Add geometric attacked-piece count bins; requires clipped phase/turn/king context")
    parser.add_argument("--activation-bias", type=float, default=.5, help="Initial clipped-ReLU bias; zero starts at its nonlinear boundary")
    parser.add_argument("--transformer-std", type=float, default=.02, help="Initial ordinary feature weight standard deviation")
    parser.add_argument("--pair-loss-weight", type=float, default=0, help="Additional supervision on marked white-turn minus black-turn label differences")
    parser.add_argument("--fresh-pair-loss-weight", type=float, default=0, help="Separate objective for fresh_deep_pair markers; both roles consume the same fresh batch stream even at zero weight")
    args = parser.parse_args()
    if not 8 <= args.hidden <= 256 or args.hidden % 8 or min(args.epochs, args.batch_size, args.threads) <= 0 or args.learning_rate <= 0:
        parser.error("Invalid training budget or hidden size")
    if not np.isfinite(args.activation_bias) or not -16 <= args.activation_bias <= 16:
        parser.error("Invalid activation bias")
    if not np.isfinite(args.transformer_std) or not 0 < args.transformer_std <= 1:
        parser.error("Invalid transformer initialization scale")
    if args.turn_output and not args.king_context:
        parser.error("Turn-aware formats require --king-context")
    if args.squared_activation and not args.turn_output:
        parser.error("Squared activation requires --turn-output")
    if args.phase_output and (not args.turn_output or args.squared_activation):
        parser.error("Phase output requires --turn-output and clipped activation")
    if args.attack_features and (not args.phase_output or not args.turn_output or not args.king_context or args.squared_activation):
        parser.error("Relation features require clipped --phase-output --turn-output --king-context")
    if not np.isfinite(args.pair_loss_weight) or not 0 <= args.pair_loss_weight <= 16:
        parser.error("Invalid pair loss weight")
    if args.pair_loss_weight and not args.turn_output:
        parser.error("Pair supervision requires --turn-output")
    if not np.isfinite(args.fresh_pair_loss_weight) or not 0 <= args.fresh_pair_loss_weight <= 16:
        parser.error("Invalid fresh pair loss weight")
    if args.fresh_pair_loss_weight and not args.turn_output:
        parser.error("Fresh pair supervision requires --turn-output")
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
    features = RELATION_FEATURES if args.attack_features else CONTEXT_FEATURES if args.king_context else FEATURES
    max_active = 84 if args.attack_features else 64 if args.king_context else 32
    white = torch.full((len(rows), max_active), features, dtype=torch.long)
    black = torch.full_like(white, features)
    target = torch.tensor([row["score_white_cp"] / 100 for row in rows], dtype=torch.float32)
    turn = torch.tensor([1.0 if row["fen"].split()[1] == "w" else -1.0 for row in rows])
    phase = torch.empty(len(rows), dtype=torch.float32)
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
    validation_games, split_provenance = validation_split(games, args.seed, args.validation_games)
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
        phase[i] = material_phase(board)
        fw, fb = feature_indices(board, chess.WHITE, args.king_context, args.attack_features), feature_indices(board, chess.BLACK, args.king_context, args.attack_features)
        if len(fw) > max_active:
            raise ValueError("Training position has more than 32 pieces")
        white[i, :len(fw)] = torch.tensor(fw); black[i, :len(fb)] = torch.tensor(fb)
        (validation_indices if row["game"] in validation_games else training_indices).append(i)
    if not training_indices or not validation_indices:
        raise ValueError("Dataset needs multiple games for a held-out game split")
    training = torch.tensor(training_indices); validation = torch.tensor(validation_indices)
    grouped = pair_partitions(rows,validation_games) if args.pair_loss_weight or args.fresh_pair_loss_weight or any(row.get("fresh_deep_pair",False) for row in rows) else {name:[] for name in ("old_training","old_validation","fresh_training","fresh_validation")}
    train_pairs,heldout_pairs = grouped["old_training"],grouped["old_validation"]
    if not args.pair_loss_weight: train_pairs,heldout_pairs = [],[]
    if args.pair_loss_weight and (not train_pairs or not heldout_pairs):
        raise ValueError("Pair supervision requires marked pairs in both whole-game partitions")
    pair_training = torch.tensor(train_pairs, dtype=torch.long).reshape(-1, 2)
    pair_validation = torch.tensor(heldout_pairs, dtype=torch.long).reshape(-1, 2)
    fresh_training = torch.tensor(grouped["fresh_training"],dtype=torch.long).reshape(-1,2)
    fresh_validation = torch.tensor(grouped["fresh_validation"],dtype=torch.long).reshape(-1,2)
    if (len(fresh_training) or len(fresh_validation) or args.fresh_pair_loss_weight) and (not len(fresh_training) or not len(fresh_validation)):
        raise ValueError("Fresh paired data requires marked pairs in both whole-game partitions")
    for pairs in (pair_training, pair_validation, fresh_training, fresh_validation):
        if len(pairs) and (not torch.equal(white[pairs[:, 0]], white[pairs[:, 1]]) or not torch.equal(black[pairs[:, 0]], black[pairs[:, 1]])):
            raise ValueError("Turn-pair features differ")
    model = PositionNetwork(args.hidden, args.classical_base, args.king_context, args.activation_bias, args.turn_output, args.squared_activation, args.transformer_std, args.phase_output, args.attack_features)
    initial_checkpoint = load_initial_checkpoint(model,args.initial_checkpoint) if args.initial_checkpoint else None
    initial_shared = hashlib.sha256()
    for tensor in (model.linear.weight, model.transformer.weight, model.bias, model.output[:args.hidden * (2 if args.turn_output else 1)]):
        initial_shared.update(tensor.detach().numpy().tobytes())
    initial_rng_sha256 = hashlib.sha256(torch.get_rng_state().numpy().tobytes()).hexdigest()
    initial_state = hashlib.sha256()
    for tensor in model.state_dict().values(): initial_state.update(tensor.detach().numpy().tobytes())
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=1e-5)

    def evaluate(indices: torch.Tensor) -> dict:
        with torch.no_grad():
            predictions = torch.cat([model(white[batch], black[batch], tempo[batch], turn[batch], phase[batch]) for batch in indices.split(args.batch_size)])
            actual = target[indices]
            return {"loss": float(objective(predictions, actual)), "mae_cp": float((predictions - actual).abs().mean() * 100),
                    "rmse_cp": float((predictions - actual).square().mean().sqrt() * 100)}

    def evaluate_pairs(selected: torch.Tensor | None = None) -> dict | None:
        selected = pair_validation if selected is None else selected
        if not len(selected): return None
        with torch.no_grad():
            deltas = []
            for pairs in selected.split(args.batch_size):
                flat = pairs.flatten()
                predictions = model(white[flat], black[flat], tempo[flat], turn[flat], phase[flat]).reshape(-1, 2)
                deltas.append(predictions[:, 0] - predictions[:, 1])
            predicted = torch.cat(deltas)
            actual = target[selected[:, 0]] - target[selected[:, 1]]
            return {"pairs": len(selected), "difference_mae_cp": float((predicted - actual).abs().mean() * 100),
                    "predicted_std_cp": float(predicted.std(unbiased=False) * 100),
                    "teacher_std_cp": float(actual.std(unbiased=False) * 100)}

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
    batch_fingerprints = []
    print(json.dumps({"initial_validation": initial, "initial_activation": initial_activation, "training_positions": len(training), "validation_positions": len(validation)}), flush=True)
    for epoch in range(1, args.epochs + 1):
        shuffled = training[torch.randperm(len(training))]
        # A separately shuffled stream contains training pairs only. Cycle once
        # exhausted so each ordinary position batch gets one paired minibatch.
        pair_batches = []
        if len(pair_training):
            pair_batches = list(pair_training[torch.randperm(len(pair_training))].split(max(1, args.batch_size // 4)))
        # Always consume the same fresh permutation and forward graph in matched
        # fresh-data runs, including the zero-weight control.
        fresh_batches = []
        if len(fresh_training):
            fresh_batches = list(fresh_training[torch.randperm(len(fresh_training))].split(max(1,args.batch_size//4)))
        batch_digest = hashlib.sha256(shuffled.numpy().tobytes())
        for pairs in pair_batches: batch_digest.update(pairs.numpy().tobytes())
        for pairs in fresh_batches: batch_digest.update(pairs.numpy().tobytes())
        batch_fingerprints.append(batch_digest.hexdigest())
        for batch_number, batch in enumerate(shuffled.split(args.batch_size)):
            optimizer.zero_grad(set_to_none=True)
            prediction = model(white[batch], black[batch], tempo[batch], turn[batch], phase[batch])
            loss = objective(prediction, target[batch])
            if pair_batches:
                pairs = pair_batches[batch_number % len(pair_batches)]
                flat = pairs.flatten()
                pair_predictions = model(white[flat], black[flat], tempo[flat], turn[flat], phase[flat]).reshape(-1, 2)
                loss = loss + args.pair_loss_weight * objective(pair_predictions[:, 0] - pair_predictions[:, 1],
                                                                target[pairs[:, 0]] - target[pairs[:, 1]])
            if fresh_batches:
                pairs = fresh_batches[batch_number % len(fresh_batches)]
                flat = pairs.flatten()
                fresh_predictions = model(white[flat],black[flat],tempo[flat],turn[flat],phase[flat]).reshape(-1,2)
                loss = loss + args.fresh_pair_loss_weight * objective(fresh_predictions[:,0]-fresh_predictions[:,1],
                    target[pairs[:,0]]-target[pairs[:,1]])
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
        history.append({"epoch": epoch, **metrics, "pair_validation": evaluate_pairs()})
        if len(fresh_validation): history[-1]["fresh_pair_validation"] = evaluate_pairs(fresh_validation)
        if metrics["loss"] < best_loss:
            best_loss = metrics["loss"]; best_weights = copy.deepcopy(model.state_dict()); best_epoch = epoch
        if epoch % 5 == 0 or epoch == args.epochs:
            print(json.dumps({"epoch": epoch, "best_epoch": best_epoch, **metrics, "seconds": round(time.monotonic() - started, 2)}), flush=True)
    model.load_state_dict(best_weights)
    model.eval()
    torch.save({"schema": 1, "hidden": args.hidden, "state_dict": model.state_dict(), "arguments": vars(args)}, output / "checkpoint.pt")
    with torch.no_grad():
        save_model(output / "model.ann", model.linear.weight[:features, 0].numpy(), model.bias.numpy(),
                   model.transformer.weight[:features].numpy(), model.output.numpy(), args.classical_base, args.king_context, args.turn_output, args.squared_activation, args.phase_output, args.attack_features)
        float_predictions = model(white[validation], black[validation], tempo[validation], turn[validation], phase[validation]).numpy() * 100
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
              "architecture": f"shared {features}->H clipped ReLU with linear term; king_context={args.king_context}; turn_output={args.turn_output}; squared_activation={args.squared_activation}; phase_output={args.phase_output}",
              "initial_shared_sha256": initial_shared.hexdigest(), "initial_rng_sha256": initial_rng_sha256,
              "initial_state_sha256": initial_state.hexdigest(), "epoch_batch_sha256": batch_fingerprints,
              "phase_validation": [{"phase_range": [low, high], "positions": int(((phase[validation].numpy() >= low) & (phase[validation].numpy() <= high)).sum()),
                  "quantized_mae_cp": float(np.abs(qp - yt)[(phase[validation].numpy() >= low) & (phase[validation].numpy() <= high)].mean())
                  if ((phase[validation].numpy() >= low) & (phase[validation].numpy() <= high)).any() else None}
                  for low, high in ((0, 8), (9, 16), (17, 24))],
              "training_positions": len(training), "validation_positions": len(validation), "training_games": len(games) - len(validation_games),
              "validation_games": sorted(validation_games), "initial_validation": initial, "selected_validation": evaluate(validation),
              "selected_epoch": best_epoch, "epochs": history, "quantized_validation_mae_cp": float(np.abs(qp - yt).mean()),
              "quantization_mae_cp": float(np.abs(qp - float_predictions).mean()), "quantization_max_error_cp": float(np.abs(qp - float_predictions).max()),
              "seconds": round(time.monotonic() - started, 3), "interpretation": "Teacher fit on held-out games, not playing strength or evidence of surpassing Stockfish."}
    report["initial_activation"] = initial_activation
    if initial_checkpoint is not None:
        if hashlib.sha256(pathlib.Path(args.initial_checkpoint).read_bytes()).hexdigest() != initial_checkpoint["sha256"]:
            raise ValueError("Initial checkpoint changed during training")
        report["initial_checkpoint"] = initial_checkpoint
    report["selected_activation"] = activation_stats()
    report["classical_base"] = args.classical_base
    if classical_provenance is not None:
        if classical_provenance.get("output_sha256", data_digest) != data_digest:
            raise ValueError("Classical score provenance does not match the training dataset")
        report["classical_score_provenance"] = classical_provenance
    report["king_context"] = args.king_context
    report["turn_output"] = args.turn_output
    report["squared_activation"] = args.squared_activation
    report["phase_output"] = args.phase_output
    report["attack_features"] = args.attack_features
    report["features"] = features
    report["paired_supervision"] = {"weight": args.pair_loss_weight, "training_pairs": len(pair_training),
        "heldout_pairs": len(pair_validation), "pair_batch_size": max(1, args.batch_size // 4),
        "selected_validation": evaluate_pairs(), "selection": "Ordinary held-out position loss only; pair diagnostics do not select epochs."}
    report["residual_cap_cp"] = 250 if args.classical_base else None
    if len(fresh_training):
        report["fresh_paired_supervision"] = {"weight":args.fresh_pair_loss_weight,"training_pairs":len(fresh_training),
            "heldout_pairs":len(fresh_validation),"pair_batch_size":max(1,args.batch_size//4),"selected_validation":evaluate_pairs(fresh_validation),
            "selection":"Same ordinary held-out targets select epochs; fresh pair metrics never select weights.",
            "batching":"Fresh training stream shuffled/evaluated at zero and nonzero weights; held-out pairs excluded from optimization."}
    if split_provenance is not None:
        if hashlib.sha256(pathlib.Path(args.validation_games).read_bytes()).hexdigest() != split_provenance["sha256"]:
            raise ValueError("Fixed validation split changed during training")
        report["fixed_split"] = split_provenance
    (output / "training.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("selected_epoch", "quantized_validation_mae_cp", "quantization_mae_cp", "seconds")}), flush=True)


if __name__ == "__main__":
    main()
