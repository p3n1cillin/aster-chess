"""Fetch the immutable neural weights for the Rust build; no engine is installed."""
import hashlib
import json
import pathlib
import shutil
import os
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
PREVIOUS_SHA256 = "066c172e22c25ee3d3b4084ad44ff761426f906a9c536cabd0127d17413d0585"

def main():
    path = ROOT / "crates/engine/viridithas.nnue.zst"
    pin = json.loads((path.parent / 'NETWORK.json').read_text(encoding='utf-8'))
    expected, url = pin['sha256'], pin['url']
    current = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    if current != expected:
        cache = ROOT / '.aster-local/networks'
        cache.mkdir(parents=True, exist_ok=True)
        if current is not None:
            if current != PREVIOUS_SHA256:
                raise ValueError('Unexpected existing network; preserve it for investigation')
            previous = cache / (current + '.nnue.zst')
            if previous.exists() and hashlib.sha256(previous.read_bytes()).hexdigest() != current:
                raise ValueError('Previous network cache checksum mismatch')
            if not previous.exists():
                shutil.copyfile(path, previous)
        temporary = path.with_name(path.name + f'.{os.getpid()}.partial')
        cached = cache / (expected + '.nnue.zst')
        if cached.exists():
            if hashlib.sha256(cached.read_bytes()).hexdigest() != expected:
                raise ValueError('Pinned network cache checksum mismatch')
            shutil.copyfile(cached, temporary)
        else:
            urllib.request.urlretrieve(url, temporary)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != expected:
            raise ValueError("Network download checksum mismatch")
        temporary.replace(path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError("Existing network checksum mismatch; preserve it for investigation")
    print(json.dumps({"status": "verified", "sha256": expected, "url": url}))

if __name__ == "__main__": main()
