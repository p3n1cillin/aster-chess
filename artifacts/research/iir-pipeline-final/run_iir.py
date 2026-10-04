"""Run the fixed 640-game IIR regression, with conditional 256-game rating."""
import datetime
import json
import pathlib
import subprocess
import sys

from assess_iir import assess
from match import frozen_source_manifest
from run_rating import digest, read, write_new
from uci_client import ROOT


def main():
    plan_path = ROOT / "artifacts/research/iir-plan-v2.json"; plan = read(plan_path)
    execution_path = ROOT / "artifacts/research/iir-execution-v1.json"
    if execution_path.exists(): raise ValueError("Never restart an existing run from its state file; inspect its authoritative process")
    pipeline = ROOT / "artifacts/research/iir-pipeline-start"
    frozen = read(pipeline / "manifest.json")
    assert frozen["plan_sha256"] == digest(plan_path)
    for entry in frozen["source_files"]:
        assert digest(pipeline / entry["path"]) == entry["sha256"]
        assert digest(ROOT / "scripts" / entry["path"]) == entry["sha256"]
    for role in ("candidate","baseline"):
        assert digest(ROOT / plan[role]) == plan[role + "_sha256"]
        frozen_source_manifest(str(ROOT / plan[role + "_source"]),plan[role + "_sha256"])
    for role in ("30ms","100ms","rating","behavior"):
        audit = read(ROOT / f"artifacts/validation/iir-{role}-audit.json")
        assert audit["passed"] and audit["suite_sha256"] == digest(ROOT / f"tests/fixtures/iir-{role}-v1.json")
    for entry in frozen["evidence"]: assert digest(ROOT / entry["path"]) == entry["sha256"]
    state = {"status":"running","started_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "plan_sha256":digest(plan_path),"runner_sha256":digest(__file__),"match_script_sha256":digest(ROOT / "scripts/match.py"),"phases":[]}
    write_new(execution_path,state)

    def phase(label,pairs,seconds,suite,baseline=False):
        prefix = ROOT / f"artifacts/matches/iir-{label}"
        command = [sys.executable,str(ROOT / "scripts/match.py"),"--engine",str(ROOT / plan["candidate"]),"--source-manifest",str(ROOT / plan["candidate_source"]),
            "--pairs",str(pairs),"--movetime",str(seconds),"--max-plies","400","--openings",str(ROOT / suite),"--output",str(prefix)]
        if baseline: command += ["--opponent",str(ROOT / plan["baseline"]),"--opponent-source-manifest",str(ROOT / plan["baseline_source"])]
        else: command += ["--opponent-uci-elo",str(plan["conditional_rating"]["setting"])]
        print(json.dumps({"phase":label,"games":2*pairs}),flush=True)
        with pathlib.Path(str(prefix) + ".txt").open("x",encoding="utf-8") as log:
            subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
        report_path = pathlib.Path(str(prefix) + ".json"); report = read(report_path)
        assert len(report["games"]) == 2*pairs and report["forfeits"] == 0
        assert report["candidate_binary_sha256"] == plan["candidate_sha256"]
        assert report["opponent_binary_sha256"] == (plan["baseline_sha256"] if baseline else plan["conditional_rating"]["opponent_sha256"])
        audit = subprocess.run([sys.executable,str(ROOT / "scripts/audit_match.py"),str(prefix)],text=True,capture_output=True,check=True)
        write_new(str(prefix) + ".audit.json",json.loads(audit.stdout))
        state["phases"].append({"label":label,"games":len(report["games"]),"report":report_path.relative_to(ROOT).as_posix(),"report_sha256":digest(report_path)})
        execution_path.write_text(json.dumps(state,indent=2) + "\n")
        print(json.dumps({"phase":label,"complete":True,**{k:report[k] for k in ("wins","draws","losses","unresolved","seconds")}}),flush=True)
    try:
        for setup in plan["matches"]:
            phase("vs-0.7.6-" + setup["label"],setup["pairs"],setup["seconds_per_move"],f"tests/fixtures/iir-{setup['label']}-v1.json",True)
        assessment = assess(); write_new(ROOT / "artifacts/research/iir-assessment-v1.json",assessment)
        state["eligible_for_engineering_promotion"] = assessment["eligible_for_engineering_promotion"]
        state["failed_gates"] = assessment["failed_gates"]
        print(json.dumps({"eligible":assessment["eligible_for_engineering_promotion"],"failed_gates":assessment["failed_gates"]}),flush=True)
        if assessment["eligible_for_engineering_promotion"]:
            rating = plan["conditional_rating"]
            phase("rating-vs-sf19-2300",rating["pairs"],rating["seconds_per_move"],"tests/fixtures/iir-rating-v1.json")
        else: state["conditional_rating"] = "Skipped; reserved openings remain unused by Aster"
        assert sum(p["games"] for p in state["phases"]) <= plan["maximum_game_budget"]
        state["status"] = "complete"
    except BaseException as error:
        state["status"] = "failed"; state["error"] = repr(error); raise
    finally:
        state["updated_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        execution_path.write_text(json.dumps(state,indent=2) + "\n")


if __name__ == "__main__": main()
