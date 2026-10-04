"""Replay every general mate-certificate branch using independent chess rules."""
import argparse
import hashlib
import json
import pathlib

import chess


def verify(proof):
    assert proof["schema"] == 1 and proof["complete"] is True and proof["reason"] == "complete"
    assert type(proof["strongSide"]) is int and proof["strongSide"] in (0, 1)
    assert type(proof["maxPlies"]) is int and 0 <= proof["maxPlies"] <= 7
    assert type(proof["nodeLimit"]) is int and 1 <= proof["nodeLimit"] <= 100000
    assert type(proof["visits"]) is int and 1 <= proof["visits"] <= proof["nodeLimit"]
    assert type(proof["rootDistance"]) is int and 0 <= proof["rootDistance"] <= proof["maxPlies"]
    nodes = proof["nodes"]; assert 0 < len(nodes) <= proof["visits"]
    root = chess.Board(proof["rootFen"]); assert root.is_valid()
    strong = chess.WHITE if proof["strongSide"] == 0 else chess.BLACK
    assert nodes[0]["distance"] == proof["rootDistance"]
    if not root.is_checkmate(): assert root.halfmove_clock + proof["maxPlies"] < 100
    reached = set(); edges = defenses = leaves = 0

    def visit(index, board, depth):
        nonlocal edges, defenses, leaves
        assert type(index) is int and 0 <= index < len(nodes) and index not in reached
        reached.add(index)
        node = nodes[index]
        assert node["id"] == index and type(node["distance"]) is int and 0 <= node["distance"] <= proof["maxPlies"] - depth
        assert board.is_valid() and board.fen(en_passant="fen") == chess.Board(node["fen"]).fen(en_passant="fen")
        legal = {m.uci() for m in board.legal_moves}; moves = [e["move"] for e in node["edges"]]
        assert len(moves) == len(set(moves)) and set(moves) <= legal
        if board.is_checkmate():
            assert board.turn != strong and node["distance"] == 0 and not moves
            leaves += 1; return
        assert board.outcome(claim_draw=True) is None and node["distance"] > 0
        if board.turn == strong: assert len(moves) == 1
        else:
            assert set(moves) == legal  # Include every legal defensive reply.
            defenses += len(moves)
        distances = []
        for edge in node["edges"]:
            child = edge["to"]; assert type(child) is int and 0 <= child < len(nodes)
            assert nodes[child]["distance"] < node["distance"]
            board.push_uci(edge["move"])
            try: visit(child, board, depth + 1)
            finally: board.pop()
            distances.append(nodes[child]["distance"])
            edges += 1
        assert node["distance"] == 1 + max(distances)

    visit(0, root, 0)
    assert len(reached) == len(nodes) and leaves > 0
    return {"passed": True, "positions": len(nodes), "edges": edges, "covered_defensive_replies": defenses,
        "checkmate_leaves": leaves, "mate_upper_bound_plies": proof["rootDistance"],
        "interpretation": "Complete winning strategy with exact rule replay from the FEN origin: every defense, strictly decreasing bounds, all leaves actual mate before draw rules. No engine, eval, tablebase or teacher dependency. Bound is not a claim of globally shortest mate or earlier history."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("certificate"); parser.add_argument("--output", required=True)
    args = parser.parse_args(); destination = pathlib.Path(args.output)
    if destination.exists(): parser.error("Preserve completed verification")
    source = pathlib.Path(args.certificate); report = verify(json.loads(source.read_text()))
    report.update({"certificate_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "verifier_sha256": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()})
    destination.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__": main()
