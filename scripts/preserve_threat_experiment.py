"""Bind a completed threat experiment to immutable sources and audited results."""
from research_reference import research_text
import hashlib
import json
import pathlib
import shutil

from uci_client import ROOT


def reference(path):
    path = pathlib.Path(path)
    return {"path": path.as_posix(), "sha256": hashlib.sha256((ROOT / path).read_bytes()).hexdigest()}


def main():
    destination = ROOT / "artifacts/research/geometric-threats-pipeline-final"
    final = ROOT / "artifacts/research/geometric-threats-experiment-manifest.json"
    if destination.exists() or final.exists(): raise ValueError("Preserve earlier experiment snapshots")
    match_prefix = pathlib.Path("artifacts/matches/geometric-threats-vs-0.6.0-v5-30ms")
    match = json.loads((ROOT / (str(match_prefix) + ".json")).read_text())
    if len(match["games"]) != 64 or match["pairs_requested"] != 32 or match["unresolved"] or match["forfeits"]:
        raise ValueError("Match incomplete or unsuccessful")
    audit = json.loads((ROOT / (str(match_prefix) + ".audit.json")).read_text())
    if audit["status"] != "passed" or audit["games"] != 64:
        raise ValueError("Complete PGN audit missing")
    engine_manifests = ["artifacts/research/geometric-threats-source/manifest.json",
                        "artifacts/research/king-context-release-source/manifest.json",
                        "artifacts/research/geometric-control-source/manifest.json"]
    engines = []
    for i, path in enumerate(engine_manifests):
        manifest = json.loads((ROOT / path).read_text())
        if reference(manifest["binary"])["sha256"] != manifest["binary_sha256"]:
            raise ValueError("Binary changed after matching")
        for entry in manifest["source_files"]:
            if reference(pathlib.Path(path).parent / entry["path"])["sha256"] != entry["sha256"]:
                raise ValueError("Frozen engine source changed")
        if i < 2:
            role = "candidate" if i == 0 else "opponent"
            if match[role + "_binary_sha256"] != manifest["binary_sha256"] or match[role + "_source_manifest"]["sha256"] != reference(path)["sha256"]:
                raise ValueError("Match differs from frozen build")
        engines.append(reference(path))
    fit_path = pathlib.Path("artifacts/training/geometric-threats-v1/fit.json")
    fit = json.loads((ROOT / fit_path).read_text())
    if reference(fit["arguments"]["data"])["sha256"] != fit["data_sha256"]:
        raise ValueError("Fit dataset changed")
    if reference(fit_path.parent / "features.npz")["sha256"] != fit["features_sha256"]:
        raise ValueError("Extracted feature evidence changed")
    for entry in fit["source_files"]:
        if reference(fit_path.parent / "source" / entry["name"])["sha256"] != entry["sha256"]:
            raise ValueError("Fit source changed")
    destination.mkdir()
    sources = []
    for name in ("fit_threats.py", "verify_threats.py", "train_network.py", "neural_format.py", "uci_client.py",
                 "generate_openings.py", "audit_openings.py", "freeze_engine_source.py", "verify.py", "tactics.py",
                 "compare_evaluation.py", "compare_search.py", "benchmark.py", "match.py", "audit_match.py",
                 "analyze_match.py", "preserve_threat_experiment.py"):
        path = pathlib.Path("scripts") / name
        shutil.copy2(ROOT / path, destination / name)
        sources.append(reference(path))
    (destination / "manifest.json").write_text(json.dumps({"source_files": sources}, indent=2) + "\n")
    paths = ["docs/GEOMETRIC-THREATS.md", "tests/fixtures/openings-v5.json", "tests/fixtures/tactics-v1.json",
             "tests/fixtures/tactics-quiet-v1.json", "artifacts/research/turn-static-experiment-manifest.json",
             research_text('opponent_manifest'), fit_path, fit_path.parent / "features.npz"]
    paths.extend(p.relative_to(ROOT) for p in (ROOT / fit_path.parent / "source").glob("*.py"))
    paths.extend(p.relative_to(ROOT) for p in (ROOT / "artifacts/data").glob("teacher-turn-60k-static-v1*"))
    paths.extend(p.relative_to(ROOT) for p in (ROOT / "artifacts/validation").glob("geometric-*.json"))
    paths.extend(p.relative_to(ROOT) for p in (ROOT / "artifacts/validation").glob("geometric-*.txt"))
    paths.extend(p.relative_to(ROOT) for p in (ROOT / "artifacts/benchmarks").glob("geometric-*.json"))
    paths.extend(str(match_prefix) + ending for ending in (".json", ".pgn", ".audit.json", ".analysis.json"))
    result = {"schema": 1, "engine_sources": engines, "pipeline": reference(destination.relative_to(ROOT) / "manifest.json"),
              "artifacts": [reference(path) for path in sorted(set(map(str, paths)))],
              "interpretation": research_text('preserve_threat_experiment.interpretation')}
    final.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"engines": len(engines), "artifacts": len(result["artifacts"])}))


if __name__ == "__main__": main()
