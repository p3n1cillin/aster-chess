"""Apply the fixed two-control, opening-family decision for the Aster experiment."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import random
import statistics


def control_report(path, expected_pairs, expected_seconds):
    report = json.loads(path.read_text(encoding="utf-8"))
    if report["limit"] != {"seconds_per_move": expected_seconds} or report["pairs_requested"] != expected_pairs:
        raise ValueError("The declared time control or match size changed")
    for role in ["candidate", "opponent"]:
        if report[role + "_options"].get("Threads") != 1 or report[role + "_options"].get("Hash") != 64:
            raise ValueError("The declared engine resources changed")
    pairs = defaultdict(list)
    for game in report["games"]:
        pairs[game["pair"]].append(game)
    if len(pairs) != expected_pairs or len(report["games"]) != 2 * expected_pairs:
        raise ValueError("All declared games must finish")
    families = defaultdict(list)
    scores = []
    unresolved = 0
    for games in pairs.values():
        if len(games) != 2 or {g["candidate_color"] for g in games} != {"white", "black"}:
            raise ValueError("Broken color-swapped pair")
        if len({(g["opening"], g.get("starting_fen", "startpos")) for g in games}) != 1:
            raise ValueError("Pair opening/history mismatch")
        if any(g["result"] == "*" for g in games):
            unresolved += 1
            continue
        points = 0
        for game in games:
            if game["result"] not in {"1/2-1/2", "1-0", "0-1"}:
                raise ValueError("Unknown game result")
            if game["result"] == "1/2-1/2":
                points += 0.5
            elif (game["result"] == "1-0") == (game["candidate_color"] == "white"):
                points += 1
        score = points / 2
        scores.append(score)
        family = (games[0].get("starting_fen", "startpos"), " ".join(games[0]["opening"].split()[:4]))
        families[family].append(score)
    if not scores:
        return {"games": len(report["games"]), "pairs": len(pairs), "resolved_pairs": 0,
                "unresolved_pairs": unresolved, "score": None,
                "passes_strength_gate": False, "reason": "No resolved pairs"}
    groups = list(families.values())
    rng = random.Random(20261019)
    samples = []
    for _ in range(20000):
        selected = [rng.choice(groups) for _ in groups]
        samples.append(statistics.mean(score for family in selected for score in family))
    samples.sort()
    interval = [samples[500], samples[19499]]
    return {"report_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "candidate_sha256": report["candidate_binary_sha256"],
            "baseline_sha256": report["opponent_binary_sha256"],
            "opening_suite_sha256": report["opening_suite"]["sha256"],
            "games": len(report["games"]), "pairs": len(pairs), "resolved_pairs": len(scores),
            "unresolved_pairs": unresolved, "forfeits": report["forfeits"],
            "wins": report["wins"], "draws": report["draws"], "losses": report["losses"],
            "score": statistics.mean(scores), "families": len(families),
            "opening_family_95_percent_interval": interval,
            "passes_strength_gate": unresolved == 0 and report["forfeits"] == 0 and interval[0] > 0.5}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--short", required=True)
    parser.add_argument("--long", required=True)
    parser.add_argument("--activity", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise ValueError("Preserve the previous decision")
    controls = {"30ms": control_report(Path(args.short), 64, 0.03),
                "100ms": control_report(Path(args.long), 32, 0.1)}
    activity = json.loads(Path(args.activity).read_text(encoding="utf-8"))
    for control in controls.values():
        if control["resolved_pairs"] and (control["candidate_sha256"], control["baseline_sha256"]) != (activity["candidate_sha256"], activity["baseline_sha256"]):
            raise ValueError("The tested binaries changed between gates")
    tactics = []
    root = Path(__file__).resolve().parents[1]
    for name in ["tactics-v1", "tactics-quiet-v1", "endgames-v1"]:
        baseline = json.loads((root / f"artifacts/tactics/aster-disagreement-control-{name}.json").read_text(encoding="utf-8"))
        candidate = json.loads((root / f"artifacts/tactics/aster-disagreement-candidate-{name}.json").read_text(encoding="utf-8"))
        if baseline["limit"] != candidate["limit"] or baseline["total"] != candidate["total"]:
            raise ValueError("Tactical test budgets differ")
        tactics.append({"suite": name, "baseline": baseline["solved"],
                        "candidate": candidate["solved"], "passed": candidate["solved"] >= baseline["solved"],
                        "changed_positions": [{"id": b["id"], "baseline": b["bestmove"], "candidate": c["bestmove"]}
                                              for b, c in zip(baseline["positions"], candidate["positions"], strict=True)
                                              if b["bestmove"] != c["bestmove"]]})
    eligible = activity["passed"] and all(t["passed"] for t in tactics) and all(c["passes_strength_gate"] for c in controls.values())
    report = {"eligible_for_confirmation": eligible, "production_enabled": False,
              "controls": controls, "tactics": tactics,
              "activity_passed": activity["passed"], "bootstrap_samples": 20000, "seed": 20261019,
              "cluster": "Full starting FEN and first four opening plies; whole families resampled within each control",
              "interpretation": "Promotion needs correctness/audits and both strict lower bounds above 50%. An eligible candidate still needs separately declared reference confirmation. No parameter tuning, absolute Elo or world-first claim."}
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"eligible_for_confirmation": eligible, "controls": controls}))


if __name__ == "__main__":
    main()
