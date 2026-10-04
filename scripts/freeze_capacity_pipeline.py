"""Freeze capacity models, scripts, initialization, cost evidence and openings."""
import datetime
import json
import shutil

from run_rating import digest, read, write_new
from uci_client import ROOT


def main():
    directory = ROOT / "artifacts/research/capacity-pipeline-start"
    preflight = read(ROOT / "artifacts/validation/capacity-preflight.json")
    assert preflight["correctness_passed"] and read(ROOT / "artifacts/validation/capacity-cost-v1.json")["passed"]
    directory.mkdir(exist_ok=False)
    scripts = []
    for name in ("declare_capacity.py","prepare_capacity.py","prepare_capacity_cost.py","test_capacity_initial.py","train_capacity.py",
            "train_network.py","neural_format.py","prepare_capacity_openings.py","validate_capacity_baseline.py","run_capacity_cost.py",
            "report_capacity_fit.py","check_capacity.py","freeze_capacity_pipeline.py","run_capacity.py","assess_capacity.py","preserve_capacity.py",
            "record_capacity_session.py","audit_capacity_match_metadata.py","report_capacity_initial_search.py","generate_openings.py","audit_openings.py",
            "verify_network.py","verify.py","tactics.py","compare_search.py","match.py","audit_match.py","analyze_rating.py","run_rating.py","uci_client.py","freeze_engine_source.py"):
        shutil.copy2(ROOT / "scripts" / name,directory / name)
        scripts.append({"path":name,"sha256":digest(directory / name)})
    paths = set()
    for folder in ("artifacts/validation","artifacts/tactics","artifacts/benchmarks","tests/fixtures","artifacts/research"):
        paths.update(path for path in (ROOT / folder).glob("capacity-*") if path.is_file())
    plan = read(ROOT / "artifacts/research/capacity-plan-v1.json")
    for key in ("data","split_path","data_bundle","prior_experiment"): paths.add(ROOT / plan[key])
    paths.add(ROOT / (plan["data"]+".classical.json"))
    for folder in ("artifacts/research/capacity-initial-v1","artifacts/research/capacity-cost-source-v1","artifacts/publish/capacity-cost"):
        paths.update(path for path in (ROOT / folder).rglob("*") if path.is_file())
    evidence = [{"path":path.relative_to(ROOT).as_posix(),"sha256":digest(path)} for path in sorted(paths)]
    write_new(directory / "manifest.json",{"created_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "plan_sha256":digest(ROOT / "artifacts/research/capacity-plan-v1.json"),"source_files":scripts,"evidence":evidence,
        "engine_sha256":preflight["engine_sha256"],"models":preflight["models"],
        "interpretation":"Frozen after both trainings/correctness/tactics/cost checks, before matches. Both128-game short screens finish regardless of tactical failures. No retuning or adaptive extension."})
    print(json.dumps({"scripts":len(scripts),"evidence":len(evidence),"manifest_sha256":digest(directory / "manifest.json")}),flush=True)


if __name__ == "__main__": main()
