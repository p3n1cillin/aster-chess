"""Freeze relations models, scripts, initialization, cost evidence and openings."""
import datetime
import json
import shutil

from run_rating import digest, read, write_new
from uci_client import ROOT
from relations_plan import load_plan


def main():
    directory = ROOT / "artifacts/research/relations-pipeline-start"
    preflight = read(ROOT / "artifacts/validation/relations-preflight.json")
    assert preflight["correctness_passed"] and read(ROOT / "artifacts/validation/relations-cost-v1.json")["passed"]
    directory.mkdir(exist_ok=False)
    scripts = []
    for name in ("relations_plan.py","verify_relations.py","scaffold_relations.py","declare_relations.py","prepare_relations.py","prepare_relations_cost.py","test_relations_initial.py","train_relations.py",
            "train_network.py","neural_format.py","prepare_relations_openings.py","validate_relations_baseline.py","run_relations_cost.py",
            "report_relations_fit.py","check_relations.py","freeze_relations_pipeline.py","run_relations.py","assess_relations.py","preserve_relations.py",
            "record_relations_session.py","audit_relations_match_metadata.py","audit_relations_cost.py","report_relations_initial_search.py","generate_openings.py","audit_openings.py",
            "verify_network.py","verify.py","tactics.py","compare_search.py","match.py","audit_match.py","analyze_rating.py","run_rating.py","uci_client.py","freeze_engine_source.py"):
        shutil.copy2(ROOT / "scripts" / name,directory / name)
        scripts.append({"path":name,"sha256":digest(directory / name)})
    paths = set()
    for folder in ("artifacts/validation","artifacts/tactics","artifacts/benchmarks","tests/fixtures","artifacts/research"):
        paths.update(path for path in (ROOT / folder).glob("relations-*") if path.is_file())
    plan = load_plan()
    for key in ("data","split_path","data_bundle","prior_experiment"): paths.add(ROOT / plan[key])
    paths.add(ROOT / (plan["data"]+".classical.json"))
    for folder in ("artifacts/research/relations-initial-v1","artifacts/research/relations-synthetic-v1","artifacts/research/relations-cost-source-v1","artifacts/publish/relations-dev","artifacts/research/relations-runtime-source-v1","artifacts/publish/relations-cost"):
        paths.update(path for path in (ROOT / folder).rglob("*") if path.is_file())
    evidence = [{"path":path.relative_to(ROOT).as_posix(),"sha256":digest(path)} for path in sorted(paths)]
    write_new(directory / "manifest.json",{"created_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "plan_sha256":digest(ROOT / "artifacts/research/relations-plan-v1.json"),"source_files":scripts,"evidence":evidence,
        "engine_sha256":preflight["engine_sha256"],"models":preflight["models"],
        "interpretation":"Frozen after both trainings/correctness/tactics/cost checks, before matches. Both128-game short screens finish regardless of tactical failures. No retuning or adaptive extension."})
    print(json.dumps({"scripts":len(scripts),"evidence":len(evidence),"manifest_sha256":digest(directory / "manifest.json")}),flush=True)


if __name__ == "__main__": main()
