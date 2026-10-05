"""Build Aster's attributed Berserk-derived C foundation with embedded pinned weights."""
import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import tempfile

from fetch_native import ASSETS, ROOT, TOOLCHAIN

SOURCES = "attacks.c bench.c berserk.c bits.c board.c eval.c history.c move.c movegen.c movepick.c perft.c random.c search.c see.c tb.c thread.c transposition.c uci.c util.c zobrist.c nn/accumulator.c nn/evaluate.c pyrrhic/tbprobe.c".split()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", help="Clang or GCC executable; otherwise use the locally fetched Windows compiler or clang from PATH")
    parser.add_argument("--output", default="artifacts/publish/berserk-foundation-v1")
    parser.add_argument("--arch", choices=["x86-64", "avx2-pext"], default="avx2-pext")
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    if output.exists(): parser.error("Preserve earlier builds; choose a new output directory")
    source_root = ROOT / "native/aster-berserk"
    network = ROOT / "tools/berserk/14/berserk-9b84c340af7e.nn"
    if not network.is_file() or hashlib.sha256(network.read_bytes()).hexdigest() != ASSETS[network.name][1]:
        parser.error("Run scripts/fetch_native.py; the pinned network is required")
    compiler = args.cc or os.environ.get("ASTER_NATIVE_CC")
    if not compiler:
        compiler = str(ROOT / "tools/native-toolchain/llvm-mingw-20260922-ucrt-x86_64/bin/clang.exe") if os.name == "nt" else "clang"
    version = subprocess.check_output([compiler, "--version"], text=True, encoding="utf-8")
    flags = ["-std=gnu11", "-Wall", "-Wextra", "-Wshadow", "-O3", "-DNDEBUG", '-DVERSION="0.9.0-foundation-dev (Berserk 14)"', '-DEVALFILE="berserk-9b84c340af7e.nn"', "-m64", "-mpopcnt"]
    if args.arch == "avx2-pext": flags += ["-msse4.1", "-mbmi", "-mfma", "-mavx2", "-DUSE_PEXT", "-mbmi2"]
    if os.name == "nt": flags += ["-static"]
    binary_name = "aster-berserk.exe" if os.name == "nt" else "aster-berserk"
    with tempfile.TemporaryDirectory(prefix="aster-native-") as temporary:
        build_dir = pathlib.Path(temporary) / "src"
        shutil.copytree(source_root / "src", build_dir)
        shutil.copy2(network, build_dir / network.name)
        command = [compiler, *flags, *SOURCES, "-pthread", "-lm", "-o", binary_name]
        result = subprocess.run(command, cwd=build_dir, capture_output=True, text=True, encoding="utf-8")
        if result.returncode:
            print(result.stdout + result.stderr)
            raise SystemExit(result.returncode)
        output.mkdir(parents=True)
        shutil.copy2(build_dir / binary_name, output / binary_name)
    entries = []
    for path in sorted(source_root.rglob("*")):
        if path.is_file():
            relative = pathlib.Path("source") / path.relative_to(source_root)
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            entries.append({"path": relative.as_posix(), "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    shutil.copy2(network, output / network.name)
    entries.append({"path": network.name, "sha256": ASSETS[network.name][1]})
    shutil.copy2(pathlib.Path(__file__), output / "build_native.py")
    entries.append({"path": "build_native.py", "sha256": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()})
    manifest = {"binary": binary_name, "binary_sha256": hashlib.sha256((output / binary_name).read_bytes()).hexdigest(),
                "upstream": "https://github.com/jhonnold/berserk", "upstream_commit": "8ae895a6151695be4a50d4fb65b0c131659c513a",
                "build": command, "compiler": version, "compiler_binary_sha256": hashlib.sha256(pathlib.Path(shutil.which(compiler) or compiler).read_bytes()).hexdigest(),
                "architecture": args.arch, "pgo": False, "toolchain_pin": TOOLCHAIN, "network_sha256": ASSETS[network.name][1],
                "source_files": entries, "note": "Source-built derivative; identity/provenance changes only. Search and neural weights retain Berserk 14 authorship. No Aster Elo assigned."}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (output / "build.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    print(json.dumps({"binary": str(output / binary_name), "sha256": manifest["binary_sha256"], "source_files": len(entries)}))


if __name__ == "__main__": main()
