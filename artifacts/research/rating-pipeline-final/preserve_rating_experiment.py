"""Independently re-audit and preserve the bounded local calibration evidence."""
import json
import pathlib
import shutil
import subprocess
import sys

from run_rating import digest, read, write_new
from uci_client import ROOT


def reference(path):
    path = pathlib.Path(path)
    return {"path": path.as_posix(), "sha256": digest(ROOT / path)}


def main():
    target = ROOT / "artifacts/research/rating-pipeline-final"
    final = ROOT / "artifacts/research/rating-experiment-v1-manifest.json"
    if target.exists() or final.exists(): raise ValueError("Preserve existing evidence; do not overwrite")
    rating_path = "artifacts/ratings/session-20261004-calibration-v1.json"
    rating = read(ROOT / rating_path); execution = read(ROOT / "artifacts/ratings/calibration-v1-execution.json")
    assert execution["status"] == "complete" and rating["all_games_audited"] == 416
    rules = read(ROOT / "artifacts/validation/rating-session-rules.json")
    assert rules["status"] == "passed" and rules["positions_checked"] == 1614
    assert rules["binary_sha256"] == rating["engine_sha256"]
    assert "49 passed, 0 failed." in (ROOT / "artifacts/validation/rating-session-engine-tests.txt").read_text(encoding="utf-8-sig")
    for role in ("match", "analysis"):
        log = (ROOT / f"artifacts/validation/rating-session-{role}-tests.txt").read_text(encoding="utf-8-sig")
        assert "Ran 7 tests" in log and "OK" in log
    bench = (ROOT / "artifacts/benchmarks/rating-session-depth7.json").read_text(encoding="utf-8-sig").splitlines()
    assert json.loads(bench[-1])["totalNodes"] == 146772
    assert read(ROOT / "artifacts/validation/rating-session-recomputation.json")["status"] == "passed"
    assert digest(ROOT / "scripts/analyze_rating.py") == rating["analyzer_sha256"]
    assert digest(ROOT / "artifacts/research/rating-analysis-precompletion/analyze_rating.py") == rating["analyzer_sha256"]
    total = 0; paths = []
    for entry in rating["evidence"]:
        path = ROOT / entry["path"]; prefix = path.with_suffix("")
        assert digest(path) == entry["sha256"] and digest(path.with_suffix(".pgn")) == entry["pgn_sha256"]
        assert digest(path.with_suffix(".audit.json")) == entry["audit_sha256"]
        command = [sys.executable, str(ROOT / "scripts/audit_match.py"), str(prefix)]
        audit = json.loads(subprocess.run(command, check=True, capture_output=True, text=True).stdout)
        assert audit == read(path.with_suffix(".audit.json"))
        total += audit["games"]
        paths += [p.relative_to(ROOT).as_posix() for p in path.parent.glob(prefix.name + ".*") if p.is_file()]
    assert total == 416
    names = ("match.py", "audit_match.py", "run_rating.py", "analyze_rating.py", "verify_rating_result.py", "test_rating_analysis.py",
             "test_match_strength.py", "test_match_setups.py", "split_rating_suite.py", "generate_openings.py",
             "audit_openings.py", "uci_client.py", "verify.py", "preserve_rating_experiment.py")
    target.mkdir(); sources = []
    for name in names:
        shutil.copy2(ROOT / "scripts" / name, target / name)
        sources.append(reference(target.relative_to(ROOT) / name))
    for name in ("docs/RATING.md", "README.md", "ROADMAP.md", "artifacts/PROGRESS.md"):
        shutil.copy2(ROOT / name, target / pathlib.Path(name).name)
        paths.append((target.relative_to(ROOT) / pathlib.Path(name).name).as_posix())
    write_new(target / "manifest.json", {"source_files": sources})
    paths += [rating_path, "artifacts/ratings/calibration-v1-execution.json", "artifacts/ratings/calibration-v1-selection.json",
              "artifacts/research/rating-plan-v1.json", "artifacts/research/conversion-default-source/manifest.json",
              "artifacts/publish/conversion-default-dotnet/Aster.dll", "artifacts/publish/conversion-default-dotnet/Aster.deps.json",
              "artifacts/publish/conversion-default-dotnet/Aster.runtimeconfig.json",
              "artifacts/research/conversion-stockfish19-provenance.json",
              "artifacts/research/conversion-stockfish19-source/manifest.json", "tools/stockfish/manifest.json"]
    sf = read(ROOT / "tools/stockfish/manifest.json")
    assert digest(ROOT / sf["executable"]) == sf["executable_sha256"]
    assert digest(ROOT / "tools/stockfish/sf_19/stockfish-windows-x86-64-universal.zip") == sf["archive_sha256"]
    paths += [sf["executable"], "tools/stockfish/sf_19/stockfish-windows-x86-64-universal.zip"]
    for manifest_path in ("artifacts/research/conversion-default-source/manifest.json",
                          "artifacts/research/conversion-stockfish19-source/manifest.json",
                          "artifacts/research/rating-pipeline-start/manifest.json"):
        manifest_file = ROOT / manifest_path
        for entry in read(manifest_file)["source_files"]:
            file = manifest_file.parent / entry["path"]
            assert digest(file) == entry["sha256"]
            paths.append(file.relative_to(ROOT).as_posix())
    for role in ("parent", "screen", "confirm"):
        paths += [f"tests/fixtures/rating-{role}-v1.json", f"artifacts/validation/rating-{role}-audit.json"]
    for directory in ("rating-pipeline-start", "rating-analysis-precompletion", "rating-pipeline-final"):
        paths += [p.relative_to(ROOT).as_posix() for p in (ROOT / "artifacts/research" / directory).iterdir() if p.is_file()]
    paths += [p.relative_to(ROOT).as_posix() for p in (ROOT / "artifacts/validation").glob("rating-session-*") if p.is_file()]
    paths += [p.relative_to(ROOT).as_posix() for p in (ROOT / "artifacts/benchmarks").glob("rating-session-*") if p.is_file()]
    write_new(final, {"schema": 1, "games": total, "rating": reference(rating_path),
                      "artifacts": [reference(p) for p in sorted(set(paths))],
                      "interpretation": "Frozen independent Aster default; bounded predeclared local calibration, no engine promotion. Public rating and full-strength Stockfish-superiority goal unestablished. Documents and exact scripts retained as immutable copies."})
    print(json.dumps({"games": total, "artifacts": len(read(final)["artifacts"]), "manifest_sha256": digest(final)}))


if __name__ == "__main__": main()
