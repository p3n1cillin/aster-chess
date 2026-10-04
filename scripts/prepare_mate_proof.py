"""Freeze fresh general-proof regression openings before candidate queries."""
import copy
import subprocess
import sys

from run_rating import digest, read, write_new
from uci_client import ROOT


def main():
    plan = read(ROOT / "artifacts/research/mate-proof-plan-v1.json"); setup = plan["generation"]
    parent_path = ROOT / "tests/fixtures/mate-proof-parent-v1.json"
    command = [sys.executable, str(ROOT / "scripts/generate_openings.py")]
    for key in ("positions", "attempts", "seed", "plies", "nodes", "verify_nodes", "max_cp"):
        command += ["--" + key.replace("_", "-"), str(setup[key])]
    for path in setup["exclude_data"]: command += ["--exclude", str(ROOT / path)]
    for path in setup["exclude_suites"]: command += ["--exclude-suite", str(ROOT / path)]
    command += ["--output", str(parent_path)]
    subprocess.run(command, check=True); parent = read(parent_path)
    subset = copy.deepcopy(parent); subset["openings"] = parent["openings"][:16]
    subset.update({"parent_suite": {"path": parent_path.relative_to(ROOT).as_posix(), "sha256": digest(parent_path)},
        "parent_indices": list(range(16)), "splitter_sha256": digest(__file__), "experiment_role": "unchanged-play paired regression"})
    write_new(ROOT / "tests/fixtures/mate-proof-match-v1.json", subset)
    for role in ("parent", "match"):
        subprocess.run([sys.executable, str(ROOT / "scripts/audit_openings.py"), str(ROOT / f"tests/fixtures/mate-proof-{role}-v1.json"),
            "--output", str(ROOT / f"artifacts/validation/mate-proof-{role}-audit.json")], check=True)


if __name__ == "__main__": main()
