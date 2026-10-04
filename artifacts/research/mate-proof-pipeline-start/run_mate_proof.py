"""Run the fixed paired unchanged-play regression with frozen preflight evidence."""
import datetime
import json
import pathlib
import subprocess
import sys

from match import frozen_source_manifest
from run_rating import digest, read, write_new
from uci_client import ROOT


def main():
    plan_path = ROOT / "artifacts/research/mate-proof-plan-v1.json"; plan = read(plan_path)
    preflight = read(ROOT / "artifacts/validation/mate-proof-preflight.json"); assert preflight["passed"]
    state_path = ROOT / "artifacts/research/mate-proof-match-execution-v1.json"
    if state_path.exists(): raise ValueError("Never restart from state JSON; inspect the authoritative process")
    snapshot = ROOT / "artifacts/research/mate-proof-pipeline-start"; frozen = read(snapshot / "manifest.json")
    assert frozen["plan_sha256"] == digest(plan_path)
    for entry in frozen["source_files"]:
        assert digest(snapshot / entry["path"]) == entry["sha256"] == digest(ROOT / "scripts" / entry["path"])
    for entry in frozen["evidence"]: assert digest(ROOT / entry["path"]) == entry["sha256"]
    for binary, source, expected in ((preflight["candidate"], preflight["candidate_source"], preflight["candidate_sha256"]),
            (plan["baseline"], plan["baseline_source"], plan["baseline_sha256"])):
        assert digest(ROOT / binary) == expected
        frozen_source_manifest(str(ROOT / source), expected)
    prefix = ROOT / "artifacts/matches/mate-proof-vs-phase-30ms"
    for suffix in (".json", ".pgn", ".txt", ".audit.json"):
        if pathlib.Path(str(prefix) + suffix).exists(): raise ValueError("Preserve existing match artifacts")
    state = {"status": "running", "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "plan_sha256": digest(plan_path), "pipeline_manifest_sha256": digest(snapshot / "manifest.json"), "runner_sha256": digest(__file__)}
    write_new(state_path, state)
    try:
        command = [sys.executable, str(ROOT / "scripts/match.py"), "--engine", str(ROOT / preflight["candidate"]), "--source-manifest", str(ROOT / preflight["candidate_source"]),
            "--opponent", str(ROOT / plan["baseline"]), "--opponent-source-manifest", str(ROOT / plan["baseline_source"]), "--pairs", "16", "--movetime", ".03",
            "--max-plies", "400", "--openings", str(ROOT / "tests/fixtures/mate-proof-match-v1.json"), "--output", str(prefix)]
        print(json.dumps({"started": True, "games": 32}), flush=True)
        with pathlib.Path(str(prefix) + ".txt").open("x", encoding="utf-8") as log: subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        audit = subprocess.run([sys.executable, str(ROOT / "scripts/audit_match.py"), str(prefix)], capture_output=True, text=True, check=True)
        write_new(str(prefix) + ".audit.json", json.loads(audit.stdout))
        result = read(str(prefix) + ".json")
        assert len(result["games"]) == 32 and result["forfeits"] == result["unresolved"] == 0
        assert result["candidate_binary_sha256"] == preflight["candidate_sha256"] and result["opponent_binary_sha256"] == plan["baseline_sha256"]
        state.update({"status": "complete", "report_sha256": digest(str(prefix) + ".json"),
            "results": {k: result[k] for k in ("wins", "draws", "losses", "unresolved", "forfeits")},
            "interpretation": "Paired unchanged-playing regression, no inference of Elo or strength increase from score. General certificate feature independently verified."})
        print(json.dumps(state["results"]), flush=True)
    except BaseException as error:
        state["status"] = "failed"; state["error"] = repr(error); raise
    finally:
        state["updated_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        state_path.write_text(json.dumps(state, indent=2) + "\n")


if __name__ == "__main__": main()
