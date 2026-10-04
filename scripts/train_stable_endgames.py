"""Run both fixed-budget stable-label trainings once, retaining all provenance."""
import datetime
import json
import subprocess
import sys

from run_rating import digest, read, write_new
from uci_client import ROOT


def main():
    plan_path = ROOT / "artifacts/research/stable-endgame-plan-v1.json"; plan = read(plan_path); setup = plan["training"]
    bundle_path = ROOT / "artifacts/research/stable-endgame-training-data-v1.json"; bundle = read(bundle_path)
    assert bundle["complete"] and bundle["plan_sha256"] == digest(plan_path)
    execution_path = ROOT / "artifacts/research/stable-endgame-training-execution-v1.json"
    if execution_path.exists(): raise ValueError("Never restart from JSON; inspect the authoritative process")
    sources = {name:digest(ROOT / "scripts" / name) for name in ("train_network.py","neural_format.py","train_stable_endgames.py")}
    for entry in bundle["datasets"].values():
        assert digest(ROOT / entry["path"]) == entry["sha256"]
        if (ROOT / entry["output"]).exists(): raise ValueError("Preserve previous/partial training outputs")
    assert digest(ROOT / bundle["split_path"]) == bundle["split_sha256"]
    state = {"schema":1,"status":"running","started_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "plan_sha256":digest(plan_path),"bundle_sha256":digest(bundle_path),"scripts":sources,"completed":[]}
    write_new(execution_path,state)
    try:
        for role,entry in bundle["datasets"].items():
            destination = ROOT / entry["output"]
            command = [sys.executable,str(ROOT / "scripts/train_network.py"),str(ROOT / entry["path"]),"--output",str(destination),
                "--validation-games",str(ROOT / bundle["split_path"])]
            for name in ("hidden","epochs","batch_size","learning_rate","threads","seed","activation_bias","transformer_std","pair_loss_weight"):
                command += ["--"+name.replace("_","-"),str(setup[name])]
            for name in ("classical_base","king_context","turn_output","phase_output","squared_activation"):
                if setup[name]: command += ["--"+name.replace("_","-")]
            print(json.dumps({"training":role,"epochs":setup["epochs"]}),flush=True)
            log_path = ROOT / f"artifacts/validation/stable-endgame-training-{role}.txt"
            with log_path.open("x",encoding="utf-8") as log: subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
            report = read(destination / "training.json")
            assert report["dataset_sha256"] == entry["sha256"] and report["fixed_split"]["sha256"] == bundle["split_sha256"]
            if role == "candidate":
                control = read(ROOT / bundle["datasets"]["control"]["output"] / "training.json")
                for name in ("validation_games","initial_shared_sha256","initial_rng_sha256","initial_state_sha256","epoch_batch_sha256","training_positions","validation_positions","training_games","paired_supervision","architecture"):
                    if name == "paired_supervision":
                        for key in ("weight","training_pairs","heldout_pairs","pair_batch_size"): assert report[name][key] == control[name][key]
                    else: assert report[name] == control[name], name
            state["completed"].append({"role":role,"training_sha256":digest(destination / "training.json"),"model_sha256":digest(destination / "model.ann"),
                "selected_epoch":report["selected_epoch"],"quantized_mae_cp":report["quantized_validation_mae_cp"]})
            execution_path.write_text(json.dumps(state,indent=2)+"\n")
            print(json.dumps(state["completed"][-1]),flush=True)
        assert sources == {name:digest(ROOT / "scripts" / name) for name in sources}
        assert digest(bundle_path) == state["bundle_sha256"] and digest(ROOT / bundle["split_path"]) == bundle["split_sha256"]
        state["status"] = "complete"
    except BaseException as error:
        state["status"] = "failed"; state["error"] = repr(error); raise
    finally:
        state["updated_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        execution_path.write_text(json.dumps(state,indent=2)+"\n")


if __name__ == "__main__": main()
