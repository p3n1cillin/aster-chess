"""Exhaustively check generated KQK/KRK WDL and optimal mate recurrences."""
import argparse
import collections
import hashlib
import json
import pathlib
import struct
import time

import chess
import chess.syzygy


def digest(path): return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump")
    parser.add_argument("--oracle", default="tools/syzygy-development-v1")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(); output = pathlib.Path(args.output)
    if output.exists(): parser.error("Preserve previous certificates")
    raw = pathlib.Path(args.dump).read_bytes()
    kind, entries = struct.unpack_from("<II", raw, 8)
    assert raw[:8] == b"ASTMAJ01" and kind in (3, 4) and entries == 524288 and len(raw) == 16 + entries * 2
    piece_type = chess.QUEEN if kind == 4 else chess.ROOK
    state, distance = raw[16:16 + entries], raw[16 + entries:]
    manifest_path = pathlib.Path(args.oracle) / "manifest.json"
    for entry in json.loads(manifest_path.read_text())["files"]:
        assert digest(pathlib.Path(args.oracle) / entry["name"]) == entry["sha256"]
    counts = collections.Counter(); edges = 0; started = time.monotonic()
    with chess.syzygy.open_tablebase(args.oracle) as oracle:
        for index in range(entries):
            p, k, d, side = index >> 13, (index >> 7) & 63, (index >> 1) & 63, index & 1
            board = chess.Board.empty()
            board.set_piece_at(p, chess.Piece(piece_type, chess.WHITE))
            board.set_piece_at(k, chess.Piece(chess.KING, chess.WHITE))
            board.set_piece_at(d, chess.Piece(chess.KING, chess.BLACK)); board.turn = side == 0
            # Count distinct pieces too: set_piece_at overwrites collisions.
            valid = p != k and p != d and k != d and board.is_valid()
            if not valid:
                assert state[index] == 0, ("invalid", board.fen(), index)
                counts["invalid"] += 1; continue
            wdl = oracle.probe_wdl(board); win = wdl > 0 if board.turn else wdl < 0
            assert state[index] == (3 if win else 2), ("wdl", board.fen(), wdl, state[index])
            counts["wins" if win else "draws"] += 1
            if not win:
                assert distance[index] == 0; continue
            children = []
            for move in list(board.legal_moves):
                board.push(move)
                try:
                    edges += 1; pieces = board.pieces(piece_type, chess.WHITE)
                    if not pieces: children.append((False, 0)); continue
                    child = next(iter(pieces)) * 8192 + board.king(chess.WHITE) * 128 + board.king(chess.BLACK) * 2 + int(not board.turn)
                    assert state[child] in (2, 3)
                    children.append((state[child] == 3, distance[child]))
                finally: board.pop()
            if board.turn:
                assert any(won for won, _ in children)
                expected = min(bound for won, bound in children if won) + 1
            elif children:
                assert all(won for won, _ in children)
                expected = max(bound for _, bound in children) + 1
            else:
                assert board.is_checkmate(); expected = 0; counts["checkmates"] += 1
            assert distance[index] == expected, ("mate recurrence", board.fen(), distance[index], expected)
            if index % 65536 == 0: print(json.dumps({"checked": index, "edges": edges}), flush=True)
    result = {"passed": True, "entries": entries, "piece": "queen" if kind == 4 else "rook", "counts": dict(counts),
              "winning_legal_edges": edges, "max_mate_distance": max(distance), "seconds": round(time.monotonic() - started, 3),
              "dump_sha256": digest(args.dump), "oracle_manifest_sha256": digest(manifest_path), "script_sha256": digest(__file__),
              "interpretation": "All valid theoretical WDL classifications agree independently with Syzygy. Every winning distance satisfies the independent legal min/max mate recurrence. Clock/history guards tested separately."}
    output.write_text(json.dumps(result, indent=2) + "\n"); print(json.dumps(result), flush=True)


if __name__ == "__main__": main()
