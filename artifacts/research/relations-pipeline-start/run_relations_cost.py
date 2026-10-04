"""Run frozen cost trace after training and before matches; retain all samples."""
import json
import shutil
import statistics
import subprocess

from run_rating import digest, read, write_new
from uci_client import ROOT
from relations_plan import load_plan


def main():
    plan_path = ROOT / "artifacts/research/relations-plan-v1.json"; plan = load_plan()
    assert read(ROOT / "artifacts/research/relations-training-execution-v1.json")["status"] == "complete"
    assert read(ROOT / "artifacts/validation/relations-parent-audit.json")["passed"]
    bundle = read(ROOT / "artifacts/research/relations-training-data-v1.json")
    package = ROOT / "artifacts/publish/relations-cost"; package.mkdir(exist_ok=False)
    for path in (ROOT / "tools/RelationCost/bin/Release/net8.0").iterdir():
        if path.is_file(): shutil.copy2(path,package / path.name)
    assert digest(package / "Aster.dll") == plan["baseline_sha256"]
    source = ROOT / "artifacts/research/relations-cost-source-v1"; source.mkdir(exist_ok=False)
    for name in ("Program.cs","RelationCost.csproj"): shutil.copy2(ROOT / "tools/RelationCost" / name,source / name)
    trace = ROOT / "artifacts/research/relations-cost-trace-v1.json"
    models = {role:ROOT / entry["output"] / "model.ann" for role,entry in bundle["outputs"].items()}
    raw_path = ROOT / "artifacts/validation/relations-cost-raw-v1.json"
    with (ROOT / "artifacts/validation/relations-cost-driver.txt").open("x",encoding="utf-8") as log:
        subprocess.run(["dotnet",str(package / "Aster.RelationCost.dll"),str(trace),str(models["control"]),str(models["candidate"]),str(raw_path)],
            stdout=log,stderr=subprocess.STDOUT,check=True)
    raw = read(raw_path)
    assert raw["passed"] and raw["root_restoration_checked"] and raw["baseline_sha256"] == plan["baseline_sha256"]
    assert raw["trace_sha256"] == digest(trace)
    samples = {role:[row["milliseconds"] for row in raw["samples"] if row["role"] == role] for role in ("classical","control","candidate")}
    assert all(len(values) == plan["cost_diagnostic"]["rounds"] for values in samples.values())
    medians = {role:statistics.median(values) for role,values in samples.items()}
    result = {"schema":1,"passed":True,"plan_sha256":digest(plan_path),"script_sha256":digest(__file__),"raw_sha256":digest(raw_path),
        "trace_sha256":digest(trace),"harness_sha256":digest(package / "Aster.RelationCost.dll"),"runtime_sha256":raw["baseline_sha256"],
        "models":{role:digest(path) for role,path in models.items()},"median_milliseconds":medians,
        "candidate_over_control_median":medians["candidate"]/medians["control"],"control_over_classical_median":medians["control"]/medians["classical"],
        "interpretation":"Identical frozen make/eval/undo/eval workload and checked roots/checksums. Local counterbalanced warmed cost diagnostic; not broad search speed, a promotion gate, Elo or strength. No retuning from timings."}
    write_new(ROOT / "artifacts/validation/relations-cost-v1.json",result); print(json.dumps(result),flush=True)


if __name__ == "__main__": main()
