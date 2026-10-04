"""Build, verify and preserve source-equivalent ordinary capacity test runtime."""
import json
import shutil
import subprocess
import sys

from run_rating import digest, read
from uci_client import ROOT


def main():
    plan = read(ROOT / "artifacts/research/capacity-plan-v1.json")
    def run(label,command):
        with (ROOT / f"artifacts/validation/capacity-{label}.txt").open("x",encoding="utf-8") as log:
            subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
    run("build",["dotnet","build","Aster.sln","-c","Release"])
    run("default-tests",["dotnet","run","--project","tests/Engine.Tests","-c","Release","--no-build"])
    run("default-rules",[sys.executable,str(ROOT / "scripts/verify.py"),"--output",str(ROOT / "artifacts/validation/capacity-default-rules.json")])
    run("bench7",["dotnet",str(ROOT / "src/Engine/bin/Release/net8.0/Aster.dll"),"bench","7"])
    package = ROOT / "artifacts/publish/capacity-rebuild"; package.mkdir(exist_ok=False)
    for name in ("Aster.dll","Aster.pdb","Aster.deps.json","Aster.runtimeconfig.json"):
        shutil.copy2(ROOT / "src/Engine/bin/Release/net8.0" / name,package / name)
    run("freeze-runtime",[sys.executable,str(ROOT / "scripts/freeze_engine_source.py"),"--binary",str(package / "Aster.dll"),
        "--directory",str(ROOT / "artifacts/research/capacity-rebuild-source"),"--build","dotnet build Aster.sln -c Release",
        "--note","Unchanged24 runtime source files; metadata-only rebuild. Capacity models/matches use the original declared frozen runtime."])
    rebuilt = read(ROOT / "artifacts/research/capacity-rebuild-source/manifest.json")
    assert rebuilt["source_files"] == read(ROOT / plan["baseline_source"])["source_files"]
    run("rebuild-comparison",[sys.executable,str(ROOT / "scripts/compare_search.py"),"--engine",str(package / "Aster.dll"),
        "--opponent",str(ROOT / plan["baseline"]),"--suite",str(ROOT / "tests/fixtures/mate-proof-parent-v1.json"),"--depth","8",
        "--output",str(ROOT / "artifacts/benchmarks/capacity-rebuild-depth8.json")])
    comparison = read(ROOT / "artifacts/benchmarks/capacity-rebuild-depth8.json")
    assert all(row["same_move"] and row["same_score"] and row["candidate"]["nodes"] == row["opponent"]["nodes"] for row in comparison["positions"])
    print(json.dumps({"passed":True,"source_files":len(rebuilt["source_files"]),"equivalent_depth8_positions":len(comparison["positions"]),"rebuilt_sha256":digest(package / "Aster.dll")}),flush=True)


if __name__ == "__main__": main()
