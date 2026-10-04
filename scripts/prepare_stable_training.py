"""Freeze identical datasets/groups for the static versus stable-label ablation."""
import json
import pathlib
import random

from run_rating import digest, read, write_new
from uci_client import ROOT


def main():
    plan_path = ROOT / "artifacts/research/stable-endgame-plan-v1.json"; plan = read(plan_path)
    audit_path = ROOT / "artifacts/validation/stable-endgame-data-audit-v1.json"; audit = read(audit_path)
    assert audit["complete"] and audit["plan_sha256"] == digest(plan_path)
    for entry in audit["inputs"]: assert digest(ROOT / entry["path"]) == entry["sha256"]
    old = ROOT / plan["old_data"]; assert digest(old) == plan["old_data_sha256"]
    old_bytes = old.read_bytes(); assert old_bytes.endswith(b"\n")
    old_rows = [json.loads(line) for line in old_bytes.splitlines() if line.strip()]
    assert len(old_rows) == 60000 and max(row["game"] for row in old_rows) < 100000
    fresh_path = ROOT / "artifacts/data/stable-endgame-4096-v1.jsonl"
    fresh = [json.loads(line) for line in fresh_path.read_text().splitlines() if line.strip()]
    prior_path = ROOT / "artifacts/training/phase-output-v1/training.json"; prior = read(prior_path)
    assert prior["dataset_sha256"] == digest(old)
    old_validation = prior["validation_games"]
    assert len(old_validation) == 269
    new_groups = sorted({row["game"] for row in fresh})
    fresh_validation = sorted(random.Random(20261117).sample(new_groups,max(1,len(new_groups)//10)))
    split = {"schema":1,"validation_games":sorted(old_validation+fresh_validation),"old_validation_games":old_validation,
        "fresh_validation_games":fresh_validation,"fresh_seed":20261117,"prior_training_sha256":digest(prior_path),
        "plan_sha256":digest(plan_path),"old_data_sha256":digest(old),"fresh_data_sha256":digest(fresh_path),
        "selection":"Whole source-game split frozen before training. Original269 held-out games retained exactly."}
    split_path = ROOT / "artifacts/research/stable-endgame-split-v1.json"
    bundle_path = ROOT / "artifacts/research/stable-endgame-training-data-v1.json"
    destinations = {role: ROOT / f"artifacts/data/stable-endgame-{role}-64096-v1-classical.jsonl" for role in ("control","candidate")}
    if any(path.exists() for path in (split_path,bundle_path,*destinations.values(),
            *[pathlib.Path(str(path)+".classical.json") for path in destinations.values()])):
        raise ValueError("Preserve prior prepared data/split; no overwrite")
    write_new(split_path,split)
    datasets = {}
    for role,path in destinations.items():
        with path.open("xb") as stream:
            stream.write(old_bytes)
            for row in fresh:
                item = dict(row)
                item["score_white_cp"] = row["static_white_cp"] if role == "control" else row["verified"]["white_cp"]
                # Both raw labels and selection provenance are retained identically.
                stream.write((json.dumps(item,separators=(",",":"))+"\n").encode("utf-8"))
        assert path.read_bytes()[:len(old_bytes)] == old_bytes
        provenance = {"schema":1,"output_sha256":digest(path),"rows":64096,"old_rows":60000,"fresh_rows":4096,
            "old_data":{"path":plan["old_data"],"sha256":digest(old),"classical_provenance":read(pathlib.Path(str(old)+".classical.json"))},
            "fresh_classical_engine":{"path":plan["baseline"],"sha256":plan["baseline_sha256"],"source_manifest":plan["baseline_source"]},
            "fresh_data_sha256":digest(fresh_path),"data_audit_sha256":digest(audit_path),"plan_sha256":digest(plan_path)}
        write_new(str(path)+".classical.json",provenance)
        datasets[role] = {"path":path.relative_to(ROOT).as_posix(),"sha256":digest(path),
            "classical_provenance_sha256":digest(str(path)+".classical.json"),"output":f"artifacts/training/stable-endgame-{role}-v1"}
    control,candidate = [[json.loads(line) for line in path.read_text().splitlines() if line.strip()] for path in destinations.values()]
    differences = 0
    for index,(a,b) in enumerate(zip(control,candidate)):
        if index < 60000: assert a == b
        else:
            differences += a["score_white_cp"] != b["score_white_cp"]
            assert {k:v for k,v in a.items() if k != "score_white_cp"} == {k:v for k,v in b.items() if k != "score_white_cp"}
    write_new(bundle_path,{"schema":1,"complete":True,"plan_sha256":digest(plan_path),"preparer_sha256":digest(__file__),
        "data_audit_sha256":digest(audit_path),"split_path":split_path.relative_to(ROOT).as_posix(),"split_sha256":digest(split_path),
        "datasets":datasets,"positions":len(control),"old_rows_byte_identical":True,"different_fresh_targets":differences,
        "old_validation_games":len(old_validation),"fresh_games":len(new_groups),"fresh_validation_games":len(fresh_validation)})
    print(json.dumps(read(bundle_path)),flush=True)


if __name__ == "__main__": main()
