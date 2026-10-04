"""Verify every strategy edge and checkmate leaf without Aster or tablebases."""
import argparse
import hashlib
import json
import pathlib

import chess


def geometry(board): return " ".join(board.fen().split()[:4])


def verify(proof):
    assert proof["complete"] is True and proof["reason"] == "complete"
    nodes = proof["nodes"]; assert 0 < len(nodes) <= proof["nodeLimit"]
    strong = chess.WHITE if proof["strongSide"] == 0 else chess.BLACK
    root = chess.Board(proof["rootFen"])
    assert geometry(root) == geometry(chess.Board(nodes[0]["fen"]))
    assert nodes[0]["distance"] == proof["rootDistance"] and root.halfmove_clock + proof["rootDistance"] < 100
    edges = 0; leaves = 0; defenses = 0; adjacency = []
    for index, node in enumerate(nodes):
        assert node["id"] == index and isinstance(node["distance"], int) and node["distance"] >= 0
        board = chess.Board(node["fen"]); assert board.is_valid() and len(board.piece_map()) == 3
        majors = board.pieces(chess.QUEEN, strong) | board.pieces(chess.ROOK, strong)
        assert len(majors) == 1
        legal = {m.uci() for m in board.legal_moves}; moves = [e["move"] for e in node["edges"]]
        assert len(set(moves)) == len(moves) and set(moves) <= legal
        if not legal:
            assert board.is_checkmate() and board.turn != strong and node["distance"] == 0 and not moves
            leaves += 1
        elif board.turn == strong:
            assert len(moves) == 1
        else:
            assert set(moves) == legal  # Every defensive reply must be included.
            defenses += len(moves)
        children = []
        for edge in node["edges"]:
            child_id = edge["to"]; assert isinstance(child_id, int) and 0 <= child_id < len(nodes)
            child = nodes[child_id]; assert child["distance"] < node["distance"]
            board.push_uci(edge["move"])
            try: assert geometry(board) == geometry(chess.Board(child["fen"]))
            finally: board.pop()
            children.append(child_id); edges += 1
        adjacency.append(children)
    reached = set(); pending = [0]
    while pending:
        index = pending.pop()
        if index not in reached: reached.add(index); pending.extend(adjacency[index])
    assert len(reached) == len(nodes) and leaves > 0
    return {"passed": True, "positions": len(nodes), "edges": edges, "covered_defensive_replies": defenses,
            "checkmate_leaves": leaves, "mate_upper_bound_plies": proof["rootDistance"], "strong_side": "white" if strong else "black",
            "interpretation": "Complete legal winning strategy: one attacker move, every defender reply, strictly decreasing bound, all leaves checkmate. Independent of Aster and Syzygy. Prior history before the FEN origin is not claimed."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("certificate"); parser.add_argument("--output", required=True)
    args = parser.parse_args(); output = pathlib.Path(args.output)
    if output.exists(): parser.error("Preserve verification reports")
    source = pathlib.Path(args.certificate)
    result = verify(json.loads(source.read_text()))
    result["certificate_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    result["verifier_sha256"] = hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()
    output.write_text(json.dumps(result, indent=2) + "\n"); print(json.dumps(result))


if __name__ == "__main__": main()
