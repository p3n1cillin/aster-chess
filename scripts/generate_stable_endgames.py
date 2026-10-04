"""Collect bounded balanced endgames with static and stable-search targets."""
import collections
import datetime
import json
import pathlib
import random
import re
import time

import chess
import chess.engine
import chess.pgn

from generate_endgame_diagnostic import key, phase
from match import OPENINGS
from run_rating import digest, read
from uci_client import ROOT, UciClient, engine_command


def label(teacher, board, nodes):
    info = teacher.analyse(board.copy(stack=False), chess.engine.Limit(nodes=nodes), multipv=1, game=object())[0]
    score = info["score"].white(); pv = [move.uci() for move in info.get("pv", [])]
    assert pv
    replay = board.copy(stack=False)
    for move in pv: replay.push_uci(move)
    return {"white_cp": score.score(), "white_mate": score.mate(), "depth": info.get("depth"),
        "reported_nodes": info.get("nodes"), "pv": pv}


def main():
    plan_path = ROOT / "artifacts/research/stable-endgame-plan-v1.json"; plan = read(plan_path); setup = plan["generation"]
    output = ROOT / "artifacts/data/stable-endgame-4096-v1.jsonl"
    candidate_path = pathlib.Path(str(output) + ".candidates.jsonl")
    pgn_path = pathlib.Path(str(output) + ".source.pgn")
    manifest_path = pathlib.Path(str(output) + ".manifest.json")
    if any(p.exists() for p in (output, candidate_path, pgn_path, manifest_path)):
        raise ValueError("Preserve prior/partial runs; never restart from manifest state")
    teacher_manifest = read(ROOT / "tools/stockfish/manifest.json"); teacher_path = ROOT / teacher_manifest["executable"]
    assert digest(teacher_path) == teacher_manifest["executable_sha256"]
    assert digest(ROOT / plan["old_data"]) == plan["old_data_sha256"]
    assert digest(ROOT / plan["baseline"]) == plan["baseline_sha256"]
    excluded = set(); exclusions = []
    for kind, paths in (("data", setup["exclude_data"]), ("suite", setup["exclude_suites"])):
        for name in paths:
            path = ROOT / name
            if kind == "data": entries = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
            else:
                suite = read(path); entries = suite.get("openings", suite.get("positions", []))
            excluded.update(key(chess.Board(e["fen"])) for e in entries)
            exclusions.append({"path": name, "kind": kind, "sha256": digest(path), "positions": len(entries)})
    rng = random.Random(setup["seed"]); seen = set(); buckets = [0]*4; games = []; queried = written = 0
    rejections = collections.Counter(); started = time.monotonic()
    metadata = {"schema": 1, "complete": False, "status": "running", "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "plan_sha256": digest(plan_path), "generator_sha256": digest(__file__), "parameters": setup,
        "teacher": teacher_manifest, "teacher_options": {"Threads":1,"Hash":64}, "classical_engine": plan["baseline"],
        "classical_binary_sha256": plan["baseline_sha256"], "exclusions": exclusions,
        "source_policy": "Independent512-node teacher player,3% seeded random legal moves from8 fixed opening lines. Labels use separate cold FEN-only search. Source outcomes are descriptive, never oracle values.",
        "opening_lines": OPENINGS, "source_games": games}
    def checkpoint(status="running"):
        metadata.update(status=status, positions_written=written, queried=queried, bucket_counts=buckets,
            rejection_counts=dict(rejections), source_games_completed=len(games), seconds=round(time.monotonic()-started,3))
        manifest_path.write_text(json.dumps(metadata, indent=2) + "\n")
    checkpoint()
    try:
        with chess.engine.SimpleEngine.popen_uci(engine_command(teacher_path), timeout=30) as player, \
                chess.engine.SimpleEngine.popen_uci(engine_command(teacher_path), timeout=30) as teacher, \
                UciClient(teacher_path) as static, UciClient(ROOT / plan["baseline"]) as classical, \
                output.open("x", encoding="utf-8") as accepted, candidate_path.open("x", encoding="utf-8") as candidates, \
                pgn_path.open("x", encoding="utf-8") as pgn:
            for process in (player, teacher): process.configure({"Threads":1,"Hash":64})
            static.send("setoption name Threads value 1"); static.send("setoption name Hash value 64"); static.ready()
            for source_id in range(setup["games"]):
                board = chess.Board(); opening_index = rng.randrange(len(OPENINGS))
                for move in OPENINGS[opening_index].split(): board.push_uci(move)
                token = object(); pending = []
                while len(board.move_stack) < setup["max_plies"] and board.outcome(claim_draw=True) is None:
                    ply = len(board.move_stack); canonical = key(board)
                    if (sum(buckets) < setup["positions"] and len(pending) < setup["per_game"] and ply >= setup["minimum_ply"]
                            and ply % setup["sample_every"] == 0 and phase(board) <= setup["maximum_phase"]
                            and len(board.piece_map()) <= setup["maximum_pieces"] and board.halfmove_clock <= setup["maximum_halfmove_clock"]
                            and not board.is_check() and canonical not in seen and canonical not in excluded):
                        seen.add(canonical); fen = board.fen(en_passant="fen")
                        sample = label(teacher, board, setup["sample_nodes"]); verified = label(teacher, board, setup["verify_nodes"])
                        static.send("position fen " + fen); trace = static.command("eval", "Final evaluation")
                        value = re.search(r"Final evaluation\s+([+-]\d+\.\d+)\s+\(white side\)", trace)
                        if not value: raise ValueError("Unexpected teacher static trace: " + trace)
                        static_cp = int(round(float(value.group(1))*100))
                        reason = "accepted"; bucket = None
                        if sample["white_cp"] is None or verified["white_cp"] is None: reason = "native_mate_label"
                        elif abs(verified["white_cp"]) > 1500: reason = "outside_score_range"
                        elif sample["pv"][0] != verified["pv"][0]: reason = "unstable_first_move"
                        elif abs(sample["white_cp"]-verified["white_cp"]) > 50: reason = "unstable_value"
                        else:
                            bucket = next(i for i,(low,high) in enumerate(setup["score_ranges_abs_cp"]) if low <= abs(verified["white_cp"]) <= high)
                            if buckets[bucket] >= setup["quota_each"]: reason = "bucket_full"
                        row = {"id": f"stable-candidate-{queried:06}", "fen":fen, "source_game":source_id, "game":100000+source_id,
                            "ply":ply,"history_uci":[m.uci() for m in board.move_stack], "opening_index":opening_index,
                            "phase":phase(board),"pieces":len(board.piece_map()),"static_white_cp":static_cp,
                            "sample":sample,"verified":verified,"acceptance":reason,"bucket":bucket}
                        queried += 1
                        candidates.write(json.dumps(row,separators=(",",":")) + "\n"); candidates.flush()
                        if reason == "accepted":
                            classical.send("position fen " + fen)
                            base = int(classical.command("eval", "info string eval ").split()[-1])
                            row["classical_white_cp"] = base if board.turn else -base
                            buckets[bucket] += 1; pending.append(row)
                        else: rejections[reason] += 1
                        if queried % 128 == 0:
                            print(json.dumps({"queried":queried,"accepted_candidates":sum(buckets),"buckets":buckets,"games":len(games),"seconds":round(time.monotonic()-started,2)}),flush=True)
                    move = rng.choice(list(board.legal_moves)) if rng.random() < setup["random_probability"] else player.play(board,chess.engine.Limit(nodes=setup["play_nodes"]),game=token).move
                    if move not in board.legal_moves: raise ValueError("Illegal source move")
                    board.push(move)
                outcome = board.outcome(claim_draw=True); result = outcome.result() if outcome else "*"
                termination = outcome.termination.name.lower() if outcome else "maximum_plies_unresolved"
                game = chess.pgn.Game.from_board(board)
                game.headers.update(Event="Aster stable endgame data",Site="local",Date="????.??.??",Round=str(source_id+1),
                    White=player.id.get("name","teacher"),Black=player.id.get("name","teacher"),Result=result,Termination=termination,
                    SourceGame=str(source_id),PlayNodes=str(setup["play_nodes"]),RandomProbability=str(setup["random_probability"]))
                pgn.write(str(game) + "\n\n"); pgn.flush()
                games.append({"source_game":source_id,"result":result,"termination":termination,"plies":len(board.move_stack),
                    "accepted_positions":len(pending),"opening_index":opening_index})
                for row in pending:
                    row.update(source_result=result,source_termination=termination)
                    accepted.write(json.dumps(row,separators=(",",":")) + "\n"); written += 1
                accepted.flush()
                if source_id % 25 == 0:
                    checkpoint()
                    print(json.dumps({"source_games":len(games),"positions_written":written,"buckets":buckets,"seconds":round(time.monotonic()-started,2)}),flush=True)
                if written == setup["positions"]: break
        for entry in exclusions: assert digest(ROOT / entry["path"]) == entry["sha256"]
        assert digest(teacher_path) == teacher_manifest["executable_sha256"] and digest(ROOT / plan["baseline"]) == plan["baseline_sha256"]
        metadata.update(complete=written==setup["positions"], data_sha256=digest(output), candidates_sha256=digest(candidate_path),
            source_pgn_sha256=digest(pgn_path), source_outcomes=dict(collections.Counter(g["result"] for g in games)),
            source_unresolved=sum(g["result"]=="*" for g in games))
        checkpoint("complete" if metadata["complete"] else "incomplete_budget_exhausted")
        if not metadata["complete"]: raise ValueError("Source-game budget exhausted; partial data preserved, no training permitted")
        print(json.dumps({"complete":True,"positions":written,"source_games":len(games),"queried":queried,"source_unresolved":metadata["source_unresolved"]}),flush=True)
    except BaseException as error:
        metadata["error"] = repr(error)
        checkpoint("failed" if not metadata.get("complete") else "complete")
        raise


if __name__ == "__main__": main()
