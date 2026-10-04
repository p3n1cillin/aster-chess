"""Exploratory paired/opening-cluster bootstrap analysis of a saved match report."""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import random
import statistics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report")
    parser.add_argument("--bootstrap", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20261003)
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.bootstrap < 100:
        parser.error("Use at least 100 bootstrap samples")
    report = json.loads(pathlib.Path(args.report).read_text(encoding="utf-8"))
    pairs: dict[int, list] = collections.defaultdict(list)
    for game in report["games"]:
        pairs[game["pair"]].append(game)
    clusters: dict[tuple[str, str], list[float]] = collections.defaultdict(list)
    unresolved_pairs = 0
    pair_scores = []
    for pair, games in sorted(pairs.items()):
        if len(games) != 2 or {game["candidate_color"] for game in games} != {"white", "black"} or len({game["opening"] for game in games}) != 1:
            raise ValueError(f"Incomplete or inconsistent color-swapped pair {pair}")
        if len({game.get("starting_fen", "startpos") for game in games}) != 1:
            raise ValueError(f"Pair {pair} has inconsistent FEN history origins")
        if any(game["result"] == "*" for game in games):
            unresolved_pairs += 1; continue
        points = 0.0
        for game in games:
            if game["result"] == "1/2-1/2": points += .5
            elif (game["result"] == "1-0") == (game["candidate_color"] == "white"): points += 1
        pair_scores.append(points / 2)
        cluster = (games[0].get("starting_fen", "startpos"), games[0]["opening"])
        clusters[cluster].append(points / 2)
    if not pair_scores:
        raise ValueError("No resolved pairs")
    rng = random.Random(args.seed)
    groups = list(clusters.values())
    bootstrapped = []
    for _ in range(args.bootstrap):
        selected = [rng.choice(groups) for _ in groups]
        bootstrapped.append(statistics.mean(score for cluster in selected for score in cluster))
    bootstrapped.sort()
    interval = [bootstrapped[int(args.bootstrap * .025)], bootstrapped[min(args.bootstrap - 1, int(args.bootstrap * .975))]]
    result = {"score": statistics.mean(pair_scores), "resolved_pairs": len(pair_scores), "unresolved_pairs": unresolved_pairs,
              "opening_clusters": len(groups), "exploratory_95_percent_interval": interval,
              "bootstrap_samples": args.bootstrap, "seed": args.seed, "pair_scores": pair_scores,
              "interpretation": "Exploratory opening-cluster resampling, not a predeclared final strength test; small cluster counts and repeated openings limit generalization. No Elo is inferred."}
    searches = [search for game in report["games"] for search in game.get("searches", [])]
    if searches:
        result["search_diagnostics"] = {}
        for role in ("candidate", "opponent"):
            moves = [search for search in searches if search["role"] == role]
            depths = [search["depth"] for search in moves if search["depth"] is not None]
            node_counts = [search["nodes"] for search in moves if search["nodes"] is not None]
            result["search_diagnostics"][role] = {"moves": len(moves), "median_completed_depth": statistics.median(depths) if depths else None,
                                                  "total_reported_nodes": sum(node_counts),
                                                  "median_elapsed_seconds": statistics.median(search["elapsed_seconds"] for search in moves)}
    if args.output:
        pathlib.Path(args.output).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("score", "resolved_pairs", "opening_clusters", "exploratory_95_percent_interval")}))


if __name__ == "__main__":
    main()
