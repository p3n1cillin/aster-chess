"""Describe selected quantized models on shared held-out targets; no selection."""
import json
import shutil

import chess
import numpy as np

from neural_format import QuantizedModel, material_phase
from run_rating import digest, read, write_new
from uci_client import ROOT


def metrics(prediction, target):
    error = prediction-target
    return {"positions":len(target),"mae_cp":float(np.abs(error).mean()),
        "rmse_cp":float(np.sqrt(np.mean(error**2))),"mean_error_cp":float(error.mean()),
        "prediction_mean_cp":float(prediction.mean()),"prediction_std_cp":float(prediction.std()),
        "target_mean_cp":float(target.mean()),"target_std_cp":float(target.std()),
        "pearson_correlation":float(np.corrcoef(prediction,target)[0,1]) if prediction.std() and target.std() else None}


def main():
    bundle_path = ROOT / "artifacts/research/capacity-training-data-v1.json"; bundle = read(bundle_path)
    execution = read(ROOT / "artifacts/research/capacity-training-execution-v1.json")
    assert execution["status"] == "complete" and digest(ROOT / bundle["data"]) == bundle["data_sha256"]
    assert digest(ROOT / bundle["split_path"]) == bundle["split_sha256"]
    held_games = set(read(ROOT / bundle["split_path"])["validation_games"])
    held = [(i,row) for i,line in enumerate((ROOT / bundle["data"]).read_text().splitlines())
        if line.strip() and (row:=json.loads(line))["game"] in held_games]
    boards = [chess.Board(row["fen"]) for _,row in held]
    targets = np.array([row["score_white_cp"] for _,row in held])
    baseline = np.array([row["classical_white_cp"] for _,row in held])
    fresh = np.array([index >= 60000 for index,_ in held])
    phases = np.array([material_phase(board) for board in boards])
    masks = {"all":np.ones(len(held),dtype=bool),"old":~fresh,"fresh":fresh,
        "fresh_white":fresh & np.array([board.turn for board in boards]),
        "fresh_black":fresh & np.array([not board.turn for board in boards])}
    for low,high in ((0,8),(9,16),(17,24)): masks[f"phase_{low}_{high}"] = (phases>=low)&(phases<=high)
    parents = {row["fen"]:i for i,(_,row) in enumerate(held) if not row.get("counterfactual_turn")}
    pairs = {"old":[],"fresh":[]}
    for i,(_,row) in enumerate(held):
        if not row.get("counterfactual_turn"): continue
        a = parents[row["source_fen"]]; parent = held[a][1]
        assert parent["game"] == row["game"] and boards[a].turn != boards[i].turn
        assert parent["fen"].split()[:1]+parent["fen"].split()[2:] == row["fen"].split()[:1]+row["fen"].split()[2:]
        pair = (a,i) if boards[a].turn else (i,a)
        pairs["fresh" if row.get("fresh_deep_pair") else "old"].append(pair)
    assert len(held) == 6050 and int(fresh.sum()) == 360 and len(pairs["fresh"]) == 180 and len(pairs["old"]) == 978
    predictions = {"classical":baseline}; raw = {}
    fingerprints = {}
    for role,entry in bundle["outputs"].items():
        folder = entry["output"]
        path = ROOT / folder / "model.ann"; report = read(path.parent / "training.json")
        assert digest(path) == report["model_sha256"] and report["dataset_sha256"] == bundle["data_sha256"]
        model = QuantizedModel(path); assert model.classical_base
        raw[role] = np.array([model.white_score(board) for board in boards])
        predictions[role] = baseline+np.clip(raw[role],-250,250)
        assert abs(metrics(predictions[role],targets)["mae_cp"]-report["quantized_validation_mae_cp"]) < 1e-10
        fingerprints[role] = {"model_sha256":digest(path),"training_sha256":digest(path.parent / "training.json")}
    ordinary = {name:{role:metrics(prediction[mask],targets[mask]) for role,prediction in predictions.items()} for name,mask in masks.items() if mask.any()}
    pair_results = {}
    for name,indices in pairs.items():
        white,black = np.array(indices).T; target = targets[white]-targets[black]; base = baseline[white]-baseline[black]
        pair_results[name] = {"pairs":len(indices),"negative_teacher_differences":int((target<0).sum()),
            "optimistic_independent_cap_floor_mae_cp":float(np.maximum(0,np.abs(target-base)-500).mean()),
            "models":{role:metrics(prediction[white]-prediction[black],target) for role,prediction in predictions.items()}}
    source = ROOT / "artifacts/research/capacity-fit-source-v1"; source.mkdir(exist_ok=False)
    shutil.copy2(__file__,source / "report_capacity_fit.py")
    result = {"schema":1,"complete":True,"post_training_diagnostic":True,
        "bundle_sha256":digest(bundle_path),"reporter_sha256":digest(__file__),"models":fingerprints,
        "ordinary":ordinary,"paired_differences":pair_results,
        "clipped_fraction":{role:float((np.abs(scores)>=250).mean()) for role,scores in raw.items()},
        "interpretation":"Shared held-out quantized CP fit. Pair difference is White-turn minus Black-turn White-relative score, not an observed game outcome or proof of zugzwang. Optimistic cap bound assumes independent perfect per-position corrections; not a realizable model. No selection, retuning, gate changes or strength inference."}
    write_new(ROOT / "artifacts/validation/capacity-quantized-heldout-fit-v1.json",result)
    print(json.dumps({"fresh_ordinary":ordinary["fresh"],"fresh_pairs":pair_results["fresh"]}),flush=True)


if __name__ == "__main__": main()
