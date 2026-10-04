"""Verify colored/reflected KPK runtime probes, clock guards and clean protocol."""
import argparse
import hashlib
import json
import pathlib
import random
import struct

import chess

from uci_client import UciClient


def digest(path): return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump")
    parser.add_argument("--engine", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = pathlib.Path(args.output)
    if output.exists(): parser.error("Preserve previous checks")
    raw = pathlib.Path(args.dump).read_bytes(); entries = struct.unpack_from("<I", raw, 8)[0]
    states = raw[12:12 + entries]; bounds = struct.unpack_from("<" + "H" * entries, raw, 12 + entries)
    sample = random.Random(20261026).sample([i for i, state in enumerate(states) if state in (2, 3)], 512)
    checked = 0
    with UciClient(args.engine) as client, UciClient(args.baseline) as baseline:
        for index in sample:
            cell = index >> 13; p = (cell // 4 + 1) * 8 + cell % 4
            k, d, side = (index >> 7) & 63, (index >> 1) & 63, index & 1
            for pawn_color in (chess.WHITE, chess.BLACK):
                for reflected in (False, True):
                    mask = (0 if pawn_color else 56) ^ (7 if reflected else 0)
                    board = chess.Board.empty()
                    board.set_piece_at(p ^ mask, chess.Piece(chess.PAWN, pawn_color))
                    board.set_piece_at(k ^ mask, chess.Piece(chess.KING, pawn_color))
                    board.set_piece_at(d ^ mask, chess.Piece(chess.KING, not pawn_color))
                    board.turn = pawn_color if side == 0 else not pawn_color
                    assert board.is_valid()
                    for clock in (0, 99):
                        board.halfmove_clock = clock; fen = board.fen()
                        client.send("position fen " + fen)
                        expected_probe = "info string kpk " + ("win" if states[index] == 3 else "draw") + " " + str(bounds[index])
                        assert client.command("kpk", "info string kpk ") == expected_probe
                        expected = 0
                        if states[index] == 3:
                            if clock + bounds[index] >= 100:
                                baseline.send("position fen " + fen)
                                expected = int(baseline.command("eval", "info string eval ").split()[-1])
                            else: expected = (1 if side == 0 else -1) * (400 - bounds[index])
                        assert int(client.command("eval", "info string eval ").split()[-1]) == expected
                        assert client.command("d", "info string fen ") == "info string fen " + fen
                        checked += 1
        client.send("position startpos")
        assert client.command("kpk", "info string kpk ") == "info string kpk unsupported"
        client.send("go infinite"); client.ready()
        client.send("stop"); best = client.until("bestmove ", timeout=5)[-1]
        assert chess.Move.from_uci(best.split()[-1]) in chess.Board().legal_moves
    report = {"passed": True, "positions": checked, "sample_states": len(sample), "engine_sha256": digest(args.engine),
              "baseline_sha256": digest(args.baseline), "dump_sha256": digest(args.dump), "source_sha256": digest(__file__),
              "interpretation": "Runtime color/file normalization, unchanged board, rule50 fallbacks and responsive isready/stop; not strength."}
    output.write_text(json.dumps(report, indent=2) + "\n"); print(json.dumps(report))


if __name__ == "__main__": main()
