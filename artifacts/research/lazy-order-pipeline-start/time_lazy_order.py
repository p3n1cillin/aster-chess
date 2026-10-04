"""Predeclared warm same-work timing comparison in two persistent processes."""
import json
import statistics
import time

import chess
import chess.engine

from match import configure
from run_rating import digest, read, write_new
from uci_client import ROOT, engine_command


def search(engine, board):
    started = time.perf_counter()
    result = engine.play(board, chess.engine.Limit(depth=10), game=object(), info=chess.engine.INFO_ALL)
    elapsed = time.perf_counter() - started
    replay = board.copy()
    for move in result.info.get("pv", []):
        assert move in replay.legal_moves; replay.push(move)
    assert result.move in board.legal_moves
    score = result.info["score"].white()
    return {"bestmove": result.move.uci(), "depth": result.info["depth"], "nodes": result.info["nodes"],
            "cp": score.score(), "mate": score.mate(), "pv": [m.uci() for m in result.info.get("pv", [])],
            "elapsed_seconds": elapsed}


def main():
    plan_path = ROOT / "artifacts/research/lazy-order-plan-v1.json"; plan = read(plan_path)
    amendment = ROOT / "artifacts/research/lazy-order-plan-amendment-v1.json"
    assert amendment.is_file()
    paths = [ROOT / plan[role] for role in ("candidate", "baseline")]
    assert [digest(p) for p in paths] == [plan[role + "_sha256"] for role in ("candidate", "baseline")]
    suite_path = ROOT / "tests/fixtures/lazy-order-30ms-v1.json"
    positions = read(suite_path)["openings"][:16]; rounds = []
    with chess.engine.SimpleEngine.popen_uci(engine_command(paths[0]), timeout=120) as candidate, \
            chess.engine.SimpleEngine.popen_uci(engine_command(paths[1]), timeout=120) as baseline:
        for engine in (candidate, baseline): configure(engine, 64)
        for iteration in range(8):
            rows = []
            for index, entry in enumerate(positions):
                board = chess.Board()
                for move in entry["moves"].split(): board.push_uci(move)
                engines = [("candidate", candidate), ("baseline", baseline)]
                if (iteration + index) % 2: engines.reverse()
                row = {"id": entry["id"]}
                for role, engine in engines: row[role] = search(engine, board)
                for field in ("bestmove", "depth", "nodes", "cp", "mate", "pv"):
                    assert row["candidate"][field] == row["baseline"][field], (entry["id"], field, row)
                rows.append(row)
            total = {role: sum(r[role]["elapsed_seconds"] for r in rows) for role in ("candidate", "baseline")}
            rounds.append({"iteration": iteration, "warmup": iteration < 2, "total_seconds": total,
                           "speed_ratio": total["baseline"] / total["candidate"], "positions": rows})
            print(json.dumps({k: rounds[-1][k] for k in ("iteration", "warmup", "total_seconds", "speed_ratio")}), flush=True)
    median = statistics.median(r["speed_ratio"] for r in rounds[2:])
    report = {"same_work": True, "median_measured_speed_ratio": median, "timing_gate_passed": median >= 1.05,
              "warmup_rounds": 2, "measured_rounds": 6, "depth": 10, "rounds": rounds,
              "candidate_sha256": digest(paths[0]), "baseline_sha256": digest(paths[1]),
              "suite_sha256": digest(suite_path), "plan_sha256": digest(plan_path), "script_sha256": digest(__file__),
              "amendment_sha256": digest(amendment),
              "interpretation": "Alternating same-work warm microbenchmark under one host's runtime/OS conditions. Fixed-depth elapsed ratio is not playing strength or Elo; no profiling build used."}
    write_new(ROOT / "artifacts/benchmarks/lazy-order-warm-timing-v1.json", report)
    print(json.dumps({"same_work": True, "median_speed_ratio": median, "timing_gate_passed": median >= 1.05}))


if __name__ == "__main__": main()
