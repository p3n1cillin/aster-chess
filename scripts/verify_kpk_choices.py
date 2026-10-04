"""Compare frozen KPK move choices with an independent WDL oracle."""
import argparse
import hashlib
import json
import pathlib
import random
import struct
import time

import chess
import chess.engine
import chess.syzygy

from uci_client import engine_command


def digest(path): return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump")
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--oracle", default="tools/syzygy-development-v1")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = pathlib.Path(args.output)
    if output.exists(): parser.error("Preserve previous results")
    raw = pathlib.Path(args.dump).read_bytes()
    assert raw[:8] == b"ASTKPK01" and struct.unpack_from("<I", raw, 8)[0] == 196608
    states = raw[12:12 + 196608]
    rng = random.Random(20261027)
    indices = rng.sample([i for i, s in enumerate(states) if s == 3 and i % 2 == 0], 128)
    indices += rng.sample([i for i, s in enumerate(states) if s == 2 and i % 2 == 1], 128)
    rows = []
    for n, index in enumerate(indices):
        cell = index >> 13
        p, k, d = (cell // 4 + 1) * 8 + cell % 4, (index >> 7) & 63, (index >> 1) & 63
        color = n % 2 == 0; mask = (0 if color else 56) ^ (7 if n % 4 >= 2 else 0)
        board = chess.Board.empty()
        board.set_piece_at(p ^ mask, chess.Piece(chess.PAWN, color))
        board.set_piece_at(k ^ mask, chess.Piece(chess.KING, color))
        board.set_piece_at(d ^ mask, chess.Piece(chess.KING, not color))
        board.turn = color if index % 2 == 0 else not color
        assert board.is_valid() and not board.is_game_over()
        rows.append({"fen": board.fen(), "stratum": "pawn_win" if n < 128 else "defender_draw"})
    # Preserve the exact sample before querying either engine.
    case_path = pathlib.Path(str(output) + ".cases.json")
    if case_path.exists(): parser.error("Preserve frozen cases")
    case_path.write_text(json.dumps({"seed": 20261027, "nodes": 5000, "positions": rows}, indent=2) + "\n")
    started = time.monotonic()
    with chess.syzygy.open_tablebase(args.oracle) as oracle:
        for row in rows:
            board = chess.Board(row["fen"]); values = {}
            row["root_wdl"] = oracle.probe_wdl(board)
            for move in list(board.legal_moves):
                board.push(move)
                try: values[move.uci()] = -oracle.probe_wdl(board)
                finally: board.pop()
            row["best_wdl"] = max(values.values())
            row["legal_move_wdl"] = values
            assert row["root_wdl"] == row["best_wdl"]
        engines = []
        for name, path in (("candidate", args.candidate), ("baseline", args.baseline)):
            passed = 0
            with chess.engine.SimpleEngine.popen_uci(engine_command(path), timeout=60) as engine:
                options = {k: v for k, v in {"Hash": 64, "Threads": 1, "Move Overhead": 0}.items() if k in engine.options}
                engine.configure(options)
                identity = dict(engine.id)
                for row in rows:
                    board = chess.Board(row["fen"])
                    result = engine.play(board, chess.engine.Limit(nodes=5000), game=object(), info=chess.engine.INFO_ALL)
                    assert result.move in board.legal_moves
                    move = result.move.uci(); value = row["legal_move_wdl"][move]
                    correct = value == row["best_wdl"]; passed += correct
                    row[name] = {"move": move, "wdl": value, "preserved": correct,
                                 "nodes": result.info.get("nodes"), "depth": result.info.get("depth")}
            engines.append({"name": name, "path": str(pathlib.Path(path).resolve()), "sha256": digest(path),
                            "id": identity, "options": options, "preserved": passed, "total": len(rows)})
    report = {"complete": True, "cases_sha256": digest(case_path), "dump_sha256": digest(args.dump),
              "oracle_manifest_sha256": digest(pathlib.Path(args.oracle) / "manifest.json"),
              "script_sha256": digest(__file__), "engines": engines, "positions": rows,
              "seconds": round(time.monotonic() - started, 3),
              "interpretation": "Fresh-clock, history-free KPK move-choice regression. WDL preservation is not conversion speed or general playing strength."}
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"engines": engines, "seconds": report["seconds"]}))


if __name__ == "__main__": main()
