"""Preserve paired-objective models' exact inference, rules and tactical preflight."""
import json
import subprocess
import sys

from match import frozen_source_manifest
from run_rating import digest, read, write_new
from uci_client import ROOT


def main():
    plan_path = ROOT / "artifacts/research/deep-turn-plan-v1.json"; plan = read(plan_path)
    bundle = read(ROOT / "artifacts/research/deep-turn-training-data-v1.json")
    output = ROOT / "artifacts/validation/deep-turn-preflight.json"
    if output.exists(): raise ValueError("Preserve completed/partial preflight")
    engine = ROOT / plan["baseline"]; source = ROOT / plan["baseline_source"]
    assert digest(engine) == plan["baseline_sha256"]
    frozen_source_manifest(str(source),digest(engine))
    for entry in read(source)["source_files"]: assert digest(ROOT / entry["path"]) == entry["sha256"]
    rebuilt = read(ROOT / "artifacts/research/deep-turn-rebuild-source/manifest.json")
    assert rebuilt["source_files"] == read(source)["source_files"]
    assert "55 passed, 0 failed." in (ROOT / "artifacts/validation/deep-turn-default-tests.txt").read_text()
    assert "Build succeeded." in (ROOT / "artifacts/validation/deep-turn-build.txt").read_text()
    assert read(ROOT / "artifacts/validation/deep-turn-default-rules.json")["binary_sha256"] == rebuilt["binary_sha256"]
    comparison = read(ROOT / "artifacts/benchmarks/deep-turn-rebuild-depth8.json")
    assert all(row["same_move"] and row["same_score"] and row["candidate"]["nodes"] == row["opponent"]["nodes"] for row in comparison["positions"])
    state = read(ROOT / "artifacts/research/deep-turn-training-execution-v1.json")
    assert state["status"] == "complete" and state["plan_sha256"] == digest(plan_path)
    for name,sha in state["scripts"].items(): assert digest(ROOT / "scripts" / name) == sha
    for role in ("parent","classical-30ms","control-30ms","classical-100ms"):
        assert read(ROOT / f"artifacts/validation/deep-turn-{role}-audit.json")["passed"]
    def run(name,command):
        with (ROOT / f"artifacts/validation/deep-turn-{name}.txt").open("x",encoding="utf-8") as log:
            subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
    run("frozen-default-rules",[sys.executable,str(ROOT / "scripts/verify.py"),"--engine",str(engine),"--setups","1000",
        "--output",str(ROOT / "artifacts/validation/deep-turn-frozen-default-rules.json")])
    models = {}; tactics = {}
    for role,directory_name in bundle["outputs"].items():
        directory = ROOT / directory_name; model = directory / "model.ann"; report = read(directory / "training.json")
        assert report["dataset_sha256"] == bundle["data_sha256"] and report["model_sha256"] == digest(model)
        models[role] = {"path":model.relative_to(ROOT).as_posix(),"sha256":digest(model),"training_sha256":digest(directory / "training.json")}
        run(role+"-network",[sys.executable,str(ROOT / "scripts/verify_network.py"),str(model),"--engine",str(engine),"--data",str(ROOT / bundle["data"]),
            "--output",str(ROOT / f"artifacts/validation/deep-turn-{role}-network.json")])
        run(role+"-rules",[sys.executable,str(ROOT / "scripts/verify.py"),"--engine",str(engine),"--eval-file",str(model),"--setups","1000",
            "--output",str(ROOT / f"artifacts/validation/deep-turn-{role}-rules.json")])
        tactics[role] = {}
        for label,suite,limit in (("tactics-depth8","tactics-v1.json",["--depth","8"]),("tactics-5000nodes","tactics-v1.json",["--nodes","5000"]),
                ("tactics-quiet-depth8","tactics-quiet-v1.json",["--depth","8"]),("tactics-quiet-5000nodes","tactics-quiet-v1.json",["--nodes","5000"]),
                ("endgames-5000nodes","endgames-v1.json",["--nodes","5000"])):
            destination = ROOT / f"artifacts/tactics/deep-turn-{role}-{label}.json"
            if destination.exists(): raise ValueError("Preserve previous tactics")
            suite_path = ROOT / "tests/fixtures" / suite
            run(role+"-"+label,[sys.executable,str(ROOT / "scripts/tactics.py"),str(suite_path),"--engine",str(engine),"--eval-file",str(model),*limit,"--output",str(destination)])
            result = read(destination); result.update(eval_file_sha256=digest(model),suite_sha256=digest(suite_path))
            destination.write_text(json.dumps(result,indent=2)+"\n")
            minimum = plan["validation"]["tactics"][label]
            tactics[role][label] = {"solved":result["solved"],"minimum":minimum,"passed":result["solved"] >= minimum}
    result = {"schema":1,"correctness_passed":True,"candidate_tactics_passed":all(entry["passed"] for entry in tactics["candidate"].values()),
        "models":models,"tactics":tactics,"engine":plan["baseline"],"engine_sha256":digest(engine),"source_manifest":plan["baseline_source"],
        "source_manifest_sha256":digest(source),"rebuilt_default_equivalent_positions":len(comparison["positions"]),"plan_sha256":digest(plan_path),
        "bundle_sha256":digest(ROOT / "artifacts/research/deep-turn-training-data-v1.json"),"script_sha256":digest(__file__),
        "interpretation":"Training-only objective ablation on unchanged runtime; same deeper targets/split/init/batches. Failures block longer confirmation, never either declared short screen."}
    write_new(output,result); print(json.dumps({"correctness_passed":True,"candidate_tactics_passed":result["candidate_tactics_passed"],"tactics":tactics}),flush=True)


if __name__ == "__main__": main()
