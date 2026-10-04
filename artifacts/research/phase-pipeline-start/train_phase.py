"""Run the two fixed-budget phase ablation trainings sequentially and retain provenance."""
import datetime
import json
import pathlib
import subprocess
import sys

from run_rating import digest, read, write_new
from uci_client import ROOT


def main():
    plan_path = ROOT / "artifacts/research/phase-plan-v1.json"; plan = read(plan_path)
    setup = plan["training"]
    execution_path = ROOT / "artifacts/research/phase-training-execution-v1.json"
    if execution_path.exists(): raise ValueError("Never restart from execution JSON; inspect the authoritative process")
    for role in ("control", "candidate"):
        if (ROOT / setup[role + "_output"]).exists(): raise ValueError("Preserve previous or partial training outputs")
    assert digest(ROOT / setup["data"]) == setup["data_sha256"]
    assert read(ROOT / "artifacts/validation/phase-formats.json")["passed"]
    sources = {name: digest(ROOT / "scripts" / name) for name in ("train_network.py", "neural_format.py", "train_phase.py")}
    state = {"status": "running", "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "plan_sha256": digest(plan_path), "scripts": sources, "completed": []}
    write_new(execution_path, state)
    try:
        for role in ("control", "candidate"):
            destination = ROOT / setup[role + "_output"]
            command = [sys.executable, str(ROOT / "scripts/train_network.py"), str(ROOT / setup["data"]), "--output", str(destination)]
            for name in ("hidden", "epochs", "batch_size", "learning_rate", "threads", "seed", "activation_bias", "transformer_std", "pair_loss_weight"):
                command += ["--" + name.replace("_", "-"), str(setup[name])]
            for name in ("classical_base", "king_context", "turn_output", "squared_activation"):
                if setup[name]: command += ["--" + name.replace("_", "-")]
            if role == "candidate": command += ["--phase-output"]
            log_path = ROOT / f"artifacts/validation/phase-training-{role}.txt"
            print(json.dumps({"training": role, "epochs": setup["epochs"]}), flush=True)
            with log_path.open("x", encoding="utf-8") as log: subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
            report = read(destination / "training.json")
            assert report["dataset_sha256"] == setup["data_sha256"]
            if role == "control": assert report["model_sha256"] == setup["expected_control_sha256"], "Matched control changed; investigate before candidate training"
            else:
                control = read(ROOT / setup["control_output"] / "training.json")
                for key in ("validation_games", "initial_shared_sha256", "initial_rng_sha256", "training_positions", "validation_positions"):
                    assert report[key] == control[key], key
            state["completed"].append({"role": role, "training_sha256": digest(destination / "training.json"),
                "model_sha256": digest(destination / "model.ann"), "quantized_mae_cp": report["quantized_validation_mae_cp"]})
            execution_path.write_text(json.dumps(state, indent=2) + "\n")
            print(json.dumps(state["completed"][-1]), flush=True)
        assert sources == {name: digest(ROOT / "scripts" / name) for name in sources}
        assert digest(ROOT / setup["data"]) == setup["data_sha256"]
        state["status"] = "complete"
    except BaseException as error:
        state["status"] = "failed"; state["error"] = repr(error); raise
    finally:
        state["updated_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        execution_path.write_text(json.dumps(state, indent=2) + "\n")


if __name__ == "__main__": main()
