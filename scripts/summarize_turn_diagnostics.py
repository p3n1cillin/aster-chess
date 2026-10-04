"""Compare variation in predicted turn effects on exactly the same frozen pairs."""
import argparse
import hashlib
import json
import pathlib

import numpy as np


def reference(path):
    return {"path": str(pathlib.Path(path).resolve()), "sha256": hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("teacher")
    parser.add_argument("scores", nargs="+")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = pathlib.Path(args.output)
    if output.exists(): parser.error("Preserve earlier comparisons")
    original = json.loads(pathlib.Path(args.teacher).read_text())
    labels = {p["source_fen"]: p["teacher_turn_delta_cp"] for p in original["pairs"]}
    models = []
    for path in args.scores:
        report = json.loads(pathlib.Path(path).read_text())
        pairs = report["pairs"]
        if {p["source_fen"] for p in pairs} != set(labels) or len(pairs) != len(labels):
            raise ValueError("Diagnostic positions differ")
        expected = np.array([labels[p["source_fen"]] for p in pairs], dtype=float)
        actual = np.array([p["turn_delta_cp"] for p in pairs], dtype=float)
        models.append({"report": reference(path), "model_sha256": report["model_sha256"],
                       "mean_turn_delta_cp": float(actual.mean()), "turn_delta_std_cp": float(actual.std()),
                       "min_turn_delta_cp": float(actual.min()), "max_turn_delta_cp": float(actual.max()),
                       "turn_delta_mae_cp": float(np.abs(actual - expected).mean()),
                       "pearson_turn_delta": float(np.corrcoef(actual, expected)[0, 1]) if actual.std() else None})
    teacher = np.array(list(labels.values()), dtype=float)
    result = {"pairs": len(labels), "teacher": reference(args.teacher), "teacher_turn_delta_std_cp": float(teacher.std()),
              "models": models, "source_sha256": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
              "interpretation": "Descriptive counterfactual held-out sample; not a rating, strength estimate or hypothesis-test result."}
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
