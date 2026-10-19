"""Recheck and freeze complete general-proof evidence and paired regression."""
from research_reference import research_text
import argparse
import datetime
import json
import pathlib
import shutil
import subprocess
import sys

from match import frozen_source_manifest
from run_rating import digest, read, write_new
from uci_client import ROOT
from verify_mate_proof import verify
from verify_strategy_proof import verify as verify_legacy


def verify_results():
    plan_path = ROOT / "artifacts/research/mate-proof-plan-v1.json"; plan = read(plan_path)
    state = read(ROOT / "artifacts/research/mate-proof-match-execution-v1.json")
    assert state["status"] == "complete", "Refuse partial regression runs"
    assert state["plan_sha256"] == digest(plan_path)
    pipeline = ROOT / "artifacts/research/mate-proof-pipeline-start"; frozen = read(pipeline / "manifest.json")
    assert digest(pipeline / "manifest.json") == state["pipeline_manifest_sha256"]
    for entry in frozen["source_files"]:
        assert digest(pipeline / entry["path"]) == entry["sha256"] == digest(ROOT / "scripts" / entry["path"])
    for entry in frozen["evidence"]: assert digest(ROOT / entry["path"]) == entry["sha256"]
    preflight = read(ROOT / "artifacts/validation/mate-proof-preflight.json"); assert preflight["passed"]
    for binary, source, expected in ((preflight["candidate"], preflight["candidate_source"], preflight["candidate_sha256"]),
            (plan["baseline"], plan["baseline_source"], plan["baseline_sha256"])):
        assert digest(ROOT / binary) == expected
        frozen_source_manifest(str(ROOT / source), expected)
    general = read(ROOT / "artifacts/validation/mate-proof-general-v2.json"); assert general["passed"]
    for entry in general["certificates"]:
        assert digest(ROOT / entry["path"]) == entry["sha256"]
        result = verify(read(ROOT / entry["path"]))
        for key, value in result.items(): assert entry[key] == value
    for entry in general["legacy_certificates"]:
        result = verify_legacy(read(ROOT / entry["path"]))
        for key, value in result.items(): assert entry[key] == value
    for path in (ROOT / "artifacts/proofs/mate-proof-general-v2").glob("castling-alternative-*.json"): verify(read(path))
    prefix = ROOT / "artifacts/matches/mate-proof-vs-phase-30ms"; report = read(str(prefix) + ".json")
    assert len(report["games"]) == 32 and report["forfeits"] == report["unresolved"] == 0
    assert digest(str(prefix) + ".json") == state["report_sha256"]
    assert report["candidate_binary_sha256"] == preflight["candidate_sha256"] and report["opponent_binary_sha256"] == plan["baseline_sha256"]
    assert report["pairs_requested"] == 16 and report["limit"] == {"seconds_per_move": .03} and report["max_plies"] == 400
    for role in ("candidate", "opponent"): assert report[role + "_options"] == {"Hash": 64, "Threads": 1, "Move Overhead": 0}
    assert report["opening_suite"]["sha256"] == digest(ROOT / "tests/fixtures/mate-proof-match-v1.json")
    result = subprocess.run([sys.executable, str(ROOT / "scripts/audit_match.py"), str(prefix)], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == read(str(prefix) + ".audit.json")
    assert state["results"] == {k: report[k] for k in ("wins", "draws", "losses", "unresolved", "forfeits")}


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(); verify_results()
    path = ROOT / "artifacts/research/mate-proof-experiment-v1-manifest.json"
    if args.verify:
        manifest = read(path)
        for entry in manifest["artifacts"]: assert digest(ROOT / entry["path"]) == entry["sha256"], entry["path"]
    else:
        if path.exists(): raise ValueError("Preserve immutable final manifest")
        summary = ROOT / "artifacts/research/mate-proof-summary-v1"; summary.mkdir(exist_ok=False)
        for name in ("docs/GENERAL-MATE-PROOFS.md", "docs/STRATEGY-PROOFS.md", "docs/RATING.md", "README.md", "ROADMAP.md", "artifacts/PROGRESS.md", "AGENTS.md"):
            shutil.copy2(ROOT / name, summary / pathlib.Path(name).name)
        paths = set()
        for folder in ("artifacts/research", "artifacts/validation", "artifacts/benchmarks", "artifacts/tactics", "artifacts/matches", "artifacts/proofs", "tests/fixtures", "artifacts/publish"):
            for item in (ROOT / folder).glob("mate-proof-*"):
                if item == path: continue
                if item.is_file(): paths.add(item)
                elif item.is_dir(): paths.update(p for p in item.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
        plan = read(ROOT / "artifacts/research/mate-proof-plan-v1.json")
        for folder in ("artifacts/publish/phase-dev", "artifacts/research/phase-source", "artifacts/proofs/samples-v1"):
            paths.update(p for p in (ROOT / folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts)
        paths.update(ROOT / entry["path"] for entry in read(ROOT / "artifacts/validation/mate-proof-general-v2.json")["legacy_certificates"])
        manifest = {"schema": 1, "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "paired_regression_games": 32,
            "artifacts": [{"path": p.relative_to(ROOT).as_posix(), "bytes": p.stat().st_size, "sha256": digest(p)} for p in sorted(paths)],
            "interpretation": research_text('preserve_mate_proof.interpretation')}
        write_new(path, manifest)
    print(json.dumps({"verified": True, "artifacts": len(manifest["artifacts"]), "manifest_sha256": digest(path)}))


if __name__ == "__main__": main()
