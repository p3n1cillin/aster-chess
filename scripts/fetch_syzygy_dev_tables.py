"""Fetch python-chess's 3- and 4-piece Syzygy test tables (WDL + DTZ) for development.

They are an independent oracle for checking the Rust core's Syzygy prober
(scripts/verify_syzygy_probe.py). First run writes a manifest pinning every
file's SHA-256; later runs verify against it.
"""
import hashlib
import json
import pathlib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
TAG = "v1.11.2"
API = f"https://api.github.com/repos/niklasf/python-chess/contents/data/syzygy/regular?ref={TAG}"
RAW = f"https://raw.githubusercontent.com/niklasf/python-chess/{TAG}/data/syzygy/regular/"
DEST = ROOT / "tools" / "syzygy-development-v2"


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    manifest_path = DEST / "manifest.json"
    pinned = {f["name"]: f for f in json.loads(manifest_path.read_text())["files"]} if manifest_path.exists() else None
    if pinned is None:
        listing = json.loads(urllib.request.urlopen(API).read())
        names = sorted(f["name"] for f in listing if f["name"].endswith((".rtbw", ".rtbz")))
    else:
        names = sorted(pinned)
    files = []
    for name in names:
        path = DEST / name
        if not path.exists():
            data = urllib.request.urlopen(RAW + name).read()
            if pinned and hashlib.sha256(data).hexdigest() != pinned[name]["sha256"]:
                raise ValueError(f"checksum mismatch for {name}")
            path.write_bytes(data)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if pinned and digest != pinned[name]["sha256"]:
            raise ValueError(f"existing {name} does not match its pinned checksum")
        files.append({"name": name, "url": RAW + name, "bytes": path.stat().st_size, "sha256": digest})
    if pinned is None:
        manifest = {"purpose": "Development oracle for the Syzygy prober; never used for play",
                    "source_tag": f"python-chess {TAG}", "license": "GPL-3.0-or-later (python-chess)", "files": files}
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"status": "verified", "files": len(files), "bytes": sum(f["bytes"] for f in files)}))


if __name__ == "__main__":
    main()
