"""Freeze the completed turn-aware experiment's sources and provenance links."""
import hashlib
import json
import pathlib
import shutil

from uci_client import ROOT


def reference(path):
    path = pathlib.Path(path)
    return {"path": path.as_posix(), "sha256": hashlib.sha256((ROOT / path).read_bytes()).hexdigest()}


def main():
    target = ROOT / "artifacts/research/turn-aware-pipeline-final"
    if target.exists():
        raise ValueError("Preserve existing snapshots")
    target.mkdir()
    names = ("train_network.py", "neural_format.py", "augment_turn_data.py", "audit_turn_pairs.py",
             "score_turn_diagnostic.py", "diagnose_turn_dependence.py", "audit_training_data.py",
             "add_classical_scores.py", "verify_network.py", "verify.py", "match.py", "audit_match.py",
             "analyze_match.py", "tactics.py", "compare_search.py", "uci_client.py", "preserve_turn_experiment.py")
    sources = []
    for name in names:
        path = pathlib.Path("scripts") / name
        shutil.copy2(ROOT / path, target / name)
        sources.append(reference(path))
    (target / "manifest.json").write_text(json.dumps({"source_files": sources,
        "note": "Final pipeline snapshot. Exact trainers are also preserved separately per model."}, indent=2) + "\n")
    models, matches = [], []
    candidate_manifest = pathlib.Path("artifacts/research/turn-aware-source/manifest.json")
    baseline_manifest = pathlib.Path("artifacts/research/king-context-release-source/manifest.json")
    for manifest_path in (candidate_manifest, baseline_manifest):
        manifest = json.loads((ROOT / manifest_path).read_text())
        if reference(manifest["binary"])["sha256"] != manifest["binary_sha256"]:
            raise ValueError("Binary fingerprint mismatch")
        for entry in manifest["source_files"]:
            frozen = ROOT / manifest_path.parent / entry["path"]
            if not frozen.exists(): frozen = ROOT / manifest_path.parent / pathlib.Path(entry["path"]).name
            if hashlib.sha256(frozen.read_bytes()).hexdigest() != entry["sha256"]:
                raise ValueError("Frozen source mismatch")
    for name in ("hybrid", "standalone", "paired-hybrid", "paired-standalone"):
        directory = pathlib.Path(f"artifacts/training/turn-aware-{name}-v1")
        report = json.loads((ROOT / directory / "training.json").read_text())
        if reference(directory / "model.ann")["sha256"] != report["model_sha256"]:
            raise ValueError("Trained model mismatch")
        if reference(report["arguments"]["data"])["sha256"] != report["dataset_sha256"]:
            raise ValueError("Training dataset mismatch")
        for entry in report["source_files"]:
            if reference(directory / "source" / entry["name"])["sha256"] != entry["sha256"]:
                raise ValueError("Preserved trainer mismatch")
        models.append({"model": reference(directory / "model.ann"), "training": reference(directory / "training.json"),
                       "checkpoint": reference(directory / "checkpoint.pt"), "trainer_sources": report["source_files"]})
        prefix = f"artifacts/matches/turn-aware-{name}-vs-0.6.0-30ms"
        match = json.loads((ROOT / (prefix + ".json")).read_text())
        for role, manifest_path in (("candidate", candidate_manifest), ("opponent", baseline_manifest)):
            manifest = json.loads((ROOT / manifest_path).read_text())
            if match[role + "_binary_sha256"] != manifest["binary_sha256"]:
                raise ValueError("Match binary differs from preserved source")
            if match[role + "_source_manifest"]["sha256"] != reference(manifest_path)["sha256"]:
                raise ValueError("Match source manifest changed")
        if match["candidate_model_sha256"] != report["model_sha256"]:
            raise ValueError("Match model differs from trained artifact")
        if match["unresolved"] or match["forfeits"] or len(match["games"]) != 32:
            raise ValueError("Match incomplete or contains forfeits")
        # Match runner pins source manifests directly; bind their exact bytes again.
        matches.append({"report": reference(prefix + ".json"), "pgn": reference(prefix + ".pgn"),
                        "analysis": reference(prefix + ".analysis.json")})
    artifacts = ["artifacts/data/teacher-balanced-50k-v1.jsonl", "artifacts/data/teacher-balanced-50k-v1-classical.jsonl",
                 "artifacts/data/teacher-turn-augmented-60k-v1.jsonl", "artifacts/data/teacher-turn-augmented-60k-v1.jsonl.manifest.json",
                 "artifacts/data/teacher-turn-augmented-60k-v1-classical.jsonl",
                 "artifacts/data/teacher-turn-augmented-60k-v1-classical.jsonl.classical.json",
                 "artifacts/validation/teacher-turn-augmented-60k-v1.json", "artifacts/validation/teacher-turn-pairs-10k-v1.json",
                 "artifacts/validation/turn-dependence-128-v1.json", "tests/fixtures/openings-v4.json",
                 "tests/fixtures/tactics-v1.json", "tests/fixtures/tactics-quiet-v1.json", "tools/stockfish/manifest.json"]
    artifacts.extend(p.relative_to(ROOT).as_posix() for p in (ROOT / "artifacts/validation").glob("turn-aware*.json"))
    result = {"schema": 1, "candidate_source": reference(candidate_manifest), "baseline_source": reference(baseline_manifest),
              "pipeline_source": reference(target.relative_to(ROOT) / "manifest.json"), "models": models,
              "matches": matches, "artifacts": [reference(p) for p in sorted(set(artifacts))],
              "interpretation": "Independent optional runtime research; no selected neural default, Elo claim or Stockfish superiority."}
    output = ROOT / "artifacts/research/turn-aware-experiment-manifest.json"
    if output.exists(): raise ValueError("Preserve prior experiment manifest")
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"models": len(models), "matches": len(matches), "artifacts": len(result["artifacts"])}))


if __name__ == "__main__":
    main()
