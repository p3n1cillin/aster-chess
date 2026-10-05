"""Create and partition the predeclared fresh continuation-history regression suite."""
import hashlib
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    plan_path = ROOT / "artifacts/research/continuation-plan-v1.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8")); generation = plan["generation"]
    command = [sys.executable, str(ROOT / "scripts/generate_openings.py")]
    for key, option in (("positions", "positions"), ("attempts", "attempts"), ("seed", "seed"), ("plies", "plies"),
                        ("selection_nodes", "nodes"), ("verification_nodes", "verify-nodes"), ("max_abs_teacher_cp", "max-cp")):
        command += ["--" + option, str(generation[key])]
    for key, option in (("excluded_data", "exclude"), ("excluded_suites", "exclude-suite")):
        for item in generation[key]:
            path = ROOT / item["path"]; assert digest(path) == item["sha256"], path
            command += ["--" + option, str(path)]
    parent = ROOT / "tests/fixtures/continuation-parent-v1.json"
    command += ["--output", str(parent)]
    subprocess.run(command, cwd=ROOT, check=True)
    subprocess.run([sys.executable, str(ROOT / "scripts/audit_openings.py"), str(parent),
                    "--output", str(ROOT / "artifacts/validation/continuation-parent-v1.json")], cwd=ROOT, check=True)
    original = json.loads(parent.read_text(encoding="utf-8")); slices = {"behavior": (0, 32), "30ms": (32, 96), "100ms": (96, 128), "rating": (128, 256)}
    for name, (start, end) in slices.items():
        output = ROOT / f"tests/fixtures/continuation-{name}-v1.json"; assert not output.exists()
        split = {key: value for key, value in original.items() if key != "openings"}
        split.update({"openings": original["openings"][start:end], "partition": name, "parent_sha256": digest(parent),
                      "plan_sha256": digest(plan_path), "range": [start, end], "partitioner_sha256": digest(pathlib.Path(__file__))})
        output.write_text(json.dumps(split, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"parent_sha256": digest(parent), "partitions": slices}))


if __name__ == "__main__": main()
