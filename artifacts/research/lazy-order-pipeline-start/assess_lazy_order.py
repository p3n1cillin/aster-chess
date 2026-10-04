"""Apply the retained original and amended pre-match optimization gates."""
import json

from analyze_rating import bootstrap, paired_groups
from run_rating import digest, read, write_new
from uci_client import ROOT


def assess():
    plan = read(ROOT / "artifacts/research/lazy-order-plan-v1.json")
    timing = read(ROOT / "artifacts/benchmarks/lazy-order-warm-timing-v1.json")
    gates = {}; evidence = []
    for role in ("candidate", "baseline"):
        assert digest(ROOT / plan[role]) == plan[role + "_sha256"]
    assert timing["plan_sha256"] == digest(ROOT / "artifacts/research/lazy-order-plan-v1.json")
    assert timing["amendment_sha256"] == digest(ROOT / "artifacts/research/lazy-order-plan-amendment-v1.json")
    assert timing["candidate_sha256"] == plan["candidate_sha256"] and timing["baseline_sha256"] == plan["baseline_sha256"]
    gates["timing_at_least_5_percent"] = timing["same_work"] and timing["median_measured_speed_ratio"] >= 1.05
    fixed = read(ROOT / "artifacts/benchmarks/lazy-order-fixed-depth8-v1.json")
    gates["fresh_fixed_work"] = len(fixed["positions"]) == 80 and all(r["same_move"] and r["same_score"] and r["candidate"]["nodes"] == r["opponent"]["nodes"] for r in fixed["positions"])
    traces = read(ROOT / "artifacts/validation/lazy-order-opening-traces.json")
    differential = read(ROOT / "artifacts/validation/lazy-order-differential.json")
    gates["full_trace_and_history_equivalence"] = traces["passed"] and traces["same_full_traces"] == 80 and differential["passed"] and differential["cases"] == 256
    for name, threshold in (("tactics-depth8", 32), ("tactics-5000nodes", 32), ("tactics-quiet-depth8", 32), ("endgames-5000nodes", 13)):
        report = read(ROOT / f"artifacts/tactics/lazy-order-{name}.json")
        assert report["binary_sha256"] == plan["candidate_sha256"]
        gates[name] = report["solved"] >= threshold
    quiet = read(ROOT / "artifacts/tactics/lazy-order-tactics-quiet-5000nodes.json")
    baseline_quiet = read(ROOT / "artifacts/tactics/lazy-order-baseline-tactics-quiet-5000nodes.json")
    fields = ("id", "bestmove", "solved", "depth", "nodes")
    gates["amended_quiet_fixed_nodes"] = quiet["solved"] >= 25 and [[r[k] for k in fields] for r in quiet["positions"]] == [[r[k] for k in fields] for r in baseline_quiet["positions"]]
    profile = [json.loads(line) for line in (ROOT / "artifacts/benchmarks/lazy-order-profile-depth9.json").read_text(encoding="utf-8-sig").splitlines()]
    baseline_profile = [json.loads(line) for line in (ROOT / "artifacts/benchmarks/lazy-order-baseline-profile-depth9.json").read_text(encoding="utf-8-sig").splitlines()]
    exact_profile = all(all(a[k] == b[k] for k in ("fen", "bestmove", "Score", "Depth", "Nodes")) for a, b in zip(profile[:-1], baseline_profile[:-1], strict=True))
    avoided = sum(r["profile"]["deferredCaptureScoring"]["avoided"] for r in profile[:-1])
    before = sum(r["profile"]["staticExchange"]["calls"] for r in baseline_profile[:-1])
    after = sum(r["profile"]["staticExchange"]["calls"] for r in profile[:-1])
    gates["profile_same_work_less_exchange"] = exact_profile and before - after == avoided and avoided > 0
    rules = read(ROOT / "artifacts/validation/lazy-order-rules.json")
    gates["correctness"] = rules["status"] == "passed" and rules["binary_sha256"] == plan["candidate_sha256"] and "49 passed, 0 failed." in (ROOT / "artifacts/validation/lazy-order-engine-tests.txt").read_text(encoding="utf-8-sig")
    matches = []
    for phase in plan["matches"]:
        prefix = ROOT / f"artifacts/matches/lazy-order-vs-0.7.4-{phase['label']}"
        report = read(str(prefix) + ".json"); audit = read(str(prefix) + ".audit.json")
        assert len(report["games"]) == audit["games"] == 2 * phase["pairs"] and audit["status"] == "passed"
        assert report["candidate_binary_sha256"] == plan["candidate_sha256"] and report["opponent_binary_sha256"] == plan["baseline_sha256"]
        assert report["candidate_options"] == report["opponent_options"] == {"Hash": 64, "Threads": 1, "Move Overhead": 0}
        assert report["limit"] == {"seconds_per_move": phase["seconds_per_move"]} and report["max_plies"] == 400
        assert report["opening_suite"]["sha256"] == digest(ROOT / f"tests/fixtures/lazy-order-{phase['label']}-v1.json")
        for role, kind in (("candidate", "candidate"), ("opponent", "baseline")):
            assert report[role + "_source_manifest"]["sha256"] == digest(ROOT / plan[kind + "_source"])
        groups, _, scores = paired_groups(report["games"], phase["pairs"])
        interval = bootstrap(groups, plan["uncertainty"]["bootstrap_samples"], plan["uncertainty"]["seed"])
        score_bounds = [sum(s[i] for s in scores) / len(scores) for i in range(2)]
        bound_gate = .45 if phase["label"] == "30ms" else .40
        gates["match-" + phase["label"]] = report["forfeits"] == report["unresolved"] == 0 and score_bounds[0] >= .5 and interval[0] >= bound_gate
        matches.append({"label": phase["label"], **{k: report[k] for k in ("wins", "draws", "losses", "unresolved", "forfeits")},
                        "games": len(report["games"]), "score_bounds": score_bounds, "primary_95_percent_interval": interval, "families": len(groups)})
        evidence.append({"path": str(prefix.relative_to(ROOT)) + ".json", "sha256": digest(str(prefix) + ".json"),
                         "pgn_sha256": digest(str(prefix) + ".pgn"), "audit_sha256": digest(str(prefix) + ".audit.json")})
    return {"schema": 1, "original_absolute_quiet_gate_passed": quiet["solved"] >= 32,
            "original_gate_failure": "Preserved factual baseline assumption error: both builds25/32 at5000nodes; pre-match amendment requires baseline equivalence.",
            "amended_gates": gates, "failed_gates": [k for k, v in gates.items() if not v],
            "eligible_for_engineering_promotion": all(gates.values()), "matches": matches,
            "median_timing_speed_ratio": timing["median_measured_speed_ratio"], "exchange_calls_before": before,
            "exchange_calls_after": after, "avoided_exchange_calls": avoided,
            "candidate_sha256": plan["candidate_sha256"], "baseline_sha256": plan["baseline_sha256"], "evidence": evidence,
            "plan_sha256": digest(ROOT / "artifacts/research/lazy-order-plan-v1.json"),
            "amendment_sha256": digest(ROOT / "artifacts/research/lazy-order-plan-amendment-v1.json"), "assessor_sha256": digest(__file__),
            "interpretation": "Engineering optimization decision using explicitly amended baseline fact before matches/timing. Not proof of Elo gain or full-strength Stockfish superiority. All results and failures retained; no adaptive retuning."}


if __name__ == "__main__":
    result = assess(); write_new(ROOT / "artifacts/research/lazy-order-assessment-v1.json", result)
    print(json.dumps(result))
