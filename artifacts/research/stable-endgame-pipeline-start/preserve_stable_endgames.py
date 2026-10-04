"""Verify and preserve a completed stable-label ablation without partial claims."""
import argparse
import datetime
import json
import pathlib
import shutil
import subprocess
import sys

from assess_stable_endgames import assess
from match import frozen_source_manifest
from run_rating import digest, read, write_new
from uci_client import ROOT


def verify_results():
    plan_path = ROOT / "artifacts/research/stable-endgame-plan-v1.json"; plan = read(plan_path)
    training = read(ROOT / "artifacts/research/stable-endgame-training-execution-v1.json")
    state = read(ROOT / "artifacts/research/stable-endgame-match-execution-v1.json")
    assert state["status"] == training["status"] == "complete","Never freeze partial runs"
    assert state["plan_sha256"] == training["plan_sha256"] == digest(plan_path)
    pipeline = ROOT / "artifacts/research/stable-endgame-pipeline-start"; frozen = read(pipeline / "manifest.json")
    assert digest(pipeline / "manifest.json") == state["pipeline_manifest_sha256"]
    for entry in frozen["source_files"]:
        assert digest(pipeline / entry["path"]) == entry["sha256"] == digest(ROOT / "scripts" / entry["path"])
    for entry in frozen["evidence"]: assert digest(ROOT / entry["path"]) == entry["sha256"]
    preflight = read(ROOT / "artifacts/validation/stable-endgame-preflight.json")
    assert preflight["correctness_passed"] and digest(ROOT / preflight["engine"]) == preflight["engine_sha256"] == plan["baseline_sha256"]
    frozen_source_manifest(str(ROOT / preflight["source_manifest"]),preflight["engine_sha256"])
    bundle = read(ROOT / "artifacts/research/stable-endgame-training-data-v1.json")
    assert bundle["complete"] and digest(ROOT / bundle["split_path"]) == bundle["split_sha256"]
    for role,entry in bundle["datasets"].items():
        assert digest(ROOT / entry["path"]) == entry["sha256"]
        model = preflight["models"][role]; path = ROOT / model["path"]
        assert digest(path) == model["sha256"]
        report = read(path.parent / "training.json")
        assert report["model_sha256"] == model["sha256"] and report["dataset_sha256"] == entry["sha256"]
    expected = ["classical-30ms","control-30ms"]
    if read(ROOT / "artifacts/research/stable-endgame-short-assessment-v1.json")["eligible_for_long_confirmation"]: expected.append("classical-100ms")
    assert [phase["label"] for phase in state["phases"]] == expected
    assert sum(phase["games"] for phase in state["phases"]) <= plan["maximum_match_games"]
    for phase in state["phases"]:
        prefix = ROOT / f"artifacts/matches/stable-endgame-{phase['label']}"
        report = read(str(prefix)+".json")
        assert digest(str(prefix)+".json") == phase["report_sha256"] and len(report["games"]) == phase["games"]
        assert report["candidate_binary_sha256"] == report["opponent_binary_sha256"] == plan["baseline_sha256"]
        assert report["candidate_model_sha256"] == preflight["models"]["candidate"]["sha256"]
        if phase["label"] == "control-30ms": assert report["opponent_model_sha256"] == preflight["models"]["control"]["sha256"]
        audit = subprocess.run([sys.executable,str(ROOT / "scripts/audit_match.py"),str(prefix)],capture_output=True,text=True,check=True)
        assert json.loads(audit.stdout) == read(str(prefix)+".audit.json")
    assert assess() == read(ROOT / "artifacts/research/stable-endgame-decision-v1.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--verify",action="store_true")
    args = parser.parse_args(); verify_results()
    manifest_path = ROOT / "artifacts/research/stable-endgame-experiment-v1-manifest.json"
    if args.verify:
        manifest = read(manifest_path)
        for entry in manifest["artifacts"]: assert digest(ROOT / entry["path"]) == entry["sha256"],entry["path"]
    else:
        if manifest_path.exists(): raise ValueError("Preserve immutable final manifest")
        summary = ROOT / "artifacts/research/stable-endgame-summary-v1"; summary.mkdir(exist_ok=False)
        for name in ("docs/STABLE-ENDGAME-LABELS.md","docs/RATING.md","README.md","ROADMAP.md","artifacts/PROGRESS.md","AGENTS.md"):
            shutil.copy2(ROOT / name,summary / pathlib.Path(name).name)
        paths = set()
        for folder in ("artifacts/validation","artifacts/tactics","artifacts/benchmarks","artifacts/matches","artifacts/research","artifacts/data","tests/fixtures"):
            for path in (ROOT / folder).glob("stable-endgame-*"):
                if path == manifest_path: continue
                if path.is_file(): paths.add(path)
                elif path.is_dir(): paths.update(p for p in path.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
        for folder in ("artifacts/publish/stable-endgame-rebuild","artifacts/training/stable-endgame-control-v1","artifacts/training/stable-endgame-candidate-v1",
                "artifacts/publish/mate-proof-dev-v2","artifacts/research/mate-proof-source-v2"):
            paths.update(p for p in (ROOT / folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts)
        paths.add(ROOT / "artifacts/data/teacher-turn-60k-static-v1-classical.jsonl")
        paths.add(ROOT / "tools/stockfish/manifest.json")
        manifest = {"schema":1,"created_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "artifacts":[{"path":path.relative_to(ROOT).as_posix(),"bytes":path.stat().st_size,"sha256":digest(path)} for path in sorted(paths)],
            "games":sum(phase["games"] for phase in read(ROOT / "artifacts/research/stable-endgame-match-execution-v1.json")["phases"]),
            "decision":read(ROOT / "artifacts/research/stable-endgame-decision-v1.json"),
            "interpretation":"Complete fixed-budget teacher-label ablation, models/checkpoints/data/native labels/source histories and audited PGNs. No Elo/Stockfish superiority inferred."}
        write_new(manifest_path,manifest)
    print(json.dumps({"verified":True,"artifacts":len(manifest["artifacts"]),"games":manifest["games"],"manifest_sha256":digest(manifest_path)}),flush=True)


if __name__ == "__main__": main()
