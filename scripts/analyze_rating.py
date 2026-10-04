"""Analyze the frozen calibration on its explicitly local reference-setting scale."""
import collections
import datetime
import json
import math
import pathlib
import random

from match import frozen_source_manifest
from run_rating import choose_setting, digest, read, write_new
from uci_client import ROOT


def equivalent(setting, score):
    if not 0 <= score <= 1:
        raise ValueError("Score outside [0, 1]")
    if score == 0: return -math.inf
    if score == 1: return math.inf
    return setting + 400 * math.log10(score / (1 - score))


def game_bounds(game):
    result = game["result"]
    if game["candidate_color"] not in ("white", "black"):
        raise ValueError("Unknown candidate color")
    if result == "*": return 0., 1.
    if result == "1/2-1/2": return .5, .5
    if result not in ("1-0", "0-1"): raise ValueError("Unknown result")
    score = float((result == "1-0") == (game["candidate_color"] == "white"))
    return score, score


def paired_groups(games, expected_pairs):
    pairs = collections.defaultdict(list)
    for game in games: pairs[game["pair"]].append(game)
    if set(pairs) != set(range(1, expected_pairs + 1)):
        raise ValueError("Missing or extra opening pairs")
    families = collections.defaultdict(list); scores = []; seen = set()
    for pair, rows in sorted(pairs.items()):
        if len(rows) != 2 or {r["candidate_color"] for r in rows} != {"white", "black"}:
            raise ValueError(f"Incomplete color-swapped pair {pair}")
        keys = {(r["starting_fen"], r["opening"], r["initial_fen"]) for r in rows}
        if len(keys) != 1: raise ValueError("Inconsistent pair history")
        key = next(iter(keys))
        # Position uniqueness matters even when histories differ.
        canonical = " ".join(key[2].split()[:4])
        if canonical in seen: raise ValueError("Repeated opening position")
        seen.add(canonical)
        moves = key[1].split()
        if len(moves) < 4: raise ValueError("Too few plies for declared opening family")
        bounds = [game_bounds(r) for r in rows]
        score = tuple(sum(b[i] for b in bounds) / 2 for i in range(2))
        scores.append(score); families[tuple(moves[:4])].append(score)
    return list(families.values()), [[s] for s in scores], scores


def bootstrap(groups, samples, seed):
    """Resample whole groups; all pairs in each selected family keep their weight."""
    if not groups or any(not g for g in groups) or samples < 100:
        raise ValueError("Nonempty groups and at least 100 samples required")
    rng = random.Random(seed)
    totals = [(sum(s[0] for s in g), sum(s[1] for s in g), len(g)) for g in groups]
    lower = []; upper = []
    for _ in range(samples):
        lo = hi = count = 0
        for _ in groups:
            a, b, n = rng.choice(totals); lo += a; hi += b; count += n
        lower.append(lo / count); upper.append(hi / count)
    lower.sort(); upper.sort()
    return [lower[int(samples * .025)], upper[min(samples - 1, int(samples * .975))]]


def rating_summary(setting, scores, primary, unresolved):
    low = sum(s[0] for s in scores) / len(scores)
    high = sum(s[1] for s in scores) / len(scores)
    point = equivalent(setting, low) if unresolved == 0 else None
    interval = [equivalent(setting, p) for p in primary]
    reasons = []
    if unresolved: reasons.append("Unresolved confirmation games")
    if not all(math.isfinite(v) for v in interval): reasons.append("Unbounded primary interval")
    elif interval[1] - interval[0] > 200: reasons.append("Primary interval wider than 200 local units")
    if point is not None and (not math.isfinite(point) or not 1320 <= point <= 3190):
        reasons.append("Point outside supported reference range")
    if not all(1320 <= v <= 3190 for v in interval): reasons.append("Primary interval outside supported reference range")
    return {"status": "provisional local estimate" if not reasons else "unestablished",
            "numeric_local_rating": point if not reasons else None,
            "score_bounds": [low, high], "score": low if not unresolved else None,
            "primary_95_percent_score_interval": primary,
            "primary_95_percent_local_interval": [v if math.isfinite(v) else None for v in interval],
            "unbounded_lower": interval[0] == -math.inf, "unbounded_upper": interval[1] == math.inf,
            "failed_numeric_gates": reasons}


