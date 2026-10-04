"""Freeze complete stable-label diagnostics and tooling before any match."""
import datetime
import json
import shutil

from run_rating import digest, read, write_new
from uci_client import ROOT


def main():
    directory = ROOT / "artifacts/research/stable-endgame-pipeline-start"
    preflight = read(ROOT / "artifacts/validation/stable-endgame-preflight.json")
    assert preflight["correctness_passed"]
    directory.mkdir(exist_ok=False)
    scripts = []
    for name in ("declare_stable_endgames.py","generate_stable_endgames.py","audit_stable_endgames.py","prepare_stable_training.py",
            "test_fixed_split.py","train_stable_endgames.py","train_network.py","neural_format.py","report_stable_fit.py",
            "prepare_stable_openings.py","check_stable_endgames.py","freeze_stable_pipeline.py","run_stable_endgames.py",
            "assess_stable_endgames.py","preserve_stable_endgames.py","generate_endgame_diagnostic.py","generate_openings.py",
            "audit_openings.py","verify_network.py","verify.py","tactics.py","compare_search.py","match.py","audit_match.py",
            "analyze_rating.py","run_rating.py","uci_client.py","freeze_engine_source.py"):
        shutil.copy2(ROOT / "scripts" / name,directory / name)
        scripts.append({"path":name,"sha256":digest(directory / name)})
    evidence = []
    for folder in ("artifacts/validation","artifacts/tactics","artifacts/benchmarks","tests/fixtures","artifacts/data","artifacts/research"):
        for path in sorted((ROOT / folder).glob("stable-endgame-*")):
            if path.is_file(): evidence.append({"path":path.relative_to(ROOT).as_posix(),"sha256":digest(path)})
    write_new(directory / "manifest.json",{"created_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "plan_sha256":digest(ROOT / "artifacts/research/stable-endgame-plan-v1.json"),"source_files":scripts,"evidence":evidence,
        "engine_sha256":preflight["engine_sha256"],"models":preflight["models"],
        "interpretation":"Frozen after both trainings/correctness/tactics, before matches. All256 short games run regardless of tactical failures. No retuning/adaptive extension."})
    print(json.dumps({"scripts":len(scripts),"evidence":len(evidence),"manifest_sha256":digest(directory / "manifest.json")}),flush=True)


if __name__ == "__main__": main()
