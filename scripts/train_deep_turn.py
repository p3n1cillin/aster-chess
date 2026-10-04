"""Run identical-data controls with only fresh-pair objective weight changed."""
import datetime
import json
import subprocess
import sys

from run_rating import digest, read, write_new
from uci_client import ROOT


def main():
    plan_path = ROOT / "artifacts/research/deep-turn-plan-v1.json"; plan = read(plan_path); setup = plan["training"]
    bundle_path = ROOT / "artifacts/research/deep-turn-training-data-v1.json"; bundle = read(bundle_path)
    assert bundle["complete"] and bundle["plan_sha256"] == digest(plan_path)
    state_path = ROOT / "artifacts/research/deep-turn-training-execution-v1.json"
    if state_path.exists(): raise ValueError("Never restart from metadata; inspect the authoritative process")
    for output in bundle["outputs"].values():
        if (ROOT / output).exists(): raise ValueError("Preserve partial training outputs")
    assert digest(ROOT / bundle["data"]) == bundle["data_sha256"] and digest(ROOT / bundle["split_path"]) == bundle["split_sha256"]
    sources = {name:digest(ROOT / "scripts" / name) for name in ("train_network.py","neural_format.py","train_deep_turn.py")}
    state = {"schema":1,"status":"running","started_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "plan_sha256":digest(plan_path),"bundle_sha256":digest(bundle_path),"scripts":sources,"completed":[]}
    write_new(state_path,state)
    try:
        for role,output in bundle["outputs"].items():
            destination = ROOT / output
            command = [sys.executable,str(ROOT / "scripts/train_network.py"),str(ROOT / bundle["data"]),"--output",str(destination),
                "--validation-games",str(ROOT / bundle["split_path"]),"--fresh-pair-loss-weight",str(setup[role+"_fresh_pair_loss_weight"])]
            for name in ("hidden","epochs","batch_size","learning_rate","threads","seed","activation_bias","transformer_std","pair_loss_weight"):
                command += ["--"+name.replace("_","-"),str(setup[name])]
            for name in ("classical_base","king_context","turn_output","phase_output","squared_activation"):
                if setup[name]: command += ["--"+name.replace("_","-")]
            print(json.dumps({"training":role,"epochs":setup["epochs"],"fresh_pair_weight":setup[role+"_fresh_pair_loss_weight"]}),flush=True)
            with (ROOT / f"artifacts/validation/deep-turn-training-{role}.txt").open("x",encoding="utf-8") as log:
                subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
            report = read(destination / "training.json")
            assert report["dataset_sha256"] == bundle["data_sha256"] and report["fixed_split"]["sha256"] == bundle["split_sha256"]
            if role == "candidate":
                control = read(ROOT / bundle["outputs"]["control"] / "training.json")
                for name in ("dataset_sha256","validation_games","initial_shared_sha256","initial_rng_sha256","initial_state_sha256",
                        "epoch_batch_sha256","training_positions","validation_positions","training_games","architecture","initial_validation"):
                    assert report[name] == control[name],name
                for name in ("paired_supervision","fresh_paired_supervision"):
                    for key in ("training_pairs","heldout_pairs","pair_batch_size"): assert report[name][key] == control[name][key]
                assert control["fresh_paired_supervision"]["weight"] == 0 and report["fresh_paired_supervision"]["weight"] == 1
            state["completed"].append({"role":role,"model_sha256":digest(destination / "model.ann"),"training_sha256":digest(destination / "training.json"),
                "selected_epoch":report["selected_epoch"],"quantized_mae_cp":report["quantized_validation_mae_cp"],"fresh_pair_validation":report["fresh_paired_supervision"]["selected_validation"]})
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
