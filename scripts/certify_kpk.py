"""Certify conversion bounds with independent legal moves and promotion oracles."""
import argparse
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
    args = parser.parse_args()
    output = pathlib.Path(args.output)
    if output.exists(): parser.error("Preserve certificates")
    raw = pathlib.Path(args.dump).read_bytes(); entries = struct.unpack_from("<I", raw, 8)[0]
    assert raw[:8] == b"ASTKPK01" and entries == 196608
    state = raw[12:12 + entries]; distance = struct.unpack_from("<" + "H" * entries, raw, 12 + entries)
    checked, edges, promoted = 0, 0, 0; started = time.monotonic()
    with chess.syzygy.open_tablebase(args.oracle) as oracle:
        for index, status in enumerate(state):
            if status != 3: continue
            cell = index >> 13; pawn = (cell // 4 + 1) * 8 + cell % 4
            own, defender, side = (index >> 7) & 63, (index >> 1) & 63, index & 1
            board = chess.Board.empty()
            board.set_piece_at(own, chess.Piece(chess.KING, chess.WHITE))
            board.set_piece_at(defender, chess.Piece(chess.KING, chess.BLACK))
            board.set_piece_at(pawn, chess.Piece(chess.PAWN, chess.WHITE))
            board.turn = side == 0
            successors = []
            for move in list(board.legal_moves):
                board.push(move)
                try:
                    edges += 1
                    if move.promotion:
                        promoted += 1
                        value = oracle.probe_wdl(board)
                        won, bound = value < 0, 0  # Black is moving after promotion.
                    elif not board.pawns:
                        won, bound = False, 0
                    else:
                        p = next(iter(board.pieces(chess.PAWN, chess.WHITE)))
                        k, d = board.king(chess.WHITE), board.king(chess.BLACK)
                        child = ((chess.square_rank(p) - 1) * 4 + chess.square_file(p)) * 8192 + k * 128 + d * 2 + int(not board.turn)
                        assert state[child] in (2, 3)
                        won, bound = state[child] == 3, distance[child]
                    successors.append((won, bound))
                finally: board.pop()
            if board.turn:
                assert any(won and bound < distance[index] for won, bound in successors), (board.fen(), distance[index])
            elif successors:
                assert all(won and bound < distance[index] for won, bound in successors), (board.fen(), distance[index])
            else:
                assert board.is_checkmate() and distance[index] == 0
            checked += 1
    report = {"passed": True, "winning_states": checked, "legal_successor_edges": edges, "promotion_edges": promoted,
              "max_conversion_bound": max(distance), "dump_sha256": digest(args.dump), "source_sha256": digest(__file__),
              "seconds": round(time.monotonic() - started, 3),
              "interpretation": "Every pawn-side win has a strictly decreasing legal conversion strategy against every defender reply. Promotion terminals independently verified with Syzygy. Bounds are conservative, not optimal distances."}
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__": main()
