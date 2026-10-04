"""Generate and audit the predeclared fresh stable-label match partitions."""
import copy
import subprocess
import sys

from run_rating import digest, read, write_new
from uci_client import ROOT


def main():
    plan_path = ROOT / "artifacts/research/stable-endgame-plan-v1.json"; plan = read(plan_path)
    setup = plan["matches"]["openings"]
    assert read(ROOT / "artifacts/validation/stable-endgame-data-audit-v1.json")["complete"]
    command = [sys.executable,str(ROOT / "scripts/generate_openings.py")]
    for name in ("positions","attempts","seed","plies","nodes","verify_nodes","max_cp"):
        command += ["--"+name.replace("_","-"),str(setup[name])]
    for path in [*plan["generation"]["exclude_data"],"artifacts/data/stable-endgame-4096-v1.jsonl"]:
        command += ["--exclude",str(ROOT / path)]
    for path in plan["generation"]["exclude_suites"]:
        suite = read(ROOT / path)
        if "openings" in suite: command += ["--exclude-suite",str(ROOT / path)]
    parent_path = ROOT / "tests/fixtures/stable-endgame-parent-v1.json"
    command += ["--output",str(parent_path)]
    if parent_path.exists(): raise ValueError("Preserve previous/partial openings; no restart")
    subprocess.run(command,check=True)
    parent = read(parent_path); assert len(parent["openings"]) == 160
    excluded_tactics = {" ".join(row["fen"].split()[:4]) for path in plan["generation"]["exclude_suites"]
        for row in read(ROOT / path).get("positions",[])}
    assert not {" ".join(row["fen"].split()[:4]) for row in parent["openings"]} & excluded_tactics
    for role,indices in {"classical-30ms":range(64),"control-30ms":range(64,128),"classical-100ms":range(128,160)}.items():
        subset = copy.deepcopy(parent); subset["openings"] = [parent["openings"][i] for i in indices]
        subset.update(experiment_role=role,parent_indices=list(indices),
            parent_suite={"path":parent_path.relative_to(ROOT).as_posix(),"sha256":digest(parent_path)},
            plan_sha256=digest(plan_path),splitter_sha256=digest(__file__))
        write_new(ROOT / f"tests/fixtures/stable-endgame-{role}-v1.json",subset)
    for role in ("parent","classical-30ms","control-30ms","classical-100ms"):
        subprocess.run([sys.executable,str(ROOT / "scripts/audit_openings.py"),str(ROOT / f"tests/fixtures/stable-endgame-{role}-v1.json"),
            "--output",str(ROOT / f"artifacts/validation/stable-endgame-{role}-audit.json")],check=True)


if __name__ == "__main__": main()
