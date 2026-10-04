"""Check row preservation and independently re-query a sample of static labels."""
import argparse
import hashlib
import json
import pathlib
import random
import re

from uci_client import ROOT, UciClient


def digest(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("static")
    parser.add_argument("--sample", type=int, default=128)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.sample < 1: parser.error("Sample must be positive")
    before = [json.loads(line) for line in pathlib.Path(args.source).read_text().splitlines() if line.strip()]
    after = [json.loads(line) for line in pathlib.Path(args.static).read_text().splitlines() if line.strip()]
    if len(before) != len(after): raise ValueError("Row count changed")
    manifest = json.loads(pathlib.Path(str(args.static) + ".manifest.json").read_text())
    if not manifest["complete"] or manifest["input_sha256"] != digest(args.source) or manifest["data_sha256"] != digest(args.static):
        raise ValueError("Static provenance differs")
    for source, static in zip(before, after):
        if static["search_score_white_cp"] != source["score_white_cp"] or static["label_kind"] != "stockfish_final_static_evaluation":
            raise ValueError("Original label lost")
        restored = dict(static)
        restored["score_white_cp"] = restored.pop("search_score_white_cp")
        restored.pop("label_kind")
        if restored != source: raise ValueError("Relabel changed position or grouping/provenance fields")
    teacher = manifest["teacher"]
    teacher_path = ROOT / teacher["executable"]
    if digest(teacher_path) != teacher["executable_sha256"]: raise ValueError("Teacher fingerprint differs")
    sample = random.Random(20261020).sample(after, min(args.sample, len(after)))
    with UciClient(teacher_path) as client:
        client.send("setoption name Threads value 1"); client.send("setoption name Hash value 64"); client.ready()
        for row in sample:
            client.send("position fen " + row["fen"])
            line = client.command("eval", "Final evaluation", timeout=10)
            value = re.search(r"Final evaluation\s+([+-]\d+\.\d+)\s+\(white side\)", line)
            if not value or int(round(float(value.group(1)) * 100)) != row["score_white_cp"]:
                raise ValueError("Static label re-query differs")
    result = {"status": "passed", "rows_preserved": len(after), "independently_requeried_labels": len(sample),
              "source_sha256": digest(args.source), "static_sha256": digest(args.static),
              "teacher_sha256": digest(teacher_path), "auditor_sha256": digest(__file__),
              "interpretation": "Row/group preservation and bounded label re-query, not playing strength."}
    pathlib.Path(args.output).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
