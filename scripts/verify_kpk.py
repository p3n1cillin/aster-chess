"""Exhaustively compare Aster's independently generated KPK table with Syzygy."""
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
    args = parser.parse_args()
    output = pathlib.Path(args.output)
    if output.exists(): parser.error("Preserve previous verification")
    raw = pathlib.Path(args.dump).read_bytes()
    assert raw[:8] == b"ASTKPK01"
    entries = struct.unpack_from("<I", raw, 8)[0]
    assert entries == 196608 and len(raw) == 12 + entries * 3
    states = raw[12:12 + entries]
    distance = struct.unpack_from("<" + "H" * entries, raw, 12 + entries)
    oracle_manifest = json.loads((pathlib.Path(args.oracle) / "manifest.json").read_text())
    for entry in oracle_manifest["files"]:
        assert digest(pathlib.Path(args.oracle) / entry["name"]) == entry["sha256"]
    counts = collections.Counter(); discrepancies = []
    started = time.monotonic()
    with chess.syzygy.open_tablebase(args.oracle) as oracle:
        for index in range(entries):
            cell = index >> 13; p = (cell // 4 + 1) * 8 + cell % 4
            own, bare, side = (index >> 7) & 63, (index >> 1) & 63, index & 1
            board = chess.Board.empty()
            board.set_piece_at(own, chess.Piece(chess.KING, chess.WHITE))
            board.set_piece_at(bare, chess.Piece(chess.KING, chess.BLACK))
            board.set_piece_at(p, chess.Piece(chess.PAWN, chess.WHITE))
            board.turn = side == 0
            if not board.is_valid():
                if states[index] != 0: discrepancies.append({"index": index, "kind": "invalid"})
                counts["invalid"] += 1
                continue
            value = oracle.probe_wdl(board)
            expected_win = (value > 0 if board.turn else value < 0)
            counts["oracle_wdl_" + str(value)] += 1
            if states[index] not in (2, 3) or (states[index] == 3) != expected_win:
                discrepancies.append({"fen": board.fen(), "index": index, "oracle": value, "aster": states[index]})
            if states[index] == 3: counts["wins"] += 1
            else: counts["draws"] += 1
            if len(discrepancies) > 20: break
    report = {"passed": not discrepancies, "entries": entries, "checked_entries": sum(counts[k] for k in ("invalid", "wins", "draws")),
              "counts": dict(counts), "discrepancies": discrepancies, "max_conversion_bound": max(distance),
              "dump_sha256": digest(args.dump), "oracle_manifest_sha256": digest(pathlib.Path(args.oracle) / "manifest.json"),
              "source_sha256": digest(__file__), "seconds": round(time.monotonic() - started, 3),
              "interpretation": "Exhaustive independent Syzygy comparison on normalized KPK states. WDL assumes fresh reversible clock; runtime near-rule50 fallback is separate."}
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    if discrepancies: raise RuntimeError("KPK mismatch; preserve failed report")


if __name__ == "__main__": main()
