"""Freeze the predeclared disjoint regression and conditional rating partitions."""
import copy
import json

from run_rating import digest, read, write_new
from uci_client import ROOT


def main():
    path = ROOT / "tests/fixtures/lazy-order-parent-v1.json"; parent = read(path)
    assert len(parent["openings"]) == 208
    for role, start, end in (("30ms", 0, 64), ("100ms", 64, 80), ("behavior", 0, 80), ("rating", 80, 208)):
        subset = copy.deepcopy(parent)
        subset["openings"] = parent["openings"][start:end]
        subset.update({"experiment_role": role, "parent_suite": {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path)},
                       "parent_indices": list(range(start, end)), "splitter_sha256": digest(__file__)})
        write_new(ROOT / f"tests/fixtures/lazy-order-{role}-v1.json", subset)
    print(json.dumps({"regression_pairs": 80, "reserved_rating_pairs": 128, "disjoint": True}))


if __name__ == "__main__": main()
