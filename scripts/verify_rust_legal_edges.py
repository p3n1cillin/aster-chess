"""Independently test existence queries around pins, promotions and terminal clocks."""
import argparse
import hashlib
import json
import pathlib

import chess

from uci_client import DEFAULT_ENGINE, UciClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', default=str(DEFAULT_ENGINE))
    parser.add_argument('--output')
    args = parser.parse_args()
    cases = [
        '8/8/8/8/2qb4/8/1Pk5/K7 w - - 0 1',  # Pinned pawn has no legal push.
        '8/8/8/8/2qb4/8/1Nk5/K7 w - - 0 1',  # Every knight probe uncovers check.
        '8/8/8/8/6N1/1q6/2k5/K7 w - - 0 1',  # Knight moves are the only escape.
        '8/8/8/8/8/1q6/2k3P1/K7 w - - 0 1',  # Pawn moves are the only escape.
        '8/7P/8/8/8/1q6/2k5/K7 w - - 0 1',   # Only promotion moves exist.
        '7k/6Q1/6K1/8/8/8/8/8 b - - 0 1',
        '7k/5Q2/6K1/8/8/8/8/8 b - - 0 1',
        '4r1k1/8/8/8/1b6/8/8/4K3 w - - 0 1',
        '5B2/7B/6P1/R4pPk/8/7K/8/8 w - f6 0 1',
        '8/8/8/8/R1pP2k1/8/8/7K b - d3 0 1',
        'r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1',
    ]
    checked = []
    with UciClient(args.engine) as engine:
        for fen in cases:
            for mirrored in (False, True):
                origin = chess.Board(fen)
                if mirrored:
                    origin = origin.mirror()
                for clock in ([0] if origin.ep_square else [0, 99, 100, 150, 255]):
                    board = origin.copy()
                    board.halfmove_clock = clock
                    assert board.is_valid(), board.fen()
                    expected = {move.uci() for move in board.legal_moves}
                    engine.send('position fen ' + board.fen(en_passant='fen'))
                    actual = engine.command('legal-exists', 'info string legal-exists ')
                    assert actual == 'info string legal-exists ' + str(bool(expected)).lower(), board.fen()
                    legal = engine.command('legal', 'info string legal')
                    assert set(legal.removeprefix('info string legal').split()) == expected
                    after = engine.command('d', 'info string fen ').removeprefix('info string fen ')
                    assert chess.Board(after).fen() == board.fen(), (board.fen(), after)
                    if not expected:
                        engine.send('go depth 1')
                        lines = engine.until('bestmove')
                        score = 'score mate 0' if board.is_checkmate() else 'score cp 0'
                        assert any(score in line for line in lines), (board.fen(), lines)
                    checked.append({'fen': board.fen(en_passant='fen'), 'legal_moves': len(expected)})
    report = {'passed': True, 'positions': len(checked), 'cases': checked,
              'binary_sha256': hashlib.sha256(pathlib.Path(args.engine).read_bytes()).hexdigest(),
              'checker_sha256': hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()}
    if args.output:
        path = pathlib.Path(args.output)
        if path.exists():
            raise ValueError('Preserve earlier verification attempts')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((json.dumps(report, indent=2) + '\n').encode())
    print(json.dumps({'passed': True, 'positions': len(checked)}))


if __name__ == '__main__':
    main()
