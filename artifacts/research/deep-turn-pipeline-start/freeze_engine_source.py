"""Freeze an engine's exact source and build flags before experimental matches."""
import argparse
import hashlib
import json
import pathlib
import shutil
import subprocess

from uci_client import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True)
    parser.add_argument("--directory", required=True)
    parser.add_argument("--build", required=True)
    parser.add_argument("--note", required=True)
    args = parser.parse_args()
    directory = pathlib.Path(args.directory)
    if directory.exists(): parser.error("Preserve prior source snapshots")
    directory.mkdir(parents=True)
    paths = [pathlib.Path(name) for name in ("Aster.sln", "Directory.Build.props", "global.json")]
    paths += sorted(pathlib.Path("src/Engine").glob("*.cs")) + [pathlib.Path("src/Engine/Engine.csproj")]
    paths += [pathlib.Path("tests/Engine.Tests/Program.cs"), pathlib.Path("tests/Engine.Tests/Engine.Tests.csproj")]
    entries = []
    for path in paths:
        target = directory / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / path, target)
        entries.append({"path": path.as_posix(), "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    binary = pathlib.Path(args.binary)
    report = {"binary": binary.as_posix(), "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
              "build": args.build, "sdk": subprocess.check_output(["dotnet", "--version"], text=True).strip(),
              "note": args.note, "source_files": entries}
    (directory / "manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"binary_sha256": report["binary_sha256"], "source_files": len(entries)}))


if __name__ == "__main__": main()
