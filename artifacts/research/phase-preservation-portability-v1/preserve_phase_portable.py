"""Normalize evidence paths for portable use of the unchanged frozen preserver."""
import pathlib

import preserve_phase
from run_rating import digest, read
from uci_client import ROOT


def main():
    amendment = read(ROOT / "artifacts/research/phase-preservation-portability-v1/manifest.json")
    assert digest(__file__) == amendment["adapter_sha256"]
    assert digest(ROOT / "scripts/preserve_phase.py") == amendment["original_preserver_sha256"]
    # Windows normalizes file.ann/../training.json on open; POSIX rejects the
    # intermediate file as a directory. Resolve before the original read.
    original_read = preserve_phase.read
    preserve_phase.read = lambda path: original_read(pathlib.Path(path).resolve())
    preserve_phase.main()


if __name__ == "__main__": main()
