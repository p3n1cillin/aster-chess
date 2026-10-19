"""Add bounded counterfactual turn labels while retaining each source-game group."""
from research_reference import research_text
import argparse
import hashlib
import json
import pathlib
import random
import time

import chess
import chess.engine

from uci_client import ROOT, engine_command


def digest(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def canonical(board):
    return " ".join(board.fen().split()[:4])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data")
    parser.add_argument("--extra", type=int, default=10000)
    parser.add_argument("--nodes", type=int, default=8192)
    parser.add_argument("--max-abs-cp", type=int, default=600)
    parser.add_argument("--seed", type=int, default=20261019)
    parser.add_argument("--exclude-suite", action="append", default=[])
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if min(args.extra, args.nodes, args.max_abs_cp) <= 0:
        parser.error("Positive budgets required")
    output = pathlib.Path(args.output)
    if output.exists(): parser.error("Preserve earlier datasets; choose another output")
    source_hash = digest(args.data)
    rows = [json.loads(line) for line in pathlib.Path(args.data).read_text().splitlines() if line.strip()]
    seen = {canonical(chess.Board(row["fen"])) for row in rows}
    if len(seen) != len(rows): raise ValueError("Duplicate source positions")
    excluded = set(); exclusions = []
    for name in args.exclude_suite:
        path = pathlib.Path(name)
        excluded.update(canonical(chess.Board(e["fen"])) for e in json.loads(path.read_text())["openings"])
        exclusions.append({"path": str(path), "sha256": digest(path)})
    if seen & excluded: raise ValueError("Source data overlap with regression fixtures")
    teacher_manifest = json.loads((ROOT / research_text('opponent_manifest')).read_text())
    teacher_path = ROOT / teacher_manifest["executable"]
    if digest(teacher_path) != teacher_manifest["executable_sha256"]:
        raise ValueError("Teacher binary differs from pinned manifest")
    shuffled = list(rows); random.Random(args.seed).shuffle(shuffled)
    manifest_path = pathlib.Path(str(output) + ".manifest.json")
    manifest = {"complete": False, "source_data": str(pathlib.Path(args.data).resolve()), "source_data_sha256": source_hash,
                "source_positions": len(rows), "extra_positions": 0, "positions_written": len(rows), "parameters": vars(args),
                "teacher": teacher_manifest, "teacher_options": {"Threads": 1, "Hash": 64}, "exclusions": exclusions,
                "generator_sha256": digest(__file__),
                "interpretation": "Opposite-turn FENs are structurally legal counterfactuals without game histories; added rows keep their parent game ID for splitting. Not game outcomes or evidence of strength."}
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    started = time.monotonic()
    with output.open("w") as target, chess.engine.SimpleEngine.popen_uci(engine_command(teacher_path), timeout=30) as teacher:
        teacher.configure({"Threads": 1, "Hash": 64})
        for row in rows: target.write(json.dumps(row) + "\n")
        for row in shuffled:
            board = chess.Board(row["fen"])
            if board.ep_square is not None: continue
            board.turn = not board.turn
            key = canonical(board)
            if key in seen or key in excluded or not board.is_valid() or board.is_check() or board.outcome(claim_draw=True) is not None:
                continue
            info = teacher.analyse(board, chess.engine.Limit(nodes=args.nodes), game=object())
            cp = info["score"].white().score()
            if cp is None or abs(cp) > args.max_abs_cp: continue
            extra = dict(row)
            extra.update(fen=board.fen(en_passant="fen"), score_white_cp=cp, nodes=info.get("nodes"), depth=info.get("depth"),
                         counterfactual_turn=True, source_fen=row["fen"])
            extra.pop("classical_white_cp", None)
            if "ply" in extra: extra["source_ply"] = extra.pop("ply")
            target.write(json.dumps(extra) + "\n"); seen.add(key)
            manifest["extra_positions"] += 1; manifest["positions_written"] += 1
            if manifest["extra_positions"] % 2000 == 0:
                print(json.dumps({"extra_positions": manifest["extra_positions"], "seconds": round(time.monotonic() - started, 2)}), flush=True)
            if manifest["extra_positions"] == args.extra: break
    manifest["complete"] = manifest["extra_positions"] == args.extra
    manifest["data_sha256"] = digest(output)
    manifest["seconds"] = round(time.monotonic() - started, 3)
    if digest(args.data) != source_hash: raise ValueError("Source data changed during generation")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    if not manifest["complete"]: raise ValueError("Source-row budget exhausted; incomplete dataset preserved")
    print(json.dumps({k: manifest[k] for k in ("complete", "positions_written", "extra_positions", "seconds")}))


if __name__ == "__main__":
    main()
