"""Compare both selected models on identical held-out targets, without selection."""
import json

import chess
import numpy as np

from neural_format import QuantizedModel, material_phase
from run_rating import digest, read, write_new
from uci_client import ROOT


def main():
    plan_path = ROOT / "artifacts/research/stable-endgame-plan-v1.json"
    bundle_path = ROOT / "artifacts/research/stable-endgame-training-data-v1.json"; bundle = read(bundle_path)
    execution = read(ROOT / "artifacts/research/stable-endgame-training-execution-v1.json")
    assert execution["status"] == "complete" and execution["plan_sha256"] == digest(plan_path)
    held_games = set(read(ROOT / bundle["split_path"])["validation_games"])
    data_path = ROOT / bundle["datasets"]["candidate"]["path"]
    assert digest(data_path) == bundle["datasets"]["candidate"]["sha256"]
    held = [(i,row) for i,line in enumerate(data_path.read_text().splitlines()) if line.strip() and (row:=json.loads(line))["game"] in held_games]
    boards = [chess.Board(row["fen"]) for _,row in held]
    phases = np.array([material_phase(board) for board in boards])
    fresh = np.array([index >= 60000 for index,_ in held])
    stable = np.array([row["score_white_cp"] for _,row in held])
    static = np.array([row["static_white_cp"] if index >= 60000 else row["score_white_cp"] for index,row in held])
    masks = {"all":np.ones(len(held),dtype=bool),"old":~fresh,"fresh":fresh}
    for low,high in ((0,8),(9,16),(17,24)): masks[f"phase_{low}_{high}"] = (phases>=low)&(phases<=high)
    for bucket in range(4): masks[f"fresh_bucket_{bucket}"] = fresh & np.array([row.get("bucket")==bucket for _,row in held])
    results = {}
    for role,entry in bundle["datasets"].items():
        model_path = ROOT / entry["output"] / "model.ann"; training = read(model_path.parent / "training.json")
        assert digest(model_path) == training["model_sha256"]
        model = QuantizedModel(model_path)
        prediction = np.array([row["classical_white_cp"]+max(-250,min(250,model.white_score(board))) for board,(_,row) in zip(boards,held)])
        results[role] = {"model_sha256":digest(model_path),"selected_epoch":training["selected_epoch"],"own_target_mae_cp":training["quantized_validation_mae_cp"],"common_targets":{}}
        for name,mask in masks.items():
            results[role]["common_targets"][name] = {"positions":int(mask.sum()),
                **{target_name:{"mae_cp":float(np.abs(prediction-target)[mask].mean()),"rmse_cp":float(np.sqrt(((prediction-target)[mask]**2).mean()))} if mask.any() else None for target_name,target in (("static",static),("stable",stable))}}
    output = ROOT / "artifacts/validation/stable-endgame-common-heldout-fit-v1.json"
    write_new(output,{"schema":1,"complete":True,"plan_sha256":digest(plan_path),"bundle_sha256":digest(bundle_path),"reporter_sha256":digest(__file__),
        "validation_rows":len(held),"fresh_validation_rows":int(fresh.sum()),"split_sha256":bundle["split_sha256"],"models":results,
        "interpretation":"Common-target held-out teacher fit only; no epoch/model selection from these diagnostics or matches. Playing-strength gates are separate."})
    print(json.dumps({"validation_rows":len(held),"fresh_validation_rows":int(fresh.sum()),"models":{role:result["common_targets"]["fresh"] for role,result in results.items()}}),flush=True)


if __name__ == "__main__": main()
