"""Fetch and verify the pinned NNUE weights used by the Aster core (crates/aster-core)."""
from research_reference import research_text
import hashlib
import json
import pathlib
import shutil
import urllib.error
import urllib.request
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
NAME = "nn-1a298aa575a0.nnue"
URL = research_text('network.primary_prefix') + NAME
MIRROR = (research_text('network.mirror_prefix') + NAME)
SHA256 = "1a298aa575a085434d29027978dc36867fe9c5bcea9376654b7a8eba1e52dfc2"


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    path = ROOT / "crates/aster-core" / NAME
    source = "existing verified file"
    if not path.exists():
        failures = []
        for url in [URL, MIRROR]:
            temporary = path.with_suffix("." + uuid.uuid4().hex + ".partial")
            try:
                with urllib.request.urlopen(url, timeout=120) as response, temporary.open("xb") as stream:
                    shutil.copyfileobj(response, stream)
                if digest(temporary) != SHA256:
                    raise ValueError("Network download checksum mismatch: " + str(temporary))
            except (OSError, ValueError) as error:
                failures.append(str(error))
                continue
            # Do not overwrite an unexpected model that appeared during download.
            if path.exists():
                if digest(path) != SHA256:
                    raise ValueError("Existing network changed during download; preserve it for investigation")
            else:
                temporary.replace(path)
            source = url
            break
        else:
            raise RuntimeError("No verified network download succeeded: " + "; ".join(failures))
    if digest(path) != SHA256:
        raise ValueError("Existing network checksum mismatch; preserve it for investigation")
    print(json.dumps({"status": "verified", "sha256": SHA256, "source": source,
                      "urls": [URL, MIRROR]}))


if __name__ == "__main__":
    main()
