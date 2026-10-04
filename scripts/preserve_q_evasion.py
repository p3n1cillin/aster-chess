"""Preserve or independently recheck the completed evasion optimization."""
import argparse
import json
import pathlib
import shutil
import subprocess
import sys

from analyze_rating import bootstrap, paired_groups, rating_summary
from assess_q_evasion import assess
from match import frozen_source_manifest
from run_rating import digest, read, write_new
from uci_client import ROOT

FINAL = ROOT / "artifacts/research/q-evasion-experiment-v1-manifest.json"
PIPELINE = ROOT / "artifacts/research/q-evasion-pipeline-final"
RATING = ROOT / "artifacts/ratings/session-20261004-q-evasion-confirmation.json"


def reference(path):
    path = pathlib.Path(path)
    return {"path":path.as_posix(), "sha256":digest(ROOT / path)}


def verify_evidence():
    plan_path = ROOT / "artifacts/research/q-evasion-plan-v1.json"
    plan = read(plan_path); state = read(ROOT / "artifacts/research/q-evasion-execution-v1.json")
    assert state["status"] == "complete" and state["eligible_for_engineering_promotion"]
    assert state["plan_sha256"] == digest(plan_path)
    assert [p["label"] for p in state["phases"]] == ["vs-0.7.4-30ms","vs-0.7.4-100ms","rating-vs-sf19-2300"]
    assert sum(p["games"] for p in state["phases"]) == plan["maximum_game_budget"] == 576
    assessment = read(ROOT / "artifacts/research/q-evasion-assessment-v1.json")
    assert assessment == assess() and not assessment["failed_gates"]
    for phase in state["phases"]:
        path = ROOT / phase["report"]
        assert digest(path) == phase["report_sha256"]
        replay = json.loads(subprocess.run([sys.executable,str(ROOT / "scripts/audit_match.py"),str(path.with_suffix(""))],
                                          text=True,capture_output=True,check=True).stdout)
        assert replay == read(path.with_suffix(".audit.json"))
        report = read(path)
        assert len(report["games"]) == replay["games"] == phase["games"]
        assert report["forfeits"] == report["unresolved"] == 0
        assert report["candidate_binary_sha256"] == plan["candidate_sha256"]
        assert report["runner_sha256"] == state["match_script_sha256"]
    assert report["opponent_binary_sha256"] == plan["conditional_rating"]["opponent_sha256"] == digest(report["opponent"])
    assert report["opponent_options"] == {"Hash":64,"Threads":1,"Move Overhead":0,"UCI_LimitStrength":True,"UCI_Elo":2300}
    assert report["candidate_options"] == {"Hash":64,"Threads":1,"Move Overhead":0}
    assert report["limit"] == {"seconds_per_move":.03} and report["max_plies"] == 400
    suite = ROOT / "tests/fixtures/q-evasion-rating-v1.json"
    assert report["opening_suite"]["sha256"] == digest(suite)
    for game in report["games"]:
        fixture = read(suite)["openings"][game["pair"]-1]
        assert game["opening"] == fixture["moves"] and game["initial_fen"] == fixture["fen"]
    rating = read(RATING); uncertainty = plan["uncertainty"]
    families,pairs,scores = paired_groups(report["games"],128)
    primary = bootstrap(families,uncertainty["bootstrap_samples"],uncertainty["seed"])
    secondary = bootstrap(pairs,uncertainty["bootstrap_samples"],uncertainty["seed"])
    recalculated = rating_summary(2300,scores,primary,report["unresolved"])
    assert all(rating[k] == v for k,v in recalculated.items()) and not rating["failed_numeric_gates"]
    assert rating["secondary_95_percent_score_interval"] == secondary
    assert rating["engine_sha256"] == plan["candidate_sha256"] and rating["all_games_audited"] == 576
    assert rating["source_manifest_sha256"] == digest(ROOT / plan["candidate_source"])
    assert rating["plan_sha256"] == digest(plan_path)
    analyzer = ROOT / "artifacts/research/q-evasion-analysis-precompletion/analyze_q_evasion_rating.py"
    assert rating["analyzer_sha256"] == digest(analyzer) == digest(ROOT / "scripts/analyze_q_evasion_rating.py")
    for entry in rating["evidence"]:
        path = ROOT / entry["path"]
        assert digest(path) == entry["sha256"] and digest(path.with_suffix(".pgn")) == entry["pgn_sha256"]
        assert digest(path.with_suffix(".audit.json")) == entry["audit_sha256"]
    source = read(ROOT / "artifacts/research/q-evasion-default-source/manifest.json")
    frozen_source_manifest(str(ROOT / "artifacts/research/q-evasion-default-source/manifest.json"),source["binary_sha256"])
    rules = read(ROOT / "artifacts/validation/q-evasion-default-rules.json")
    assert rules["status"] == "passed" and rules["binary_sha256"] == source["binary_sha256"]
    assert "51 passed, 0 failed." in (ROOT / "artifacts/validation/q-evasion-default-engine-tests.txt").read_text(encoding="utf-8-sig")
    bench = (ROOT / "artifacts/benchmarks/q-evasion-default-depth7.json").read_text(encoding="utf-8-sig").splitlines()
    assert json.loads(bench[-1])["totalNodes"] == 146772
    traces = read(ROOT / "artifacts/validation/q-evasion-default-traces.json")
    assert traces["passed"] and traces["same_full_traces"] == 416
    assert traces["engine_sha256"] == source["binary_sha256"] and traces["matched_candidate_sha256"] == plan["candidate_sha256"]
    # Promotion changes only the previously active preprocessor branch and name.
    old_root = ROOT / "artifacts/research/q-evasion-source"
    new_root = ROOT / "artifacts/research/q-evasion-default-source"
    for entry in source["source_files"]:
        old = (old_root / entry["path"]).read_text(encoding="utf-8-sig")
        new = (new_root / entry["path"]).read_text(encoding="utf-8-sig")
        if entry["path"] == "src/Engine/Search.cs":
            active = []; in_q = False; keep = True
            for line in old.splitlines(keepends=True):
                if line.strip() == "#if ASTER_Q_EVASION": in_q = True; continue
                if in_q and line.strip() == "#else": keep = False; continue
                if in_q and line.strip() == "#endif": in_q = False; keep = True; continue
                if keep: active.append(line)
            old = "".join(active)
        elif entry["path"] == "src/Engine/Uci.cs":
            old = old.replace('#if ASTER_Q_EVASION\n                        Write("id name Aster 0.7.6-q-evasion-dev");\n#elif ASTER_LAZY_ORDER', '#if ASTER_LAZY_ORDER')
            old = old.replace('Write("id name Aster 0.7.4-feature-dev")', 'Write("id name Aster 0.7.6-feature-dev")')
        assert old == new, entry["path"]
    start = ROOT / "artifacts/research/q-evasion-pipeline-start/manifest.json"
    for entry in read(start)["source_files"]: assert digest(start.parent / entry["path"]) == entry["sha256"]
    assert state["runner_sha256"] == digest(start.parent / "run_q_evasion.py")
    assert state["match_script_sha256"] == digest(start.parent / "match.py")
    return plan,rating


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--verify",action="store_true")
    args = parser.parse_args()
    if args.verify:
        manifest = read(FINAL)
        for entry in manifest["artifacts"]: assert digest(ROOT / entry["path"]) == entry["sha256"], entry["path"]
        verify_evidence()
        print(json.dumps({"passed":True,"games":576,"artifacts":len(manifest["artifacts"]),"manifest_sha256":digest(FINAL)}))
        return
    if FINAL.exists() or PIPELINE.exists(): raise ValueError("Preserve previous snapshots")
    plan,rating = verify_evidence(); paths = []
    manifests = [plan["candidate_source"],plan["baseline_source"],
        "artifacts/research/q-evasion-default-source/manifest.json",
        "artifacts/research/q-evasion-profile-source/manifest.json",
        "artifacts/research/lazy-order-baseline-profile-source/manifest.json"]
    for manifest_path in manifests:
        manifest = read(ROOT / manifest_path)
        frozen_source_manifest(str(ROOT / manifest_path),manifest["binary_sha256"])
        assert digest(ROOT / manifest["binary"]) == manifest["binary_sha256"]
        paths += [manifest_path,manifest["binary"]]
        directory = (ROOT / manifest_path).parent
        paths += [(directory / e["path"]).relative_to(ROOT).as_posix() for e in manifest["source_files"]]
        paths += [p.relative_to(ROOT).as_posix() for p in (ROOT / manifest["binary"]).parent.glob("Aster.*") if p.is_file()]
    PIPELINE.mkdir()
    names = ("match.py","audit_match.py","run_q_evasion.py","assess_q_evasion.py","analyze_q_evasion_rating.py",
        "time_q_evasion.py","verify_q_evasion.py","verify_q_evasion_openings.py","verify_q_evasion_promotion.py",
        "split_q_evasion_suite.py","generate_openings.py","audit_openings.py","analyze_rating.py","run_rating.py",
        "uci_client.py","verify.py","tactics.py","compare_search.py","freeze_engine_source.py","preserve_q_evasion.py")
    for name in names: shutil.copy2(ROOT / "scripts" / name,PIPELINE / name)
    for name in ("docs/QUIESCENCE-EVASIONS.md","docs/RATING.md","README.md","ROADMAP.md","artifacts/PROGRESS.md","AGENTS.md"):
        shutil.copy2(ROOT / name,PIPELINE / pathlib.Path(name).name)
    write_new(PIPELINE / "manifest.json",{"source_files":[reference(p.relative_to(ROOT)) for p in sorted(PIPELINE.iterdir())]})
    for directory in ("artifacts/research","artifacts/matches","artifacts/validation","artifacts/tactics","artifacts/benchmarks","tests/fixtures"):
        for path in (ROOT / directory).glob("q-evasion-*"):
            paths += [p.relative_to(ROOT).as_posix() for p in (path.rglob("*") if path.is_dir() else [path]) if p.is_file()]
    paths += [RATING.relative_to(ROOT).as_posix(),"artifacts/ratings/session-20261004-calibration-v1.json",
        "artifacts/research/rating-experiment-v1-manifest.json","artifacts/benchmarks/lazy-order-baseline-profile-depth9.json",
        "artifacts/tactics/lazy-order-baseline-tactics-quiet-5000nodes.json","tools/stockfish/manifest.json",
        "tools/stockfish/sf_19/stockfish/stockfish-windows-x86-64-universal.exe",
        "tools/stockfish/sf_19/stockfish-windows-x86-64-universal.zip"]
    paths += [p.relative_to(ROOT).as_posix() for p in (ROOT / "artifacts/research/conversion-stockfish19-source").rglob("*") if p.is_file()]
    write_new(FINAL,{"schema":1,"games":576,"candidate_promoted":True,"promoted_default_source":manifests[2],
        "rating_record":reference(RATING.relative_to(ROOT)),"artifacts":[reference(p) for p in sorted(set(paths))],
        "interpretation":"Same-work optimization passes every frozen engineering gate and becomes ordinary0.7.6 source. All576 PGNs independently audited. Exact matched candidate local estimate2319, interval2277..2360, overlaps earlier rating. Renamed default repeats416 full traces; no automatic rating transfer. Public Elo and full-strength Stockfish superiority remain unestablished; goal active."})
    print(json.dumps({"games":576,"artifacts":len(read(FINAL)["artifacts"]),"candidate_promoted":True,"manifest_sha256":digest(FINAL)}))


if __name__ == "__main__": main()
