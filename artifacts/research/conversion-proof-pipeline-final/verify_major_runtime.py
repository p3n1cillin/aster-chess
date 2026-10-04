"""Verify color/D4 normalization, clock fallbacks and actual root conversion moves."""
import argparse
import hashlib
import json
import pathlib
import random
import struct

import chess
import chess.engine

from uci_client import UciClient, engine_command


def digest(path): return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def transform(square, symmetry):
    f, r = square % 8, square // 8
    if symmetry & 1: f, r = r, f
    if symmetry & 2: f = 7 - f
    if symmetry & 4: r = 7 - r
    return r * 8 + f


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True)
    parser.add_argument("--control", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(); output = pathlib.Path(args.output)
    if output.exists(): parser.error("Preserve runtime evidence")
    tables = []; rng = random.Random(20261029)
    for name in ("queen", "rook"):
        path = pathlib.Path("artifacts/validation/major-" + name + "-v1.bin"); raw = path.read_bytes()
        entries = struct.unpack_from("<I", raw, 12)[0]
        states, bounds = raw[16:16 + entries], raw[16 + entries:]
        sample = rng.sample([i for i, s in enumerate(states) if s in (2, 3)], 128)
        tables.append((name, path, states, bounds, sample))
    probes = 0; searches = 0; restricted = 0
    with UciClient(args.engine) as client, UciClient(args.control) as control, \
            chess.engine.SimpleEngine.popen_uci(engine_command(args.engine), timeout=60) as engine:
        engine.configure({"Hash": 64, "Threads": 1, "Move Overhead": 0})
        for name, _, states, bounds, sample in tables:
            for index in sample:
                p, k, d, side = index >> 13, (index >> 7) & 63, (index >> 1) & 63, index & 1
                for symmetry in range(8):
                    for color in (chess.WHITE, chess.BLACK):
                        board = chess.Board.empty()
                        board.set_piece_at(transform(p, symmetry), chess.Piece(chess.QUEEN if name == "queen" else chess.ROOK, color))
                        board.set_piece_at(transform(k, symmetry), chess.Piece(chess.KING, color))
                        board.set_piece_at(transform(d, symmetry), chess.Piece(chess.KING, not color))
                        board.turn = color if side == 0 else not color
                        assert board.is_valid()
                        for clock in (0, 99):
                            board.halfmove_clock = clock; fen = board.fen()
                            client.send("position fen " + fen)
                            assert client.command("major", "info string major ") == f"info string major {'win' if states[index] == 3 else 'draw'} {0 if color else 1} {bounds[index]}"
                            if states[index] == 2: expected = 0
                            elif clock + bounds[index] < 100: expected = (1 if side == 0 else -1) * (2000 - bounds[index])
                            else:
                                control.send("position fen " + fen)
                                expected = int(control.command("eval", "info string eval ").split()[-1])
                            assert int(client.command("eval", "info string eval ").split()[-1]) == expected
                            assert client.command("d", "info string fen ") == "info string fen " + fen
                            probes += 1
                        if symmetry == 0 and color == chess.WHITE and side == 0 and states[index] == 3:
                            board.halfmove_clock = 0
                            response = engine.play(board, chess.engine.Limit(nodes=100), game=object())
                            assert response.move in board.legal_moves
                            board.push(response.move)
                            child = next(iter(board.pieces(chess.QUEEN if name == "queen" else chess.ROOK, color))) * 8192 + board.king(color) * 128 + board.king(not color) * 2 + int(board.turn != color)
                            assert states[child] == 3 and bounds[child] < bounds[index]
                            board.pop(); searches += 1
                            # A caller can explicitly request a legal non-progress move.
                            alternative = None
                            for move in list(board.legal_moves):
                                board.push(move)
                                child = next(iter(board.pieces(chess.QUEEN if name == "queen" else chess.ROOK, color))) * 8192 + board.king(color) * 128 + board.king(not color) * 2 + int(board.turn != color)
                                board.pop()
                                if states[child] != 3 or bounds[child] >= bounds[index]: alternative = move; break
                            if alternative:
                                result = engine.play(board, chess.engine.Limit(nodes=100), root_moves=[alternative], game=object())
                                assert result.move == alternative; restricted += 1
        client.send("position fen 7k/8/8/8/8/8/Q7/K7 w - - 0 1")
        client.send("go infinite"); client.ready(); client.send("stop")
        move = chess.Move.from_uci(client.until("bestmove ", timeout=5)[-1].split()[-1])
        assert move in chess.Board("7k/8/8/8/8/8/Q7/K7 w - - 0 1").legal_moves
    result = {"passed": True, "runtime_probes": probes, "progress_searches": searches, "restricted_searchmoves": restricted,
              "engine_sha256": digest(args.engine), "control_sha256": digest(args.control),
              "tables": [{"piece": name, "sha256": digest(path)} for name, path, *_ in tables], "script_sha256": digest(__file__),
              "interpretation": "All D4/color transformations, unchanged FENs, late-clock evaluation fallback, actual decreasing-distance root choices, explicit searchmoves and responsive infinite-search stop checked."}
    output.write_text(json.dumps(result, indent=2) + "\n"); print(json.dumps(result))


if __name__ == "__main__": main()
