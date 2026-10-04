"""Verify the stable-label models and freeze diagnostics before matches."""
import json
import subprocess
import sys

from match import frozen_source_manifest
from run_rating import digest, read, write_new
from uci_client import ROOT


def main():
    plan_path = ROOT / "artifacts/research/stable-endgame-plan-v1.json"; plan = read(plan_path)
    bundle = read(ROOT / "artifacts/research/stable-endgame-training-data-v1.json")
    output = ROOT / "artifacts/validation/stable-endgame-preflight.json"
    if output.exists(): raise ValueError("Preserve prior preflight")
    engine = ROOT / plan["baseline"]; source = ROOT / plan["baseline_source"]
    assert digest(engine) == plan["baseline_sha256"]
    frozen_source_manifest(str(source),digest(engine))
    for entry in read(source)["source_files"]: assert digest(ROOT / entry["path"]) == entry["sha256"]
    execution = read(ROOT / "artifacts/research/stable-endgame-training-execution-v1.json")
    assert execution["status"] == "complete" and execution["plan_sha256"] == digest(plan_path)
    for name,sha in execution["scripts"].items(): assert digest(ROOT / "scripts" / name) == sha
    assert read(ROOT / "artifacts/validation/stable-endgame-frozen-default-rules.json")["binary_sha256"] == digest(engine)
    assert read(ROOT / "artifacts/validation/stable-endgame-frozen-default-rules.json")["status"] == "passed"
    assert "55 passed, 0 failed." in (ROOT / "artifacts/validation/stable-endgame-default-tests.txt").read_text()
    assert "Build succeeded." in (ROOT / "artifacts/validation/stable-endgame-build.txt").read_text()
    rebuilt_source = read(ROOT / "artifacts/research/stable-endgame-rebuild-source/manifest.json")
    assert rebuilt_source["source_files"] == read(source)["source_files"]
    comparison = read(ROOT / "artifacts/benchmarks/stable-endgame-rebuild-depth8.json")
    assert all(row["same_move"] and row["same_score"] and row["candidate"]["nodes"] == row["opponent"]["nodes"] for row in comparison["positions"])
    for role in ("parent","classical-30ms","control-30ms","classical-100ms"):
        assert read(ROOT / f"artifacts/validation/stable-endgame-{role}-audit.json")["passed"]
    assert read(ROOT / "artifacts/validation/stable-endgame-common-heldout-fit-v1.json")["complete"]

    def run(name,command):
        with (ROOT / f"artifacts/validation/stable-endgame-{name}.txt").open("x",encoding="utf-8") as log:
            subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)

    models = {}; tactics = {}
    for role,entry in bundle["datasets"].items():
        directory = ROOT / entry["output"]; model = directory / "model.ann"; report = read(directory / "training.json")
        assert report["dataset_sha256"] == entry["sha256"] and report["model_sha256"] == digest(model)
        models[role] = {"path":model.relative_to(ROOT).as_posix(),"sha256":digest(model),"training_sha256":digest(directory / "training.json")}
        run(role+"-network",[sys.executable,str(ROOT / "scripts/verify_network.py"),str(model),"--engine",str(engine),
            "--data",str(ROOT / entry["path"]),"--original-only","--output",str(ROOT / f"artifacts/validation/stable-endgame-{role}-network.json")])
        run(role+"-rules",[sys.executable,str(ROOT / "scripts/verify.py"),"--engine",str(engine),"--eval-file",str(model),"--setups","1000",
            "--output",str(ROOT / f"artifacts/validation/stable-endgame-{role}-rules.json")])
        tactics[role] = {}
        for label,suite,limit,minimum in (("tactics-depth8","tactics-v1.json",["--depth","8"],32),
                ("tactics-5000nodes","tactics-v1.json",["--nodes","5000"],32),
                ("tactics-quiet-depth8","tactics-quiet-v1.json",["--depth","8"],32),
                ("tactics-quiet-5000nodes","tactics-quiet-v1.json",["--nodes","5000"],25),
                ("endgames-5000nodes","endgames-v1.json",["--nodes","5000"],13)):
            destination = ROOT / f"artifacts/tactics/stable-endgame-{role}-{label}.json"
            if destination.exists(): raise ValueError("Preserve prior tactics")
            suite_path = ROOT / "tests/fixtures" / suite
            run(role+"-"+label,[sys.executable,str(ROOT / "scripts/tactics.py"),str(suite_path),"--engine",str(engine),"--eval-file",str(model),*limit,"--output",str(destination)])
            result = read(destination); result.update(eval_file_sha256=digest(model),suite_sha256=digest(suite_path))
            destination.write_text(json.dumps(result,indent=2)+"\n")
            tactics[role][label] = {"solved":result["solved"],"minimum":minimum,"passed":result["solved"] >= minimum}
    result = {"schema":1,"correctness_passed":True,"candidate_tactics_passed":all(item["passed"] for item in tactics["candidate"].values()),
        "models":models,"tactics":tactics,"engine":plan["baseline"],"engine_sha256":digest(engine),"source_manifest":plan["baseline_source"],
        "source_manifest_sha256":digest(source),"rebuilt_default_equivalent_positions":len(comparison["positions"]),
        "plan_sha256":digest(plan_path),"bundle_sha256":digest(ROOT / "artifacts/research/stable-endgame-training-data-v1.json"),"script_sha256":digest(__file__),
        "interpretation":"Frozen0.7.9 runtime with both models; exact inference, rules and tactics. Both short screens run even if tactics fail. Ratings do not transfer to these models."}
    write_new(output,result)
    print(json.dumps({"correctness_passed":True,"candidate_tactics_passed":result["candidate_tactics_passed"],"tactics":tactics}),flush=True)


if __name__ == "__main__": main()
