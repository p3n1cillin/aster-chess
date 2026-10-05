"""Fetch checksum-pinned Berserk knowledge and an optional Windows C toolchain."""
import argparse
import hashlib
import json
import pathlib
import urllib.request
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
ASSETS = {
    "berserk-14-avx2-pext.exe": ("https://github.com/jhonnold/berserk/releases/download/14/berserk-14-avx2-pext.exe", "0a4f120db51b8416bc200d510fb355448406a9bd073f064adf7d2671cbbc36f2"),
    "berserk-9b84c340af7e.nn": ("https://github.com/jhonnold/berserk/releases/download/14/berserk-9b84c340af7e.nn", "9b84c340af7e45f6e07f0046235ccb327f4ae0840c8ee2c4b97b99121e5c5084"),
}
TOOLCHAIN = ("https://github.com/mstorsjo/llvm-mingw/releases/download/20260922/llvm-mingw-20260922-ucrt-x86_64.zip", "e3ad77d117a4bea19a7a3b333341824d79a5a371004a10e25b8504e7b3047666")


def fetch(path, url, expected):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        temporary = path.with_suffix(path.suffix + ".partial")
        urllib.request.urlretrieve(url, temporary)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != expected:
            raise ValueError("Download checksum mismatch: " + url)
        temporary.replace(path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError("Existing file checksum mismatch: " + str(path))
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toolchain", action="store_true", help="Also install the pinned portable Windows LLVM/MinGW compiler locally")
    args = parser.parse_args()
    for name, (url, digest) in ASSETS.items():
        fetch(ROOT / "tools/berserk/14" / name, url, digest)
    if args.toolchain:
        archive = fetch(ROOT / "tools/native-toolchain/llvm-mingw-20260922-ucrt-x86_64.zip", *TOOLCHAIN)
        destination = ROOT / "tools/native-toolchain"
        if not (destination / "llvm-mingw-20260922-ucrt-x86_64/bin/clang.exe").exists():
            with zipfile.ZipFile(archive) as source:
                for member in source.infolist():
                    resolved = (destination / member.filename).resolve()
                    if not resolved.is_relative_to(destination.resolve()):
                        raise ValueError("Archive path escapes toolchain directory")
                source.extractall(destination)
    print(json.dumps({"status": "verified", "assets": list(ASSETS), "toolchain": args.toolchain}))


if __name__ == "__main__": main()
