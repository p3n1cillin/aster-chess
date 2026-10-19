"""Freeze the completed endgame diagnostic pipeline and all referenced evidence."""
from research_reference import research_text
import json
import pathlib
import shutil

from generate_endgame_diagnostic import digest
from uci_client import ROOT


def reference(path):
    path = pathlib.Path(path)
    return {"path": path.as_posix(), "sha256": digest(ROOT / path)}


def main():
    directory = ROOT / "artifacts/research/endgame-diagnostic-pipeline-final"
    final = ROOT / "artifacts/research/endgame-diagnostic-experiment-manifest.json"
    if directory.exists() or final.exists(): raise ValueError("Preserve prior snapshots")
    data = pathlib.Path("artifacts/data/endgame-diagnostic-512-v1.jsonl")
    manifest = json.loads((ROOT / (str(data) + ".manifest.json")).read_text())
    assert manifest["complete"] and manifest["positions_written"] == 512 and manifest["data_sha256"] == digest(ROOT / data)
    assert manifest["source_pgn_sha256"] == digest(ROOT / (str(data) + ".source.pgn"))
    for entry in manifest["exclusions"]: assert digest(ROOT / entry["path"]) == entry["sha256"]
    teacher = manifest["teacher"]
    assert digest(ROOT / teacher["executable"]) == teacher["executable_sha256"]
    audit_path = pathlib.Path("artifacts/validation/endgame-diagnostic-audit.json")
    audit = json.loads((ROOT / audit_path).read_text())
    assert audit["passed"] and audit["positions"] == 512 and audit["source_games"] == 187 and audit["source_unresolved"] == 7
    score_path = pathlib.Path("artifacts/validation/endgame-diagnostic-scores.json")
    scored = json.loads((ROOT / score_path).read_text())
    assert scored["data_sha256"] == digest(ROOT / data) and scored["suite_sha256"] == digest(ROOT / "tests/fixtures/endgames-v1.json")
    for config in scored["configs"]:
        assert digest(ROOT / config["engine"]) == config["binary_sha256"]
        assert digest(ROOT / config["source"]) == config["source_manifest"]["sha256"]
        if config.get("model"): assert digest(ROOT / config["model"]) == config["model_sha256"]
    recheck = json.loads((ROOT / "artifacts/validation/endgame-diagnostic-label-recheck.json").read_text())
    assert recheck["summary"]["positions"] == 128 and recheck["summary"]["fixture_bestmove_agreement"] == 16
    directory.mkdir()
    names = ("generate_endgame_diagnostic.py", "audit_endgame_diagnostic.py", "score_endgame_diagnostic.py", "recheck_endgame_labels.py",
             "preserve_endgame_diagnostic.py", "tactics.py", "match.py", "neural_format.py", "uci_client.py", "verify.py")
    sources = []
    for name in names:
        path = pathlib.Path("scripts") / name
        shutil.copy2(ROOT / path, directory / name)
        sources.append(reference(path))
    (directory / "manifest.json").write_text(json.dumps({"source_files": sources}, indent=2) + "\n")
    paths = [data, str(data) + ".manifest.json", str(data) + ".source.pgn", "tests/fixtures/endgames-v1.json", "docs/ENDGAME-DIAGNOSTIC.md",
             "artifacts/research/geometric-threats-experiment-manifest.json", "artifacts/research/pair-loss-experiment-manifest.json",
             "artifacts/research/turn-static-experiment-manifest.json", research_text('opponent_manifest')]
    paths += [research_text('archive.reference_source_prefix') + name for name in ("evaluate.cpp", "score.cpp", "uci.cpp")]
    paths.extend(p.relative_to(ROOT) for p in (ROOT / "artifacts/validation").glob("endgame-diagnostic*.json"))
    paths.extend(p.relative_to(ROOT) for p in (ROOT / "artifacts/validation").glob("endgame-diagnostic*.txt"))
    result = {"schema": 1, "pipeline": reference(directory.relative_to(ROOT) / "manifest.json"),
              "artifacts": [reference(path) for path in sorted(set(map(str, paths)))],
              "interpretation": "Fresh native-label and source-outcome diagnostics; no new training/default or strength claim. Seven source games remain unresolved."}
    final.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"scripts": len(sources), "artifacts": len(result["artifacts"])}))


if __name__ == "__main__": main()
