"""Independent Python reference for Aster's quantized model format and inference."""
from __future__ import annotations

import pathlib
import struct

import chess
import numpy as np

FEATURES = 768
CONTEXT_FEATURES = FEATURES * 17
ACTIVATION_SCALE = OUTPUT_SCALE = 256


def feature_indices(board: chess.Board, perspective: bool, king_context: bool = False) -> list[int]:
    result = []
    for square, piece in board.piece_map().items():
        relative = (0 if piece.color == perspective else 6) + piece.piece_type - 1
        result.append(relative * 64 + (square if perspective == chess.WHITE else square ^ 56))
    if king_context:
        king = board.king(perspective)
        if king is None: raise ValueError("King-context inference requires both kings")
        oriented = king if perspective == chess.WHITE else king ^ 56
        bucket = (chess.square_rank(oriented) // 2) * 4 + chess.square_file(oriented) // 2
        result += [FEATURES * (bucket + 1) + feature for feature in result]
    return result


def quantize(values: np.ndarray, scale: float = 1) -> np.ndarray:
    rounded = np.rint(values * scale)
    if not np.isfinite(rounded).all() or (np.abs(rounded) > 32767).any():
        raise ValueError("Model weights exceed the signed 16-bit representation")
    return rounded.astype("<i2")


def save_model(path: pathlib.Path, linear: np.ndarray, bias: np.ndarray, weights: np.ndarray, output: np.ndarray, classical_base: bool = False, king_context: bool = False) -> None:
    hidden = bias.size
    features = CONTEXT_FEATURES if king_context else FEATURES
    if linear.shape != (features,) or weights.shape != (features, hidden) or output.shape != (hidden,) or not 8 <= hidden <= 256 or hidden % 8:
        raise ValueError("Invalid model dimensions")
    with path.open("wb") as file:
        version = (3 if classical_base else 4) if king_context else (2 if classical_base else 1)
        file.write(struct.pack("<8s5i", b"ASTNN001", version, features, hidden, ACTIVATION_SCALE, OUTPUT_SCALE))
        file.write(quantize(linear, 100).tobytes())  # training uses pawn units
        file.write(quantize(bias, ACTIVATION_SCALE).tobytes())
        file.write(quantize(weights, ACTIVATION_SCALE).tobytes())
        file.write(quantize(output, 100 * OUTPUT_SCALE).tobytes())


class QuantizedModel:
    def __init__(self, path: str | pathlib.Path):
        data = pathlib.Path(path).read_bytes()
        magic, version, features, hidden, qa, qb = struct.unpack_from("<8s5i", data)
        context = version in (3, 4)
        if magic != b"ASTNN001" or version not in (1, 2, 3, 4) or features != (CONTEXT_FEATURES if context else FEATURES) or not 8 <= hidden <= 256 or hidden % 8 or qa != 256 or qb != 256:
            raise ValueError("Unsupported Aster neural network format")
        values = np.frombuffer(data, dtype="<i2", offset=28).astype(np.int64)
        if len(values) != features + 2 * hidden + features * hidden:
            raise ValueError("Invalid payload length")
        self.hidden = hidden
        self.classical_base = version in (2, 3)
        self.king_context = context
        self.linear = values[:features]
        self.bias = values[features:features + hidden]
        self.weights = values[features + hidden:features + hidden + features * hidden].reshape(features, hidden)
        self.output = values[-hidden:]

    def white_score(self, board: chess.Board) -> int:
        white = feature_indices(board, chess.WHITE, self.king_context)
        black = feature_indices(board, chess.BLACK, self.king_context)
        linear = int(self.linear[white].sum() - self.linear[black].sum())
        aw = np.clip(self.bias + self.weights[white].sum(axis=0), 0, 256)
        ab = np.clip(self.bias + self.weights[black].sum(axis=0), 0, 256)
        residual = int((aw - ab) @ self.output)
        # C# signed integer division truncates toward zero, not toward -infinity.
        return int(linear / 2) + int(residual / (256 * 256))

    def side_score(self, board: chess.Board, classical_score: int | None = None) -> int:
        white = self.white_score(board)
        if self.classical_base:
            if classical_score is None:
                raise ValueError("Hybrid inference requires the classical side-to-move score")
            white = max(-250, min(250, white))
            baseline = classical_score
        else:
            baseline = 12
        return max(-28000, min(28000, (white if board.turn else -white) + baseline))
