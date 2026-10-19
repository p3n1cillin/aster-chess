"""Run a frozen independent tactical suite and save per-position engine results."""
import argparse
import hashlib
import json
import pathlib

import chess
import chess.engine

from uci_client import DEFAULT_ENGINE, engine_command


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite")
    parser.add_argument("--engine", default=str(DEFAULT_ENGINE))
    parser.add_argument("--engine-arg", action="append", default=[], help="Native engine subcommand, e.g. legacy")
    parser.add_argument("--depth", type=int, default=8)
    parser.add_argument("--nodes", type=int)
    parser.add_argument("--eval-file")
    parser.add_argument("--output", required=True)
    parser.add_argument("--require-solved", type=int, help="Fail below this tactical regression threshold")
    parser.add_argument("--reference-report", help="Require identical deterministic moves/work to a frozen baseline report")
    args = parser.parse_args()
    if not 1 <= args.depth <= 126 or (args.nodes is not None and args.nodes < 1):
        parser.error("Depth must be 1..126 and nodes must be positive")
    suite = json.loads(pathlib.Path(args.suite).read_text(encoding="utf-8"))
    solved = 0; positions = []
    with chess.engine.SimpleEngine.popen_uci([*engine_command(args.engine), *args.engine_arg], timeout=60) as engine:
        options = {name: value for name, value in {"Threads": 1, "Hash": 64}.items() if name in engine.options}
        if args.eval_file:
            options["EvalFile"] = str(pathlib.Path(args.eval_file).resolve())
        engine.configure(options)
        for test in suite["positions"]:
            board = chess.Board(test["fen"])
            limit = chess.engine.Limit(nodes=args.nodes) if args.nodes else chess.engine.Limit(depth=args.depth)
            result = engine.play(board, limit, game=object(), info=chess.engine.INFO_ALL)
            if result.move not in board.legal_moves:
                raise RuntimeError("Engine returned an illegal tactical move")
            correct = result.move.uci() in test["best_moves"]
            solved += correct
            positions.append({"id": test["id"], "bestmove": result.move.uci(), "solved": correct, "expected": test["best_moves"],
                              "depth": result.info.get("depth"), "nodes": result.info.get("nodes"), "time": result.info.get("time")})
    with pathlib.Path(args.engine).open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    report = {"engine": str(pathlib.Path(args.engine).resolve()), "binary_sha256": digest, "suite": str(pathlib.Path(args.suite).resolve()),
              "limit": {"nodes": args.nodes} if args.nodes else {"depth": args.depth}, "eval_file": args.eval_file,
              "solved": solved, "total": len(positions), "positions": positions,
              "interpretation": "Teacher-verified tactical regression set; neither an Elo estimate nor proof of general playing strength."}
    report["engine_arguments"] = args.engine_arg
    if args.reference_report:
        reference_path = pathlib.Path(args.reference_report)
        reference = json.loads(reference_path.read_text(encoding="utf-8"))
        keys = ["id", "bestmove", "solved", "expected", "depth", "nodes"]
        report["reference_report_sha256"] = hashlib.sha256(reference_path.read_bytes()).hexdigest()
        report["reference_match"] = (reference["limit"] == report["limit"] and
            reference.get("eval_file") == report["eval_file"] and
            reference.get("engine_arguments", []) == args.engine_arg and
            [{key: p[key] for key in keys} for p in reference["positions"]] ==
            [{key: p[key] for key in keys} for p in positions])
    output = pathlib.Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"solved": solved, "total": len(positions)}))
    if args.reference_report and not report["reference_match"]:
        raise RuntimeError("Tactical moves or deterministic work differ from the frozen baseline")
    if args.require_solved is not None and solved < args.require_solved:
        raise RuntimeError(f"Tactical regression: {solved} solved, at least {args.require_solved} required")


if __name__ == "__main__":
    main()
