"""Verify the trained phase ablation and preserve fixed pre-match diagnostics."""
import json
import pathlib
import subprocess
import sys

from match import frozen_source_manifest
from run_rating import digest, read, write_new
from uci_client import ROOT


def main():
    plan_path = ROOT / "artifacts/research/phase-plan-v1.json"; plan = read(plan_path)
    output = ROOT / "artifacts/validation/phase-preflight.json"
    if output.exists(): raise ValueError("Preserve completed preflight")
    engine = ROOT / "artifacts/publish/phase-dev/Aster.dll"
    source = ROOT / "artifacts/research/phase-source/manifest.json"
    manifest = read(source); frozen_source_manifest(str(source), digest(engine))
    for entry in manifest["source_files"]: assert digest(ROOT / entry["path"]) == entry["sha256"]
    execution = read(ROOT / "artifacts/research/phase-training-execution-v1.json")
    assert execution["status"] == "complete" and execution["plan_sha256"] == digest(plan_path)
    for name, expected in execution["scripts"].items(): assert digest(ROOT / "scripts" / name) == expected
    assert read(ROOT / "artifacts/validation/phase-formats.json")["engine_sha256"] == digest(engine)
    assert read(ROOT / "artifacts/validation/phase-default-rules.json")["status"] == "passed"
    for role in ("parent", "classical-30ms", "control-30ms", "classical-100ms"):
        assert read(ROOT / f"artifacts/validation/phase-{role}-audit.json")["passed"]

    def run(name, command):
        log = ROOT / f"artifacts/validation/phase-{name}.txt"
        with log.open("x", encoding="utf-8") as stream:
            subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True)

    run("final-tests", ["dotnet", "run", "--project", "tests/Engine.Tests", "-c", "Release", "--no-build"])
    assert "53 passed, 0 failed." in (ROOT / "artifacts/validation/phase-final-tests.txt").read_text(encoding="utf-8")
    run("bench7", ["dotnet", str(engine), "bench", "7"])
    models = {}; tactics = {}
    for role in ("control", "candidate"):
        directory = ROOT / plan["training"][role + "_output"]; model = directory / "model.ann"
        report = read(directory / "training.json")
        assert report["dataset_sha256"] == plan["training"]["data_sha256"] and report["model_sha256"] == digest(model)
        models[role] = {"path": model.relative_to(ROOT).as_posix(), "sha256": digest(model), "training_sha256": digest(directory / "training.json")}
        run(role + "-network", [sys.executable, str(ROOT / "scripts/verify_network.py"), str(model), "--engine", str(engine),
            "--data", str(ROOT / plan["training"]["data"]), "--original-only", "--output", str(ROOT / f"artifacts/validation/phase-{role}-network.json")])
        run(role + "-rules", [sys.executable, str(ROOT / "scripts/verify.py"), "--engine", str(engine), "--eval-file", str(model), "--setups", "1000",
            "--output", str(ROOT / f"artifacts/validation/phase-{role}-rules.json")])
        tactics[role] = {}
        for label, suite, limit in (("tactics-depth8", "tactics-v1.json", ["--depth", "8"]),
                ("tactics-5000nodes", "tactics-v1.json", ["--nodes", "5000"]),
                ("tactics-quiet-depth8", "tactics-quiet-v1.json", ["--depth", "8"]),
                ("tactics-quiet-5000nodes", "tactics-quiet-v1.json", ["--nodes", "5000"]),
                ("endgames-5000nodes", "endgames-v1.json", ["--nodes", "5000"])):
            destination = ROOT / f"artifacts/tactics/phase-{role}-{label}.json"
            if destination.exists(): raise ValueError("Preserve prior tactics")
            suite_path = ROOT / "tests/fixtures" / suite
            run(role + "-" + label, [sys.executable, str(ROOT / "scripts/tactics.py"), str(suite_path), "--engine", str(engine),
                "--eval-file", str(model), *limit, "--output", str(destination)])
            result = read(destination)
            result.update({"eval_file_sha256": digest(model), "suite_sha256": digest(suite_path)})
            destination.write_text(json.dumps(result, indent=2) + "\n")
            tactics[role][label] = {"solved": result["solved"], "minimum": plan["tactics"][label], "passed": result["solved"] >= plan["tactics"][label]}
    destination = ROOT / "artifacts/benchmarks/phase-default-vs-baseline-depth8.json"
    run("default-comparison", [sys.executable, str(ROOT / "scripts/compare_search.py"), "--engine", str(engine),
        "--opponent", str(ROOT / plan["baseline"]), "--suite", str(ROOT / "tests/fixtures/phase-parent-v1.json"), "--depth", "8", "--output", str(destination)])
    comparison = read(destination)
    assert all(row["same_move"] and row["same_score"] and row["candidate"]["nodes"] == row["opponent"]["nodes"] for row in comparison["positions"])
    result = {"correctness_passed": True, "candidate_tactics_passed": all(entry["passed"] for entry in tactics["candidate"].values()),
        "models": models, "tactics": tactics, "engine": engine.relative_to(ROOT).as_posix(), "engine_sha256": digest(engine),
        "source_manifest": source.relative_to(ROOT).as_posix(), "source_manifest_sha256": digest(source),
        "default_unchanged_positions": len(comparison["positions"]), "plan_sha256": digest(plan_path), "script_sha256": digest(__file__),
        "interpretation": "Pre-match correctness and tactical checks. Failures block conditional longer confirmation but both short screens still run. Exact default search traces preserve classical behavior; rating remains attached to the earlier matched binary."}
    write_new(output, result)
    print(json.dumps({"correctness_passed": True, "candidate_tactics_passed": result["candidate_tactics_passed"], "tactics": tactics}))


if __name__ == "__main__": main()
