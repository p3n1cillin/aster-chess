"""Re-query bounded endgame labels at a larger budget, preserving native scores."""
import argparse
import json
import pathlib
import random
import statistics

import chess
import chess.engine

from generate_endgame_diagnostic import digest, labels
from uci_client import ROOT, engine_command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data")
    parser.add_argument("--suite", required=True)
    parser.add_argument("--nodes", type=int, default=262144)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.nodes < 1: parser.error("Positive node budget required")
    output = pathlib.Path(args.output)
    if output.exists(): parser.error("Preserve previous queries")
    data_hash = digest(args.data)
    rows = [json.loads(line) for line in pathlib.Path(args.data).read_text().splitlines() if line.strip()]
    manifest = json.loads(pathlib.Path(str(args.data) + ".manifest.json").read_text())
    assert manifest["complete"] and manifest["data_sha256"] == data_hash
    fixture = json.loads(pathlib.Path(args.suite).read_text())
    assert fixture["data_sha256"] == data_hash
    mandatory = {position["id"] for position in fixture["positions"]}
    selected = [row for row in rows if row["id"] in mandatory]
    remaining = [row for row in rows if row["id"] not in mandatory]
    rng = random.Random(20261025)
    strata = [("finite_within600", 40), ("finite_outside600", 40), ("mate", 32)]
    for name, count in strata:
        pool = [row for row in remaining if (row["verified"][0]["white_mate"] is not None if name == "mate"
                else row["verified"][0]["white_cp"] is not None and (abs(row["verified"][0]["white_cp"]) <= 600) == (name == "finite_within600"))]
        selected.extend(rng.sample(pool, count))
    assert len(selected) == 128 and len({row["id"] for row in selected}) == 128
    teacher_path = ROOT / manifest["teacher"]["executable"]
    assert digest(teacher_path) == manifest["teacher"]["executable_sha256"]
    results = []
    with chess.engine.SimpleEngine.popen_uci(engine_command(teacher_path), timeout=60) as teacher:
        teacher.configure({"Threads": 1, "Hash": 64})
        for i, row in enumerate(selected):
            board = chess.Board(row["fen"])
            rechecked = labels(teacher, board, args.nodes)
            results.append({"id": row["id"], "game": row["game"], "original": row["verified"], "rechecked": rechecked,
                            "bestmove_agrees": row["verified"][0]["pv"][0] == rechecked[0]["pv"][0]})
            if (i + 1) % 32 == 0: print(json.dumps({"positions": i + 1}), flush=True)
    finite = [entry for entry in results if all(entry[tier][0]["white_cp"] is not None for tier in ("original", "rechecked"))]
    differences = [abs(entry["original"][0]["white_cp"] - entry["rechecked"][0]["white_cp"]) for entry in finite]
    fixture_results = [entry for entry in results if entry["id"] in mandatory]
    report = {"data_sha256": data_hash, "suite_sha256": digest(args.suite), "teacher_sha256": digest(teacher_path),
              "teacher_options": {"Threads": 1, "Hash": 64}, "nodes": args.nodes, "source_sha256": digest(__file__),
              "selection": "All 16 frozen fixture positions plus seeded 40 finite within600, 40 finite outside600 and 32 native-mate rows.",
              "results": results, "summary": {"positions": len(results), "bestmove_agreement": sum(r["bestmove_agrees"] for r in results),
              "finite_pairs": len(finite), "finite_score_change_mae_cp": statistics.mean(differences),
              "mate_class_changes": sum((e["original"][0]["white_mate"] is None) != (e["rechecked"][0]["white_mate"] is None) for e in results),
              "fixture_bestmove_agreement": sum(e["bestmove_agrees"] for e in fixture_results), "fixture_positions": len(fixture_results)},
              "interpretation": "Larger-budget label consistency, not optimality or oracle outcomes. Frozen fixture is not silently changed."}
    assert digest(args.data) == data_hash
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["summary"]))


if __name__ == "__main__": main()
