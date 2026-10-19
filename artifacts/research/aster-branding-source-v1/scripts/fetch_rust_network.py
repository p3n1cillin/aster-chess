"""Fetch the immutable neural weights for the Rust build; no engine is installed."""
import hashlib
import json
import pathlib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
URL = "https://github.com/cosmobobak/viridithas-networks/releases/download/v109/sandhi-s2-b200.nnue.zst"
SHA256 = "066c172e22c25ee3d3b4084ad44ff761426f906a9c536cabd0127d17413d0585"

def main():
    path = ROOT / "crates/engine/viridithas.nnue.zst"
    if not path.exists():
        temporary = path.with_suffix(".partial")
        urllib.request.urlretrieve(URL, temporary)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != SHA256:
            raise ValueError("Network download checksum mismatch")
        temporary.replace(path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != SHA256:
        raise ValueError("Existing network checksum mismatch; preserve it for investigation")
    print(json.dumps({"status": "verified", "sha256": SHA256, "url": URL}))

if __name__ == "__main__": main()
