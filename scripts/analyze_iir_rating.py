"""Apply the predeclared local rating model to conditional IIR confirmation."""
from research_reference import research_text
import datetime
import json

from analyze_rating import bootstrap, paired_groups, rating_summary
from run_rating import digest, read, write_new
from uci_client import ROOT


def main():
    plan_path = ROOT / "artifacts/research/iir-plan-v2.json"; plan = read(plan_path)
    state = read(ROOT / "artifacts/research/iir-execution-v1.json")
    assert state["status"] == "complete" and state["eligible_for_engineering_promotion"]
    assert state["plan_sha256"] == digest(plan_path)
    assert [p["label"] for p in state["phases"]] == ["vs-0.7.6-30ms", "vs-0.7.6-100ms", "rating-vs-sf19-2300"]
    evidence = []; total = 0
    for phase in state["phases"]:
        path = ROOT / phase["report"]; report = read(path); audit = read(path.with_suffix(".audit.json"))
        assert digest(path) == phase["report_sha256"]
        assert len(report["games"]) == phase["games"] == audit["games"] and audit["status"] == "passed" and report["forfeits"] == 0
        assert report["candidate_binary_sha256"] == plan["candidate_sha256"] == digest(ROOT / plan["candidate"])
        assert report["candidate_source_manifest"]["sha256"] == digest(ROOT / plan["candidate_source"])
        assert report["runner_sha256"] == state["match_script_sha256"]
        for key in ("wins", "draws", "losses", "unresolved"): assert report[key] == audit[key]
        total += len(report["games"])
        evidence.append({"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path),
                         "pgn_sha256": digest(path.with_suffix(".pgn")), "audit_sha256": digest(path.with_suffix(".audit.json"))})
    assert total == plan["maximum_game_budget"] == 896
    confirmation = report; expected = plan["conditional_rating"]
    assert len(confirmation["games"]) == 2 * expected["pairs"] == 256
    assert confirmation["opponent_binary_sha256"] == expected["opponent_sha256"] == digest(confirmation["opponent"])
    assert confirmation["opponent_options"] == {"Hash":64,"Threads":1,"Move Overhead":0,"UCI_LimitStrength":True,"UCI_Elo":2300}
    assert confirmation["candidate_options"] == {"Hash":64,"Threads":1,"Move Overhead":0}
    assert confirmation["candidate_option_defaults"]["EvalFile"] == "<classical>"
    assert confirmation["limit"] == {"seconds_per_move":.03} and confirmation["max_plies"] == 400
    suite = ROOT / "tests/fixtures/iir-rating-v1.json"
    assert confirmation["opening_suite"]["sha256"] == digest(suite)
    assert read(ROOT / "artifacts/validation/iir-rating-audit.json")["suite_sha256"] == digest(suite)
    fixtures = read(suite)["openings"]
    for game in confirmation["games"]:
        fixture = fixtures[game["pair"] - 1]
        assert game["opening"] == fixture["moves"] and game["initial_fen"] == fixture["fen"]
    families, pairs, scores = paired_groups(confirmation["games"], 128)
    uncertainty = plan["uncertainty"]
    primary = bootstrap(families, uncertainty["bootstrap_samples"], uncertainty["seed"])
    secondary = bootstrap(pairs, uncertainty["bootstrap_samples"], uncertainty["seed"])
    result = rating_summary(2300, scores, primary, confirmation["unresolved"])
    result.update({"schema":1,"timestamp_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   "local_scale":"SF19 UCI_Elo-setting equivalent at 30 ms/move, one thread, 64 MiB hash",
                   "public_elo":None,"public_rating_status":"unestablished","engine":plan["candidate"],
                   "engine_sha256":plan["candidate_sha256"],"engine_name":confirmation["candidate_name"],
                   "source_manifest":plan["candidate_source"],"source_manifest_sha256":digest(ROOT / plan["candidate_source"]),
                   "all_games_audited":total,"confirmation_games":256,"confirmation_pairs":128,"opening_families":len(families),
                   **{k:confirmation[k] for k in ("wins","draws","losses","unresolved")},
                   "secondary_95_percent_score_interval":secondary,"bootstrap_samples":uncertainty["bootstrap_samples"],"seed":uncertainty["seed"],
                   "platform":confirmation["platform"],"hardware":confirmation["hardware"],"resources":plan["resources"],
                   "opponent_release":confirmation[research_text('legacy_release_key')],"opponent_options":confirmation["opponent_options"],
                   "opponent_option_defaults":confirmation["opponent_option_defaults"],"evidence":evidence,
                   "plan_sha256":digest(plan_path),"analyzer_sha256":digest(__file__),
                   "interpretation":research_text('analyze_iir_rating.interpretation')})
    write_new(ROOT / "artifacts/ratings/session-20261004-iir-confirmation.json", result)
    print(json.dumps({k:result[k] for k in ("status","numeric_local_rating","primary_95_percent_local_interval","failed_numeric_gates")}))


if __name__ == "__main__": main()
