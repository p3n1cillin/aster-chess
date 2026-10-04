"""Check explicit whole-game isolation and preservation of the original split."""
import json
import pathlib
import random
import tempfile

from run_rating import read, write_new
from train_network import validation_split
from uci_client import ROOT


def main():
    games = list(range(30))
    original, provenance = validation_split(games,42,None)
    assert original == set(random.Random(42).sample(games,3)) and provenance is None
    checked = 1
    with tempfile.TemporaryDirectory() as temporary:
        path = pathlib.Path(temporary)/"split.json"
        for valid in ([2,12,22],{"validation_games":[2,12,22]}):
            path.write_text(json.dumps(valid))
            selected, source = validation_split(games,999,str(path))
            assert selected == {2,12,22} and source["sha256"]
            checked += 1
        for invalid in ([],[True],["2"],[2,2],[30],games,{"wrong":[2]},[2.0]):
            path.write_text(json.dumps(invalid))
            try: validation_split(games,42,str(path))
            except ValueError: pass
            else: raise AssertionError("Accepted invalid whole-game partition")
            checked += 1
    prior = read(ROOT / "artifacts/training/phase-output-v1/training.json")
    rows = [json.loads(line) for line in (ROOT / "artifacts/data/teacher-turn-60k-static-v1-classical.jsonl").read_text().splitlines() if line.strip()]
    all_games = sorted({row["game"] for row in rows})
    selected, _ = validation_split(all_games,prior["arguments"]["seed"],None)
    assert sorted(selected) == prior["validation_games"]
    assert sum(row["game"] in selected for row in rows) == prior["validation_positions"]
    checked += 1
    result = {"passed":True,"checks":checked,"old_validation_games":len(selected),"old_validation_positions":prior["validation_positions"]}
    write_new(ROOT / "artifacts/validation/stable-endgame-fixed-split-tests.json",result)
    print(json.dumps(result))


if __name__ == "__main__": main()
