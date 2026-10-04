"""Describe the fixed residual cap's optimistic fit floor; never select a model."""
import json
import shutil
import statistics

import chess

from neural_format import QuantizedModel, material_phase
from run_rating import digest, read, write_new
from uci_client import ROOT


def main():
    bundle_path = ROOT / "artifacts/research/stable-endgame-training-data-v1.json"; bundle = read(bundle_path)
    assert read(ROOT / "artifacts/research/stable-endgame-training-execution-v1.json")["status"] == "complete"
    data_path = ROOT / bundle["datasets"]["candidate"]["path"]
    assert digest(data_path) == bundle["datasets"]["candidate"]["sha256"]
    held_games = set(read(ROOT / bundle["split_path"])["validation_games"])
    rows = [(i,row) for i,line in enumerate(data_path.read_text().splitlines()) if line.strip() and (row:=json.loads(line))["game"] in held_games]
    groups = {"all":list(range(len(rows))),"old":[],"fresh":[],**{f"fresh_bucket_{i}":[] for i in range(4)},
        **{f"phase_{low}_{high}":[] for low,high in ((0,8),(9,16),(17,24))}}
    boards = []
    for i,(index,row) in enumerate(rows):
        board = chess.Board(row["fen"]); boards.append(board)
        groups["old" if index < 60000 else "fresh"].append(i)
        if index >= 60000: groups[f"fresh_bucket_{row['bucket']}"] .append(i)
        value = material_phase(board)
        for low,high in ((0,8),(9,16),(17,24)):
            if low <= value <= high: groups[f"phase_{low}_{high}"].append(i)
    targets = {"static":[row["static_white_cp"] if index >= 60000 else row["score_white_cp"] for index,row in rows],
        "stable":[row["score_white_cp"] for _,row in rows]}
    base = [row["classical_white_cp"] for _,row in rows]
    raw = {}
    for role,entry in bundle["datasets"].items():
        path = ROOT / entry["output"] / "model.ann"; report = read(path.parent / "training.json")
        assert digest(path) == report["model_sha256"] and report["residual_cap_cp"] == 250
        model = QuantizedModel(path)
        assert model.classical_base
        raw[role] = [model.white_score(board) for board in boards]
    result = {}
    for name,indices in groups.items():
        result[name] = {"positions":len(indices),"targets":{}}
        for target_name,target in targets.items():
            floors = [max(0,abs(base[i]-target[i])-250) for i in indices]
            models = {}
            for role,scores in raw.items():
                errors = [abs(base[i]+max(-250,min(250,scores[i]))-target[i]) for i in indices]
                assert all(error >= floor for error,floor in zip(errors,floors))
                models[role] = {"mae_cp":statistics.mean(errors) if errors else None,
                    "clipped_fraction":sum(abs(scores[i])>=250 for i in indices)/len(indices) if indices else None,
                    "mae_above_optimistic_floor_cp":statistics.mean(error-floor for error,floor in zip(errors,floors)) if errors else None}
            result[name]["targets"][target_name] = {"classical_mae_cp":statistics.mean(abs(base[i]-target[i]) for i in indices) if indices else None,
                "optimistic_cap_floor_mae_cp":statistics.mean(floors) if floors else None,
                "targets_outside_cap_fraction":sum(abs(base[i]-target[i])>250 for i in indices)/len(indices) if indices else None,"models":models}
    source_dir = ROOT / "artifacts/research/stable-endgame-residual-diagnostic-source"; source_dir.mkdir(exist_ok=False)
    shutil.copy2(__file__,source_dir / "diagnose_stable_residual.py")
    output = ROOT / "artifacts/validation/stable-endgame-residual-diagnostic-v1.json"
    write_new(output,{"schema":1,"complete":True,"post_training_diagnostic":True,"script_sha256":digest(__file__),"bundle_sha256":digest(bundle_path),
        "split_sha256":bundle["split_sha256"],"groups":result,"residual_cap_cp":250,
        "interpretation":"Optimistic independent per-position correction bound, with perfect access to each teacher label. It is not a realizable evaluator, does not make labels oracles, and estimates no strength. Post-training descriptive diagnostic only; gates/models/epochs/data unchanged."})
    print(json.dumps(result["fresh"]),flush=True)


if __name__ == "__main__": main()
