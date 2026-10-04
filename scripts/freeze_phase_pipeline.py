"""Freeze complete phase diagnostics, scripts and models before paired matches."""
import datetime
import json
import shutil

from run_rating import digest, read, write_new
from uci_client import ROOT


def main():
    directory = ROOT / "artifacts/research/phase-pipeline-start"
    directory.mkdir(exist_ok=False)
    preflight = read(ROOT / "artifacts/validation/phase-preflight.json"); assert preflight["correctness_passed"]
    scripts = []
    for name in ("declare_phase.py", "prepare_phase.py", "train_phase.py", "train_network.py", "neural_format.py",
            "verify_phase.py", "verify_network.py", "check_phase.py", "run_phase.py", "assess_phase.py", "preserve_phase.py",
            "freeze_phase_pipeline.py", "match.py", "audit_match.py", "analyze_rating.py", "run_rating.py", "uci_client.py",
            "verify.py", "tactics.py", "compare_search.py", "generate_openings.py", "audit_openings.py", "freeze_engine_source.py"):
        shutil.copy2(ROOT / "scripts" / name, directory / name)
        scripts.append({"path": name, "sha256": digest(directory / name)})
    evidence = []
    for folder in ("artifacts/validation", "artifacts/tactics", "artifacts/benchmarks", "tests/fixtures"):
        for path in sorted((ROOT / folder).glob("phase-*.json")):
            evidence.append({"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path)})
    write_new(directory / "manifest.json", {"created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "plan_sha256": digest(ROOT / "artifacts/research/phase-plan-v1.json"), "source_files": scripts, "evidence": evidence,
        "engine_sha256": preflight["engine_sha256"], "models": preflight["models"],
        "interpretation": "Frozen after correctness/tactics, before matches. All short games run regardless of tactical failures. No retuning or adaptive extension."})
    print(json.dumps({"scripts": len(scripts), "evidence": len(evidence), "manifest_sha256": digest(directory / "manifest.json")}))


if __name__ == "__main__": main()
