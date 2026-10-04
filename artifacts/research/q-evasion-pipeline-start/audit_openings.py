"""Audit opening histories, canonical exclusions and pinned generation provenance."""
import argparse
import hashlib
import json
import pathlib

import chess

from uci_client import ROOT


def digest(path): return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def key(board): return " ".join(board.fen().split()[:4])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = pathlib.Path(args.output)
    if output.exists(): parser.error("Preserve previous audits")
    suite = json.loads(pathlib.Path(args.suite).read_text())
    excluded = set(); refs = []
    for entry in suite["training_exclusions"]:
        path = pathlib.Path(entry["path"])
        if digest(path) != entry["sha256"]: raise ValueError("Changed excluded training set")
        values = {key(chess.Board(json.loads(line)["fen"])) for line in path.read_text().splitlines() if line.strip()}
        assert len(values) == entry["positions"]
        excluded.update(values); refs.append(entry)
    for entry in suite["prior_suites_excluded"]:
        path = pathlib.Path(entry["path"])
        if digest(path) != entry["sha256"]: raise ValueError("Changed excluded opening suite")
        values = json.loads(path.read_text())["openings"]
        assert len(values) == entry["positions"]
        excluded.update(key(chess.Board(row["fen"])) for row in values); refs.append(entry)
    teacher = suite["teacher"]
    assert digest(ROOT / teacher["executable"]) == teacher["executable_sha256"]
    seen = set()
    for entry in suite["openings"]:
        board = chess.Board()
        for text in entry["moves"].split(): board.push_uci(text)
        assert len(board.move_stack) == suite["plies"]
        assert board.fen() == entry["fen"] and board.is_valid()
        assert board.outcome(claim_draw=True) is None
        canonical = key(board)
        assert canonical not in excluded and canonical not in seen
        assert abs(entry["teacher_white_cp"]) <= suite["max_abs_teacher_cp"]
        seen.add(canonical)
    report = {"passed": True, "positions": len(seen), "suite_sha256": digest(args.suite), "exclusions": refs,
              "teacher_sha256": teacher["executable_sha256"], "source_sha256": digest(__file__),
              "interpretation": "Legal complete histories, canonical deduplication, exact exclusions and provenance. Recorded bounded scores are not re-queried; no final strength claim."}
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": True, "positions": len(seen), "exclusion_sources": len(refs)}))


if __name__ == "__main__": main()
