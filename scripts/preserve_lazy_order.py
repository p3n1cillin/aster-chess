"""Re-audit and freeze the complete deferred-capture experiment, including failure."""
from research_reference import research_text
import datetime
import json
import pathlib
import shutil
import subprocess
import sys

from assess_lazy_order import assess
from match import frozen_source_manifest
from run_rating import digest, read, write_new
from uci_client import ROOT


def reference(path):
    path = pathlib.Path(path)
    return {"path": path.as_posix(), "sha256": digest(ROOT / path)}


def main():
    final = ROOT / "artifacts/research/lazy-order-experiment-v1-manifest.json"
    pipeline = ROOT / "artifacts/research/lazy-order-pipeline-final"
    rating_path = ROOT / "artifacts/ratings/session-20261004-lazy-order.json"
    if any(p.exists() for p in (final, pipeline, rating_path)): raise ValueError("Preserve previous snapshots")
    state = read(ROOT / "artifacts/research/lazy-order-execution-v1.json")
    assert state["status"] == "complete" and not state["eligible_for_engineering_promotion"]
    assert [p["label"] for p in state["phases"]] == ["vs-0.7.4-30ms", "vs-0.7.4-100ms"]
    assert sum(p["games"] for p in state["phases"]) == 160
    assessment = read(ROOT / "artifacts/research/lazy-order-assessment-v1.json")
    assert assessment == assess()
    assert not assessment["amended_gates"]["timing_at_least_5_percent"]
    paths = []
    for phase in state["phases"]:
        path = ROOT / phase["report"]; prefix = path.with_suffix("")
        assert digest(path) == phase["report_sha256"]
        command = [sys.executable, str(ROOT / "scripts/audit_match.py"), str(prefix)]
        replay = json.loads(subprocess.run(command, text=True, capture_output=True, check=True).stdout)
        assert replay == read(path.with_suffix(".audit.json"))
        paths += [p.relative_to(ROOT).as_posix() for p in path.parent.glob(prefix.name + ".*") if p.is_file()]
    plan = read(ROOT / "artifacts/research/lazy-order-plan-v1.json")
    manifests = [plan["candidate_source"], plan["baseline_source"],
                 "artifacts/research/lazy-order-default-source/manifest.json",
                 "artifacts/research/lazy-order-profile-source/manifest.json",
                 "artifacts/research/lazy-order-baseline-profile-source/manifest.json"]
    for manifest_path in manifests:
        manifest = read(ROOT / manifest_path)
        frozen_source_manifest(str(ROOT / manifest_path), manifest["binary_sha256"])
        assert digest(ROOT / manifest["binary"]) == manifest["binary_sha256"]
        paths += [manifest_path, manifest["binary"]]
        directory = (ROOT / manifest_path).parent
        paths += [(directory / r["path"]).relative_to(ROOT).as_posix() for r in manifest["source_files"]]
        paths += [p.relative_to(ROOT).as_posix() for p in (ROOT / manifest["binary"]).parent.glob("Aster.*") if p.is_file()]
    current_rules = read(ROOT / "artifacts/validation/lazy-order-default-rules.json")
    assert current_rules["status"] == "passed"
    default_source = read(ROOT / "artifacts/research/lazy-order-default-source/manifest.json")
    assert current_rules["binary_sha256"] == default_source["binary_sha256"]
    default_comparison = read(ROOT / "artifacts/benchmarks/lazy-order-default-vs-rated-depth8.json")
    assert len(default_comparison["positions"]) == 80 and all(r["same_move"] and r["same_score"] and r["candidate"]["nodes"] == r["opponent"]["nodes"] for r in default_comparison["positions"])
    assert "49 passed, 0 failed." in (ROOT / "artifacts/validation/lazy-order-default-engine-tests.txt").read_text(encoding="utf-8-sig")
    benchmark = (ROOT / "artifacts/benchmarks/lazy-order-default-depth7.json").read_text(encoding="utf-8-sig").splitlines()
    assert json.loads(benchmark[-1])["totalNodes"] == 146772
    original_rating_path = "artifacts/ratings/session-20261004-calibration-v1.json"
    previous_rating = read(ROOT / original_rating_path)
    write_new(rating_path, {"schema": 1, "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                           "status": "last measured reference retained; experimental candidate unrated", "public_elo": None,
                           "last_measured_local_rating": previous_rating["numeric_local_rating"],
                           "primary_95_percent_local_interval": previous_rating["primary_95_percent_local_interval"],
                           "local_scale": previous_rating["local_scale"], "rated_engine_sha256": previous_rating["engine_sha256"],
                           "rated_engine": previous_rating["engine"], "rated_version": previous_rating["engine_name"],
                           "reference_record": reference(original_rating_path), "candidate_sha256": plan["candidate_sha256"],
                           "candidate_general_regression": assessment["matches"], "failed_gates": assessment["failed_gates"],
                           "reason": "Deferred-scoring candidate fails declared speed gate and remains opt-in. The old rating stays attached to its exact frozen engine; no Elo inferred from regression or microbenchmark."})
    pipeline.mkdir(); names = ("match.py", "audit_match.py", "run_lazy_order.py", "assess_lazy_order.py", "time_lazy_order.py",
        "verify_lazy_order.py", "verify_lazy_order_openings.py", "split_lazy_order_suite.py", "generate_openings.py", "audit_openings.py",
        "analyze_rating.py", "run_rating.py", "uci_client.py", "verify.py", "tactics.py", "compare_search.py", "freeze_engine_source.py", "preserve_lazy_order.py")
    entries = []
    for name in names:
        shutil.copy2(ROOT / "scripts" / name, pipeline / name)
        entries.append(reference(pipeline.relative_to(ROOT) / name))
    write_new(pipeline / "manifest.json", {"source_files": entries})
    for name in ("docs/DEFERRED-CAPTURES.md", "docs/RATING.md", "README.md", "ROADMAP.md", "artifacts/PROGRESS.md"):
        shutil.copy2(ROOT / name, pipeline / pathlib.Path(name).name)
    for pattern, directory in (("lazy-order-*", "tests/fixtures"), ("lazy-order-*", "artifacts/validation"),
                               ("lazy-order-*", "artifacts/tactics"), ("lazy-order-*", "artifacts/benchmarks")):
        paths += [p.relative_to(ROOT).as_posix() for p in (ROOT / directory).glob(pattern) if p.is_file()]
    for name in ("lazy-order-pipeline-start", "lazy-order-pipeline-final"):
        paths += [p.relative_to(ROOT).as_posix() for p in (ROOT / "artifacts/research" / name).iterdir() if p.is_file()]
    paths += ["artifacts/research/lazy-order-plan-v1.json", "artifacts/research/lazy-order-plan-amendment-v1.json",
              "artifacts/research/lazy-order-execution-v1.json", "artifacts/research/lazy-order-assessment-v1.json",
              rating_path.relative_to(ROOT).as_posix(), original_rating_path,
              "artifacts/research/rating-experiment-v1-manifest.json", research_text('opponent_manifest')]
    start_manifest = ROOT / "artifacts/research/lazy-order-pipeline-start/manifest.json"
    for entry in read(start_manifest)["source_files"]: assert digest(start_manifest.parent / entry["path"]) == entry["sha256"]
    write_new(final, {"schema": 1, "games": 160, "artifacts": [reference(p) for p in sorted(set(paths))],
                      "candidate_promoted": False, "reserved_rating_pairs": 128, "reserved_rating_queried_by_aster": False,
                      "interpretation": research_text('preserve_lazy_order.interpretation')})
    print(json.dumps({"games": 160, "artifacts": len(read(final)["artifacts"]), "candidate_promoted": False, "manifest_sha256": digest(final)}))


if __name__ == "__main__": main()
