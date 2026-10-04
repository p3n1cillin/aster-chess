"""Apply only the phase ablation's predeclared tactical and paired-game gates."""
import json

from analyze_rating import bootstrap, paired_groups
from run_rating import digest, read
from uci_client import ROOT


def match_summary(label, pairs):
    prefix = ROOT / f"artifacts/matches/phase-{label}"
    report = read(str(prefix) + ".json"); audit = read(str(prefix) + ".audit.json")
    assert audit["status"] == "passed" and audit["games"] == 2*pairs and len(report["games"]) == 2*pairs
    plan = read(ROOT / "artifacts/research/phase-plan-v1.json"); setup = plan["matches"]
    families, _, scores = paired_groups(report["games"], pairs)
    interval = bootstrap(families, setup["bootstrap_samples"], setup["bootstrap_seed"])
    score = sum(s[0] for s in scores) / len(scores) if report["unresolved"] == 0 else None
    return {"games": 2*pairs, "wins": report["wins"], "draws": report["draws"], "losses": report["losses"],
        "unresolved": report["unresolved"], "forfeits": report["forfeits"], "score": score,
        "primary_95_percent_family_interval": interval, "families": len(families),
        "report_sha256": digest(str(prefix) + ".json"), "pgn_sha256": digest(str(prefix) + ".pgn"), "audit_sha256": digest(str(prefix) + ".audit.json")}


def assess():
    plan_path = ROOT / "artifacts/research/phase-plan-v1.json"; plan = read(plan_path)
    preflight = read(ROOT / "artifacts/validation/phase-preflight.json")
    assert preflight["correctness_passed"] and preflight["plan_sha256"] == digest(plan_path)
    results = {label: match_summary(label, 32) for label in ("classical-30ms", "control-30ms")}
    gates = {"correctness": preflight["correctness_passed"], "tactics": preflight["candidate_tactics_passed"],
        "classical_short": results["classical-30ms"]["primary_95_percent_family_interval"][0] > .5,
        "control_short": results["control-30ms"]["score"] is not None and results["control-30ms"]["score"] >= .5
            and results["control-30ms"]["primary_95_percent_family_interval"][0] >= .45,
        "short_zero_unresolved_forfeits": all(r["unresolved"] == r["forfeits"] == 0 for r in results.values())}
    eligible = all(gates.values())
    long_path = ROOT / "artifacts/matches/phase-classical-100ms.json"
    if long_path.exists():
        assert eligible, "Conditional long confirmation ran without qualifying"
        results["classical-100ms"] = match_summary("classical-100ms", 16)
        long = results["classical-100ms"]
        gates["classical_long"] = long["score"] is not None and long["score"] >= .5 and long["primary_95_percent_family_interval"][0] >= .45 and long["unresolved"] == long["forfeits"] == 0
    return {"schema": 1, "plan_sha256": digest(plan_path), "assessor_sha256": digest(__file__),
        "results": results, "gates": gates, "failed_gates": [k for k, passed in gates.items() if not passed],
        "eligible_for_long_confirmation": eligible, "eligible_for_promotion": eligible and gates.get("classical_long", False),
        "interpretation": "Predeclared architecture screen only. No Elo inferred and no Stockfish superiority. Failed tactics or confidence gates keep the neural model experimental; classical default retained."}


if __name__ == "__main__": print(json.dumps(assess()))
