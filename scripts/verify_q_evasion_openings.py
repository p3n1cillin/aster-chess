"""Verify full depth-eight traces on every fresh regression opening."""
import contextlib
import json

import chess

from run_rating import digest, read, write_new
from uci_client import ROOT, UciClient
from verify import validate_pv
from verify_q_evasion import normalize


def main():
    plan = read(ROOT / "artifacts/research/q-evasion-plan-v1.json")
    suite = ROOT / "tests/fixtures/q-evasion-behavior-v1.json"
    rows = []; paths = [ROOT / plan[role] for role in ("candidate", "baseline")]
    assert [digest(p) for p in paths] == [plan[role + "_sha256"] for role in ("candidate", "baseline")]
    with contextlib.ExitStack() as stack:
        clients = [stack.enter_context(UciClient(path)) for path in paths]
        for client in clients:
            client.send("setoption name Hash value 64"); client.ready()
        for opening in read(suite)["openings"]:
            board = chess.Board()
            for move in opening["moves"].split(): board.push_uci(move)
            traces = []
            for client in clients:
                client.send("ucinewgame"); client.send("position startpos moves " + opening["moves"])
                client.send("go depth 8"); lines = client.until("bestmove ")
                validate_pv(board, lines); traces.append(normalize(lines))
            assert traces[0] == traces[1], (opening["id"], traces)
            rows.append({"id": opening["id"], "trace": traces[0]})
    write_new(ROOT / "artifacts/validation/q-evasion-opening-traces.json",
              {"passed": True, "positions": len(rows), "same_full_traces": len(rows), "rows": rows,
               "candidate_sha256": digest(paths[0]), "baseline_sha256": digest(paths[1]),
               "suite_sha256": digest(suite), "script_sha256": digest(__file__)})
    print(json.dumps({"passed": True, "same_full_traces": len(rows)}))


if __name__ == "__main__": main()
