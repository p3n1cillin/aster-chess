"""Freeze and independently audit fresh capacity match openings."""
import copy
import subprocess
import sys

from run_rating import digest, read, write_new
from uci_client import ROOT


def main():
    plan_path = ROOT / "artifacts/research/capacity-plan-v1.json"; plan = read(plan_path)
    setup = plan["matches"]["openings"]
    bundle = read(ROOT / "artifacts/research/capacity-training-data-v1.json"); assert bundle["complete"]
    parent_path = ROOT / "tests/fixtures/capacity-parent-v1.json"
    if parent_path.exists(): raise ValueError("Preserve prior/partial opening collection")
    command = [sys.executable,str(ROOT / "scripts/generate_openings.py")]
    for name in ("positions","attempts","seed","plies","nodes","verify_nodes","max_cp"):
        command += ["--"+name.replace("_","-"),str(setup[name])]
    prior = read(ROOT / "artifacts/research/deep-turn-plan-v1.json")
    for path in [*prior["generation"]["exclude_counter_data"],"artifacts/data/stable-endgame-candidate-64096-v1-classical.jsonl",bundle["data"]]:
        command += ["--exclude",str(ROOT / path)]
    for path in prior["generation"]["exclude_counter_suites"]:
        if "openings" in read(ROOT / path): command += ["--exclude-suite",str(ROOT / path)]
    command += ["--exclude-suite",str(ROOT / "tests/fixtures/deep-turn-parent-v1.json")]
    command += ["--output",str(parent_path)]; subprocess.run(command,check=True)
    parent = read(parent_path); assert len(parent["openings"]) == 160
    excluded_tactics = {" ".join(row["fen"].split()[:4]) for path in prior["generation"]["exclude_counter_suites"] for row in read(ROOT / path).get("positions",[])}
    assert not {" ".join(row["fen"].split()[:4]) for row in parent["openings"]} & excluded_tactics
    for role,indices in {"classical-30ms":range(64),"control-30ms":range(64,128),"classical-100ms":range(128,160)}.items():
        subset = copy.deepcopy(parent); subset["openings"] = [parent["openings"][i] for i in indices]
        subset.update(experiment_role=role,parent_indices=list(indices),
            parent_suite={"path":parent_path.relative_to(ROOT).as_posix(),"sha256":digest(parent_path)},plan_sha256=digest(plan_path),splitter_sha256=digest(__file__))
        write_new(ROOT / f"tests/fixtures/capacity-{role}-v1.json",subset)
    for role in ("parent","classical-30ms","control-30ms","classical-100ms"):
        subprocess.run([sys.executable,str(ROOT / "scripts/audit_openings.py"),str(ROOT / f"tests/fixtures/capacity-{role}-v1.json"),
            "--output",str(ROOT / f"artifacts/validation/capacity-{role}-audit.json")],check=True)


if __name__ == "__main__": main()
