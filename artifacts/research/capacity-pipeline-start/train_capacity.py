"""Train a reproduced H64 control then nested H128 with identical batch RNG."""
import datetime
import json
import subprocess
import sys

from run_rating import digest, read, write_new
from uci_client import ROOT


def main():
    plan_path = ROOT / "artifacts/research/capacity-plan-v1.json"; plan = read(plan_path); setup = plan["training"]
    bundle_path = ROOT / "artifacts/research/capacity-training-data-v1.json"; bundle = read(bundle_path)
    assert bundle["complete"] and bundle["plan_sha256"] == digest(plan_path)
    assert read(ROOT / "artifacts/validation/capacity-initial-tests-v1.json")["passed"]
    state_path = ROOT / "artifacts/research/capacity-training-execution-v1.json"
    if state_path.exists(): raise ValueError("Never restart from JSON; inspect the authoritative process")
    for entry in bundle["outputs"].values():
        assert digest(ROOT / entry["initial_checkpoint"]) == entry["sha256"]
        if (ROOT / entry["output"]).exists(): raise ValueError("Preserve previous/partial training")
    sources = {name:digest(ROOT / "scripts" / name) for name in ("train_network.py","neural_format.py","train_capacity.py")}
    state = {"schema":1,"status":"running","started_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "plan_sha256":digest(plan_path),"bundle_sha256":digest(bundle_path),"scripts":sources,"completed":[]}
    write_new(state_path,state)
    try:
        for role,entry in bundle["outputs"].items():
            destination = ROOT / entry["output"]
            command = [sys.executable,str(ROOT / "scripts/train_network.py"),str(ROOT / bundle["data"]),"--output",str(destination),
                "--validation-games",str(ROOT / bundle["split_path"]),"--initial-checkpoint",str(ROOT / entry["initial_checkpoint"]),
                "--hidden",str(setup[role+"_hidden"]),"--fresh-pair-loss-weight",str(setup["fresh_pair_loss_weight"])]
            for name in ("epochs","batch_size","learning_rate","threads","seed","activation_bias","transformer_std","pair_loss_weight"):
                command += ["--"+name.replace("_","-"),str(setup[name])]
            for name in ("classical_base","king_context","turn_output","phase_output","squared_activation"):
                if setup[name]: command += ["--"+name.replace("_","-"),]
            print(json.dumps({"training":role,"hidden":setup[role+"_hidden"],"epochs":setup["epochs"]}),flush=True)
            with (ROOT / f"artifacts/validation/capacity-training-{role}.txt").open("x",encoding="utf-8") as log:
                subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
            report = read(destination / "training.json")
            assert report["dataset_sha256"] == bundle["data_sha256"] and report["fixed_split"]["sha256"] == bundle["split_sha256"]
            assert report["initial_state_sha256"] == entry["initial_state_sha256"]
            assert report["initial_rng_sha256"] == bundle["common_training_rng_sha256"]
            control = read(ROOT / "artifacts/training/deep-turn-control-v1/training.json") if role == "control" else read(ROOT / bundle["outputs"]["control"]["output"] / "training.json")
            for name in ("dataset_sha256","validation_games","initial_rng_sha256","epoch_batch_sha256","training_positions","validation_positions","training_games"):
                assert report[name] == control[name],name
            if role == "control":
                for name in ("model_sha256","selected_epoch","initial_state_sha256","initial_shared_sha256","quantized_validation_mae_cp","initial_validation"):
                    assert report[name] == control[name],name
            else:
                assert abs(report["initial_validation"]["loss"]-control["initial_validation"]["loss"]) < 1e-7
            state["completed"].append({"role":role,"model_sha256":digest(destination / "model.ann"),"training_sha256":digest(destination / "training.json"),
                "selected_epoch":report["selected_epoch"],"quantized_mae_cp":report["quantized_validation_mae_cp"]})
            state_path.write_text(json.dumps(state,indent=2)+"\n"); print(json.dumps(state["completed"][-1]),flush=True)
        assert sources == {name:digest(ROOT / "scripts" / name) for name in sources}
        assert digest(ROOT / bundle["data"]) == bundle["data_sha256"] and digest(ROOT / bundle["split_path"]) == bundle["split_sha256"]
        state["status"] = "complete"
    except BaseException as error:
        state["status"] = "failed"; state["error"] = repr(error); raise
    finally:
        state["updated_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        state_path.write_text(json.dumps(state,indent=2)+"\n")


if __name__ == "__main__": main()
