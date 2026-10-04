"""Correct a missing dataset filename, then freeze the declared opening pool."""
import copy
import json
import subprocess
import sys

from run_rating import digest, read, write_new
from uci_client import ROOT


def main():
    original = ROOT / "artifacts/research/iir-plan-v1.json"
    path = ROOT / "artifacts/research/iir-plan-v2.json"
    plan = copy.deepcopy(read(original))
    assert plan["generation"]["exclude_data"][-1] == "artifacts/data/endgame-diagnostic-v1.jsonl"
    plan["generation"]["exclude_data"][-1] = "artifacts/data/endgame-diagnostic-512-v1.jsonl"
    plan["status"] = "Missing dataset filename corrected after unit/rule checks, before fixture generation or opening/tactical/match queries"
    plan["previous_plan"] = {"path":original.relative_to(ROOT).as_posix(),"sha256":digest(original)}
    plan["correction"] = "Only the intended512-position development dataset pathname changes; all algorithms, budgets, seeds and gates remain exactly as originally declared. Original plan retained."
    write_new(path,plan)
    generation = plan["generation"]
    command = [sys.executable,str(ROOT / "scripts/generate_openings.py")]
    for key in ("positions","attempts","seed","plies","nodes","verify_nodes","max_cp"):
        command += ["--" + key.replace("_","-"),str(generation[key])]
    for data in generation["exclude_data"]: command += ["--exclude",str(ROOT / data)]
    for suite in generation["exclude_suites"]: command += ["--exclude-suite",str(ROOT / suite)]
    command += ["--output",str(ROOT / "tests/fixtures/iir-parent-v1.json")]
    subprocess.run(command,check=True)
    parent_path = ROOT / "tests/fixtures/iir-parent-v1.json"; parent = read(parent_path)
    assert len(parent["openings"]) == 448
    partitions = {"30ms":range(256),"100ms":range(256,320),"rating":range(320,448),
                  "behavior":[*range(32),*range(256,288)]}
    for role,indices in partitions.items():
        subset = copy.deepcopy(parent); subset["openings"] = [parent["openings"][i] for i in indices]
        subset.update({"experiment_role":role,"parent_indices":list(indices),
            "parent_suite":{"path":parent_path.relative_to(ROOT).as_posix(),"sha256":digest(parent_path)},"splitter_sha256":digest(__file__)})
        write_new(ROOT / f"tests/fixtures/iir-{role}-v1.json",subset)
    for role in ("parent","30ms","100ms","rating","behavior"):
        subprocess.run([sys.executable,str(ROOT / "scripts/audit_openings.py"),str(ROOT / f"tests/fixtures/iir-{role}-v1.json"),
            "--output",str(ROOT / f"artifacts/validation/iir-{role}-audit.json")],check=True)
    print(json.dumps({"frozen":True,"pairs":320,"reserved_rating_pairs":128,"plan_sha256":digest(path)}))


if __name__ == "__main__": main()
