"""Augment a teacher dataset with the frozen classical evaluator's scores."""
import argparse
import hashlib
import json
import pathlib

from uci_client import DEFAULT_ENGINE, UciClient


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data")
    parser.add_argument("--engine", default=str(DEFAULT_ENGINE))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = pathlib.Path(args.output)
    if output.exists():
        parser.error("Output already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    engine_digest = hashlib.sha256(pathlib.Path(args.engine).read_bytes()).hexdigest()
    count = 0
    with UciClient(args.engine) as client, pathlib.Path(args.data).open(encoding="utf-8") as source, output.open("w", encoding="utf-8") as destination:
        for line in source:
            row = json.loads(line)
            client.send("position fen " + row["fen"])
            score = int(client.command("eval", "info string eval ").split()[-1])
            row["classical_white_cp"] = score if row["fen"].split()[1] == "w" else -score
            destination.write(json.dumps(row, separators=(",", ":")) + "\n")
            count += 1
    fingerprint = hashlib.sha256(pathlib.Path(args.engine).read_bytes()).hexdigest()
    if fingerprint != engine_digest: raise ValueError("Classical engine changed during scoring")
    metadata = {"input": str(pathlib.Path(args.data).resolve()), "classical_engine": str(pathlib.Path(args.engine).resolve()),
                "classical_binary_sha256": fingerprint, "positions": count,
                "input_sha256": hashlib.sha256(pathlib.Path(args.data).read_bytes()).hexdigest(),
                "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest()}
    pathlib.Path(str(output) + ".classical.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata))


if __name__ == "__main__":
    main()
