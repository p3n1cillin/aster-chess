"""Compare bounded experimental search activity and cost at equal node limits."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import statistics
import time

import chess
import chess.engine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--suite", required=True)
    parser.add_argument("--nodes", type=int, default=20000)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists() or args.nodes < 1:
        raise ValueError("Use a fresh report and a positive node budget")
    suite = Path(args.suite)
    positions = json.loads(suite.read_text(encoding="utf-8"))["openings"]
    engines = {}
    observations = []
    try:
        for role, path in [("baseline", args.baseline), ("candidate", args.candidate)]:
            engine = chess.engine.SimpleEngine.popen_uci([str(Path(path).resolve())], timeout=60)
            engines[role] = engine
            engine.configure({"Hash": 64, "Threads": 1})
        for index, position in enumerate(positions):
            board = chess.Board(position.get("start_fen", chess.STARTING_FEN))
            for move in position["moves"].split():
                board.push_uci(move)
            cases = {}
            for role in (["baseline", "candidate"] if index % 2 == 0 else ["candidate", "baseline"]):
                started = time.perf_counter()
                result = engines[role].play(board, chess.engine.Limit(nodes=args.nodes),
                                            game=object(), info=chess.engine.INFO_ALL)
                elapsed = time.perf_counter() - started
                if result.move not in board.legal_moves:
                    raise ValueError("Illegal move at " + str(index))
                replay = board.copy()
                for move in result.info.get("pv", []):
                    if not replay.is_legal(move):
                        raise ValueError("Illegal PV at " + str(index))
                    replay.push(move)
                activity = re.search(r"Aster disagreement guard audits (\d+) max_per_thread (\d+)",
                                     result.info.get("string", ""))
                if role == "candidate" and activity is None:
                    raise ValueError("Experimental activity telemetry is missing")
                audits = int(activity[1]) if activity else 0
                if activity and (int(activity[2]) != 256 or audits > 256):
                    raise ValueError("Per-search budget exceeded")
                score = result.info["score"].white()
                cases[role] = {"bestmove": result.move.uci(), "cp": score.score(),
                               "mate": score.mate(), "depth": result.info.get("depth"),
                               "nodes": result.info["nodes"], "wall_seconds": elapsed,
                               "pv": [move.uci() for move in result.info.get("pv", [])],
                               "audits": audits}
            base, candidate = cases["baseline"], cases["candidate"]
            throughput = (candidate["nodes"] / candidate["wall_seconds"]) / (base["nodes"] / base["wall_seconds"])
            observations.append({"index": index, "opening": position.get("id"),
                                 "fen": board.fen(), "results": cases,
                                 "candidate_over_baseline_throughput": throughput})
    finally:
        for engine in engines.values():
            engine.quit()
    activity = sum(case["results"]["candidate"]["audits"] for case in observations)
    throughput = statistics.median(case["candidate_over_baseline_throughput"] for case in observations)
    report = {"passed": activity > 0 and throughput >= 0.90,
              "candidate_sha256": hashlib.sha256(Path(args.candidate).read_bytes()).hexdigest(),
              "baseline_sha256": hashlib.sha256(Path(args.baseline).read_bytes()).hexdigest(),
              "suite_sha256": hashlib.sha256(suite.read_bytes()).hexdigest(),
              "node_limit": args.nodes, "positions": len(observations),
              "audits": activity, "median_throughput_ratio": throughput,
              "observations": observations,
              "limits": "Equal-node desktop engineering screen, including protocol/reset cost. Not a strength estimate or proof. All enabled moves/PVs are independently replayed."}
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps({key: report[key] for key in ["passed", "positions", "audits", "median_throughput_ratio"]}))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
