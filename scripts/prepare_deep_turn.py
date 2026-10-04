"""Freeze one identical two-sided dataset and inherited whole-game split."""
import json
import pathlib

from run_rating import digest, read, write_new
from uci_client import ROOT


def main():
    plan_path = ROOT / "artifacts/research/deep-turn-plan-v1.json"; plan = read(plan_path)
    audit_path = ROOT / "artifacts/validation/deep-turn-data-audit-v1.json"; audit = read(audit_path)
    assert audit["complete"] and audit["checks_passed"] and audit["plan_sha256"] == digest(plan_path)
    for entry in audit["inputs"]: assert digest(ROOT / entry["path"]) == entry["sha256"]
    assert read(ROOT / "artifacts/validation/deep-turn-pair-tests-v1.json")["passed"]
    assert read(ROOT / "artifacts/validation/deep-turn-legacy-control-check.json")["passed"]
    old = ROOT / plan["old_data"]; assert digest(old) == plan["old_data_sha256"]
    old_bytes = old.read_bytes(); assert old_bytes.endswith(b"\n")
    old_rows = [json.loads(line) for line in old_bytes.splitlines() if line.strip()]; assert len(old_rows) == 60000
    pairs_path = ROOT / "artifacts/data/deep-turn-pairs-v1.jsonl"
    pairs = [json.loads(line) for line in pairs_path.read_text().splitlines() if line.strip()]
    assert len(pairs) == audit["pairs"]
    output = ROOT / "artifacts/data/deep-turn-training-v1-classical.jsonl"
    split_path = ROOT / "artifacts/research/deep-turn-split-v1.json"
    bundle_path = ROOT / "artifacts/research/deep-turn-training-data-v1.json"
    if any(path.exists() for path in (output,pathlib.Path(str(output)+".classical.json"),split_path,bundle_path)):
        raise ValueError("Preserve previous/partial prepared data")
    prior = read(ROOT / plan["prior_split"]); assert digest(ROOT / plan["prior_split"]) == plan["prior_split_sha256"]
    groups = {pair["parent"]["game"] for pair in pairs}
    old_validation = prior["old_validation_games"]; assert len(old_validation) == 269
    fresh_validation = sorted(groups & set(prior["fresh_validation_games"]))
    split = {"schema":1,"validation_games":sorted(old_validation+fresh_validation),"old_validation_games":old_validation,
        "fresh_validation_games":fresh_validation,"prior_split_sha256":plan["prior_split_sha256"],"plan_sha256":digest(plan_path),
        "policy":"Eligible groups retain their already-frozen partition; absent groups removed, no present held-out group moved to training."}
    write_new(split_path,split)
    with output.open("xb") as destination:
        destination.write(old_bytes)
        for pair in pairs:
            white = dict(pair["parent"]); white["score_white_cp"] = white["verified"]["white_cp"]
            black = dict(pair["counter"])
            assert white["fen"].split()[1] == "w" and black["fen"].split()[1] == "b"
            for row in (white,black): destination.write((json.dumps(row,separators=(",",":"))+"\n").encode())
    assert output.read_bytes()[:len(old_bytes)] == old_bytes
    provenance = {"schema":1,"output_sha256":digest(output),"old_rows":60000,"fresh_rows":2*len(pairs),
        "old_data":{"path":plan["old_data"],"sha256":digest(old),"classical_provenance":read(str(old)+".classical.json")},
        "fresh_classical_engine":{"path":plan["baseline"],"sha256":plan["baseline_sha256"],"source_manifest":plan["baseline_source"]},
        "pairs_sha256":digest(pairs_path),"data_audit_sha256":digest(audit_path),"plan_sha256":digest(plan_path)}
    write_new(str(output)+".classical.json",provenance)
    all_rows = [json.loads(line) for line in output.read_text().splitlines() if line.strip()]
    # Exercise the actual trainer's partition and marker contract before either
    # model runs; every pair must stay entirely in its inherited group.
    from train_network import pair_partitions
    partitions = pair_partitions(all_rows,set(split["validation_games"]))
    assert len(partitions["old_training"]) == 9022 and len(partitions["old_validation"]) == 978
    assert len(partitions["fresh_training"]) == audit["training_pairs"] and len(partitions["fresh_validation"]) == audit["heldout_pairs"]
    result = {"schema":1,"complete":True,"plan_sha256":digest(plan_path),"preparer_sha256":digest(__file__),
        "data_audit_sha256":digest(audit_path),"data":output.relative_to(ROOT).as_posix(),"data_sha256":digest(output),
        "classical_provenance_sha256":digest(str(output)+".classical.json"),"split_path":split_path.relative_to(ROOT).as_posix(),
        "split_sha256":digest(split_path),"positions":len(all_rows),"old_rows_byte_identical":True,
        "fresh_side_counts":{"w":len(pairs),"b":len(pairs)},"old_validation_games":len(old_validation),"fresh_validation_games":len(fresh_validation),
        "training_pairs":{group:len(values) for group,values in partitions.items()},
        "outputs":{role:f"artifacts/training/deep-turn-{role}-v1" for role in ("control","candidate")}}
    write_new(bundle_path,result); print(json.dumps(result),flush=True)


if __name__ == "__main__": main()
