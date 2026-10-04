"""Independent Python reference for Aster's quantized model format and inference."""
from __future__ import annotations

import pathlib
import struct

import chess
import numpy as np

FEATURES = 768
CONTEXT_FEATURES = FEATURES * 17
ATTACK_CATEGORIES = 20
RELATION_FEATURES = CONTEXT_FEATURES + ATTACK_CATEGORIES * 4
ACTIVATION_SCALE = OUTPUT_SCALE = 256


def material_phase(board: chess.Board) -> int:
    return min(24, sum(len(board.pieces(piece, color)) * weight
                      for piece, weight in ((chess.KNIGHT, 1), (chess.BISHOP, 1), (chess.ROOK, 2), (chess.QUEEN, 4))
                      for color in (chess.WHITE, chess.BLACK)))


def attack_feature_bins(board: chess.Board) -> list[int]:
    """Absolute White/Black, P/N/B/R/Q, undefended/defended counts, clipped at3.

    python-chess geometric attacks deliberately include pins and friendly blockers.
    These counts do not prove a legal capture or an exchange outcome.
    """
    control = {chess.WHITE: 0, chess.BLACK: 0}
    for square, piece in board.piece_map().items():
        control[piece.color] |= board.attacks_mask(square)
    result = []
    for color in (chess.WHITE, chess.BLACK):
        for kind in range(chess.PAWN, chess.KING):
            attacked = board.pieces_mask(kind, color) & control[not color]
            result += [min(3, (attacked & ~control[color]).bit_count()),
                       min(3, (attacked & control[color]).bit_count())]
    return result


def feature_indices(board: chess.Board, perspective: bool, king_context: bool = False, attack_features: bool = False) -> list[int]:
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
    if attack_features:
        if not king_context: raise ValueError("Relation features require king context")
        bins = attack_feature_bins(board)
        result += [CONTEXT_FEATURES + (((category // 10) ^ (not perspective)) * 10 + category % 10) * 4 + count
                   for category, count in enumerate(bins)]
    return result


def quantize(values: np.ndarray, scale: float = 1) -> np.ndarray:
    rounded = np.rint(values * scale)
    if not np.isfinite(rounded).all() or (np.abs(rounded) > 32767).any():
        raise ValueError("Model weights exceed the signed 16-bit representation")
    return rounded.astype("<i2")


def save_model(path: pathlib.Path, linear: np.ndarray, bias: np.ndarray, weights: np.ndarray, output: np.ndarray, classical_base: bool = False, king_context: bool = False, turn_output: bool = False, squared_activation: bool = False, phase_output: bool = False, attack_features: bool = False) -> None:
    hidden = bias.size
    features = RELATION_FEATURES if attack_features else CONTEXT_FEATURES if king_context else FEATURES
    if attack_features and (not king_context or not turn_output or not phase_output or squared_activation):
        raise ValueError("Relation features require clipped phase/turn/king-context output")
    if linear.shape != (features,) or weights.shape != (features, hidden) or output.shape != (hidden * (4 if phase_output else 2 if turn_output else 1),) or not 8 <= hidden <= 256 or hidden % 8 or (turn_output and not king_context) or (squared_activation and not turn_output) or (phase_output and (not turn_output or squared_activation)):
        raise ValueError("Invalid model dimensions")
    with path.open("wb") as file:
        version = (11 if classical_base else 12) if attack_features else (9 if classical_base else 10) if phase_output else (7 if classical_base else 8) if squared_activation else (5 if classical_base else 6) if turn_output else (3 if classical_base else 4) if king_context else (2 if classical_base else 1)
        file.write(struct.pack("<8s5i", b"ASTNN001", version, features, hidden, ACTIVATION_SCALE, OUTPUT_SCALE))
        file.write(quantize(linear, 100).tobytes())  # training uses pawn units
        file.write(quantize(bias, ACTIVATION_SCALE).tobytes())
        file.write(quantize(weights, ACTIVATION_SCALE).tobytes())
        file.write(quantize(output, 100 * OUTPUT_SCALE).tobytes())


class QuantizedModel:
    def __init__(self, path: str | pathlib.Path):
        data = pathlib.Path(path).read_bytes()
        magic, version, features, hidden, qa, qb = struct.unpack_from("<8s5i", data)
        context, turn_output = version in range(3, 13), version in range(5, 13)
        phase_output, attack_features = version in (9, 10, 11, 12), version in (11, 12)
        if magic != b"ASTNN001" or version not in range(1, 13) or features != (RELATION_FEATURES if attack_features else CONTEXT_FEATURES if context else FEATURES) or not 8 <= hidden <= 256 or hidden % 8 or qa != 256 or qb != 256:
            raise ValueError("Unsupported Aster neural network format")
        values = np.frombuffer(data, dtype="<i2", offset=28).astype(np.int64)
        outputs = hidden * (4 if phase_output else 2 if turn_output else 1)
        if len(values) != features + hidden + outputs + features * hidden:
            raise ValueError("Invalid payload length")
        self.hidden = hidden
        self.classical_base = version in (2, 3, 5, 7, 9, 11)
        self.king_context = context
        self.turn_output = turn_output
        self.squared_activation = version in (7, 8)
        self.phase_output = phase_output
        self.attack_features = attack_features
        self.linear = values[:features]
        self.bias = values[features:features + hidden]
        self.weights = values[features + hidden:features + hidden + features * hidden].reshape(features, hidden)
        self.output = values[-outputs:]

    def white_score(self, board: chess.Board) -> int:
        white = feature_indices(board, chess.WHITE, self.king_context, self.attack_features)
        black = feature_indices(board, chess.BLACK, self.king_context, self.attack_features)
        linear = int(self.linear[white].sum() - self.linear[black].sum())
        aw = np.clip(self.bias + self.weights[white].sum(axis=0), 0, 256)
        ab = np.clip(self.bias + self.weights[black].sum(axis=0), 0, 256)
        if self.squared_activation:
            aw, ab = aw * aw // 256, ab * ab // 256
        if self.turn_output:
            own, other = (aw, ab) if board.turn else (ab, aw)
            residual = int(own @ self.output[:self.hidden] + other @ self.output[self.hidden:2*self.hidden])
            if self.phase_output:
                endgame = int(own @ self.output[2*self.hidden:3*self.hidden] + other @ self.output[3*self.hidden:])
                phase = material_phase(board)
                residual = residual * phase + endgame * (24 - phase)
            residual *= 1 if board.turn else -1
        else:
            residual = int((aw - ab) @ self.output)
        # C# signed integer division truncates toward zero, not toward -infinity.
        divisor = 256 * 256 * (24 if self.phase_output else 1)
        return int(linear / 2) + (abs(residual) // divisor) * (1 if residual >= 0 else -1)

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
