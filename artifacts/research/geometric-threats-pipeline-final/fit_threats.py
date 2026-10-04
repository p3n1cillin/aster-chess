"""Fit a constrained, original geometric-threat correction on training games."""
import argparse
import hashlib
import json
import pathlib
import random
import shutil
import time

import chess
import numpy as np
import torch

from train_network import objective


NAMES = ["loose_pawn", "loose_minor", "loose_rook", "loose_queen",
         "lower_attacked_minor", "lower_attacked_rook", "lower_attacked_queen"]


def features(board):
    controls, pawn, minor, rook = [0, 0], [0, 0], [0, 0], [0, 0]
    for square, piece in board.piece_map().items():
        color = int(piece.color)
        attacks = int(board.attacks(square))
        controls[color] |= attacks
        if piece.piece_type == chess.PAWN: pawn[color] |= attacks
        elif piece.piece_type in (chess.KNIGHT, chess.BISHOP): minor[color] |= attacks
        elif piece.piece_type == chess.ROOK: rook[color] |= attacks
    counts = [0] * 7
    phase = 0
    for square, piece in board.piece_map().items():
        kind, own = piece.piece_type, int(piece.color)
        phase += {chess.KNIGHT: 1, chess.BISHOP: 1, chess.ROOK: 2, chess.QUEEN: 4}.get(kind, 0)
        if kind == chess.KING: continue
        bit = 1 << square
        sign = -1 if own else 1  # Black weakness increases White's score.
        if controls[1 - own] & bit and not controls[own] & bit:
            category = 0 if kind == chess.PAWN else 1 if kind <= chess.BISHOP else kind - 2
            counts[category] += sign
        elif kind >= chess.KNIGHT:
            lower = pawn[1 - own]
            if kind >= chess.ROOK: lower |= minor[1 - own]
            if kind == chess.QUEEN: lower |= rook[1 - own]
            if lower & bit:
                category = 4 if kind <= chess.BISHOP else kind + 1
                counts[category] += sign
    return counts, min(24, phase)


def digest(path): return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def metrics(scores, labels):
    error = np.asarray(scores) - labels
    return {"mae_cp": float(np.abs(error).mean()), "rmse_cp": float(np.sqrt(np.square(error).mean()))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data")
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=20261014)
    parser.add_argument("--epochs", type=int, default=500)
    args = parser.parse_args()
    output = pathlib.Path(args.output)
    if output.exists(): parser.error("Preserve existing experiments")
    if args.epochs < 1: parser.error("Positive epoch budget required")
    started = time.monotonic()
    data_hash = digest(args.data)
    rows = [json.loads(line) for line in pathlib.Path(args.data).read_text().splitlines() if line.strip()]
    # Keep the split's full group universe, but fit only original played positions.
    games = sorted({row["game"] for row in rows})
    groups = set(random.Random(args.seed).sample(games, max(1, len(games) // 10)))
    rows = [row for row in rows if not row.get("counterfactual_turn")]
    counts, phases = [], []
    for row in rows:
        board = chess.Board(row["fen"])
        if not board.is_valid() or board.outcome(claim_draw=True) is not None:
            raise ValueError("Invalid or terminal input")
        f, phase = features(board)
        counts.append(f); phases.append(phase)
    counts = np.asarray(counts, dtype=np.int32)
    phases = np.asarray(phases, dtype=np.int32)
    mg = counts * phases[:, None] / 24
    eg = counts * (24 - phases[:, None]) / 24
    x = np.concatenate([mg, eg], axis=1).astype(np.float32)
    target = np.asarray([row["score_white_cp"] for row in rows], dtype=np.float32)
    baseline = np.asarray([row["classical_white_cp"] for row in rows], dtype=np.float32)
    heldout = np.asarray([row["game"] in groups for row in rows])
    if not heldout.any() or heldout.all(): raise ValueError("Empty group partition")
    torch.set_num_threads(4)
    torch.manual_seed(args.seed)
    torch.use_deterministic_algorithms(True)
    tx = torch.tensor(x[~heldout])
    tb, ty = torch.tensor(baseline[~heldout] / 100), torch.tensor(target[~heldout] / 100)
    weights = torch.nn.Parameter(torch.zeros(14))
    optimizer = torch.optim.Adam([weights], lr=1.0)
    for _ in range(args.epochs):
        optimizer.zero_grad()
        prediction = tb + tx @ weights / 100
        loss = objective(prediction, ty) + .0001 * (weights / 100).square().sum()
        loss.backward(); optimizer.step()
        with torch.no_grad(): weights.clamp_(0, 150)
    integer = np.rint(weights.detach().numpy()).astype(np.int32)
    # Integer correction is truncated toward zero before addition to the baseline.
    correction = np.trunc((counts @ integer[:7] * phases + counts @ integer[7:] * (24 - phases)) / 24).astype(np.int32)
    predicted = baseline + correction
    buckets = {}
    for label, mask in (("all", heldout), ("any_threat", heldout & np.any(counts != 0, axis=1)),
                        ("no_net_threat", heldout & np.all(counts == 0, axis=1))):
        if mask.any(): buckets[label] = {"positions": int(mask.sum()), "classical": metrics(baseline[mask], target[mask]),
                                        "corrected": metrics(predicted[mask], target[mask])}
    output.mkdir(parents=True)
    source = output / "source"; source.mkdir()
    source_files = []
    for name in ("fit_threats.py", "train_network.py", "neural_format.py"):
        path = pathlib.Path(__file__).with_name(name)
        shutil.copy2(path, source / name)
        source_files.append({"name": name, "sha256": digest(path)})
    if digest(args.data) != data_hash: raise ValueError("Dataset changed during fitting")
    np.savez_compressed(output / "features.npz", counts=counts, phases=phases, target=target, baseline=baseline, heldout=heldout)
    report = {"schema": 1, "arguments": vars(args), "data_sha256": data_hash, "source_files": source_files,
              "training_positions": int((~heldout).sum()), "validation_positions": int(heldout.sum()),
              "validation_games": sorted(groups), "feature_names": NAMES, "mg_weights_cp": integer[:7].tolist(),
              "eg_weights_cp": integer[7:].tolist(), "float_weights_cp": weights.detach().tolist(),
              "training_baseline": metrics(baseline[~heldout], target[~heldout]),
              "training_corrected": metrics(predicted[~heldout], target[~heldout]), "heldout_buckets": buckets,
              "features_sha256": digest(output / "features.npz"), "seconds": round(time.monotonic() - started, 3),
              "interpretation": "Geometric attacks including pins; nonnegative capped weights fit training games only. Neither legal capture proofs nor playing-strength evidence."}
    (output / "fit.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("mg_weights_cp", "eg_weights_cp", "heldout_buckets", "seconds")}))


if __name__ == "__main__": main()
