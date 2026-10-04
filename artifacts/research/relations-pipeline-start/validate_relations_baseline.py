"""Freeze the new runtime and compare unchanged classical playing behavior."""
import json
import shutil
import subprocess
import sys

from run_rating import digest, read, write_new
from uci_client import ROOT


def main():
    plan_path = ROOT / "artifacts/research/relations-plan-v1.json"; plan = read(plan_path)
    prior = plan["frozen_classical_reference"]
    assert "57 passed, 0 failed." in (ROOT / "artifacts/validation/relations-default-tests.txt").read_text()
    assert "Build succeeded." in (ROOT / "artifacts/validation/relations-build.txt").read_text()
    assert read(ROOT / "artifacts/validation/relations-geometry-v1.json")["passed"]
    assert read(ROOT / "artifacts/validation/relations-default-rules.json")["binary_sha256"] == digest(ROOT / "src/Engine/bin/Release/net8.0/Aster.dll")
    package = ROOT / "artifacts/publish/relations-dev"; package.mkdir(exist_ok=True)
    for name in ("Aster.dll","Aster.pdb","Aster.deps.json","Aster.runtimeconfig.json"):
        target = package / name
        original = ROOT / "src/Engine/bin/Release/net8.0" / name
        if target.exists(): assert digest(target) == digest(original)
        else: shutil.copy2(original,target)
    def run(label,command):
        with (ROOT / f"artifacts/validation/relations-{label}.txt").open("x",encoding="utf-8") as log:
            subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
    source = ROOT / "artifacts/research/relations-runtime-source-v1"
    if not (source / "manifest.json").exists():
        run("freeze-runtime",[sys.executable,str(ROOT / "scripts/freeze_engine_source.py"),"--binary",str(package / "Aster.dll"),
            "--directory",str(source),"--build","dotnet build Aster.sln -c Release",
            "--note","Optional original relation feature inference and diagnostic command; classical evaluation, search and rules unchanged."])
    rebuilt = read(source / "manifest.json")
    assert rebuilt["binary_sha256"] == digest(package / "Aster.dll")
    for entry in rebuilt["source_files"]: assert digest(ROOT / entry["path"]) == entry["sha256"]
    old = {entry["path"]:entry["sha256"] for entry in read(ROOT / prior["baseline_source"])["source_files"]}
    changed = [entry["path"] for entry in rebuilt["source_files"] if entry["sha256"] != old[entry["path"]]]
    assert sorted(changed) == ["src/Engine/NeuralNetwork.cs","src/Engine/Uci.cs","tests/Engine.Tests/Program.cs"],changed
    run("rebuild-comparison",[sys.executable,str(ROOT / "scripts/compare_search.py"),"--engine",str(package / "Aster.dll"),
        "--opponent",str(ROOT / prior["baseline"]),"--suite",str(ROOT / "tests/fixtures/mate-proof-parent-v1.json"),"--depth","8",
        "--output",str(ROOT / "artifacts/benchmarks/relations-rebuild-depth8.json")])
    comparison = read(ROOT / "artifacts/benchmarks/relations-rebuild-depth8.json")
    assert all(row["same_move"] and row["same_score"] and row["candidate"]["nodes"] == row["opponent"]["nodes"] for row in comparison["positions"])
    assert "146772" in (ROOT / "artifacts/validation/relations-bench7.txt").read_text()
    result = {"passed":True,"plan_sha256":digest(plan_path),"script_sha256":digest(__file__),
        "baseline":(package / "Aster.dll").relative_to(ROOT).as_posix(),"baseline_sha256":digest(package / "Aster.dll"),
        "baseline_source":(source / "manifest.json").relative_to(ROOT).as_posix(),"source_manifest_sha256":digest(source / "manifest.json"),
        "changed_source_files":changed,"classical_equivalent_depth8_positions":len(comparison["positions"])}
    write_new(ROOT / "artifacts/research/relations-runtime-v1.json",result)
    print(json.dumps(result),flush=True)


if __name__ == "__main__": main()
