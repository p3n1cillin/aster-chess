"""Freeze the predeclared disjoint evasion regression/rating partitions."""
import copy
import json

from run_rating import digest, read, write_new
from uci_client import ROOT


def main():
    path = ROOT / "tests/fixtures/q-evasion-parent-v1.json"; parent = read(path)
    assert len(parent["openings"]) == 288
    for role, start, end in (("30ms", 0, 128), ("100ms", 128, 160), ("behavior", 0, 160), ("rating", 160, 288)):
        subset = copy.deepcopy(parent); subset["openings"] = parent["openings"][start:end]
        subset.update({"experiment_role": role, "parent_suite": {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path)},
                       "parent_indices": list(range(start, end)), "splitter_sha256": digest(__file__)})
        write_new(ROOT / f"tests/fixtures/q-evasion-{role}-v1.json", subset)
    print(json.dumps({"regression_pairs": 160, "reserved_rating_pairs": 128, "disjoint": True}))


if __name__ == "__main__": main()
