"""Label every declared hypothetical Black counterpart once, retaining rejections."""
from research_reference import research_text
import collections
import datetime
import json
import pathlib
import re
import time

import chess
import chess.engine

from generate_endgame_diagnostic import key
from generate_stable_endgames import label
from run_rating import digest, read
from uci_client import ROOT, UciClient, engine_command


def main():
    plan_path = ROOT / "artifacts/research/deep-turn-plan-v1.json"; plan = read(plan_path); setup = plan["generation"]
    parent_path = ROOT / plan["parents"]
    assert digest(parent_path) == plan["parents_sha256"]
    assert digest(ROOT / plan["old_data"]) == plan["old_data_sha256"]
    assert digest(ROOT / plan["parent_audit"]) == plan["parent_audit_sha256"] and read(ROOT / plan["parent_audit"])["complete"]
    assert digest(ROOT / plan["prior_split"]) == plan["prior_split_sha256"]
    parents = [json.loads(line) for line in parent_path.read_text().splitlines() if line.strip()]
    assert len(parents) == setup["maximum_parents"]
    paths = {name: ROOT / f"artifacts/data/deep-turn-{name}-v1.{extension}" for name,extension in (("candidates","jsonl"),("pairs","jsonl"),("generation","json"))}
    if any(path.exists() for path in paths.values()): raise ValueError("Preserve partial runs; never restart from metadata")
    teacher_meta = read(ROOT / research_text('opponent_manifest')); teacher_path = ROOT / teacher_meta["executable"]
    assert digest(teacher_path) == teacher_meta["executable_sha256"]
    assert digest(ROOT / plan["baseline"]) == plan["baseline_sha256"]
    excluded = set(); exclusions = []
    for kind,names in (("data",setup["exclude_counter_data"]),("suite",setup["exclude_counter_suites"])):
        for name in names:
            path = ROOT / name
            if kind == "data": entries = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
            else:
                suite = read(path); entries = suite.get("openings",suite.get("positions",[]))
            excluded.update(key(chess.Board(row["fen"])) for row in entries)
            exclusions.append({"path":name,"kind":kind,"sha256":digest(path),"positions":len(entries)})
    held = set(read(ROOT / plan["prior_split"])["validation_games"])
    seen = set(); rejection = collections.Counter(); written = queried = visited = held_pairs = 0; groups = set()
    started = time.monotonic()
    metadata = {"schema":1,"status":"running","complete":False,"started_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "plan_sha256":digest(plan_path),"generator_sha256":digest(__file__),"parents_sha256":digest(parent_path),
        "teacher":teacher_meta,"teacher_options":{"Threads":1,"Hash":64},"classical_binary_sha256":plan["baseline_sha256"],
        "exclusions":exclusions,"source_pgn":{"path":plan["parents"]+".source.pgn","sha256":digest(str(parent_path)+".source.pgn")},
        "outcome_scope":"Only actual White parents have played histories/source game outcomes. Black counterparts are cold-FEN hypotheses with no observed result."}
    def checkpoint(status="running"):
        metadata.update(status=status,parents_visited=visited,counter_roots_queried=queried,paired_parents=written,
            training_pairs=written-held_pairs,heldout_pairs=held_pairs,source_groups=len(groups),rejections=dict(rejection),seconds=round(time.monotonic()-started,3))
        paths["generation"].write_text(json.dumps(metadata,indent=2)+"\n")
    checkpoint()
    try:
        with chess.engine.SimpleEngine.popen_uci(engine_command(teacher_path),timeout=30) as teacher, UciClient(teacher_path) as static, \
                UciClient(ROOT / plan["baseline"]) as classical, paths["candidates"].open("x",encoding="utf-8") as candidates, \
                paths["pairs"].open("x",encoding="utf-8") as pairs:
            teacher.configure({"Threads":1,"Hash":64})
            static.send("setoption name Threads value 1"); static.send("setoption name Hash value 64"); static.ready()
            for index,parent in enumerate(parents):
                fields = parent["fen"].split(); assert fields[1] == "w" and parent["acceptance"] == "accepted"
                fields[1] = "b"; fen = " ".join(fields); board = chess.Board(fen)
                row = {"id":f"deep-turn-{index:04}","parent_index":index,"parent_id":parent["id"],"source_fen":parent["fen"],
                    "fen":fen,"game":parent["game"],"source_game":parent["source_game"],"counterfactual_turn":True,"fresh_deep_pair":True,
                    "source_history_uci":parent["history_uci"],"source_game_result":parent["source_result"],
                    "source_game_termination":parent["source_termination"],"counterfactual_outcome":None,
                    "sample":None,"verified":None,"static_white_cp":None,"acceptance":None}
                reason = "accepted"
                if not board.is_valid(): reason = "invalid_counter_fen"
                elif board.is_check(): reason = "counter_in_check"
                elif board.outcome(claim_draw=True) is not None: reason = "counter_terminal"
                else:
                    canonical = key(board)
                    if canonical in excluded: reason = "excluded_counter"
                    elif canonical in seen: reason = "duplicate_counter"
                    else:
                        seen.add(canonical); queried += 1
                        row["sample"] = label(teacher,board,setup["sample_nodes"])
                        row["verified"] = label(teacher,board,setup["verify_nodes"])
                        static.send("position fen "+fen); trace = static.command("eval","Final evaluation")
                        value = re.search(r"Final evaluation\s+([+-]\d+\.\d+)\s+\(white side\)",trace)
                        if not value: raise ValueError("Unexpected teacher static trace: "+trace)
                        row["static_white_cp"] = int(round(float(value.group(1))*100))
                        sample,verified = row["sample"],row["verified"]
                        if sample["white_cp"] is None or verified["white_cp"] is None: reason = "native_mate_label"
                        elif abs(verified["white_cp"]) > 1500: reason = "outside_score_range"
                        elif sample["pv"][0] != verified["pv"][0]: reason = "unstable_first_move"
                        elif abs(sample["white_cp"]-verified["white_cp"]) > 50: reason = "unstable_value"
                row["acceptance"] = reason
                if reason == "accepted":
                    classical.send("position fen "+fen)
                    row["classical_white_cp"] = -int(classical.command("eval","info string eval ").split()[-1])
                    row["score_white_cp"] = row["verified"]["white_cp"]
                    pairs.write(json.dumps({"parent":parent,"counter":row},separators=(",",":"))+"\n"); pairs.flush()
                    written += 1; held_pairs += parent["game"] in held; groups.add(parent["game"])
                else: rejection[reason] += 1
                candidates.write(json.dumps(row,separators=(",",":"))+"\n"); candidates.flush(); visited += 1
                if visited % 128 == 0:
                    checkpoint(); print(json.dumps({"visited":visited,"queried":queried,"pairs":written,"heldout_pairs":held_pairs,"seconds":round(time.monotonic()-started,2)}),flush=True)
        for entry in exclusions: assert digest(ROOT / entry["path"]) == entry["sha256"]
        assert digest(parent_path) == plan["parents_sha256"] and digest(ROOT / plan["baseline"]) == plan["baseline_sha256"]
        assert digest(teacher_path) == teacher_meta["executable_sha256"]
        eligible = written >= setup["minimum_pairs"] and written-held_pairs >= setup["minimum_training_pairs"] and held_pairs >= setup["minimum_heldout_pairs"]
        metadata.update(complete=True,training_eligible=eligible,candidates_sha256=digest(paths["candidates"]),pairs_sha256=digest(paths["pairs"]),
            fresh_side_counts={"w":written,"b":written},source_parent_policy="Only eligible White/Black pairs are appended; unpaired White parents are retained in source evidence, not training.")
        checkpoint("complete" if eligible else "complete_insufficient_pairs")
        if not eligible: raise ValueError("Fixed one-pass collection does not meet declared pair/split minima; no training permitted")
        print(json.dumps({"complete":True,"paired_parents":written,"fresh_positions":2*written,"training_pairs":written-held_pairs,"heldout_pairs":held_pairs}),flush=True)
    except BaseException as error:
        metadata["error"] = repr(error); checkpoint("failed" if not metadata["complete"] else metadata["status"]); raise


if __name__ == "__main__": main()
