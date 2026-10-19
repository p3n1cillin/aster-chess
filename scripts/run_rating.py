"""Execute the frozen two-stage, bounded local rating calibration."""
from research_reference import research_text
import datetime
import hashlib
import json
import pathlib
import subprocess
import sys

from match import frozen_source_manifest
from uci_client import ROOT


def digest(path): return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
def read(path): return json.loads(pathlib.Path(path).read_text(encoding="utf-8-sig"))
def write_new(path, data):
    with pathlib.Path(path).open("x", encoding="utf-8") as target: target.write(json.dumps(data, indent=2) + "\n")


def screen_score(report):
    return (report["wins"] + report["draws"] * .5 + report["unresolved"] * .5) / len(report["games"])


def choose_setting(reports):
    return min(reports, key=lambda setting: (abs(screen_score(reports[setting]) - .5), setting))


def main():
    plan_path = ROOT / "artifacts/research/rating-plan-v1.json"; plan = read(plan_path)
    execution_path = ROOT / "artifacts/ratings/calibration-v1-execution.json"
    selection_path = ROOT / "artifacts/ratings/calibration-v1-selection.json"
    if execution_path.exists() or selection_path.exists(): raise ValueError("Do not restart/overwrite an existing calibration; inspect its actual process and retained evidence")
    candidate = ROOT / plan["engine"]; assert digest(candidate) == plan["engine_sha256"]
    frozen_source_manifest(str(ROOT / plan["source_manifest"]), plan["engine_sha256"])
    teacher = read(ROOT / research_text('opponent_manifest'))
    assert digest(ROOT / teacher["executable"]) == plan["opponent_sha256"] == teacher["executable_sha256"]
    screen_path = ROOT / "tests/fixtures/rating-screen-v1.json"; confirm_path = ROOT / "tests/fixtures/rating-confirm-v1.json"
    screen, confirm = read(screen_path), read(confirm_path)
    assert len(screen["openings"]) == 16 and len(confirm["openings"]) == 128
    assert not {r["fen"] for r in screen["openings"]} & {r["fen"] for r in confirm["openings"]}
    for role, path in (("screen", screen_path), ("confirm", confirm_path)):
        audit = read(ROOT / ("artifacts/validation/rating-" + role + "-audit.json"))
        assert audit["passed"] and audit["suite_sha256"] == digest(path)
    execution_path.parent.mkdir(exist_ok=True)
    execution = {"status": "running", "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                 "plan_sha256": digest(plan_path), "runner_sha256": digest(__file__), "match_script_sha256": digest(ROOT / "scripts/match.py"),
                 "screen_suite_sha256": digest(screen_path), "confirmation_suite_sha256": digest(confirm_path), "completed_phases": []}
    write_new(execution_path, execution)

    def run_phase(label, setting, pairs, suite):
        prefix = ROOT / ("artifacts/matches/rating-v1-" + label)
        cmd = [sys.executable, str(ROOT / "scripts/match.py"), "--engine", str(candidate), "--source-manifest", str(ROOT / plan["source_manifest"]),
               "--opponent-uci-elo", str(setting), "--pairs", str(pairs), "--movetime", str(plan["resources"]["seconds_per_move"]),
               "--max-plies", str(plan["resources"]["max_plies"]), "--openings", str(suite), "--output", str(prefix)]
        print(json.dumps({"phase": label, "setting": setting, "requested_games": 2 * pairs}), flush=True)
        with pathlib.Path(str(prefix) + ".txt").open("x", encoding="utf-8") as log:
            subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, check=True)
        report_path = pathlib.Path(str(prefix) + ".json"); report = read(report_path)
        assert len(report["games"]) == 2 * pairs and report["forfeits"] == 0
        assert report["candidate_binary_sha256"] == plan["engine_sha256"] and report["opponent_binary_sha256"] == plan["opponent_sha256"]
        assert report["opponent_options"]["UCI_Elo"] == setting and report["opponent_options"]["UCI_LimitStrength"] is True
        audit = subprocess.run([sys.executable, str(ROOT / "scripts/audit_match.py"), str(prefix)], capture_output=True, text=True, check=True)
        write_new(str(prefix) + ".audit.json", json.loads(audit.stdout))
        execution["completed_phases"].append({"label": label, "setting": setting, "report": str(report_path.relative_to(ROOT)),
                                              "report_sha256": digest(report_path), "games": len(report["games"])})
        execution_path.write_text(json.dumps(execution, indent=2) + "\n")
        print(json.dumps({"phase": label, "complete": True, **{k: report[k] for k in ("wins", "draws", "losses", "unresolved", "seconds")}}), flush=True)
        return report

    try:
        reports = {setting: run_phase("screen-" + str(setting), setting, plan["screen"]["pairs_per_setting"], screen_path)
                   for setting in plan["screen"]["settings"]}
        selected = choose_setting(reports)
        selection = {"selected_setting": selected, "rule": plan["screen"]["selection"], "plan_sha256": digest(plan_path),
                     "screen": [{"setting": s, "score_for_selection": screen_score(r), "games": len(r["games"])} for s, r in reports.items()],
                     "interpretation": "Independent confirmation still required; screening does not assign an Elo."}
        write_new(selection_path, selection); print(json.dumps(selection), flush=True)
        run_phase("confirmation", selected, plan["confirmation"]["pairs"], confirm_path)
        assert sum(p["games"] for p in execution["completed_phases"]) == plan["total_game_budget"]
        execution["status"] = "complete"
    except BaseException as error:
        execution["status"] = "failed"; execution["error"] = repr(error); raise
    finally:
        execution["updated_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        execution_path.write_text(json.dumps(execution, indent=2) + "\n")


if __name__ == "__main__": main()
