"""Freeze and independently audit the phase ablation's fresh opening partitions."""
import copy
import subprocess
import sys

from run_rating import digest, read, write_new
from uci_client import ROOT


def main():
    plan_path = ROOT / "artifacts/research/phase-plan-v1.json"
    plan = read(plan_path); setup = plan["generation"]
    command = [sys.executable, str(ROOT / "scripts/generate_openings.py")]
    for name in ("positions", "attempts", "seed", "plies", "nodes", "verify_nodes", "max_cp"):
        command += ["--" + name.replace("_", "-"), str(setup[name])]
    for path in setup["exclude_data"]: command += ["--exclude", str(ROOT / path)]
    for path in setup["exclude_suites"]: command += ["--exclude-suite", str(ROOT / path)]
    parent_path = ROOT / "tests/fixtures/phase-parent-v1.json"
    command += ["--output", str(parent_path)]
    subprocess.run(command, check=True)
    parent = read(parent_path); assert len(parent["openings"]) == 80
    for role, indices in {"classical-30ms": range(32), "control-30ms": range(32, 64), "classical-100ms": range(64, 80)}.items():
        subset = copy.deepcopy(parent); subset["openings"] = [parent["openings"][i] for i in indices]
        subset.update({"experiment_role": role, "parent_indices": list(indices),
            "parent_suite": {"path": parent_path.relative_to(ROOT).as_posix(), "sha256": digest(parent_path)},
            "plan_sha256": digest(plan_path), "splitter_sha256": digest(__file__)})
        write_new(ROOT / f"tests/fixtures/phase-{role}-v1.json", subset)
    for role in ("parent", "classical-30ms", "control-30ms", "classical-100ms"):
        subprocess.run([sys.executable, str(ROOT / "scripts/audit_openings.py"), str(ROOT / f"tests/fixtures/phase-{role}-v1.json"),
            "--output", str(ROOT / f"artifacts/validation/phase-{role}-audit.json")], check=True)


if __name__ == "__main__": main()
