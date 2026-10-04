"""Check completed match resources, exact models and frozen opening partitions."""
import json
import pathlib
import shutil

from match import frozen_source_manifest
from run_rating import digest, read, write_new
from uci_client import ROOT


def main():
    plan_path = ROOT / "artifacts/research/deep-turn-plan-v1.json"; plan = read(plan_path)
    state = read(ROOT / "artifacts/research/deep-turn-match-execution-v1.json")
    assert state["status"] == "complete" and state["plan_sha256"] == digest(plan_path)
    preflight = read(ROOT / "artifacts/validation/deep-turn-preflight.json")
    source = frozen_source_manifest(str(ROOT / plan["baseline_source"]),plan["baseline_sha256"])
    assert source is not None
    parent = read(ROOT / "tests/fixtures/deep-turn-parent-v1.json")["openings"]
    checked = []
    for phase in state["phases"]:
        label = phase["label"]
        fixture_path = ROOT / f"tests/fixtures/deep-turn-{label}-v1.json"; fixture = read(fixture_path)
        indices = fixture["parent_indices"]
        start,count = (0,64) if label == "classical-30ms" else (64,64) if label == "control-30ms" else (128,32)
        assert indices == list(range(start,start+count)) and fixture["openings"] == parent[start:start+count]
        prefix = ROOT / f"artifacts/matches/deep-turn-{label}"; report = read(str(prefix)+".json")
        assert digest(str(prefix)+".json") == phase["report_sha256"]
        assert report["pairs_requested"] == count and len(report["games"]) == 2*count
        assert report["opening_suite"]["sha256"] == digest(fixture_path)
        seconds = plan["matches"]["long_seconds_per_move"] if label == "classical-100ms" else plan["matches"]["seconds_per_move"]
        assert report["limit"] == {"seconds_per_move":seconds}
        assert report["max_plies"] == plan["matches"]["resources"]["max_additional_plies"]
        for role in ("candidate","opponent"):
            assert report[role+"_binary_sha256"] == plan["baseline_sha256"]
            assert report[role+"_source_manifest"] == source
            options = report[role+"_options"]
            for key in ("Threads","Hash","Move Overhead"): assert options[key] == plan["matches"]["resources"][key]
            model_role = "candidate" if role == "candidate" else "control" if label == "control-30ms" else None
            if model_role is not None:
                model = preflight["models"][model_role]
                assert report[role+"_model_sha256"] == model["sha256"] == digest(pathlib.Path(options["EvalFile"]))
            else:
                assert role+"_model_sha256" not in report and options.get("EvalFile","<classical>") == "<classical>"
        for game in report["games"]:
            opening = fixture["openings"][game["pair"]-1]
            expected = opening["moves"] if isinstance(opening,dict) else opening
            assert game["opening"] == expected
            assert game["plies"] <= len(expected.split())+report["max_plies"]
        checked.append({"phase":label,"games":len(report["games"]),"report_sha256":digest(str(prefix)+".json"),
            "opening_sha256":digest(fixture_path),"seconds_per_move":seconds})
    source_dir = ROOT / "artifacts/research/deep-turn-match-metadata-source-v1"; source_dir.mkdir(exist_ok=False)
    shutil.copy2(__file__,source_dir / pathlib.Path(__file__).name)
    result = {"schema":1,"passed":True,"post_match_audit":True,"script_sha256":digest(__file__),
        "plan_sha256":digest(plan_path),"phases":checked,
        "scope":"Exact applied resource options, evaluator fingerprints, frozen source manifests, time controls, ply caps and opening partitions. Independent PGN legality/outcome audits are retained separately. No gate changes or tuning."}
    write_new(ROOT / "artifacts/validation/deep-turn-match-metadata-audit-v1.json",result)
    print(json.dumps(result),flush=True)


if __name__ == "__main__": main()
