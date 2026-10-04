"""Verify and freeze complete-game conversion, native proofs and session rating status."""
import datetime
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


def main():
    directory = ROOT / "artifacts/research/conversion-proof-pipeline-final"
    final = ROOT / "artifacts/research/conversion-proof-experiment-manifest.json"
    rating_path = pathlib.Path("artifacts/ratings/session-20261004-proof.json")
    if directory.exists() or final.exists() or (ROOT / rating_path).exists(): raise ValueError("Preserve earlier snapshots")
    engine_manifests = ["artifacts/research/" + name + "/manifest.json" for name in
                        ("conversion-source", "proof-source", "conversion-default-source", "kpk-source", "kpk-control-source")]
    binaries = []
    for path in engine_manifests:
        manifest = read(path)
        assert digest(ROOT / manifest["binary"]) == manifest["binary_sha256"]
        for entry in manifest["source_files"]:
            assert digest((ROOT / path).parent / entry["path"]) == entry["sha256"]
        binaries.append(manifest["binary"])
    for name in ("queen", "rook"):
        report = read("artifacts/validation/major-" + name + "-exhaustive.json")
        assert report["passed"] and report["entries"] == 524288
        assert report["dump_sha256"] == digest(ROOT / ("artifacts/validation/major-" + name + "-v1.bin"))
        assert report["script_sha256"] == digest(ROOT / "scripts/verify_major_mates.py")
    sf_path = "tools/stockfish/manifest.json"; sf = read(sf_path)
    assert digest(ROOT / sf["executable"]) == sf["executable_sha256"]
    oracle_path = "tools/syzygy-development-v1/manifest.json"; oracle = read(oracle_path)
    oracle_files = [str(pathlib.Path(oracle_path).parent / e["name"]) for e in oracle["files"]]
    for path, entry in zip(oracle_files, oracle["files"], strict=True): assert digest(ROOT / path) == entry["sha256"]
    prefixes = ["artifacts/matches/" + name for name in
                ("kpk-conversion-vs-control-5000nodes", "kpk-conversion-vs-stockfish19-5000nodes",
                 "kpk-control-vs-stockfish19-5000nodes", "major-conversion-vs-control-5000nodes",
                 "major-conversion-vs-stockfish19-5000nodes", "major-conversion-vs-control-v5-100ms")]
    total_games = 0
    for prefix in prefixes:
        report = read(prefix + ".json"); audit = read(prefix + ".audit.json")
        assert len(report["games"]) == 2 * report["pairs_requested"] == audit["games"]
        assert report["forfeits"] == report["unresolved"] == 0 and audit["status"] == "passed"
        assert report["runner_sha256"] == digest(ROOT / "scripts/match.py")
        for role in ("candidate", "opponent"):
            assert digest(report[role]) == report[role + "_binary_sha256"]
            if role + "_source_manifest" in report:
                assert digest(report[role + "_source_manifest"]["path"]) == report[role + "_source_manifest"]["sha256"]
        assert digest(report["opening_suite"]["path"]) == report["opening_suite"]["sha256"]
        total_games += len(report["games"])
    assert total_games == 512
    samples = read("artifacts/proofs/samples-v1/manifest.json")
    assert samples["passed"] and len(samples["certificates"]) == 32
    assert samples["verifier_sha256"] == digest(ROOT / "scripts/verify_strategy_proof.py")
    for entry in samples["certificates"]: assert digest(ROOT / entry["path"]) == entry["sha256"]
    protocol = read("artifacts/validation/proof-protocol.json")
    assert protocol["passed"] and protocol["behavior_positions"] == 66
    for name, total in (("major-engine-tests", 49), ("proof-engine-tests", 51), ("conversion-default-engine-tests", 49)):
        assert f"{total} passed, 0 failed." in (ROOT / ("artifacts/validation/" + name + ".txt")).read_text(encoding="utf-8-sig")
    default = read("artifacts/validation/conversion-default-rules.json")
    assert default["status"] == "passed" and default["binary_sha256"] == read(engine_manifests[2])["binary_sha256"]
    timed = read(prefixes[-1] + ".json"); analysis = read(prefixes[-1] + ".analysis.json")
    (ROOT / rating_path).parent.mkdir(exist_ok=True)
    rating = {"schema": 1, "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "status": "unestablished", "numeric_elo": None, "rating_scale": None,
              "production": {"name": "Aster 0.6.0", "path": "artifacts/publish/win-x64/Aster.exe",
                             "sha256": digest(ROOT / "artifacts/publish/win-x64/Aster.exe")},
              "experimental": [{"path": read(p)["binary"], "sha256": read(p)["binary_sha256"]} for p in engine_manifests[:3]],
              "latest_general_regression": {"report": reference(prefixes[-1] + ".json"), "games": 64,
                                             "wins": timed["wins"], "draws": timed["draws"], "losses": timed["losses"],
                                             "score": analysis["score"], "exploratory_interval": analysis["exploratory_95_percent_interval"]},
              "reason": "No calibrated opponent pool and scale support an absolute rating. A small relative regression and selected endgame games cannot establish Elo.",
              "next": "Predeclare a bounded calibration on a named local scale with a frozen binary, sufficient paired held-out openings, pinned references and uncertainty."}
    (ROOT / rating_path).write_text(json.dumps(rating, indent=2) + "\n")
    names = ("match.py", "audit_match.py", "analyze_match.py", "test_match_setups.py", "generate_kpk_setups.py",
             "analyze_kpk_conversion.py", "verify_major_mates.py", "verify_major_runtime.py", "verify_strategy_proof.py",
             "test_strategy_proof.py", "sample_strategy_proofs.py", "verify_proof_protocol.py", "preserve_conversion_experiment.py",
             "freeze_engine_source.py", "tactics.py", "verify.py", "uci_client.py")
    directory.mkdir(); sources = []
    for name in names:
        path = pathlib.Path("scripts") / name; shutil.copy2(ROOT / path, directory / name); sources.append(reference(path))
    # Preserve the earlier rule-only checker exactly for the retained initial reports.
    initial = (ROOT / "scripts/verify_strategy_proof.py").read_bytes()
    initial = initial.replace(b'    assert proof["strongSide"] in (0, 1)\n', b'').replace(b'    assert root.is_valid()\n', b'')
    assert hashlib.sha256(initial).hexdigest() == "f4e7532cf418fafbbaced3a35f3f7bc110a9985b278436ae55ab14b4ec4add02"
    (directory / "verify_strategy_proof_initial.py").write_bytes(initial)
    (directory / "manifest.json").write_text(json.dumps({"source_files": sources,
        "initial_verifier": reference(directory.relative_to(ROOT) / "verify_strategy_proof_initial.py")}, indent=2) + "\n")
    paths = engine_manifests + binaries + oracle_files + [oracle_path, sf_path, sf["executable"], rating_path.as_posix(),
            "artifacts/research/kpk-conversion-plan-v1.json", "artifacts/research/major-conversion-plan-v1.json",
            "artifacts/research/kpk-experiment-manifest.json", "tests/fixtures/kpk-setups-v1.json", "tests/fixtures/openings-v5.json",
            "tests/fixtures/tactics-v1.json", "tests/fixtures/tactics-quiet-v1.json", "tests/fixtures/endgames-v1.json",
            "docs/ENDGAME-CONVERSION.md", "docs/STRATEGY-PROOFS.md", "docs/RATING.md",
            "artifacts/publish/conversion-default-dotnet/Aster.runtimeconfig.json", "artifacts/publish/conversion-default-dotnet/Aster.deps.json"]
    paths += [p.relative_to(ROOT).as_posix() for p in (ROOT / "artifacts/proofs").rglob("*.json")]
    for prefix in prefixes:
        paths += [p.relative_to(ROOT).as_posix() for p in (ROOT / "artifacts/matches").glob(pathlib.Path(prefix).name + ".*")]
    for pattern in ("major*", "proof*", "conversion-default*"):
        paths += [p.relative_to(ROOT).as_posix() for p in (ROOT / "artifacts/validation").glob(pattern) if p.is_file()]
        paths += [p.relative_to(ROOT).as_posix() for p in (ROOT / "artifacts/benchmarks").glob(pattern) if p.is_file()]
    for name in ("kpk-conversion-vs-control", "kpk-conversion-vs-stockfish19", "kpk-control-conversion-vs-stockfish19"):
        paths.append("artifacts/validation/" + name + ".json")
    result = {"schema": 1, "pipeline": reference(directory.relative_to(ROOT) / "manifest.json"),
              "artifacts": [reference(p) for p in sorted(set(paths))], "complete_games": total_games,
              "interpretation": "Original exact major-piece mating knowledge fixes targeted conversion failures; native complete strategy proofs independently verified. General timed regression negative/inconclusive: scoring remains opt-in, production preserved, rating unestablished, Stockfish-superiority goal unachieved."}
    final.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"scripts": len(sources), "artifacts": len(result["artifacts"]), "complete_games": total_games, "rating": "unestablished"}))


if __name__ == "__main__": main()
