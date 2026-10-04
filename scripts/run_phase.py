"""Run both fixed short phase screens and only the qualified longer confirmation."""
import datetime
import json
import pathlib
import subprocess
import sys

from assess_phase import assess
from match import frozen_source_manifest
from run_rating import digest, read, write_new
from uci_client import ROOT


def main():
    plan_path = ROOT / "artifacts/research/phase-plan-v1.json"; plan = read(plan_path)
    directory = ROOT / "artifacts/research/phase-pipeline-start"; frozen = read(directory / "manifest.json")
    execution_path = ROOT / "artifacts/research/phase-match-execution-v1.json"
    if execution_path.exists(): raise ValueError("Never restart from state JSON; inspect the authoritative process")
    assert frozen["plan_sha256"] == digest(plan_path)
    for entry in frozen["source_files"]:
        assert digest(directory / entry["path"]) == entry["sha256"] == digest(ROOT / "scripts" / entry["path"])
    for entry in frozen["evidence"]: assert digest(ROOT / entry["path"]) == entry["sha256"]
    preflight = read(ROOT / "artifacts/validation/phase-preflight.json")
    assert digest(ROOT / preflight["engine"]) == frozen["engine_sha256"]
    frozen_source_manifest(str(ROOT / preflight["source_manifest"]), frozen["engine_sha256"])
    assert digest(ROOT / plan["baseline"]) == plan["baseline_sha256"]
    frozen_source_manifest(str(ROOT / plan["baseline_source"]), plan["baseline_sha256"])
    for entry in preflight["models"].values(): assert digest(ROOT / entry["path"]) == entry["sha256"]
    state = {"status": "running", "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "plan_sha256": digest(plan_path), "runner_sha256": digest(__file__), "pipeline_manifest_sha256": digest(directory / "manifest.json"), "phases": []}
    write_new(execution_path, state)

    def phase(label, pairs, seconds, control=False):
        prefix = ROOT / f"artifacts/matches/phase-{label}"
        for suffix in (".txt", ".json", ".pgn", ".audit.json"):
            if pathlib.Path(str(prefix) + suffix).exists(): raise ValueError("Preserve prior match artifacts")
        command = [sys.executable, str(ROOT / "scripts/match.py"), "--engine", str(ROOT / preflight["engine"]),
            "--source-manifest", str(ROOT / preflight["source_manifest"]), "--eval-file", str(ROOT / preflight["models"]["candidate"]["path"]),
            "--opponent", str(ROOT / (preflight["engine"] if control else plan["baseline"])),
            "--opponent-source-manifest", str(ROOT / (preflight["source_manifest"] if control else plan["baseline_source"])),
            "--pairs", str(pairs), "--movetime", str(seconds), "--max-plies", "400",
            "--openings", str(ROOT / f"tests/fixtures/phase-{label}-v1.json"), "--output", str(prefix)]
        if control: command += ["--opponent-eval-file", str(ROOT / preflight["models"]["control"]["path"])]
        print(json.dumps({"phase": label, "games": 2*pairs}), flush=True)
        with pathlib.Path(str(prefix) + ".txt").open("x", encoding="utf-8") as log: subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        result = subprocess.run([sys.executable, str(ROOT / "scripts/audit_match.py"), str(prefix)], capture_output=True, text=True, check=True)
        write_new(str(prefix) + ".audit.json", json.loads(result.stdout))
        report = read(str(prefix) + ".json")
        assert len(report["games"]) == 2*pairs and report["candidate_binary_sha256"] == preflight["engine_sha256"]
        assert report["opponent_binary_sha256"] == (preflight["engine_sha256"] if control else plan["baseline_sha256"])
        state["phases"].append({"label": label, "games": 2*pairs, "report_sha256": digest(str(prefix) + ".json")})
        execution_path.write_text(json.dumps(state, indent=2) + "\n")
        print(json.dumps({"phase": label, "complete": True, **{k: report[k] for k in ("wins", "draws", "losses", "unresolved", "forfeits")}}), flush=True)
    try:
        phase("classical-30ms", 32, .03)
        phase("control-30ms", 32, .03, True)
        short = assess(); write_new(ROOT / "artifacts/research/phase-short-assessment-v1.json", short)
        if short["eligible_for_long_confirmation"]: phase("classical-100ms", 16, .1)
        else: state["conditional_long"] = "Skipped; last16 reserved opening pairs unused by Aster"
        final = assess(); write_new(ROOT / "artifacts/research/phase-decision-v1.json", final)
        assert sum(p["games"] for p in state["phases"]) <= plan["maximum_games"]
        state["status"] = "complete"
        print(json.dumps({"complete": True, "eligible_for_promotion": final["eligible_for_promotion"], "failed_gates": final["failed_gates"]}), flush=True)
    except BaseException as error:
        state["status"] = "failed"; state["error"] = repr(error); raise
    finally:
        state["updated_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        execution_path.write_text(json.dumps(state, indent=2) + "\n")


if __name__ == "__main__": main()
