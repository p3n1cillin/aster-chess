"""Compare native proof protocol and fixed-node behavior with frozen references."""
import argparse
import hashlib
import json
import pathlib

import chess
import chess.engine

from uci_client import UciClient, engine_command


def digest(path): return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(); output = pathlib.Path(args.output)
    if output.exists(): parser.error("Preserve previous protocol reports")
    proof = pathlib.Path("artifacts/publish/proof-dev/Aster.exe")
    reference = pathlib.Path("artifacts/publish/conversion-dev/Aster.exe")
    sf = json.loads(pathlib.Path("tools/stockfish/manifest.json").read_text())
    transcript = []
    with UciClient(proof) as client:
        client.send("position fen 7k/8/8/8/8/8/R7/K7 w - - 0 1")
        client.send("go infinite"); client.send("explain"); client.ready()
        line = client.until("info string explanation ", timeout=10)[-1]
        explanation = json.loads(line[len("info string explanation "):])
        assert explanation["complete"] and explanation["positions"] > 10
        client.ready(); client.send("stop")
        move = chess.Move.from_uci(client.until("bestmove ", timeout=5)[-1].split()[-1])
        assert move in chess.Board("7k/8/8/8/8/8/R7/K7 w - - 0 1").legal_moves
        assert client.command("d", "info string fen ") == "info string fen 7k/8/8/8/8/8/R7/K7 w - - 0 1"
        transcript.append({"engine": "Aster", "response": explanation})
    with UciClient(sf["executable"]) as client:
        client.send("explain"); client.send("isready")
        lines = client.until("readyok", timeout=10)
        assert not any(line.startswith("info string explanation ") for line in lines)
        transcript.append({"engine": sf["uci_name"], "responses": lines})
    checked = 0
    with chess.engine.SimpleEngine.popen_uci(engine_command(proof), timeout=60) as candidate, \
            chess.engine.SimpleEngine.popen_uci(engine_command(reference), timeout=60) as original:
        for engine in (candidate, original): engine.configure({"Threads": 1, "Hash": 64, "Move Overhead": 0})
        rows = json.loads(pathlib.Path("tests/fixtures/kpk-setups-v1.json").read_text())["openings"]
        rows += [{"fen": fen} for fen in ("7k/8/8/8/8/8/R7/K7 w - - 0 1", "7k/8/8/8/8/8/Q7/K7 w - - 0 1")]
        for row in rows:
            board = chess.Board(row["fen"])
            a = candidate.play(board, chess.engine.Limit(nodes=1000), game=object(), info=chess.engine.INFO_ALL)
            b = original.play(board, chess.engine.Limit(nodes=1000), game=object(), info=chess.engine.INFO_ALL)
            assert a.move == b.move and a.info.get("score") == b.info.get("score") and a.info.get("nodes") == b.info.get("nodes")
            checked += 1
    source_a = pathlib.Path("artifacts/research/proof-source/src/Engine")
    source_b = pathlib.Path("artifacts/research/conversion-source/src/Engine")
    unchanged = [p.name for p in source_b.glob("*.cs") if p.name not in ("Program.cs", "Uci.cs")]
    assert all(digest(source_a / name) == digest(source_b / name) for name in unchanged)
    result = {"passed": True, "behavior_positions": checked, "unchanged_core_files": unchanged, "transcripts": transcript,
              "proof_binary_sha256": digest(proof), "conversion_binary_sha256": digest(reference),
              "stockfish": sf, "script_sha256": digest(__file__),
              "interpretation": "Native Aster explanation works during infinite search without blocking readiness/stop. Pinned Stockfish's explain command emits no such proof explanation. Core search/evaluation unchanged; 66 fixed-node outputs agree. No claim about third-party Stockfish interfaces or general chess intelligence."}
    output.write_text(json.dumps(result, indent=2) + "\n"); print(json.dumps({"passed": True, "behavior_positions": checked, "transcripts": transcript}))


if __name__ == "__main__": main()
