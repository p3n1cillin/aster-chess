"""Audit and preserve a terminal IIR experiment without rewriting earlier evidence."""
from research_reference import research_text
import argparse
import json
import pathlib
import shutil
import subprocess
import sys

from analyze_rating import bootstrap, paired_groups, rating_summary
from assess_iir import assess
from match import frozen_source_manifest
from run_rating import digest, read, write_new
from uci_client import ROOT

FINAL = ROOT / "artifacts/research/iir-experiment-v1-manifest.json"
PIPELINE = ROOT / "artifacts/research/iir-pipeline-final"
RATING = ROOT / "artifacts/ratings/session-20261004-iir-confirmation.json"


def reference(path):
    path = pathlib.Path(path)
    return {"path":path.as_posix(),"sha256":digest(ROOT / path)}


def verify_results():
    state = read(ROOT / "artifacts/research/iir-execution-v1.json")
    # Check this before opening or replaying a match report: it can still be
    # changing while the runner is live, even if its requested count is reached.
    if state["status"] != "complete": raise ValueError("Experiment is not terminal; preserve no interim results")
    path = ROOT / "artifacts/research/iir-plan-v2.json"; plan = read(path)
    assert state["plan_sha256"] == digest(path)
    start = ROOT / "artifacts/research/iir-pipeline-start"
    frozen = read(start / "manifest.json")
    assert frozen["plan_sha256"] == digest(path)
    for entry in frozen["source_files"]: assert digest(start / entry["path"]) == entry["sha256"]
    for entry in frozen["evidence"]: assert digest(ROOT / entry["path"]) == entry["sha256"]
    assert state["runner_sha256"] == digest(start / "run_iir.py") == digest(ROOT / "scripts/run_iir.py")
    assert state["match_script_sha256"] == digest(start / "match.py") == digest(ROOT / "scripts/match.py")
    assessment = read(ROOT / "artifacts/research/iir-assessment-v1.json")
    assert assessment == assess()
    eligible = assessment["eligible_for_engineering_promotion"]
    assert state["eligible_for_engineering_promotion"] == eligible
    labels = ["vs-0.7.6-30ms","vs-0.7.6-100ms"] + (["rating-vs-sf19-2300"] if eligible else [])
    assert [phase["label"] for phase in state["phases"]] == labels
    total = sum(phase["games"] for phase in state["phases"])
    assert total == (896 if eligible else 640)
    for phase in state["phases"]:
        report_path = ROOT / phase["report"]; report = read(report_path)
        assert digest(report_path) == phase["report_sha256"]
        replay = json.loads(subprocess.run([sys.executable,str(ROOT / "scripts/audit_match.py"),str(report_path.with_suffix(""))],
            text=True,capture_output=True,check=True).stdout)
        assert replay == read(report_path.with_suffix(".audit.json"))
        assert phase["games"] == replay["games"] == len(report["games"])
        assert replay["status"] == "passed" and report["forfeits"] == 0
        assert report["candidate_binary_sha256"] == plan["candidate_sha256"]
        assert report["runner_sha256"] == state["match_script_sha256"]
    if eligible:
        rating = read(RATING)
        assert report["opponent_binary_sha256"] == plan["conditional_rating"]["opponent_sha256"] == digest(report["opponent"])
        assert report["opponent_options"] == {"Hash":64,"Threads":1,"Move Overhead":0,"UCI_LimitStrength":True,"UCI_Elo":2300}
        assert report["candidate_options"] == {"Hash":64,"Threads":1,"Move Overhead":0}
        assert report["limit"] == {"seconds_per_move":.03} and report["max_plies"] == 400
        suite = ROOT / "tests/fixtures/iir-rating-v1.json"
        assert report["opening_suite"]["sha256"] == digest(suite)
        fixtures = read(suite)["openings"]
        for game in report["games"]:
            fixture = fixtures[game["pair"]-1]
            assert game["opening"] == fixture["moves"] and game["initial_fen"] == fixture["fen"]
        families,pairs,scores = paired_groups(report["games"],128); uncertainty = plan["uncertainty"]
        primary = bootstrap(families,uncertainty["bootstrap_samples"],uncertainty["seed"])
        computed = rating_summary(2300,scores,primary,report["unresolved"])
        assert all(rating[k] == v for k,v in computed.items())
        assert rating["secondary_95_percent_score_interval"] == bootstrap(pairs,uncertainty["bootstrap_samples"],uncertainty["seed"])
        assert rating["engine_sha256"] == plan["candidate_sha256"] and rating["all_games_audited"] == total
        assert rating["analyzer_sha256"] == digest(start / "analyze_iir_rating.py") == digest(ROOT / "scripts/analyze_iir_rating.py")
        assert rating["plan_sha256"] == digest(path)
        for entry in rating["evidence"]:
            report_path = ROOT / entry["path"]
            assert digest(report_path) == entry["sha256"]
            assert digest(report_path.with_suffix(".pgn")) == entry["pgn_sha256"]
            assert digest(report_path.with_suffix(".audit.json")) == entry["audit_sha256"]
    else:
        assert not RATING.exists(), "A rejected candidate must not acquire a conditional rating"
    return plan,state,assessment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check",action="store_true",help="Audit completed results without writing a manifest")
    parser.add_argument("--verify",action="store_true",help="Recheck an already preserved experiment")
    args = parser.parse_args()
    if args.check and args.verify: parser.error("Choose one read-only mode")
    plan,state,assessment = verify_results()
    if args.check:
        print(json.dumps({"passed":True,"games":sum(p["games"] for p in state["phases"]),"eligible":assessment["eligible_for_engineering_promotion"]})); return
    if args.verify:
        manifest = read(FINAL)
        for entry in manifest["artifacts"]: assert digest(ROOT / entry["path"]) == entry["sha256"],entry["path"]
        print(json.dumps({"passed":True,"games":manifest["games"],"artifacts":len(manifest["artifacts"]),"manifest_sha256":digest(FINAL)})); return
    if FINAL.exists() or PIPELINE.exists(): raise ValueError("Preserve previous final snapshots")
    # The decision is recorded only after the concrete implementation/rejection
    # and its checks. Eligibility by itself never asserts a source promotion.
    decision_path = ROOT / "artifacts/research/iir-decision-v1.json"; decision = read(decision_path)
    assert decision["assessment_sha256"] == digest(ROOT / "artifacts/research/iir-assessment-v1.json")
    assert decision["candidate_promoted"] == assessment["eligible_for_engineering_promotion"]
    paths = []; manifests = [plan["candidate_source"],plan["baseline_source"],
        "artifacts/research/iir-profile-source/manifest.json",decision["default_source_manifest"]]
    for manifest_path in manifests:
        manifest = read(ROOT / manifest_path)
        frozen_source_manifest(str(ROOT / manifest_path),manifest["binary_sha256"])
        assert digest(ROOT / manifest["binary"]) == manifest["binary_sha256"]
        paths += [manifest_path,manifest["binary"]]
        paths += [((ROOT / manifest_path).parent / e["path"]).relative_to(ROOT).as_posix() for e in manifest["source_files"]]
        paths += [p.relative_to(ROOT).as_posix() for p in (ROOT / manifest["binary"]).parent.glob("Aster.*") if p.is_file()]
    default = read(ROOT / decision["default_source_manifest"])
    checks = decision["default_verification"]
    rules = read(ROOT / checks["rules"])
    assert rules["status"] == "passed" and rules["binary_sha256"] == default["binary_sha256"]
    expected_tests = 52 if decision["candidate_promoted"] else 51
    assert f"{expected_tests} passed, 0 failed." in (ROOT / checks["tests"]).read_text(encoding="utf-8-sig")
    benchmark = (ROOT / checks["benchmark"]).read_text(encoding="utf-8-sig").splitlines()
    assert json.loads(benchmark[-1])["totalNodes"] > 0
    behavior = read(ROOT / checks["behavior"])
    if decision["candidate_promoted"]:
        assert behavior["passed"] and behavior["same_full_traces"] == 320
        assert behavior["engine_sha256"] == default["binary_sha256"] and behavior["matched_candidate_sha256"] == plan["candidate_sha256"]
    else:
        assert json.loads(benchmark[-1])["totalNodes"] == 146772
        assert [e["sha256"] for e in behavior["engines"]] == [default["binary_sha256"],plan["baseline_sha256"]]
        assert len(behavior["positions"]) == 64 and all(r["same_move"] and r["same_score"] and r["candidate"]["nodes"] == r["opponent"]["nodes"] for r in behavior["positions"])
    paths += list(checks.values())
    for entry in decision["verification"]:
        assert digest(ROOT / entry["path"]) == entry["sha256"]
        paths.append(entry["path"])
    PIPELINE.mkdir()
    for name in [e["path"] for e in read(ROOT / "artifacts/research/iir-pipeline-start/manifest.json")["source_files"]] + ["preserve_iir.py"]:
        shutil.copy2(ROOT / "scripts" / name,PIPELINE / name)
    for name in ("docs/INTERNAL-REDUCTIONS.md","docs/RATING.md","docs/VERSION-CONTROL.md","README.md","ROADMAP.md","artifacts/PROGRESS.md","AGENTS.md"):
        shutil.copy2(ROOT / name,PIPELINE / pathlib.Path(name).name)
    write_new(PIPELINE / "manifest.json",{"source_files":[reference(p.relative_to(ROOT)) for p in sorted(PIPELINE.iterdir())]})
    for directory in ("artifacts/research","artifacts/validation","artifacts/benchmarks","artifacts/tactics","artifacts/matches","tests/fixtures"):
        for path in (ROOT / directory).glob("iir-*"):
            paths += [p.relative_to(ROOT).as_posix() for p in (path.rglob("*") if path.is_dir() else [path]) if p.is_file()]
    if assessment["eligible_for_engineering_promotion"]: paths.append(RATING.relative_to(ROOT).as_posix())
    paths += ["artifacts/ratings/session-20261004-q-evasion-confirmation.json","artifacts/research/q-evasion-experiment-v1-manifest.json",research_text('opponent_manifest'),
        research_text('archive.reference_executable'),research_text('archive.reference_zip')]
    paths += [p.relative_to(ROOT).as_posix() for p in (ROOT / research_text('archive.reference_sources')).rglob("*") if p.is_file()]
    write_new(FINAL,{"schema":1,"games":sum(p["games"] for p in state["phases"]),"candidate_promoted":decision["candidate_promoted"],
        "decision":reference(decision_path.relative_to(ROOT)),"failed_gates":assessment["failed_gates"],"artifacts":[reference(p) for p in sorted(set(paths))],
        "interpretation":research_text('preserve_iir.interpretation')})
    print(json.dumps({"games":read(FINAL)["games"],"artifacts":len(read(FINAL)["artifacts"]),"candidate_promoted":decision["candidate_promoted"],"manifest_sha256":digest(FINAL)}))


if __name__ == "__main__": main()
