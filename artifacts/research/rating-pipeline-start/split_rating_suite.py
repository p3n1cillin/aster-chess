"""Freeze screening and independent confirmation openings before engine queries."""
import argparse
import hashlib
import json
import pathlib


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("suite")
    args = parser.parse_args(); parent = pathlib.Path(args.suite)
    data = json.loads(parent.read_text()); assert len(data["openings"]) == 144
    paths = [pathlib.Path("tests/fixtures/rating-screen-v1.json"), pathlib.Path("tests/fixtures/rating-confirm-v1.json")]
    if any(p.exists() for p in paths): parser.error("Preserve frozen rating partitions")
    for role, path, begin, end in (("screen", paths[0], 0, 16), ("confirmation", paths[1], 16, 144)):
        split = {k: v for k, v in data.items() if k != "openings"}
        split.update({"rating_role": role, "parent_suite": {"path": parent.as_posix(), "sha256": hashlib.sha256(parent.read_bytes()).hexdigest()},
                      "parent_indices": list(range(begin, end)), "splitter_sha256": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
                      "openings": data["openings"][begin:end]})
        path.write_text(json.dumps(split, indent=2) + "\n")
        print(json.dumps({"role": role, "positions": end - begin, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}))


if __name__ == "__main__": main()
