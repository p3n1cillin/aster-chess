"""Save fixed-depth search benchmark JSON with an engine binary fingerprint."""
import argparse
import datetime
import hashlib
import json
import pathlib
import subprocess

from uci_client import DEFAULT_ENGINE, engine_command


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", default=str(DEFAULT_ENGINE))
    parser.add_argument("--depth", type=int, default=7)
    parser.add_argument("--eval-file", help="Optional Aster model to benchmark")
    parser.add_argument("--output", default="artifacts/benchmarks/current.json")
    args = parser.parse_args()
    engine = pathlib.Path(args.engine).resolve()
    command = engine_command(engine) + ["bench", str(args.depth)]
    model = pathlib.Path(args.eval_file).resolve() if args.eval_file else None
    if model: command.append(str(model))
    result = subprocess.run(command,
                            capture_output=True, text=True, check=True, timeout=300)
    lines = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    with engine.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    report = {"timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "engine": str(engine), "binary_sha256": digest, "requested_depth": args.depth,
              "positions": lines[:-1], "aggregate": lines[-1],
              "interpretation": "Fixed-depth engineering benchmark; elapsed times include JIT and are machine-dependent. Not a strength measurement."}
    if model:
        report["eval_file"] = str(model)
        report["model_sha256"] = hashlib.sha256(model.read_bytes()).hexdigest()
    output = pathlib.Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["aggregate"]))


if __name__ == "__main__":
    main()
