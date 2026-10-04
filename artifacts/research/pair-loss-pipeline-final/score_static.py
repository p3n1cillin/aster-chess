"""Rescore non-check teacher positions with Stockfish's static evaluation trace."""
import argparse
import hashlib
import json
import pathlib
import re
import time

import chess

from uci_client import ROOT, UciClient


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data")
    parser.add_argument("--output", required=True)
    parser.add_argument("--positions", type=int, help="Optional bounded subset")
    args = parser.parse_args()
    if args.positions is not None and args.positions < 1:
        parser.error("Position limit must be positive")
    output = pathlib.Path(args.output)
    if output.exists():
        parser.error("Output already exists")
    manifest = json.loads((ROOT / "tools/stockfish/manifest.json").read_text(encoding="utf-8"))
    teacher_path = ROOT / manifest["executable"]
    teacher_hash = hashlib.sha256(teacher_path.read_bytes()).hexdigest()
    if teacher_hash != manifest["executable_sha256"]:
        raise ValueError("Teacher binary differs from pinned manifest")
    input_path = pathlib.Path(args.data)
    input_hash = hashlib.sha256(input_path.read_bytes()).hexdigest()
    source_rows = [json.loads(line) for line in input_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.positions: source_rows = source_rows[:args.positions]
    if not source_rows: raise ValueError("Empty source dataset")
    output.parent.mkdir(parents=True, exist_ok=True)
    metadata = {"schema": 2, "complete": False, "teacher": manifest, "teacher_options": {"Threads": 1, "Hash": 64},
                "input": str(input_path.resolve()), "input_sha256": input_hash, "positions_written": 0,
                "parameters": {**vars(args), "max_abs_cp": 30000}, "generator_sha256": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
                "label_kind": "final static eval trace; no search at label time",
                "interpretation": "Static labels on preserved legal source positions, retaining source-game groups. Teacher fit is not playing strength."}
    manifest_path = pathlib.Path(str(output) + ".manifest.json")
    manifest_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    started = time.monotonic(); count = 0
    with UciClient(teacher_path) as teacher, output.open("w", encoding="utf-8") as destination:
        teacher.send("setoption name Threads value 1"); teacher.send("setoption name Hash value 64"); teacher.ready()
        for row in source_rows:
            board = chess.Board(row["fen"])
            if not board.is_valid() or board.is_check() or board.outcome(claim_draw=True) is not None:
                raise ValueError("Static source position must be legal, nonterminal and outside check")
            teacher.send("position fen " + row["fen"])
            evaluation = teacher.command("eval", "Final evaluation", timeout=10)
            match = re.search(r"Final evaluation\s+([+-]\d+\.\d+)\s+\(white side\)", evaluation)
            if not match:
                raise RuntimeError("Unexpected static evaluation trace: " + evaluation)
            row["search_score_white_cp"] = row["score_white_cp"]
            row["score_white_cp"] = int(round(float(match.group(1)) * 100))
            if abs(row["score_white_cp"]) > 30000:
                raise ValueError("Static score outside centipawn range")
            row["label_kind"] = "stockfish_final_static_evaluation"
            destination.write(json.dumps(row, separators=(",", ":")) + "\n")
            count += 1
            if count % 2000 == 0:
                print(json.dumps({"positions": count, "seconds": round(time.monotonic() - started, 3)}), flush=True)
            if args.positions and count >= args.positions:
                break
    with output.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if hashlib.sha256(input_path.read_bytes()).hexdigest() != input_hash:
        raise ValueError("Source data changed during static scoring")
    metadata.update(complete=count == len(source_rows), positions=count, positions_written=count,
                    data_sha256=digest, seconds=round(time.monotonic() - started, 3))
    manifest_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"positions": count, "seconds": metadata["seconds"], "sha256": digest}), flush=True)


if __name__ == "__main__":
    main()
