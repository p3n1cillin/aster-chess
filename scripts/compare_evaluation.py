"""Compare static evaluation on a pinned position dataset, saving every difference."""
import argparse
import hashlib
import json
import pathlib

import chess

from uci_client import DEFAULT_ENGINE, UciClient


def digest(path):
    with pathlib.Path(path).open("rb") as source: return hashlib.file_digest(source, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data")
    parser.add_argument("--engine", default=str(DEFAULT_ENGINE))
    parser.add_argument("--opponent", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--require-identical", action="store_true")
    args = parser.parse_args()
    differences = []; checked = 0; total_delta = 0; max_delta = 0
    with UciClient(args.engine) as candidate, UciClient(args.opponent) as opponent:
        for line in pathlib.Path(args.data).read_text(encoding="utf-8").splitlines():
            if not line.strip(): continue
            row = json.loads(line); board = chess.Board(row["fen"])
            if not board.is_valid(): raise ValueError("Invalid evaluation fixture")
            values = []
            for client in (candidate, opponent):
                client.send("position fen " + row["fen"])
                values.append(int(client.command("eval", "info string eval ").split()[-1]))
            delta = values[0] - values[1]; checked += 1
            total_delta += abs(delta); max_delta = max(max_delta, abs(delta))
            if delta: differences.append({"fen": row["fen"], "candidate_stm_cp": values[0], "opponent_stm_cp": values[1]})
        names = [candidate.name, opponent.name]
    if not checked: raise ValueError("Empty evaluation dataset")
    result = {"positions": checked, "differences": len(differences), "mean_absolute_delta_cp": total_delta / checked,
              "max_absolute_delta_cp": max_delta, "data": str(pathlib.Path(args.data).resolve()), "data_sha256": digest(args.data),
              "engines": [{"path": str(pathlib.Path(path).resolve()), "name": name, "sha256": digest(path)}
                          for path, name in zip((args.engine, args.opponent), names)],
              "changed_positions": differences, "interpretation": "Static behavior comparison; neither a teacher-fit metric nor a playing-strength test."}
    output = pathlib.Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("positions", "differences", "mean_absolute_delta_cp", "max_absolute_delta_cp")}))
    if args.require_identical and differences: raise RuntimeError("Static evaluation regression")


if __name__ == "__main__": main()
