"""Freeze an evaluator-cost trace without model scores or timing selection."""
import json
import random

import chess

from run_rating import digest, read, write_new
from uci_client import ROOT


def main():
    plan_path = ROOT / "artifacts/research/capacity-plan-v1.json"; plan = read(plan_path); setup = plan["cost_diagnostic"]
    assert digest(ROOT / plan["data"]) == plan["data_sha256"]
    held = set(read(ROOT / plan["split_path"])["validation_games"])
    data = [json.loads(line) for line in (ROOT / plan["data"]).read_text().splitlines() if line.strip()]
    groups = [[(i,row) for i,row in enumerate(data) if row["game"] in held and (i>=60000) == fresh] for fresh in (False,True)]
    positions = []
    for group in groups:
        for index in range(32):
            source_index,row = group[index*len(group)//32]; board = chess.Board(row["fen"])
            moves = sorted(move.uci() for move in board.legal_moves)
            assert len(moves)>=2
            positions.append({"row":source_index,"fen":row["fen"],"moves":moves[:2]})
    assert len(positions) == setup["positions"]
    # Three cyclic rotations repeated three times: each role occupies each
    # measured order slot exactly three times. Seed only chooses base ordering.
    order = [0,1,2]; random.Random(20261123).shuffle(order)
    orders = [order[r%3:]+order[:r%3] for r in range(setup["rounds"])]
    result = {"schema":1,"plan_sha256":digest(plan_path),"data_sha256":plan["data_sha256"],"preparer_sha256":digest(__file__),
        "repetitions":setup["repetitions_per_round"],"warmup_rounds":setup["warmup_rounds"],"orders":orders,"positions":positions,
        "selection":"Evenly spaced32 old plus32 fresh held-out rows in frozen file order. First two lexicographically sorted legal moves. No model errors, teacher values, timing or match results select work."}
    write_new(ROOT / "artifacts/research/capacity-cost-trace-v1.json",result); print(json.dumps({"positions":len(positions),"orders":orders}),flush=True)


if __name__ == "__main__": main()
