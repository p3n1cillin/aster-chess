"""Read the immutable relation plan together with its separately frozen runtime."""
from run_rating import digest, read
from uci_client import ROOT


def load_plan():
    path = ROOT / "artifacts/research/relations-plan-v1.json"
    plan = read(path)
    runtime = read(ROOT / "artifacts/research/relations-runtime-v1.json")
    assert runtime["plan_sha256"] == digest(path)
    assert digest(ROOT / runtime["baseline"]) == runtime["baseline_sha256"]
    assert digest(ROOT / runtime["baseline_source"]) == runtime["source_manifest_sha256"]
    return {**plan, **{key:runtime[key] for key in ("baseline","baseline_sha256","baseline_source")}}
