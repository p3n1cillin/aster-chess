"""Apply the frozen strength gates to the independent IIR candidate."""
from research_reference import research_text
import json

from analyze_rating import bootstrap, paired_groups
from run_rating import digest, read, write_new
from uci_client import ROOT


def assess():
    path = ROOT / "artifacts/research/iir-plan-v2.json"; plan = read(path); gates = {}; evidence = []
    for role in ("candidate","baseline"): assert digest(ROOT / plan[role]) == plan[role + "_sha256"]
    rules = read(ROOT / "artifacts/validation/iir-rules.json")
    assert rules["binary_sha256"] == plan["candidate_sha256"]
    gates["correctness"] = rules["status"] == "passed" and "52 passed, 0 failed." in (ROOT / "artifacts/validation/iir-engine-tests.txt").read_text(encoding="utf-8-sig")
    cases = read(ROOT / "artifacts/validation/iir-differential.json")
    assert cases["candidate_sha256"] == plan["candidate_sha256"] and cases["baseline_sha256"] == plan["baseline_sha256"]
    gates["history_and_limits"] = cases["passed"] and cases["cases"] == 256
    fixed = read(ROOT / "artifacts/benchmarks/iir-fixed-depth8-v1.json")
    assert [e["sha256"] for e in fixed["engines"]] == [plan[role + "_sha256"] for role in ("candidate","baseline")]
    assert fixed["suite_sha256"] == digest(ROOT / "tests/fixtures/iir-behavior-v1.json")
    gates["opening_behavior"] = len(fixed["positions"]) == 64
    for name,threshold in plan["tactics"].items():
        report = read(ROOT / f"artifacts/tactics/iir-{name}.json")
        assert report["binary_sha256"] == plan["candidate_sha256"]
        gates[name] = report["solved"] >= threshold
    profile = [json.loads(line) for line in (ROOT / "artifacts/benchmarks/iir-profile-depth9.json").read_text(encoding="utf-8-sig").splitlines()]
    triggers = sum(row["profile"]["internalIterativeReduction"]["reducedNodes"] for row in profile[:-1])
    gates["profile_trigger"] = triggers > 0
    matches = []
    for phase in plan["matches"]:
        report_path = ROOT / f"artifacts/matches/iir-vs-0.7.6-{phase['label']}.json"
        report = read(report_path); audit = read(report_path.with_suffix(".audit.json"))
        assert len(report["games"]) == audit["games"] == 2*phase["pairs"] and audit["status"] == "passed"
        assert report["candidate_binary_sha256"] == plan["candidate_sha256"] and report["opponent_binary_sha256"] == plan["baseline_sha256"]
        assert report["candidate_options"] == report["opponent_options"] == {"Hash":64,"Threads":1,"Move Overhead":0}
        assert report["limit"] == {"seconds_per_move":phase["seconds_per_move"]} and report["max_plies"] == 400
        assert report["runner_sha256"] == digest(ROOT / "scripts/match.py")
        assert report["opening_suite"]["sha256"] == digest(ROOT / f"tests/fixtures/iir-{phase['label']}-v1.json")
        for role,kind in (("candidate","candidate"),("opponent","baseline")):
            assert report[role + "_source_manifest"]["sha256"] == digest(ROOT / plan[kind + "_source"])
        for key in ("wins","draws","losses","unresolved"): assert report[key] == audit[key]
        groups,_,scores = paired_groups(report["games"],phase["pairs"])
        interval = bootstrap(groups,plan["uncertainty"]["bootstrap_samples"],plan["uncertainty"]["seed"])
        bounds = [sum(s[i] for s in scores)/len(scores) for i in range(2)]
        confidence = interval[0] > phase["family_lower_strictly_above"] if "family_lower_strictly_above" in phase else interval[0] >= phase["minimum_family_lower"]
        gates["match-" + phase["label"]] = report["forfeits"] == report["unresolved"] == 0 and bounds[0] >= phase["minimum_score"] and confidence
        matches.append({"label":phase["label"],"games":len(report["games"]),**{k:report[k] for k in ("wins","draws","losses","unresolved","forfeits")},
            "score_bounds":bounds,"primary_95_percent_interval":interval,"families":len(groups)})
        evidence.append({"path":report_path.relative_to(ROOT).as_posix(),"sha256":digest(report_path),"pgn_sha256":digest(report_path.with_suffix(".pgn")),"audit_sha256":digest(report_path.with_suffix(".audit.json"))})
    return {"schema":1,"gates":gates,"failed_gates":[k for k,v in gates.items() if not v],"eligible_for_engineering_promotion":all(gates.values()),
        "matches":matches,"profile_reduced_nodes":triggers,"candidate_sha256":plan["candidate_sha256"],"baseline_sha256":plan["baseline_sha256"],
        "evidence":evidence,"plan_sha256":digest(path),"assessor_sha256":digest(__file__),
        "interpretation":research_text('assess_iir.interpretation')}


if __name__ == "__main__":
    result = assess(); write_new(ROOT / "artifacts/research/iir-assessment-v1.json",result); print(json.dumps(result))
