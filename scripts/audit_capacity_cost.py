"""Independently replay frozen legal cost operations and verify score checksums."""
import json
import shutil

import chess

from neural_format import QuantizedModel
from run_rating import digest, read, write_new
from uci_client import ROOT, UciClient


def main():
    plan = read(ROOT / "artifacts/research/capacity-plan-v1.json")
    trace_path = ROOT / "artifacts/research/capacity-cost-trace-v1.json"; trace = read(trace_path)
    raw_path = ROOT / "artifacts/validation/capacity-cost-raw-v1.json"; raw = read(raw_path)
    assert raw["passed"] and digest(trace_path) == raw["trace_sha256"]
    assert digest(ROOT / plan["baseline"]) == raw["baseline_sha256"] == plan["baseline_sha256"]
    bundle = read(ROOT / "artifacts/research/capacity-training-data-v1.json")
    models = {role:QuantizedModel(ROOT / entry["output"] / "model.ann") for role,entry in bundle["outputs"].items()}
    sums = dict(classical=0,control=0,candidate=0); checked = 0
    with UciClient(str(ROOT / plan["baseline"])) as client:
        def score(board):
            nonlocal checked
            client.send("position fen "+board.fen(en_passant="fen"))
            base = int(client.command("eval","info string eval ").split()[-1]); checked += 1
            return {"classical":base,**{role:model.side_score(board,base) for role,model in models.items()}}
        for row in trace["positions"]:
            board = chess.Board(row["fen"]); assert board.is_valid()
            assert row["moves"] == sorted(move.uci() for move in board.legal_moves)[:2]
            root = score(board)
            for uci in row["moves"]:
                board.push_uci(uci)
                try: child = score(board)
                finally: board.pop()
                assert board.fen(en_passant="fen") == row["fen"]
                for role in sums: sums[role] += child[role]+root[role]
    expected = {role:value*trace["repetitions"] for role,value in sums.items()}
    for sample in raw["samples"]: assert sample["checksum"] == expected[sample["role"]]
    source = ROOT / "artifacts/research/capacity-cost-audit-source-v1"; source.mkdir(exist_ok=False)
    shutil.copy2(__file__,source / "audit_capacity_cost.py")
    result = {"schema":1,"passed":True,"post_freeze_read_only_audit":True,"script_sha256":digest(__file__),"raw_sha256":digest(raw_path),
        "trace_sha256":digest(trace_path),"positions":len(trace["positions"]),"root_child_scores":checked,"checksum_per_role":expected,
        "scope":"Independent python-chess legal replay and full raw-FEN restoration, classical cold-FEN reference scores and Python quantized H64/H128 inference. Verifies every measured make/eval/undo/eval score checksum; no new timing, filtering or gate changes."}
    write_new(ROOT / "artifacts/validation/capacity-cost-checksum-audit-v1.json",result); print(json.dumps(result),flush=True)


if __name__ == "__main__": main()
