"""Apply the declared evasion optimization gates without changing thresholds."""
import json

from analyze_rating import bootstrap, paired_groups
from run_rating import digest, read, write_new
from uci_client import ROOT


def assess():
    plan_path = ROOT / "artifacts/research/q-evasion-plan-v1.json"; plan = read(plan_path)
    timing = read(ROOT / "artifacts/benchmarks/q-evasion-warm-timing-v1.json")
    gates = {}; evidence = []
    for role in ("candidate", "baseline"): assert digest(ROOT / plan[role]) == plan[role + "_sha256"]
    assert timing["plan_sha256"] == digest(plan_path)
    assert timing["candidate_sha256"] == plan["candidate_sha256"] and timing["baseline_sha256"] == plan["baseline_sha256"]
    gates["warm_timing"] = timing["same_work"] and timing["median_measured_speed_ratio"] >= plan["timing"]["minimum_median_speed_ratio"]
    fixed = read(ROOT / "artifacts/benchmarks/q-evasion-fixed-depth8-v1.json")
    gates["fixed_work"] = len(fixed["positions"]) == 160 and all(r["same_move"] and r["same_score"] and r["candidate"]["nodes"] == r["opponent"]["nodes"] for r in fixed["positions"])
    traces = read(ROOT / "artifacts/validation/q-evasion-opening-traces.json")
    differential = read(ROOT / "artifacts/validation/q-evasion-differential.json")
    gates["full_traces"] = traces["passed"] and traces["same_full_traces"] == 160 and differential["passed"] and differential["cases"] == 256
    for name, threshold in (("tactics-depth8", 32), ("tactics-5000nodes", 32), ("tactics-quiet-depth8", 32), ("tactics-quiet-5000nodes", 25), ("endgames-5000nodes", 13)):
        report = read(ROOT / f"artifacts/tactics/q-evasion-{name}.json")
        assert report["binary_sha256"] == plan["candidate_sha256"]
        gates[name] = report["solved"] >= threshold
    quiet = read(ROOT / "artifacts/tactics/q-evasion-tactics-quiet-5000nodes.json")
    baseline_quiet = read(ROOT / "artifacts/tactics/lazy-order-baseline-tactics-quiet-5000nodes.json")
    assert baseline_quiet["binary_sha256"] == plan["baseline_sha256"]
    fields = ("id", "bestmove", "solved", "depth", "nodes")
    gates["quiet_fixed_node_equivalence"] = [[r[k] for k in fields] for r in quiet["positions"]] == [[r[k] for k in fields] for r in baseline_quiet["positions"]]
    profile = [json.loads(line) for line in (ROOT / "artifacts/benchmarks/q-evasion-profile-depth9.json").read_text(encoding="utf-8-sig").splitlines()]
    baseline_profile = [json.loads(line) for line in (ROOT / "artifacts/benchmarks/lazy-order-baseline-profile-depth9.json").read_text(encoding="utf-8-sig").splitlines()]
    exact = all(all(a[k] == b[k] for k in ("fen", "bestmove", "Score", "Depth", "Nodes")) for a, b in zip(profile[:-1], baseline_profile[:-1], strict=True))
    before = sum(r["profile"]["legalMoveExistence"]["calls"] for r in baseline_profile[:-1])
    after = sum(r["profile"]["legalMoveExistence"]["calls"] for r in profile[:-1])
    gates["profile"] = exact and before > after
    rules = read(ROOT / "artifacts/validation/q-evasion-rules.json")
    gates["correctness"] = rules["status"] == "passed" and rules["binary_sha256"] == plan["candidate_sha256"] and "51 passed, 0 failed." in (ROOT / "artifacts/validation/q-evasion-engine-tests.txt").read_text(encoding="utf-8-sig")
    matches = []
    for phase in plan["matches"]:
        prefix = ROOT / f"artifacts/matches/q-evasion-vs-0.7.4-{phase['label']}"
        report = read(str(prefix) + ".json"); audit = read(str(prefix) + ".audit.json")
        assert len(report["games"]) == audit["games"] == 2 * phase["pairs"] and audit["status"] == "passed"
        assert report["candidate_binary_sha256"] == plan["candidate_sha256"] and report["opponent_binary_sha256"] == plan["baseline_sha256"]
        assert report["candidate_options"] == report["opponent_options"] == {"Hash": 64, "Threads": 1, "Move Overhead": 0}
        assert report["limit"] == {"seconds_per_move": phase["seconds_per_move"]} and report["max_plies"] == 400
        assert report["opening_suite"]["sha256"] == digest(ROOT / f"tests/fixtures/q-evasion-{phase['label']}-v1.json")
        assert report["runner_sha256"] == digest(ROOT / "scripts/match.py")
        for role, kind in (("candidate", "candidate"), ("opponent", "baseline")):
            assert report[role + "_source_manifest"]["sha256"] == digest(ROOT / plan[kind + "_source"])
        for key in ("wins", "draws", "losses", "unresolved"): assert report[key] == audit[key]
        groups, _, scores = paired_groups(report["games"], phase["pairs"])
        interval = bootstrap(groups, plan["uncertainty"]["bootstrap_samples"], plan["uncertainty"]["seed"])
        bounds = [sum(s[i] for s in scores) / len(scores) for i in range(2)]
        gates["match-" + phase["label"]] = report["forfeits"] == report["unresolved"] == 0 and bounds[0] >= .5 and interval[0] >= phase["minimum_family_lower"]
        matches.append({"label": phase["label"], **{k: report[k] for k in ("wins", "draws", "losses", "unresolved", "forfeits")},
                        "games": len(report["games"]), "score_bounds": bounds, "primary_95_percent_interval": interval, "families": len(groups)})
        evidence.append({"path": str(prefix.relative_to(ROOT)) + ".json", "sha256": digest(str(prefix) + ".json"),
                         "pgn_sha256": digest(str(prefix) + ".pgn"), "audit_sha256": digest(str(prefix) + ".audit.json")})
    return {"schema": 1, "gates": gates, "failed_gates": [k for k, v in gates.items() if not v],
            "eligible_for_engineering_promotion": all(gates.values()), "matches": matches,
            "median_timing_speed_ratio": timing["median_measured_speed_ratio"], "legal_existence_calls_before": before,
            "legal_existence_calls_after": after, "avoided_legal_existence_calls": before - after,
            "candidate_sha256": plan["candidate_sha256"], "baseline_sha256": plan["baseline_sha256"], "evidence": evidence,
            "plan_sha256": digest(plan_path), "assessor_sha256": digest(__file__),
            "interpretation": "Engineering optimization qualification under declared independent correctness, same-work, speed and equal-time regression gates. Not proof of Elo gain or full-strength Stockfish superiority."}


if __name__ == "__main__":
    result = assess(); write_new(ROOT / "artifacts/research/q-evasion-assessment-v1.json", result)
    print(json.dumps(result))
