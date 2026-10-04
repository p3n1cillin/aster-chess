"""Independently replay every source game and audit stable endgame selection."""
import argparse
import collections
import json
import pathlib
import random
import re
import statistics
import time

import chess
import chess.engine
import chess.pgn

from generate_endgame_diagnostic import key, phase
from generate_stable_endgames import label
from run_rating import digest, read, write_new
from uci_client import ROOT, UciClient, engine_command


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-incomplete",action="store_true",help="Audit terminal exhausted source-game budget; never authorize training")
    args = parser.parse_args()
    started = time.monotonic()
    report_path = ROOT / "artifacts/validation/stable-endgame-data-audit-v1.json"
    if report_path.exists(): raise ValueError("Audit report already exists; preserve it")
    plan_path = ROOT / "artifacts/research/stable-endgame-plan-v1.json"
    plan = read(plan_path); setup = plan["generation"]
    data_path = ROOT / "artifacts/data/stable-endgame-4096-v1.jsonl"
    candidate_path = pathlib.Path(str(data_path) + ".candidates.jsonl")
    pgn_path = pathlib.Path(str(data_path) + ".source.pgn")
    meta = read(pathlib.Path(str(data_path) + ".manifest.json"))
    if meta["complete"]: assert meta["status"] == "complete"
    else:
        assert args.allow_incomplete and meta["status"] == "failed"
        assert meta["source_games_completed"] == setup["games"]
        assert "Source-game budget exhausted" in meta["error"]
    assert digest(plan_path) == meta["plan_sha256"]
    assert digest(data_path) == meta["data_sha256"] and digest(candidate_path) == meta["candidates_sha256"]
    assert digest(pgn_path) == meta["source_pgn_sha256"]
    accepted = rows(data_path); candidates = rows(candidate_path)
    assert len(accepted) == meta["positions_written"] <= setup["positions"]
    assert (len(accepted) == setup["positions"]) == meta["complete"]
    assert len(candidates) == meta["queried"]
    excluded = set()
    for entry in meta["exclusions"]:
        path = ROOT / entry["path"]; assert digest(path) == entry["sha256"]
        entries = rows(path) if entry["kind"] == "data" else read(path).get("openings", read(path).get("positions", []))
        assert len(entries) == entry["positions"]
        excluded.update(key(chess.Board(row["fen"])) for row in entries)
    by_game = collections.defaultdict(dict)
    for row in candidates:
        assert row["ply"] not in by_game[row["source_game"]]
        by_game[row["source_game"]][row["ply"]] = row
    counts = [0]*4; seen = set(); rejected = collections.Counter(); selected = []
    pv_plies = 0
    for index, row in enumerate(candidates):
        assert row["id"] == f"stable-candidate-{index:06}" and row["game"] == 100000+row["source_game"]
        board = chess.Board(row["fen"]); canonical = key(board)
        assert board.is_valid() and not board.is_check() and board.outcome(claim_draw=True) is None
        assert canonical not in seen and canonical not in excluded; seen.add(canonical)
        assert row["ply"] >= setup["minimum_ply"] and row["ply"] % setup["sample_every"] == 0
        assert row["phase"] == phase(board) <= setup["maximum_phase"]
        assert row["pieces"] == len(board.piece_map()) <= setup["maximum_pieces"]
        assert board.halfmove_clock <= setup["maximum_halfmove_clock"]
        assert type(row["static_white_cp"]) is int
        for name in ("sample", "verified"):
            item = row[name]
            assert (item["white_cp"] is None) != (item["white_mate"] is None)
            assert type(item["white_cp"] if item["white_cp"] is not None else item["white_mate"]) is int
            assert item["pv"] and type(item["reported_nodes"]) is int and item["reported_nodes"] > 0
            replay = board.copy(stack=False)
            for move in item["pv"]:
                replay.push_uci(move); pv_plies += 1
        sample, verified = row["sample"], row["verified"]
        reason = "accepted"; bucket = None
        if sample["white_cp"] is None or verified["white_cp"] is None: reason = "native_mate_label"
        elif abs(verified["white_cp"]) > 1500: reason = "outside_score_range"
        elif sample["pv"][0] != verified["pv"][0]: reason = "unstable_first_move"
        elif abs(sample["white_cp"]-verified["white_cp"]) > 50: reason = "unstable_value"
        else:
            bucket = next(i for i,(low,high) in enumerate(setup["score_ranges_abs_cp"]) if low <= abs(verified["white_cp"]) <= high)
            if counts[bucket] >= setup["quota_each"]: reason = "bucket_full"
        assert (row["acceptance"], row["bucket"]) == (reason, bucket)
        if reason == "accepted": counts[bucket] += 1; selected.append(row)
        else: rejected[reason] += 1
    assert counts == meta["bucket_counts"] and all(count <= setup["quota_each"] for count in counts)
    if meta["complete"]: assert counts == [setup["quota_each"]]*4
    assert dict(rejected) == meta["rejection_counts"] and len(selected) == len(accepted)
    for original, row in zip(selected, accepted):
        assert all(row[field] == value for field,value in original.items())
        assert set(row)-set(original) == {"classical_white_cp", "source_result", "source_termination"}
        assert type(row["classical_white_cp"]) is int
    # Check each candidate against the actual PGN prefix, retaining played history
    # for draw checks while comparing raw EP and both clocks exactly.
    outcomes = collections.Counter(); total_plies = games = histories = 0
    with pgn_path.open(encoding="utf-8") as source:
        while (game := chess.pgn.read_game(source)) is not None:
            assert not game.errors
            summary = meta["source_games"][games]
            assert summary["source_game"] == games == int(game.headers["SourceGame"])
            board = game.board(); history = []
            for move in game.mainline_moves():
                if len(history) in by_game[games]:
                    row = by_game[games][len(history)]
                    assert row["history_uci"] == history and row["fen"] == board.fen(en_passant="fen")
                    assert row["opening_index"] == summary["opening_index"]
                    assert board.outcome(claim_draw=True) is None; histories += 1
                assert move in board.legal_moves; board.push(move); history.append(move.uci())
            opening = meta["opening_lines"][summary["opening_index"]].split()
            assert history[:len(opening)] == opening
            outcome = board.outcome(claim_draw=True)
            result = outcome.result() if outcome else "*"
            termination = outcome.termination.name.lower() if outcome else "maximum_plies_unresolved"
            assert result == summary["result"] == game.headers["Result"]
            assert termination == summary["termination"] == game.headers["Termination"]
            assert len(history) == summary["plies"] <= setup["max_plies"]
            if outcome is None: assert len(history) == setup["max_plies"]
            fresh = [row for row in accepted if row["source_game"] == games]
            assert len(fresh) == summary["accepted_positions"] <= setup["per_game"]
            assert all(row["source_result"] == result and row["source_termination"] == termination for row in fresh)
            total_plies += len(history); outcomes[result] += 1; games += 1
    assert games == meta["source_games_completed"] == len(meta["source_games"]) <= setup["games"]
    assert histories == len(candidates) and dict(outcomes) == meta["source_outcomes"]
    assert outcomes["*"] == meta["source_unresolved"]
    print(json.dumps({"replayed_games":games,"plies":total_plies,"candidates":histories,"pv_plies":pv_plies}),flush=True)
    teacher_path = ROOT / meta["teacher"]["executable"]
    assert digest(teacher_path) == meta["teacher"]["executable_sha256"]
    assert digest(ROOT / plan["baseline"]) == plan["baseline_sha256"]
    classical_checks = 0
    with UciClient(ROOT / plan["baseline"]) as engine:
        for row in accepted:
            engine.send("position fen " + row["fen"])
            value = int(engine.command("eval", "info string eval ").split()[-1])
            assert row["classical_white_cp"] == (value if chess.Board(row["fen"]).turn else -value)
            classical_checks += 1
    rng = random.Random(setup["seed"]+1)
    requery_indices = sorted(rng.sample(range(len(accepted)),64)) if meta["complete"] else []
    deeper_indices = sorted(rng.sample(range(len(accepted)),32)) if meta["complete"] else []
    rechecks = []; deeper = []
    with chess.engine.SimpleEngine.popen_uci(engine_command(teacher_path), timeout=30) as teacher, UciClient(teacher_path) as static:
        teacher.configure({"Threads":1,"Hash":64})
        static.send("setoption name Threads value 1"); static.send("setoption name Hash value 64"); static.ready()
        for index in requery_indices:
            row = accepted[index]; board = chess.Board(row["fen"])
            checks = {}
            static.send("position fen "+row["fen"])
            trace = static.command("eval","Final evaluation")
            native_static = re.search(r"Final evaluation\s+([+-]\d+\.\d+)\s+\(white side\)",trace)
            assert native_static and int(round(float(native_static.group(1))*100)) == row["static_white_cp"]
            checks["static_white_cp"] = row["static_white_cp"]
            checks["static_trace"] = trace
            for name, nodes in (("sample",setup["sample_nodes"]),("verified",setup["verify_nodes"])):
                checks[name] = label(teacher, board, nodes)
                assert checks[name] == row[name], (index,name,checks[name],row[name])
            rechecks.append({"index":index,"id":row["id"],**checks})
        for index in deeper_indices:
            row = accepted[index]; result = label(teacher,chess.Board(row["fen"]),262144)
            deeper.append({"index":index,"id":row["id"],"label":result,
                "first_move_stable":result["pv"][0] == row["verified"]["pv"][0],
                "cp_difference":result["white_cp"]-row["verified"]["white_cp"] if result["white_cp"] is not None else None})
    descriptions = []
    for bucket in range(4):
        group = [row for row in accepted if row["bucket"] == bucket]
        descriptions.append({"bucket":bucket,"positions":len(group),"source_games":len({row["game"] for row in group}),
            "phase_counts":dict(collections.Counter(row["phase"] for row in group)),
            "side_to_move_counts":dict(collections.Counter(row["fen"].split()[1] for row in group)),
            "static_vs_verified_mae_cp":statistics.mean(abs(row["static_white_cp"]-row["verified"]["white_cp"]) for row in group) if group else None,
            "sample_vs_verified_mae_cp":statistics.mean(abs(row["sample"]["white_cp"]-row["verified"]["white_cp"]) for row in group) if group else None})
    write_new(report_path,{"schema":1,"complete":meta["complete"],"checks_passed":True,"plan_sha256":digest(plan_path),"auditor_sha256":digest(__file__),
        "inputs":[{"path":str(path.relative_to(ROOT)).replace("\\","/"),"sha256":digest(path)} for path in (data_path,candidate_path,pgn_path)],
        "games":games,"source_plies":total_plies,"source_outcomes":dict(outcomes),"source_unresolved":outcomes["*"],
        "candidates":len(candidates),"accepted":len(accepted),"buckets":counts,"rejections":dict(rejected),"native_pv_plies":pv_plies,
        "classical_score_checks":classical_checks,"requery_seed":setup["seed"]+1,"exact_requeries":rechecks,"deeper_diagnostic":deeper,
        "bucket_descriptions":descriptions,
        "deeper_first_move_stable":sum(item["first_move_stable"] for item in deeper),"seconds":round(time.monotonic()-started,3),
        "interpretation":"Legal history/outcome/selection audit and independent re-query only. No deeper diagnostic post-filtering; teacher scores and source results are not oracles."})
    print(json.dumps({"complete":meta["complete"],"checks_passed":True,"report_sha256":digest(report_path),"exact_requeries":len(rechecks),"deeper_diagnostic":len(deeper)}),flush=True)


if __name__ == "__main__": main()
