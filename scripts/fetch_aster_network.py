"""Fetch and verify the pinned NNUE weights used by the Aster core (crates/aster-core)."""
import hashlib
import json
import pathlib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
NAME = "nn-1a298aa575a0.nnue"
URL = "https://tests.stockfishchess.org/api/nn/" + NAME
SHA256 = "1a298aa575a085434d29027978dc36867fe9c5bcea9376654b7a8eba1e52dfc2"


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    path = ROOT / "crates/aster-core" / NAME
    if not path.exists():
        temporary = path.with_suffix(".partial")
        urllib.request.urlretrieve(URL, temporary)
        if digest(temporary) != SHA256:
            raise ValueError("Network download checksum mismatch")
        temporary.replace(path)
    if digest(path) != SHA256:
        raise ValueError("Existing network checksum mismatch; preserve it for investigation")
    print(json.dumps({"status": "verified", "sha256": SHA256, "url": URL}))


if __name__ == "__main__":
    main()
