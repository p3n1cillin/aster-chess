"""Describe saved searches on paired identical opening roots; never a speed claim."""
import collections
import json
import pathlib
import shutil
import statistics

from run_rating import digest, read, write_new
from uci_client import ROOT
from relations_plan import load_plan


def main():
    state = read(ROOT / "artifacts/research/relations-match-execution-v1.json")
    assert state["status"] == "complete"
    results = {}
    for phase in state["phases"]:
        prefix = ROOT / f"artifacts/matches/relations-{phase['label']}"; report = read(str(prefix)+".json")
        assert digest(str(prefix)+".json") == phase["report_sha256"]
        paired = collections.defaultdict(dict)
        for game in report["games"]: paired[game["pair"]][game["candidate_color"]] = game
        rows = []
        for pair,games in sorted(paired.items()):
            a,b = games["white"],games["black"]
            assert (a["starting_fen"],a["opening"],a["initial_fen"]) == (b["starting_fen"],b["opening"],b["initial_fen"])
            assert a["initial_fen"].split()[1] == "w"
            candidate,opponent = a["searches"][0],b["searches"][0]
            assert candidate["role"] == "candidate" and opponent["role"] == "opponent"
            assert candidate["ply"] == opponent["ply"] == len(a["opening"].split())+1
            rows.append({"pair":pair,"initial_fen":a["initial_fen"],"candidate":candidate,"opponent":opponent})
        summary = {"pairs":len(rows),"same_first_move":sum(row["candidate"]["move"] == row["opponent"]["move"] for row in rows)}
        for role in ("candidate","opponent"):
            summary[role] = {"median_"+key:statistics.median(row[role][key] for row in rows) for key in ("depth","nodes","elapsed_seconds")}
        summary["median_candidate_minus_opponent_depth"] = statistics.median(row["candidate"]["depth"]-row["opponent"]["depth"] for row in rows)
        summary["median_candidate_over_opponent_nodes"] = statistics.median(row["candidate"]["nodes"]/row["opponent"]["nodes"] for row in rows if row["opponent"]["nodes"]>0)
        results[phase["label"]] = {"report_sha256":phase["report_sha256"],"summary":summary,"paired_initial_searches":rows}
    source = ROOT / "artifacts/research/relations-initial-search-source-v1"; source.mkdir(exist_ok=False)
    shutil.copy2(__file__,source / pathlib.Path(__file__).name)
    result = {"schema":1,"complete":True,"post_match_diagnostic":True,"script_sha256":digest(__file__),"phases":results,
        "interpretation":"Saved first searches at identical full opening histories and White roots under swapped colors. Different evaluations change search trees, so node/depth differences are descriptive execution evidence, not isolated evaluator speed, guaranteed quality, Elo or playing strength. No filtering, new queries, selection or retuning."}
    write_new(ROOT / "artifacts/validation/relations-initial-search-v1.json",result)
    print(json.dumps({label:entry["summary"] for label,entry in results.items()}),flush=True)


if __name__ == "__main__": main()
