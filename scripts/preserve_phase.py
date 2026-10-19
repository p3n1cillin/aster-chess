"""Verify and freeze the completed phase experiment; refuse partial runs."""
from research_reference import research_text
import argparse
import datetime
import json
import pathlib
import shutil
import subprocess
import sys

from assess_phase import assess
from match import frozen_source_manifest
from run_rating import digest, read, write_new
from uci_client import ROOT


def verify_results():
    plan_path = ROOT / "artifacts/research/phase-plan-v1.json"; plan = read(plan_path)
    state = read(ROOT / "artifacts/research/phase-match-execution-v1.json")
    training = read(ROOT / "artifacts/research/phase-training-execution-v1.json")
    assert state["status"] == training["status"] == "complete", "Never freeze partial runs"
    assert state["plan_sha256"] == training["plan_sha256"] == digest(plan_path)
    pipeline = ROOT / "artifacts/research/phase-pipeline-start"; frozen = read(pipeline / "manifest.json")
    assert digest(pipeline / "manifest.json") == state["pipeline_manifest_sha256"]
    for entry in frozen["source_files"]:
        assert digest(pipeline / entry["path"]) == entry["sha256"] == digest(ROOT / "scripts" / entry["path"])
    for entry in frozen["evidence"]: assert digest(ROOT / entry["path"]) == entry["sha256"]
    preflight = read(ROOT / "artifacts/validation/phase-preflight.json")
    assert preflight["correctness_passed"] and digest(ROOT / preflight["engine"]) == preflight["engine_sha256"]
    frozen_source_manifest(str(ROOT / preflight["source_manifest"]), preflight["engine_sha256"])
    frozen_source_manifest(str(ROOT / plan["baseline_source"]), plan["baseline_sha256"])
    assert digest(ROOT / plan["baseline"]) == plan["baseline_sha256"]
    assert digest(ROOT / plan["training"]["data"]) == plan["training"]["data_sha256"]
    for role, model in preflight["models"].items():
        assert digest(ROOT / model["path"]) == model["sha256"]
        report = read(ROOT / model["path"] / ".." / "training.json")
        assert report["model_sha256"] == model["sha256"] and report["dataset_sha256"] == plan["training"]["data_sha256"]
    expected_labels = ["classical-30ms", "control-30ms"]
    if read(ROOT / "artifacts/research/phase-short-assessment-v1.json")["eligible_for_long_confirmation"]: expected_labels.append("classical-100ms")
    assert [p["label"] for p in state["phases"]] == expected_labels
    assert sum(p["games"] for p in state["phases"]) <= plan["maximum_games"]
    for phase in state["phases"]:
        prefix = ROOT / f"artifacts/matches/phase-{phase['label']}"
        report = read(str(prefix) + ".json")
        assert digest(str(prefix) + ".json") == phase["report_sha256"] and len(report["games"]) == phase["games"]
        assert report["candidate_binary_sha256"] == preflight["engine_sha256"]
        assert report["opponent_binary_sha256"] == (preflight["engine_sha256"] if phase["label"] == "control-30ms" else plan["baseline_sha256"])
        audit = subprocess.run([sys.executable, str(ROOT / "scripts/audit_match.py"), str(prefix)], capture_output=True, text=True, check=True)
        assert json.loads(audit.stdout) == read(str(prefix) + ".audit.json")
    assert assess() == read(ROOT / "artifacts/research/phase-decision-v1.json"), "Saved gates disagree with recomputation"


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(); verify_results()
    manifest_path = ROOT / "artifacts/research/phase-experiment-v1-manifest.json"
    if args.verify:
        manifest = read(manifest_path)
        for entry in manifest["artifacts"]: assert digest(ROOT / entry["path"]) == entry["sha256"], entry["path"]
    else:
        if manifest_path.exists(): raise ValueError("Preserve immutable final manifest")
        summary = ROOT / "artifacts/research/phase-summary-v1"; summary.mkdir(exist_ok=False)
        for name in ("docs/PHASE-OUTPUT.md", "docs/RATING.md", "README.md", "ROADMAP.md", "artifacts/PROGRESS.md", "AGENTS.md"):
            shutil.copy2(ROOT / name, summary / pathlib.Path(name).name)
        paths = set()
        for folder in ("artifacts/validation", "artifacts/tactics", "artifacts/benchmarks", "artifacts/matches", "artifacts/research", "tests/fixtures"):
            for path in (ROOT / folder).glob("phase-*"):
                if path == manifest_path: continue
                if path.is_file(): paths.add(path)
                elif path.is_dir(): paths.update(p for p in path.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
        for folder in ("artifacts/publish/phase-dev", "artifacts/training/phase-control-v1", "artifacts/training/phase-output-v1",
                "artifacts/publish/q-evasion-default-dotnet", "artifacts/research/q-evasion-default-source"):
            paths.update(p for p in (ROOT / folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts)
        paths.add(ROOT / "artifacts/data/teacher-turn-60k-static-v1-classical.jsonl")
        entries = [{"path": p.relative_to(ROOT).as_posix(), "bytes": p.stat().st_size, "sha256": digest(p)} for p in sorted(paths)]
        manifest = {"schema": 1, "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "artifacts": entries, "games": sum(p["games"] for p in read(ROOT / "artifacts/research/phase-match-execution-v1.json")["phases"]),
            "decision": read(ROOT / "artifacts/research/phase-decision-v1.json"),
            "interpretation": research_text('preserve_phase.interpretation')}
        write_new(manifest_path, manifest)
    print(json.dumps({"verified": True, "artifacts": len(manifest["artifacts"]), "games": manifest["games"], "manifest_sha256": digest(manifest_path)}))


if __name__ == "__main__": main()
