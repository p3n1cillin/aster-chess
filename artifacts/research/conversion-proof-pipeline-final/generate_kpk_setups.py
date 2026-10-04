"""Freeze fresh KPK setups by outcome, turn and pawn-file strata before play."""
import argparse
import hashlib
import json
import pathlib
import random
import struct

import chess
import chess.syzygy


def digest(path): return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def normalize(board):
    color = chess.WHITE if board.pieces(chess.PAWN, chess.WHITE) else chess.BLACK
    p = next(iter(board.pieces(chess.PAWN, color))); k = board.king(color); d = board.king(not color)
    mask = (0 if color else 56)
    if (p ^ mask) % 8 >= 4: mask ^= 7
    p ^= mask; k ^= mask; d ^= mask
    return ((p // 8 - 1) * 4 + p % 8) * 8192 + k * 128 + d * 2 + int(board.turn != color)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dump", default="artifacts/validation/kpk-generated-v1.bin")
    parser.add_argument("--oracle", default="tools/syzygy-development-v1")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(); output = pathlib.Path(args.output)
    if output.exists(): parser.error("Preserve frozen suites")
    raw = pathlib.Path(args.dump).read_bytes(); assert raw[:8] == b"ASTKPK01"
    entries = struct.unpack_from("<I", raw, 8)[0]; assert entries == 196608
    states = raw[12:12 + entries]; bounds = struct.unpack_from("<" + "H" * entries, raw, 12 + entries)
    exclusions = ["artifacts/validation/kpk-move-choices.json.cases.json",
                  "tests/fixtures/tactics-v1.json", "tests/fixtures/tactics-quiet-v1.json", "tests/fixtures/endgames-v1.json"]
    excluded = set()
    for path in exclusions:
        data = json.loads(pathlib.Path(path).read_text())
        for row in data["positions"]:
            board = chess.Board(row["fen"])
            if len(board.piece_map()) == 3 and board.pawns.bit_count() == 1: excluded.add(normalize(board))
    rng = random.Random(20261028); strata = {}; chosen = []
    for status in (3, 2):
        for side in (0, 1):
            for rook in (True, False):
                pool = [i for i, s in enumerate(states) if s == status and i % 2 == side
                        and (((i >> 13) % 4 == 0) == rook) and i not in excluded
                        and (status == 2 or bounds[i] >= 18)]
                label = f"{'win' if status == 3 else 'draw'}-{'pawn' if side == 0 else 'defender'}-{'rook' if rook else 'other'}"
                sample = rng.sample(pool, 8); strata[label] = {"eligible": len(pool), "sampled": 8}
                chosen.extend((i, label) for i in sample)
    # Interleave strata so every prefix of eight includes all classifications.
    chosen = [chosen[group * 8 + within] for within in range(8) for group in range(8)]
    manifest_path = pathlib.Path(args.oracle) / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for entry in manifest["files"]: assert digest(pathlib.Path(args.oracle) / entry["name"]) == entry["sha256"]
    openings = []
    with chess.syzygy.open_tablebase(args.oracle) as oracle:
        for n, (index, label) in enumerate(chosen):
            cell = index >> 13; p = (cell // 4 + 1) * 8 + cell % 4
            k, d, side = (index >> 7) & 63, (index >> 1) & 63, index & 1
            color = (n // 8 + n % 8) % 2 == 0; mask = (0 if color else 56) ^ (7 if n % 4 >= 2 else 0)
            board = chess.Board.empty()
            board.set_piece_at(p ^ mask, chess.Piece(chess.PAWN, color))
            board.set_piece_at(k ^ mask, chess.Piece(chess.KING, color))
            board.set_piece_at(d ^ mask, chess.Piece(chess.KING, not color))
            board.turn = color if side == 0 else not color
            assert board.is_valid() and not board.is_game_over()
            value = oracle.probe_wdl(board)
            assert value == ((2 if side == 0 else -2) if states[index] == 3 else 0)
            openings.append({"id": f"kpk-{n+1:03d}", "start_fen": board.fen(), "moves": "", "fen": board.fen(),
                             "normalized_index": index, "stratum": label, "oracle_wdl": value,
                             "conversion_bound": bounds[index], "pawn_color": "white" if color else "black"})
    report = {"schema": 2, "kind": "synthetic-kpk-setups", "seed": 20261028, "strata": strata,
              "history_origin": "Legal synthetic FEN, fresh halfmove clock, no preceding repetition history; all subsequent play retained.",
              "dump_sha256": digest(args.dump), "oracle_manifest_sha256": digest(manifest_path), "generator_sha256": digest(__file__),
              "exclusions": [{"path": p, "sha256": digest(p)} for p in exclusions], "openings": openings,
              "interpretation": "Targeted endgame conversion/defense diagnostic, not balanced general-strength openings. Selected before querying either Aster build."}
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"positions": len(openings), "strata": strata, "sha256": digest(output)}))


if __name__ == "__main__": main()
