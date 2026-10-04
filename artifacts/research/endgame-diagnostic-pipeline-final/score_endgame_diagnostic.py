"""Freeze fresh finite-score endgame tactics, then measure unchanged evaluators."""
import argparse
import contextlib
import json
import pathlib
import statistics

import chess

from generate_endgame_diagnostic import digest
from match import frozen_source_manifest
from uci_client import UciClient


def errors(values, target):
    differences = [a - b for a, b in zip(values, target)]
    return {"positions": len(values), "mae_cp": statistics.mean(abs(x) for x in differences),
            "rmse_cp": statistics.mean(x * x for x in differences) ** .5}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data")
    parser.add_argument("--suite", required=True)
    parser.add_argument("--positions", type=int, default=16)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output, suite_path = pathlib.Path(args.output), pathlib.Path(args.suite)
    if output.exists() or suite_path.exists(): parser.error("Preserve previous results")
    rows = [json.loads(line) for line in pathlib.Path(args.data).read_text().splitlines() if line.strip()]
    manifest = json.loads(pathlib.Path(str(args.data) + ".manifest.json").read_text())
    assert manifest["complete"] and digest(args.data) == manifest["data_sha256"]
    selected, selected_games = [], set()
    for row in rows:
        sample, verified = row["sample"], row["verified"]
        sign = 1 if row["fen"].split()[1] == "w" else -1
        if row["game"] in selected_games or len(sample) != 2 or len(verified) != 2: continue
        if any(label["white_cp"] is None for label in sample + verified): continue
        if sample[0]["pv"][0] != verified[0]["pv"][0] or abs(verified[0]["white_cp"]) > 1500: continue
        gaps = [sign * (labels[0]["white_cp"] - labels[1]["white_cp"]) for labels in (sample, verified)]
        if min(gaps) < 120: continue
        selected.append({"id": row["id"], "fen": row["fen"], "best_moves": [verified[0]["pv"][0]],
                         "source_game": row["game"], "score_gaps_cp": gaps, "sample": sample, "verified": verified})
        selected_games.add(row["game"])
        if len(selected) == args.positions: break
    if len(selected) != args.positions: raise ValueError("Insufficient independent finite-score unique moves")
    # Freeze before observing any Aster moves or evaluation errors.
    suite_path.write_text(json.dumps({"schema": 1, "positions": selected, "data_sha256": digest(args.data),
        "source": str(pathlib.Path(args.data).resolve()), "teacher": manifest["teacher"], "source_sha256": digest(__file__),
        "selection": "First eligible position per source game; same best move at 8192/65536 nodes, both gaps >=120 cp, finite verified score within +/-1500 cp.",
        "interpretation": "Fresh bounded teacher-verified endgames; not an optimality proof or final strength test."}, indent=2) + "\n")
    configs = [
        {"name": "classical", "engine": "artifacts/publish/baseline-0.6.0/Aster.exe", "source": "artifacts/research/king-context-release-source/manifest.json"},
        {"name": "threats", "engine": "artifacts/publish/geometric-threats-dev/Aster.exe", "source": "artifacts/research/geometric-threats-source/manifest.json"},
        {"name": "static_hybrid", "engine": "artifacts/publish/geometric-control-dev/Aster.exe", "source": "artifacts/research/geometric-control-source/manifest.json", "model": "artifacts/training/turn-static-hybrid-v1/model.ann"},
        {"name": "paired_hybrid", "engine": "artifacts/publish/geometric-control-dev/Aster.exe", "source": "artifacts/research/geometric-control-source/manifest.json", "model": "artifacts/training/pair-loss-moderate-v1/model.ann"}]
    predictions = {c["name"]: [] for c in configs}
    with contextlib.ExitStack() as stack:
        clients = []
        for config in configs:
            config["binary_sha256"] = digest(config["engine"])
            config["source_manifest"] = frozen_source_manifest(config["source"], config["binary_sha256"])
            client = stack.enter_context(UciClient(config["engine"]))
            if config.get("model"):
                training = json.loads(pathlib.Path(config["model"]).with_name("training.json").read_text())
                assert digest(config["model"]) == training["model_sha256"]
                config["model_sha256"] = digest(config["model"])
                client.send("setoption name EvalFile value " + str(pathlib.Path(config["model"]).resolve())); client.ready()
            clients.append(client)
        for row in rows:
            for client, config in zip(clients, configs):
                client.send("position fen " + row["fen"])
                cp = int(client.command("eval", "info string eval ").split()[-1])
                predictions[config["name"]].append(cp if row["fen"].split()[1] == "w" else -cp)
    summaries = {}
    masks = {"finite": [i for i, r in enumerate(rows) if r["verified"][0]["white_cp"] is not None],
             "within_training_window": [i for i, r in enumerate(rows) if r["verified"][0]["white_cp"] is not None and abs(r["verified"][0]["white_cp"]) <= 600]}
    finite = masks["finite"]
    summaries["static_vs_search"] = errors([rows[i]["static_white_cp"] for i in finite], [rows[i]["verified"][0]["white_cp"] for i in finite])
    summaries["sample_vs_verified"] = errors([rows[i]["sample"][0]["white_cp"] for i in finite if rows[i]["sample"][0]["white_cp"] is not None],
        [rows[i]["verified"][0]["white_cp"] for i in finite if rows[i]["sample"][0]["white_cp"] is not None])
    for name, values in predictions.items():
        summaries[name] = {}
        for label, indices in masks.items():
            summaries[name][label] = {"against_verified_search": errors([values[i] for i in indices], [rows[i]["verified"][0]["white_cp"] for i in indices]),
                                    "against_static": errors([values[i] for i in indices], [rows[i]["static_white_cp"] for i in indices])}
    result = {"configs": configs, "summaries": summaries, "data_sha256": digest(args.data), "suite_sha256": digest(suite_path),
              "source_sha256": digest(__file__), "positions": [{"id": r["id"], "game": r["game"], "verified": r["verified"][0],
              "static_white_cp": r["static_white_cp"], "predictions": {n: v[i] for n, v in predictions.items()}} for i, r in enumerate(rows)],
              "interpretation": "Same fresh sparse positions for unchanged evaluators. Finite-score MAE only; mate labels retain native distances. Source games are descriptive; no Elo/strength inference."}
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(summaries))


if __name__ == "__main__": main()
