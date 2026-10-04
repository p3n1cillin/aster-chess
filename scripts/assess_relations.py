"""Apply the frozen relations tactical and paired-game gates."""
import json

from analyze_rating import bootstrap, paired_groups
from run_rating import digest, read
from uci_client import ROOT
from relations_plan import load_plan


def match_summary(label,pairs):
    prefix = ROOT / f"artifacts/matches/relations-{label}"
    report = read(str(prefix)+".json"); audit = read(str(prefix)+".audit.json")
    assert audit["status"] == "passed" and audit["games"] == 2*pairs == len(report["games"])
    setup = read(ROOT / "artifacts/research/relations-plan-v1.json")["matches"]
    families,_,scores = paired_groups(report["games"],pairs)
    interval = bootstrap(families,setup["bootstrap_samples"],setup["bootstrap_seed"])
    return {"games":2*pairs,"wins":report["wins"],"draws":report["draws"],"losses":report["losses"],
        "unresolved":report["unresolved"],"forfeits":report["forfeits"],"score":sum(s[0] for s in scores)/len(scores) if report["unresolved"] == 0 else None,
        "primary_95_percent_family_interval":interval,"families":len(families),
        "report_sha256":digest(str(prefix)+".json"),"pgn_sha256":digest(str(prefix)+".pgn"),"audit_sha256":digest(str(prefix)+".audit.json")}


def assess():
    plan_path = ROOT / "artifacts/research/relations-plan-v1.json"; plan = load_plan()
    preflight = read(ROOT / "artifacts/validation/relations-preflight.json")
    assert preflight["correctness_passed"] and preflight["plan_sha256"] == digest(plan_path)
    results = {label:match_summary(label,plan["matches"]["short_pairs_each"]) for label in ("classical-30ms","control-30ms")}
    gates = {"correctness":True,"tactics":preflight["candidate_tactics_passed"],
        "classical_short":results["classical-30ms"]["primary_95_percent_family_interval"][0] > .5,
        "control_short":results["control-30ms"]["score"] is not None and results["control-30ms"]["score"] >= .5 and results["control-30ms"]["primary_95_percent_family_interval"][0] >= .45,
        "short_zero_unresolved_forfeits":all(r["unresolved"] == r["forfeits"] == 0 for r in results.values())}
    eligible = all(gates.values())
    if (ROOT / "artifacts/matches/relations-classical-100ms.json").exists():
        assert eligible,"Long confirmation ran without qualifying"
        long = match_summary("classical-100ms",plan["matches"]["conditional_long_pairs"]); results["classical-100ms"] = long
        gates["classical_long"] = long["score"] is not None and long["score"] >= .5 and long["primary_95_percent_family_interval"][0] >= .45 and long["unresolved"] == long["forfeits"] == 0
    return {"schema":1,"plan_sha256":digest(plan_path),"assessor_sha256":digest(__file__),"results":results,"gates":gates,
        "failed_gates":[k for k,passed in gates.items() if not passed],"eligible_for_long_confirmation":eligible,
        "eligible_for_promotion":eligible and gates.get("classical_long",False),
        "interpretation":"Predeclared geometric relation feature ablation. No Elo or Stockfish superiority inferred; any failed gate keeps the candidate experimental."}


if __name__ == "__main__": print(json.dumps(assess()))
