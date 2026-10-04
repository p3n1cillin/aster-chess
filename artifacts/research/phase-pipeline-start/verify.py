"""Independent legality, perft, FEN, search and UCI integration verification."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import random
import re
import time

import chess
import chess.engine

from uci_client import DEFAULT_ENGINE, UciClient, engine_command

SPECIAL_FENS = [
    chess.STARTING_FEN,
    "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
    "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
    "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
    "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8",
    "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10",
    "8/8/8/r4pPK/8/8/8/4k3 w - f6 0 1",
    "7k/P7/8/8/8/8/8/7K w - - 0 1",
    "4kr2/8/8/8/8/8/8/4K2R w K - 0 1",
    "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1",
    "7k/6Q1/6K1/8/8/8/8/8 b - - 100 1",
    "k7/n1K5/8/8/8/8/8/R7 b - - 0 1",
    "k7/nnK5/8/8/8/8/8/R6B b - - 0 1",
    "r7/8/8/8/8/8/B1k5/K7 w - - 0 1",
]


def reference_perft(board: chess.Board, depth: int) -> int:
    if depth == 0:
        return 1
    if depth == 1:
        return board.legal_moves.count()
    nodes = 0
    for move in list(board.legal_moves):
        board.push(move)
        nodes += reference_perft(board, depth - 1)
        board.pop()
    return nodes


def haslegal_supported(name: str) -> bool:
    version = re.match(r"Aster (\d+)\.(\d+)", name)
    return version is not None and tuple(map(int, version.groups())) >= (0, 5)


def verify_position(client: UciClient, board: chess.Board) -> None:
    fen = board.fen(en_passant="fen")
    client.send("position fen " + fen)
    legal_line = client.command("legal", "info string legal")
    actual = set(legal_line[len("info string legal"):].split())
    expected = {move.uci() for move in board.legal_moves}
    if actual != expected:
        raise AssertionError(f"Move mismatch at {fen}\nmissing={expected - actual}\nextra={actual - expected}")
    # The new predicate is checked independently, not inferred from perft.
    if haslegal_supported(client.name):
        has_legal = client.command("haslegal", "info string haslegal ").split()[-1] == "true"
        assert has_legal == bool(expected), (fen, has_legal, expected)
    actual_fen = client.command("d", "info string fen ")[len("info string fen "):]
    assert actual_fen == fen, (fen, actual_fen)


def validate_pv(board: chess.Board, lines: list[str]) -> None:
    for line in lines:
        if " pv " not in line:
            continue
        copy = board.copy()
        for text in line.split(" pv ", 1)[1].split():
            move = chess.Move.from_uci(text)
            assert move in copy.legal_moves, (board.fen(), line, text)
            copy.push(move)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", default=str(DEFAULT_ENGINE))
    parser.add_argument("--games", type=int, default=16)
    parser.add_argument("--plies", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20261003)
    parser.add_argument("--setups", type=int, default=0, help="Additional bounded random legal material configurations")
    parser.add_argument("--output", help="Optional JSON verification report")
    parser.add_argument("--eval-file", help="Optional Aster network to exercise the neural runtime")
    args = parser.parse_args()
    assert args.games > 0 and args.plies > 0 and args.setups >= 0
    random_source = random.Random(args.seed)
    checked = 0
    setup_counts = {"positions": 0, "in_check": 0, "checkmates": 0, "stalemates": 0}
    started = time.monotonic()
    with UciClient(args.engine) as client:
        if args.eval_file:
            client.send("setoption name EvalFile value " + str(pathlib.Path(args.eval_file).resolve())); client.ready()
        for fen in SPECIAL_FENS:
            board = chess.Board(fen)
            verify_position(client, board)
            expected = reference_perft(board, 3)
            actual = int(client.command("perft 3", "info string perft 3 ").split()[-1])
            assert actual == expected, (fen, expected, actual)
            checked += 1
        for _ in range(args.games):
            board = chess.Board()
            for _ in range(args.plies):
                verify_position(client, board)
                checked += 1
                legal = list(board.legal_moves)
                if not legal:
                    break
                board.push(random_source.choice(legal))

        for _ in range(args.setups * 20):
            if setup_counts["positions"] == args.setups: break
            board = chess.Board.empty()
            squares = random_source.sample(range(64), 2 + random_source.randrange(7))
            board.set_piece_at(squares[0], chess.Piece(chess.KING, chess.WHITE))
            board.set_piece_at(squares[1], chess.Piece(chess.KING, chess.BLACK))
            for square in squares[2:]:
                kind = random_source.choice([chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN])
                board.set_piece_at(square, chess.Piece(kind, random_source.choice([chess.WHITE, chess.BLACK])))
            board.turn = random_source.choice([chess.WHITE, chess.BLACK])
            if not board.is_valid(): continue
            verify_position(client, board); checked += 1; setup_counts["positions"] += 1
            setup_counts["in_check"] += board.is_check()
            if not any(board.legal_moves):
                setup_counts["checkmates" if board.is_check() else "stalemates"] += 1
        assert setup_counts["positions"] == args.setups, "Random setup attempt budget exhausted"

        client.send("position startpos")
        client.send("go infinite")
        client.until("info depth ")
        ready_started = time.monotonic()
        client.ready()
        assert time.monotonic() - ready_started < 1, "isready blocked during search"
        stop_started = time.monotonic()
        client.send("stop")
        stopped = client.until("bestmove ")
        assert time.monotonic() - stop_started < 1, "stop did not promptly interrupt search"
        validate_pv(chess.Board(), stopped)
        assert chess.Move.from_uci(stopped[-1].split()[1]) in chess.Board().legal_moves

        # A command following searchmoves must not be parsed as a move.
        client.send("position startpos")
        assert client.command("go searchmoves e2e4 depth 3", "bestmove ").split()[1] == "e2e4"
        client.send("position startpos")
        client.send("go nodes 1000")
        node_lines = client.until("bestmove ")
        for line in node_lines:
            if line.startswith("info depth "):
                assert int(line.split(" nodes ")[1].split()[0]) <= 1000
        validate_pv(chess.Board(), node_lines)

        client.send("position startpos")
        timed_started = time.monotonic()
        move = client.command("go movetime 50", "bestmove ").split()[1]
        assert chess.Move.from_uci(move) in chess.Board().legal_moves
        assert time.monotonic() - timed_started < 1, "movetime limit ignored"
        for fen in ["7k/5Q2/6K1/8/8/8/8/8 b - - 0 1", "3Q2k1/5ppp/8/8/8/8/5PPP/6K1 b - - 100 1"]:
            client.send("position fen " + fen)
            assert client.command("go depth 3", "bestmove ") == "bestmove 0000"

        client.send("position startpos")
        client.send("position startpos moves e2e5")
        client.until("info string error:")
        assert client.command("d", "info string fen ") == "info string fen " + chess.STARTING_FEN
        # Finished searches must be reusable without restarting the process.
        for _ in range(8):
            client.send("position startpos moves e2e4 e7e5")
            board = chess.Board()
            board.push_uci("e2e4"); board.push_uci("e7e5")
            client.send("go depth 4")
            lines = client.until("bestmove ")
            validate_pv(board, lines)
            assert chess.Move.from_uci(lines[-1].split()[1]) in board.legal_moves

    # Exercise a separate, established UCI client as well as our raw client.
    with chess.engine.SimpleEngine.popen_uci(engine_command(args.engine), timeout=10) as engine:
        if args.eval_file:
            engine.configure({"EvalFile": str(pathlib.Path(args.eval_file).resolve())})
        for fen in SPECIAL_FENS[:6]:
            board = chess.Board(fen)
            result = engine.play(board, chess.engine.Limit(time=0.05))
            assert result.move in board.legal_moves, (fen, result)

    with pathlib.Path(args.engine).open("rb") as binary:
        digest = hashlib.file_digest(binary, "sha256").hexdigest()
    report = {"status": "passed", "engine": str(pathlib.Path(args.engine).resolve()), "binary_sha256": digest,
              "positions_checked": checked, "reference_perft_positions": len(SPECIAL_FENS),
              "protocol_checks": "passed", "seed": args.seed, "seconds": round(time.monotonic() - started, 3)}
    report["legal_move_existence_positions"] = checked if haslegal_supported(client.name) else 0
    report["random_setups"] = setup_counts
    report["eval_file"] = args.eval_file
    if args.output:
        output = pathlib.Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
