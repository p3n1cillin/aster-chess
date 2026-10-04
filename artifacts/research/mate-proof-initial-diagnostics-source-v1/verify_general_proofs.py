"""Independently check general certificates, bounded oracle agreement and protocol limits."""
import copy
import json
import pathlib
import random
import subprocess
import sys
import time

import chess

from run_rating import digest, write_new
from uci_client import ROOT, UciClient, engine_command
from verify_mate_proof import verify
from verify_strategy_proof import verify as verify_legacy


class OracleLimit(Exception): pass


def bounded_oracle(board, strong, bound, budget=100000):
    visited = 0
    def visit(remaining):
        nonlocal visited
        if visited >= budget: raise OracleLimit()
        visited += 1
        if board.is_checkmate(): return board.turn != strong
        if remaining == 0 or board.outcome(claim_draw=True) is not None: return False
        choose = board.turn == strong
        # Different deterministic order from Aster; no native search or eval.
        for move in sorted(board.legal_moves, key=lambda m: m.uci()):
            board.push(move)
            try: won = visit(remaining - 1)
            finally: board.pop()
            if choose and won: return True
            if not choose and not won: return False
        return not choose
    try: return visit(bound), visited
    except OracleLimit: return None, visited


def main():
    engine = ROOT / "artifacts/publish/mate-proof-dev/Aster.dll"
    directory = ROOT / "artifacts/proofs/mate-proof-general-v1"; directory.mkdir(exist_ok=False)
    examples = ["6k1/5ppp/8/8/8/8/5PPP/3Q2K1 w - - 0 1", "7k/7p/4K1Q1/8/8/8/8/8 w - - 0 1",
        "k7/p1P5/2K5/8/8/8/8/8 w - - 0 1", "5B2/7B/6P1/R4pPk/8/7K/8/8 w - f6 0 1",
        "5k2/4p1p1/8/3B3B/8/8/8/4K2R w K - 0 1", "8/8/4K3/1k6/8/1p6/8/Q1R5 w - - 0 1"]
    certificates = []; controls = []
    def export(board, strong, bound, label):
        destination = directory / (label + ".json")
        result = subprocess.run([*engine_command(engine), "certify-mate", str(destination), str(bound), "white" if strong else "black", board.fen(en_passant="fen")], capture_output=True, text=True)
        if result.returncode: raise AssertionError((board.fen(), result.stdout, result.stderr))
        proof = json.loads(destination.read_text()); checked = verify(proof)
        certificates.append({"path": destination.relative_to(ROOT).as_posix(), "sha256": digest(destination),
            "visits": proof["visits"], "strong_side": "white" if strong else "black", **checked})
        return proof, destination
    for index, fen in enumerate(examples):
        for mirror in (False, True):
            board = chess.Board(fen); board = board.mirror() if mirror else board
            proof, path = export(board, board.turn, 7, f"example-{index}-{'black' if mirror else 'white'}")
            if proof["rootDistance"] > 1:
                board.push_uci(proof["nodes"][0]["edges"][0]["move"])
                export(board, not board.turn, 6, f"defender-{index}-{'black' if mirror else 'white'}")
            if index == 4:
                # Independent valid alternative exercises exact castling replay;
                # the engine picks the equally mating rook move first.
                castle = copy.deepcopy(proof); root = chess.Board(castle["rootFen"])
                move = "e8g8" if mirror else "e1g1"
                root.push_uci(move); assert root.is_checkmate()
                castle["nodes"][0]["edges"][0]["move"] = move; castle["nodes"][1]["fen"] = root.fen(en_passant="fen")
                verify(castle); write_new(directory / f"castling-alternative-{mirror}.json", castle)

    seed = 20261115; rng = random.Random(seed); differential = []; attempts = 0
    with UciClient(engine) as client:
        while len(differential) < 64 and attempts < 4096:
            attempts += 1; board = chess.Board(None)
            pieces = [chess.Piece(chess.KING, True), chess.Piece(chess.KING, False),
                chess.Piece(rng.choice([chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN]), True),
                chess.Piece(rng.choice([chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN]), True),
                chess.Piece(chess.PAWN, False)]
            if attempts % 3 == 0: pieces.append(chess.Piece(chess.ROOK, False))
            for square, piece in zip(rng.sample(range(64), len(pieces)), pieces): board.set_piece_at(square, piece)
            board.turn = chess.WHITE
            if not board.is_valid() or board.outcome(claim_draw=True) is not None: continue
            if len(differential) % 2: board = board.mirror()
            original = board.fen(en_passant="fen")
            client.send("position fen " + original)
            line = client.command("explain mate 3 50000", "info string explanation ")
            native = json.loads(line[len("info string explanation "):]); assert native["visits"] <= 50000
            expected, visits = bounded_oracle(board, board.turn, 3)
            assert board.fen(en_passant="fen") == original
            if native["complete"]:
                assert expected is not False
                export(board, board.turn, 3, f"seeded-{len(differential)}")
            elif native["reason"] == "unproven_within_bound": assert expected is not True
            else: assert native["reason"] == "node_limit"
            assert client.command("d", "info string fen ") == "info string fen " + original
            differential.append({"fen": original, "native_complete": native["complete"], "native_reason": native["reason"],
                "native_visits": native["visits"], "oracle_proved": expected, "oracle_visits": visits})
        assert len(differential) == 64

        # Readiness may consume an early completed explanation; retain that line.
        root = examples[-1]; client.send("position fen " + root); client.send("go infinite"); client.send("explain mate 7")
        started = time.monotonic(); client.send("isready"); lines = client.until("readyok")
        ready_seconds = time.monotonic() - started; assert ready_seconds < 1
        explanation_lines = [line for line in lines if line.startswith("info string explanation ")]
        if not explanation_lines: explanation_lines = [client.until("info string explanation ")[-1]]
        explanation = json.loads(explanation_lines[-1][len("info string explanation "):]); assert explanation["complete"]
        started = time.monotonic(); client.send("stop"); stopped = client.until("bestmove ")
        stop_seconds = time.monotonic() - started; assert stop_seconds < 1
        assert chess.Move.from_uci(stopped[-1].split()[1]) in chess.Board(root).legal_moves
        assert client.command("d", "info string fen ") == "info string fen " + root
        cancellations = []
        for _ in range(8):
            client.send("position startpos"); client.send("explain mate 7 100000"); started = time.monotonic()
            client.send("stop"); client.send("isready"); stopped = client.until("readyok")
            elapsed = time.monotonic() - started; assert elapsed < 1
            result = [line for line in stopped if line.startswith("info string explanation ")]
            assert result; status = json.loads(result[-1][len("info string explanation "):])
            assert not status["complete"] and status["reason"] in ("cancelled", "node_limit", "unproven_within_bound")
            assert client.command("d", "info string fen ") == "info string fen " + chess.STARTING_FEN
            cancellations.append({"reason": status["reason"], "seconds": elapsed})
        assert any(row["reason"] == "cancelled" for row in cancellations)
        for command in ("explain mate 8", "explain mate 3 0", "explain something", "explain mate 3 5 extra"):
            client.send(command); assert client.until("info string error:")[-1].startswith("info string error:")
        client.send("position fen " + examples[0]); line = client.command("explain", "info string explanation ")
        assert json.loads(line[len("info string explanation "):])["complete"]

    original = json.loads((directory / "example-5-white.json").read_text()); mutations = []
    def reject(name, action):
        value = copy.deepcopy(original); action(value)
        try: verify(value)
        except (AssertionError, ValueError, KeyError, IndexError): mutations.append(name)
        else: raise AssertionError("Corruption accepted: " + name)
    defender = next(n["id"] for n in original["nodes"] if len(n["edges"]) > 1)
    reject("missing defense", lambda p: p["nodes"][defender]["edges"].pop())
    reject("illegal edge", lambda p: p["nodes"][0]["edges"][0].update(move="e2e5"))
    reject("cycle", lambda p: p["nodes"][0]["edges"][0].update(to=0))
    reject("false bound", lambda p: p["nodes"][1].update(distance=p["nodes"][0]["distance"]))
    reject("false leaf", lambda p: p["nodes"][-1].update(fen=chess.STARTING_FEN))
    reject("clock mismatch", lambda p: p["nodes"][1].update(fen=" ".join(p["nodes"][1]["fen"].split()[:4]) + " 98 1"))
    reject("unreachable node", lambda p: p["nodes"].append(copy.deepcopy(p["nodes"][-1])))
    reject("wrong winner", lambda p: p.update(strongSide=1))
    reject("incomplete claim", lambda p: p.update(complete=False))
    reject("unsupported horizon", lambda p: p.update(maxPlies=8))
    reject("false work budget", lambda p: p.update(visits=1))
    path = directory / "example-0-white.json"; before = digest(path)
    overwrite = subprocess.run([*engine_command(engine), "certify-mate", str(path), "1", "white", examples[0]], capture_output=True, text=True)
    assert overwrite.returncode == 2 and digest(path) == before
    absent = directory / "unproven-must-not-export.json"
    failure = subprocess.run([*engine_command(engine), "certify-mate", str(absent), "0", "white", chess.STARTING_FEN], capture_output=True, text=True)
    assert failure.returncode == 2 and not absent.exists()
    legacy = []
    for path in sorted((ROOT / "artifacts/proofs").glob("*.json")):
        data = json.loads(path.read_text())
        if data.get("complete") is True and "strongSide" in data and "schema" not in data:
            legacy.append({"path": path.relative_to(ROOT).as_posix(), **verify_legacy(data)})
    old = chess.Board("5B2/8/R5P1/R4pPk/8/7K/8/8 w - f6 0 1"); old.push_uci("g5f6")
    controls.append({"fixture_correction": "Initial expected en passant mate had a g6 escape because f6 blocks the a6 rook. Replace that rook with a bishop on h7 to defend g6. First failed test log retained; algorithm unchanged.", "original_escape_moves": [m.uci() for m in old.legal_moves]})
    report = {"passed": True, "engine_sha256": digest(engine), "script_sha256": digest(__file__), "verifier_sha256": digest(ROOT / "scripts/verify_mate_proof.py"),
        "certificates": certificates, "certificate_positions": sum(r["positions"] for r in certificates), "certificate_edges": sum(r["edges"] for r in certificates),
        "differential_seed": seed, "differential_attempts": attempts, "differential_cases": differential,
        "corruptions_rejected": mutations, "legacy_certificates": legacy, "controls": controls,
        "protocol": {"ready_seconds": ready_seconds, "stop_seconds": stop_seconds, "cancellations": cancellations,
            "explanation_during_infinite_search": explanation, "overwrite_refused": True, "incomplete_export_refused": True},
        "interpretation": "Independent winning strategies and bounded oracle agreement. Unknown budgets are retained. Covers general material, both colors, attacker/defender roots, special moves, cancellation and protocol. No playing strength or Stockfish superiority inferred."}
    write_new(ROOT / "artifacts/validation/mate-proof-general.json", report)
    print(json.dumps({"passed": True, "certificates": len(certificates), "positions": report["certificate_positions"], "differential_cases": 64, "corruptions": len(mutations), "legacy_certificates": len(legacy)}))


if __name__ == "__main__": main()
