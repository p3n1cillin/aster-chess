"""Verify and freeze the completed KPK experiment, scripts and evidence."""
from research_reference import research_text
import hashlib
import json
import pathlib
import shutil

from uci_client import ROOT


def digest(path): return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
def read(path): return json.loads((ROOT / path).read_text(encoding="utf-8-sig"))
def reference(path):
    path = pathlib.Path(path)
    return {"path": path.as_posix(), "sha256": digest(ROOT / path)}


def check_engine(path):
    manifest = read(path); directory = (ROOT / path).parent
    assert digest(ROOT / manifest["binary"]) == manifest["binary_sha256"]
    for entry in manifest["source_files"]:
        assert digest(directory / entry["path"]) == entry["sha256"]
    return reference(path)


def main():
    directory = ROOT / "artifacts/research/kpk-pipeline-final"
    final = ROOT / "artifacts/research/kpk-experiment-manifest.json"
    if directory.exists() or final.exists(): raise ValueError("Preserve previous snapshots")
    candidate_path = "artifacts/research/kpk-source/manifest.json"
    baseline_path = "artifacts/research/king-context-release-source/manifest.json"
    control_path = "artifacts/research/kpk-control-source/manifest.json"
    engines = [check_engine(p) for p in (candidate_path, baseline_path, control_path)]
    candidate = read(candidate_path)["binary_sha256"]
    baseline = read(baseline_path)["binary_sha256"]
    dump = "artifacts/validation/kpk-generated-v1.bin"
    exhaustive = read("artifacts/validation/kpk-exhaustive-v1.json")
    certificate = read("artifacts/validation/kpk-conversion-certificate.json")
    runtime = read("artifacts/validation/kpk-runtime.json")
    for report in (exhaustive, certificate, runtime):
        assert report["passed"] and report["dump_sha256"] == digest(ROOT / dump)
    assert exhaustive["checked_entries"] == 196608 and exhaustive["discrepancies"] == []
    assert certificate["winning_states"] == exhaustive["counts"]["wins"] == 111282
    assert runtime["engine_sha256"] == candidate and runtime["baseline_sha256"] == baseline
    oracle_path = "tools/syzygy-development-v1/manifest.json"
    assert exhaustive["oracle_manifest_sha256"] == digest(ROOT / oracle_path)
    oracle = read(oracle_path)
    oracle_files = []
    for entry in oracle["files"]:
        p = pathlib.Path(oracle_path).parent / entry["name"]
        assert digest(ROOT / p) == entry["sha256"]
        oracle_files.append(p)
    choices = read("artifacts/validation/kpk-move-choices.json")
    assert choices["complete"] and len(choices["positions"]) == 256
    assert choices["dump_sha256"] == digest(ROOT / dump)
    assert choices["cases_sha256"] == digest(ROOT / "artifacts/validation/kpk-move-choices.json.cases.json")
    assert [e["sha256"] for e in choices["engines"]] == [candidate, baseline]
    for name, count in (("kpk-tactics", 32), ("kpk-quiet-tactics", 32), ("kpk-endgame-tactics", 13)):
        report = read("artifacts/validation/" + name + ".json")
        assert report["binary_sha256"] == candidate and report["solved"] == count
    for name, binary in (("kpk-rules", candidate), ("kpk-control-rules", read(control_path)["binary_sha256"])):
        report = read("artifacts/validation/" + name + ".json")
        assert report["status"] == "passed" and report["binary_sha256"] == binary
    prefix = "artifacts/matches/kpk-vs-0.6.0-v5-30ms"
    match = read(prefix + ".json"); audit = read(prefix + ".audit.json")
    assert len(match["games"]) == 2 * match["pairs_requested"] == 64
    assert match["forfeits"] == match["unresolved"] == 0 and audit["status"] == "passed"
    assert match["candidate_binary_sha256"] == candidate and match["opponent_binary_sha256"] == baseline
    for role in ("candidate", "opponent"):
        entry = match[role + "_source_manifest"]
        assert digest(entry["path"]) == entry["sha256"]
    assert digest(match["opening_suite"]["path"]) == match["opening_suite"]["sha256"]
    for name, expected in (("kpk-engine-tests", "46 passed, 0 failed."), ("kpk-control-engine-tests", "45 passed, 0 failed.")):
        assert expected in (ROOT / ("artifacts/validation/" + name + ".txt")).read_text(encoding="utf-8-sig")
    names = ("verify_kpk.py", "certify_kpk.py", "verify_kpk_runtime.py", "verify_kpk_choices.py",
             "preserve_kpk_experiment.py", "kpk_match_coverage.py", "freeze_engine_source.py", "tactics.py", "match.py",
             "audit_match.py", "analyze_match.py", "uci_client.py", "verify.py")
    directory.mkdir()
    sources = []
    for name in names:
        p = pathlib.Path("scripts") / name
        shutil.copy2(ROOT / p, directory / name); sources.append(reference(p))
    (directory / "manifest.json").write_text(json.dumps({"source_files": sources}, indent=2) + "\n")
    paths = [dump, oracle_path, "artifacts/research/kpk-plan-v1.json", "docs/KPK.md",
             "tests/fixtures/openings-v5.json", "tests/fixtures/endgames-v1.json"] + oracle_files
    paths += [e["path"] for e in engines]
    paths += [read(p)["binary"] for p in (candidate_path, baseline_path, control_path)]
    paths += [p.relative_to(ROOT) for p in (ROOT / "artifacts/validation").glob("kpk*") if p.is_file()]
    paths += [p.relative_to(ROOT) for p in (ROOT / "artifacts/benchmarks").glob("kpk*") if p.is_file()]
    paths += [prefix + suffix for suffix in (".json", ".pgn", ".audit.json", ".analysis.json")]
    result = {"schema": 1, "pipeline": reference(directory.relative_to(ROOT) / "manifest.json"),
              "engines": engines, "artifacts": [reference(p) for p in sorted(set(map(str, paths)))],
              "interpretation": research_text('preserve_kpk_experiment.interpretation')}
    final.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"scripts": len(sources), "artifacts": len(result["artifacts"])}))


if __name__ == "__main__": main()
