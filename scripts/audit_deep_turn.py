"""Audit all hypothetical roots and pair selection, histories, labels and scores."""
import collections
import json
import random
import statistics
import time

import chess
import chess.engine

from generate_endgame_diagnostic import key
from generate_stable_endgames import label
from run_rating import digest, read, write_new
from uci_client import ROOT, UciClient, engine_command


def rows(path): return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main():
    started = time.monotonic(); plan_path = ROOT / "artifacts/research/deep-turn-plan-v1.json"; plan = read(plan_path)
    output = ROOT / "artifacts/validation/deep-turn-data-audit-v1.json"
    if output.exists(): raise ValueError("Preserve prior audit")
    meta_path = ROOT / "artifacts/data/deep-turn-generation-v1.json"; meta = read(meta_path)
    assert meta["complete"] and meta["training_eligible"] and meta["status"] == "complete"
    assert meta["plan_sha256"] == digest(plan_path)
    parent_path = ROOT / plan["parents"]; candidates_path = ROOT / "artifacts/data/deep-turn-candidates-v1.jsonl"
    pairs_path = ROOT / "artifacts/data/deep-turn-pairs-v1.jsonl"
    assert digest(parent_path) == plan["parents_sha256"] == meta["parents_sha256"]
    assert digest(candidates_path) == meta["candidates_sha256"] and digest(pairs_path) == meta["pairs_sha256"]
    assert digest(ROOT / plan["parent_audit"]) == plan["parent_audit_sha256"] and read(ROOT / plan["parent_audit"])["complete"]
    assert digest(ROOT / meta["source_pgn"]["path"]) == meta["source_pgn"]["sha256"]
    parents,candidates,pairs = rows(parent_path),rows(candidates_path),rows(pairs_path)
    assert len(parents) == len(candidates) == meta["parents_visited"] == plan["generation"]["maximum_parents"]
    excluded = set()
    for entry in meta["exclusions"]:
        path = ROOT / entry["path"]; assert digest(path) == entry["sha256"]
        if entry["kind"] == "data": entries = rows(path)
        else:
            suite = read(path); entries = suite.get("openings",suite.get("positions",[]))
        assert len(entries) == entry["positions"]
        excluded.update(key(chess.Board(row["fen"])) for row in entries)
    seen = set(); accepted = []; rejected = collections.Counter(); queried = pv_plies = history_plies = 0
    for index,(parent,counter) in enumerate(zip(parents,candidates)):
        assert counter["id"] == f"deep-turn-{index:04}" and counter["parent_index"] == index and counter["parent_id"] == parent["id"]
        assert counter["counterfactual_turn"] is True and counter["fresh_deep_pair"] is True and counter["counterfactual_outcome"] is None
        assert counter["game"] == parent["game"] and counter["source_game"] == parent["source_game"]
        assert counter["source_fen"] == parent["fen"] and counter["source_history_uci"] == parent["history_uci"]
        assert counter["source_game_result"] == parent["source_result"] and counter["source_game_termination"] == parent["source_termination"]
        fields = parent["fen"].split(); assert fields[1] == "w"; fields[1] = "b"
        assert counter["fen"] == " ".join(fields)
        # Played history proves only the White parent; do not replay it as Black.
        source = chess.Board()
        for move in parent["history_uci"]: source.push_uci(move); history_plies += 1
        assert source.fen(en_passant="fen") == parent["fen"] and source.outcome(claim_draw=True) is None
        board = chess.Board(counter["fen"]); reason = "accepted"
        if not board.is_valid(): reason = "invalid_counter_fen"
        elif board.is_check(): reason = "counter_in_check"
        elif board.outcome(claim_draw=True) is not None: reason = "counter_terminal"
        else:
            canonical = key(board)
            if canonical in excluded: reason = "excluded_counter"
            elif canonical in seen: reason = "duplicate_counter"
            else:
                seen.add(canonical); queried += 1
                assert type(counter["static_white_cp"]) is int
                for name in ("sample","verified"):
                    item = counter[name]
                    assert (item["white_cp"] is None) != (item["white_mate"] is None)
                    assert type(item["white_cp"] if item["white_cp"] is not None else item["white_mate"]) is int
                    assert item["pv"] and item["reported_nodes"] > 0
                    replay = board.copy(stack=False)
                    for move in item["pv"]: replay.push_uci(move); pv_plies += 1
                sample,verified = counter["sample"],counter["verified"]
                if sample["white_cp"] is None or verified["white_cp"] is None: reason = "native_mate_label"
                elif abs(verified["white_cp"]) > 1500: reason = "outside_score_range"
                elif sample["pv"][0] != verified["pv"][0]: reason = "unstable_first_move"
                elif abs(sample["white_cp"]-verified["white_cp"]) > 50: reason = "unstable_value"
        assert counter["acceptance"] == reason
        if reason in ("invalid_counter_fen","counter_in_check","counter_terminal","excluded_counter","duplicate_counter"):
            assert counter["sample"] is counter["verified"] is counter["static_white_cp"] is None
        if reason == "accepted":
            assert counter["score_white_cp"] == counter["verified"]["white_cp"] and type(counter["classical_white_cp"]) is int
            accepted.append({"parent":parent,"counter":counter})
        else: rejected[reason] += 1
    assert accepted == pairs and len(pairs) == meta["paired_parents"]
    assert dict(rejected) == meta["rejections"] and queried == meta["counter_roots_queried"]
    held = set(read(ROOT / plan["prior_split"])["validation_games"])
    held_pairs = sum(pair["parent"]["game"] in held for pair in pairs)
    assert held_pairs == meta["heldout_pairs"] and len(pairs)-held_pairs == meta["training_pairs"]
    assert meta["fresh_side_counts"] == {"w":len(pairs),"b":len(pairs)}
    print(json.dumps({"parents":len(parents),"pairs":len(pairs),"history_plies":history_plies,"pv_plies":pv_plies}),flush=True)
    assert digest(ROOT / plan["baseline"]) == plan["baseline_sha256"]
    with UciClient(ROOT / plan["baseline"]) as engine:
        for pair in pairs:
            for name in ("parent","counter"):
                row = pair[name]; engine.send("position fen "+row["fen"])
                value = int(engine.command("eval","info string eval ").split()[-1])
                assert row["classical_white_cp"] == (value if chess.Board(row["fen"]).turn else -value)
    teacher_path = ROOT / meta["teacher"]["executable"]
    assert digest(teacher_path) == meta["teacher"]["executable_sha256"]
    setup = plan["validation"]; rng = random.Random(setup["requery_seed"])
    requery_indices = sorted(rng.sample(range(len(pairs)),setup["requery_pairs"]))
    deeper_indices = sorted(rng.sample(range(len(pairs)),setup["deeper_pairs"]))
    rechecks = []; deeper = []
    with chess.engine.SimpleEngine.popen_uci(engine_command(teacher_path),timeout=30) as teacher:
        teacher.configure({"Threads":1,"Hash":64})
        for index in requery_indices:
            evidence = {"index":index,"labels":{}}
            for side in ("parent","counter"):
                row = pairs[index][side]; board = chess.Board(row["fen"]); checks = {}
                for name,nodes in (("sample",plan["generation"]["sample_nodes"]),("verified",plan["generation"]["verify_nodes"])):
                    checks[name] = label(teacher,board,nodes)
                    assert checks[name] == row[name],(index,side,name)
                evidence["labels"][side] = checks
            rechecks.append(evidence)
        for index in deeper_indices:
            evidence = {"index":index,"labels":{}}
            for side in ("parent","counter"):
                row = pairs[index][side]; result = label(teacher,chess.Board(row["fen"]),setup["deeper_nodes"])
                evidence["labels"][side] = {"label":result,"first_move_stable":result["pv"][0] == row["verified"]["pv"][0],
                    "cp_difference":result["white_cp"]-row["verified"]["white_cp"] if result["white_cp"] is not None else None}
            deeper.append(evidence)
    deltas = [pair["parent"]["verified"]["white_cp"]-pair["counter"]["verified"]["white_cp"] for pair in pairs]
    write_new(output,{"schema":1,"complete":True,"checks_passed":True,"plan_sha256":digest(plan_path),"auditor_sha256":digest(__file__),
        "inputs":[{"path":path.relative_to(ROOT).as_posix(),"sha256":digest(path)} for path in (meta_path,parent_path,candidates_path,pairs_path)],
        "parents":len(parents),"queried":queried,"pairs":len(pairs),"fresh_positions":2*len(pairs),"training_pairs":len(pairs)-held_pairs,"heldout_pairs":held_pairs,
        "history_plies":history_plies,"native_pv_plies":pv_plies,"classical_score_checks":2*len(pairs),"rejections":dict(rejected),
        "parent_buckets":dict(collections.Counter(pair["parent"]["bucket"] for pair in pairs)),
        "teacher_pair_difference_mean_cp":statistics.mean(deltas),"teacher_pair_difference_std_cp":statistics.pstdev(deltas),
        "teacher_negative_pair_differences":sum(delta<0 for delta in deltas),"exact_requeries":rechecks,"deeper_diagnostic":deeper,
        "seconds":round(time.monotonic()-started,3),"interpretation":"Hypothetical Black roots are independently derived from actual White histories; no counterfactual game outcome exists. Native finite/mate labels kept distinct. No deeper diagnostic filtering or model selection."})
    print(json.dumps({"complete":True,"pairs":len(pairs),"requeried_pairs":len(rechecks),"deeper_pairs":len(deeper),"audit_sha256":digest(output)}),flush=True)


if __name__ == "__main__": main()
