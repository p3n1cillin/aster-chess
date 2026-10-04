"""Replay all saved candidate traces against the promoted ordinary build."""
import json

import chess

from run_rating import digest, read, write_new
from uci_client import ROOT, UciClient
from verify import validate_pv
from verify_q_evasion import normalize


def main():
    binary = ROOT / "artifacts/publish/q-evasion-default-dotnet/Aster.dll"
    manifest = ROOT / "artifacts/research/q-evasion-default-source/manifest.json"
    assert digest(binary) == read(manifest)["binary_sha256"]
    plan = read(ROOT / "artifacts/research/q-evasion-plan-v1.json")
    state = read(ROOT / "artifacts/research/q-evasion-execution-v1.json")
    assert state["status"] == "complete" and state["eligible_for_engineering_promotion"]
    saved_cases = ROOT / "artifacts/validation/q-evasion-differential.json"
    saved_openings = ROOT / "artifacts/validation/q-evasion-opening-traces.json"
    cases = read(saved_cases); openings = read(saved_openings)
    for report in (cases, openings):
        assert report["passed"] and report["candidate_sha256"] == plan["candidate_sha256"]
    rows = []
    with UciClient(binary) as client:
        assert client.name == "Aster 0.7.6-feature-dev"
        client.send("setoption name Hash value 64")
        client.send("setoption name Move Overhead value 0"); client.ready()
        for case in cases["positions"]:
            board = chess.Board(case["origin"])
            for move in case["moves"]: board.push_uci(move)
            position = "position fen " + case["origin"]
            if case["moves"]: position += " moves " + " ".join(case["moves"])
            client.send(position)
            client.send("go depth 4 nodes 1000"); warm = client.until("bestmove ")
            client.send(case["command"]); search = client.until("bestmove ")
            validate_pv(board, warm); validate_pv(board, search)
            assert {"warm":normalize(warm), "search":normalize(search)} == case["trace"], case["id"]
            assert client.command("d", "info string fen ") == "info string fen " + board.fen(en_passant="fen")
            rows.append(case["id"])
    suite = ROOT / "tests/fixtures/q-evasion-behavior-v1.json"
    assert digest(suite) == openings["suite_sha256"]
    with UciClient(binary) as client:
        client.send("setoption name Hash value 64"); client.ready()
        fixtures = read(suite)["openings"]
        for opening, saved in zip(fixtures, openings["rows"], strict=True):
            assert opening["id"] == saved["id"]
            board = chess.Board()
            for move in opening["moves"].split(): board.push_uci(move)
            client.send("ucinewgame"); client.send("position startpos moves " + opening["moves"])
            client.send("go depth 8"); lines = client.until("bestmove ")
            validate_pv(board, lines)
            assert normalize(lines) == saved["trace"], opening["id"]
            rows.append(opening["id"])
    assert len(rows) == 416
    output = ROOT / "artifacts/validation/q-evasion-default-traces.json"
    write_new(output, {"passed":True, "same_full_traces":len(rows), "history_cases":256, "fresh_openings":160,
        "engine_sha256":digest(binary), "engine_name":"Aster 0.7.6-feature-dev", "source_manifest_sha256":digest(manifest),
        "matched_candidate_sha256":plan["candidate_sha256"], "script_sha256":digest(__file__), "cases":rows,
        "saved_traces":[{"path":p.relative_to(ROOT).as_posix(), "sha256":digest(p)} for p in (saved_cases,saved_openings)],
        "interpretation":"Promotion retains all 416 complete candidate traces, including nodes, PV and warm/history cases. Only time/nps excluded. Does not automatically transfer the exact candidate rating or prove universal equivalence."})
    print(json.dumps({"passed":True,"same_full_traces":len(rows),"engine_sha256":digest(binary)}))


if __name__ == "__main__": main()
