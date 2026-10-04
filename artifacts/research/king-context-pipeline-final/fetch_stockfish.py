"""Fetch an official Windows x64 Stockfish release and verify its published SHA-256."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import urllib.request
import zipfile

from uci_client import ROOT, UciClient


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="sf_19", help="Pinned release tag, or latest to update deliberately")
    args = parser.parse_args()
    if not re.fullmatch(r"sf_\d+(?:\.\d+)?|latest", args.tag):
        parser.error("Expected a release tag such as sf_19, or latest")
    endpoint = "latest" if args.tag == "latest" else "tags/" + args.tag
    request = urllib.request.Request(
        "https://api.github.com/repos/official-stockfish/Stockfish/releases/" + endpoint,
        headers={"User-Agent": "Aster-chess-benchmark", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.load(response)
    compatible = [asset for asset in release["assets"]
                  if asset["name"] == "stockfish-windows-x86-64-universal.zip"]
    if not compatible:
        # Older releases use a portable, baseline x86-64 binary.
        compatible = [asset for asset in release["assets"] if asset["name"] == "stockfish-windows-x86-64.zip"]
    if not compatible:
        raise RuntimeError("This release has no supported Windows x64 asset. Download a compatible official binary manually.")
    asset = compatible[0]
    url = asset["browser_download_url"]
    if not url.startswith("https://github.com/official-stockfish/Stockfish/releases/download/"):
        raise RuntimeError("Unexpected download origin")
    expected = asset.get("digest", "")
    if not expected.startswith("sha256:"):
        raise RuntimeError("Release asset has no published SHA-256; verification requires a digest.")
    destination = ROOT / "tools/stockfish" / release["tag_name"]
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / asset["name"]
    if not archive.exists():
        print(f"Downloading {asset['name']} ({asset['size'] / 1024 / 1024:.1f} MiB)", flush=True)
        urllib.request.urlretrieve(url, archive)
    with archive.open("rb") as archive_file:
        actual = hashlib.file_digest(archive_file, "sha256").hexdigest()
    if actual != expected.split(":", 1)[1]:
        raise RuntimeError(f"SHA-256 mismatch for {archive}; remove the invalid archive before retrying")
    with zipfile.ZipFile(archive) as zipped:
        for item in zipped.infolist():
            target = (destination / item.filename).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise RuntimeError("Archive contains a path outside its destination")
        zipped.extractall(destination)
    executables = sorted(destination.rglob("stockfish*.exe"))
    if len(executables) != 1:
        raise RuntimeError(f"Expected one universal Stockfish executable, found {executables}")
    executable = executables[0]
    with UciClient(executable) as client:
        name = client.name
    with executable.open("rb") as executable_file:
        executable_digest = hashlib.file_digest(executable_file, "sha256").hexdigest()
    manifest = {"tag": release["tag_name"], "release_url": release["html_url"], "asset_url": url,
                "archive_sha256": actual, "executable": str(executable.relative_to(ROOT)),
                "executable_sha256": executable_digest, "uci_name": name}
    (ROOT / "tools/stockfish/manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
