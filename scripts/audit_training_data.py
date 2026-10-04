"""Independently audit legal teacher data, provenance, exclusions and sampling."""
import argparse
import collections
import hashlib
import json
import pathlib
import statistics

import chess

from uci_client import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data")
    parser.add_argument("--exclude-suite", action="append", default=[])
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    path = pathlib.Path(args.data)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows: raise ValueError("Empty dataset")
    excluded = set(); suites = []
    for name in args.exclude_suite:
        fixture = pathlib.Path(name)
        entries = json.loads(fixture.read_text(encoding="utf-8"))["openings"]
        excluded.update(" ".join(chess.Board(e["fen"]).fen().split()[:4]) for e in entries)
        suites.append({"path": str(fixture.resolve()), "sha256": hashlib.sha256(fixture.read_bytes()).hexdigest()})
    seen = set(); games = set(); scores = []; phases = collections.Counter(); kings = collections.Counter(); checks = 0
    for row in rows:
        board = chess.Board(row["fen"])
        if not board.is_valid() or board.outcome(claim_draw=True) is not None:
            raise ValueError("Invalid or terminal training position")
        key = " ".join(board.fen().split()[:4])
        if key in seen: raise ValueError("Duplicate canonical position")
        if key in excluded: raise ValueError("Regression-suite overlap")
        seen.add(key); games.add(row["game"]); scores.append(row["score_white_cp"]); checks += board.is_check()
        phase = sum(len(board.pieces(piece, color)) * weight for color in (chess.WHITE, chess.BLACK)
                    for piece, weight in ((chess.KNIGHT, 1), (chess.BISHOP, 1), (chess.ROOK, 2), (chess.QUEEN, 4)))
        phases["endgame" if phase <= 8 else "middlegame" if phase <= 16 else "opening"] += 1
        for color in (chess.WHITE, chess.BLACK):
            king = board.king(color)
            rank = chess.square_rank(king) if color else 7 - chess.square_rank(king)
            kings[rank // 2 * 4 + chess.square_file(king) // 2] += 1
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path = pathlib.Path(str(path) + ".manifest.json")
    manifest = None
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not manifest["complete"] or manifest["positions_written"] != len(rows) or manifest["data_sha256"] != digest:
            raise ValueError("Dataset does not match its completed manifest")
        teacher = manifest["teacher"]
        if hashlib.sha256((ROOT / teacher["executable"]).read_bytes()).hexdigest() != teacher["executable_sha256"]:
            raise ValueError("Teacher binary no longer matches the pinned manifest")
        if max(abs(score) for score in scores) > manifest["parameters"].get("max_abs_cp", 1500):
            raise ValueError("Dataset exceeds its label bound")
    report = {"status": "passed", "data": str(path.resolve()), "data_sha256": digest, "positions": len(rows),
              "games_with_positions": len(games), "canonical_duplicates": 0, "regression_overlap": 0,
              "checks": checks, "phase_distribution": dict(phases), "king_region_counts": dict(sorted(kings.items())),
              "score_distribution": {"negative": sum(s < 0 for s in scores), "zero": scores.count(0), "positive": sum(s > 0 for s in scores),
                                     "median_abs_cp": statistics.median(abs(s) for s in scores), "max_abs_cp": max(abs(s) for s in scores)},
              "label_node_median": None if all(row.get("label_kind") == "stockfish_final_static_evaluation" for row in rows)
                  else statistics.median(row["nodes"] for row in rows),
              "source_search_node_median": statistics.median(row["nodes"] for row in rows)
                  if all(row.get("label_kind") == "stockfish_final_static_evaluation" for row in rows) else None,
              "label_kind_counts": dict(collections.Counter(row.get("label_kind", "search_score") for row in rows)), "exclusions": suites,
              "manifest_checked": manifest is not None,
              "interpretation": "Legality/provenance and exact-position exclusions only; opening-family overlap can remain. Teacher-produced labels are not outcomes or playing-strength evidence; retained source search budgets do not describe static relabeling."}
    output = pathlib.Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__": main()