def require(condition, message):
    if not condition: raise ValueError(message)


def main():
    plan_path = ROOT / "artifacts/research/rating-plan-v1.json"; plan = read(plan_path)
    execution = read(ROOT / "artifacts/ratings/calibration-v1-execution.json")
    selection = read(ROOT / "artifacts/ratings/calibration-v1-selection.json")
    require(execution["status"] == "complete", "Calibration has not completed")
    require(execution["plan_sha256"] == selection["plan_sha256"] == digest(plan_path), "Plan changed")
    start = ROOT / "artifacts/research/rating-pipeline-start"
    require(execution["runner_sha256"] == digest(start / "run_rating.py"), "Runner provenance mismatch")
    require(execution["match_script_sha256"] == digest(start / "match.py"), "Match provenance mismatch")
    frozen_source_manifest(str(ROOT / plan["source_manifest"]), plan["engine_sha256"])
    require(digest(ROOT / plan["engine"]) == plan["engine_sha256"], "Candidate changed")
    suites = {role: read(ROOT / f"tests/fixtures/rating-{role}-v1.json") for role in ("screen", "confirm")}
    require(execution["screen_suite_sha256"] == digest(ROOT / "tests/fixtures/rating-screen-v1.json"), "Screen suite changed")
    require(execution["confirmation_suite_sha256"] == digest(ROOT / "tests/fixtures/rating-confirm-v1.json"), "Confirmation suite changed")
    require(not {r["fen"] for r in suites["screen"]["openings"]} & {r["fen"] for r in suites["confirm"]["openings"]}, "Screen/confirmation overlap")
    for role in ("screen", "confirm"):
        audit = read(ROOT / f"artifacts/validation/rating-{role}-audit.json")
        require(audit["passed"] and audit["suite_sha256"] == digest(ROOT / f"tests/fixtures/rating-{role}-v1.json"), "Opening audit mismatch")
    labels = [f"screen-{s}" for s in plan["screen"]["settings"]] + ["confirmation"]
    require([p["label"] for p in execution["completed_phases"]] == labels, "Incomplete execution phases")
    reports = {}; evidence = []
    for phase in execution["completed_phases"]:
        path = ROOT / phase["report"]; report = read(path); audit = read(path.with_suffix(".audit.json"))
        require(digest(path) == phase["report_sha256"], "Report changed")
        count = plan["confirmation"]["games"] if phase["label"] == "confirmation" else 2 * plan["screen"]["pairs_per_setting"]
        require(len(report["games"]) == count == phase["games"] == audit["games"], "Missing games")
        require(audit["status"] == "passed" and report["forfeits"] == 0, "Failed game audit or forfeit")
        for key in ("wins", "draws", "losses", "unresolved"): require(report[key] == audit[key], "Audit count mismatch")
        require(report["candidate_binary_sha256"] == plan["engine_sha256"], "Different candidate")
        require(report["opponent_binary_sha256"] == plan["opponent_sha256"] == digest(report["opponent"]), "Different opponent")
        require(report["runner_sha256"] == execution["match_script_sha256"], "Different match script")
        require(report["candidate_options"] == {"Hash": 64, "Threads": 1, "Move Overhead": 0}, "Candidate options changed")
        require(report["candidate_option_defaults"]["EvalFile"] == "<classical>", "Unexpected candidate evaluation")
        require(report["opponent_options"] == {"Hash": 64, "Threads": 1, "Move Overhead": 0, "UCI_LimitStrength": True, "UCI_Elo": phase["setting"]}, "Opponent options changed")
        require(report["limit"] == {"seconds_per_move": plan["resources"]["seconds_per_move"]} and report["max_plies"] == plan["resources"]["max_plies"], "Control changed")
        require(digest(report["candidate_source_manifest"]["path"]) == report["candidate_source_manifest"]["sha256"] == digest(ROOT / plan["source_manifest"]), "Source lineage mismatch")
        role = "confirm" if phase["label"] == "confirmation" else "screen"
        require(report["opening_suite"]["sha256"] == digest(ROOT / f"tests/fixtures/rating-{role}-v1.json"), "Different openings")
        paired_groups(report["games"], count // 2)
        for game in report["games"]:
            fixture = suites[role]["openings"][game["pair"] - 1]
            require(game["opening"] == fixture["moves"] and game["initial_fen"] == fixture["fen"], "Game disagrees with frozen fixture")
        reports[phase["label"]] = report
        evidence.append({"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path),
                         "pgn_sha256": digest(path.with_suffix(".pgn")), "audit_sha256": digest(path.with_suffix(".audit.json"))})
    require(sum(len(r["games"]) for r in reports.values()) == plan["total_game_budget"] == 416, "Wrong total budget")
    selected = choose_setting({s: reports[f"screen-{s}"] for s in plan["screen"]["settings"]})
    require(selected == selection["selected_setting"] == reports["confirmation"]["opponent_options"]["UCI_Elo"], "Selection rule not followed")
    confirmation = reports["confirmation"]
    families, pairs, scores = paired_groups(confirmation["games"], plan["confirmation"]["pairs"])
    uncertainty = plan["uncertainty"]
    primary = bootstrap(families, uncertainty["bootstrap_samples"], uncertainty["seed"])
    secondary = bootstrap(pairs, uncertainty["bootstrap_samples"], uncertainty["seed"])
    result = rating_summary(selected, scores, primary, confirmation["unresolved"])
    result.update({"schema": 1, "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   "local_scale": plan["local_scale"], "public_elo": None, "public_rating_status": "unestablished",
                   "engine": plan["engine"], "engine_name": confirmation["candidate_name"], "engine_sha256": plan["engine_sha256"],
                   "source_manifest": plan["source_manifest"], "source_manifest_sha256": digest(ROOT / plan["source_manifest"]),
                   "selected_reference_setting": selected, "confirmation_games": 256, "confirmation_pairs": 128,
                   "opening_families": len(families), "wins": confirmation["wins"], "draws": confirmation["draws"],
                   "losses": confirmation["losses"], "unresolved": confirmation["unresolved"], "all_games_audited": 416,
                   "secondary_95_percent_score_interval": secondary,
                   "secondary_95_percent_local_interval": [v if math.isfinite(v := equivalent(selected, p)) else None for p in secondary],
                   "bootstrap_samples": uncertainty["bootstrap_samples"], "seed": uncertainty["seed"],
                   "bootstrap_implementation": "Each analysis starts a separate RNG with declared seed. Resample families/pairs, weighting all included pairs equally. Endpoints use sorted indices floor(B*.025), floor(B*.975).",
                   "platform": confirmation["platform"], "hardware": confirmation["hardware"], "resources": plan["resources"],
                   "opponent_release": confirmation["stockfish_release"], "opponent_options": confirmation["opponent_options"],
                   "opponent_option_defaults": confirmation["opponent_option_defaults"], "candidate_options": confirmation["candidate_options"],
                   "candidate_option_defaults": confirmation["candidate_option_defaults"],
                   "plan_sha256": digest(plan_path), "analyzer_sha256": digest(__file__), "evidence": evidence,
                   "interpretation": plan["scope"] + " Family bootstrap addresses opening dependence, not opponent-dial calibration error or generalization to other controls. Experimental proof/conversion scoring and production 0.6 are not rated by this result. Goal of surpassing full-strength Stockfish remains unachieved."})
    output = ROOT / "artifacts/ratings/session-20261004-calibration-v1.json"
    write_new(output, result)
    print(json.dumps({k: result[k] for k in ("status", "numeric_local_rating", "primary_95_percent_local_interval", "score", "wins", "draws", "losses", "opening_families", "failed_numeric_gates")}))


if __name__ == "__main__": main()
