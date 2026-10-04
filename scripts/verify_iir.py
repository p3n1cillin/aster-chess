"""Independent legal-PV and root restoration checks under changed search policy."""
import contextlib
import json
import random

import chess

from run_rating import digest, read, write_new
from uci_client import ROOT, UciClient
from verify import SPECIAL_FENS, validate_pv
from verify_q_evasion import normalize


def main():
    plan = read(ROOT / "artifacts/research/iir-plan-v2.json")
    paths = [ROOT / plan[role] for role in ("candidate","baseline")]
    assert [digest(p) for p in paths] == [plan[role + "_sha256"] for role in ("candidate","baseline")]
    rng = random.Random(20261110); roots = []; board = chess.Board()
    for _ in range(64):
        for _ in range(rng.randrange(3,9)):
            if board.outcome(claim_draw=True) is not None: board = chess.Board()
            board.push(rng.choice(list(board.legal_moves)))
        roots.append(board.copy())
    cases = []
    for i,root in enumerate(roots):
        cases.append((f"history-{i}",root,"go depth 8 nodes 5000"))
        cases.append((f"fen-{i}",chess.Board(root.fen()),"go depth 8 nodes 5000"))
        near = chess.Board(root.fen()); near.halfmove_clock = 99
        cases.append((f"rule50-{i}",near,"go depth 8 nodes 5000"))
    special = [chess.Board(fen) for fen in SPECIAL_FENS[:7]]
    repeated = chess.Board()
    for move in "g1f3 g8f6 f3g1 f6g8 g1f3 g8f6 f3g1 f6g8".split(): repeated.push_uci(move)
    special.append(repeated)
    for i,root in enumerate(special):
        first = next(iter(root.legal_moves),None)
        for variant in range(8):
            command = "go depth 8 nodes " + str((1,50,500,5000)[variant % 4])
            if variant >= 4 and first: command += " searchmoves " + first.uci()
            cases.append((f"special-{i}-{variant}",root,command))
    assert len(cases) == 256
    rows = []
    with contextlib.ExitStack() as stack:
        clients = [stack.enter_context(UciClient(path)) for path in paths]
        for client in clients:
            client.send("setoption name Hash value 64"); client.send("setoption name Move Overhead value 0"); client.ready()
        for label,root,command in cases:
            origin = root.root().fen(en_passant="fen"); position = "position fen " + origin
            if root.move_stack: position += " moves " + " ".join(m.uci() for m in root.move_stack)
            traces = []
            for client in clients:
                client.send(position)
                client.send("go depth 4 nodes 1000"); warm = client.until("bestmove ")
                client.send(command); lines = client.until("bestmove ")
                validate_pv(root,warm); validate_pv(root,lines)
                move = lines[-1].split()[1]
                assert move == "0000" if not list(root.legal_moves) else chess.Move.from_uci(move) in root.legal_moves
                if " searchmoves " in command: assert move == command.split(" searchmoves ")[1]
                assert client.command("d","info string fen ") == "info string fen " + root.fen(en_passant="fen")
                for line in lines:
                    if line.startswith("info depth "): assert int(line.split(" nodes ")[1].split()[0]) <= int(command.split(" nodes ")[1].split()[0])
                traces.append({"warm":normalize(warm),"search":normalize(lines)})
            rows.append({"id":label,"origin":origin,"moves":[m.uci() for m in root.move_stack],"fen":root.fen(),
                "command":command,"same_trace":traces[0] == traces[1],"candidate":traces[0],"baseline":traces[1]})
    write_new(ROOT / "artifacts/validation/iir-differential.json",{"passed":True,"cases":len(rows),"seed":20261110,
        "script_sha256":digest(__file__),"candidate_sha256":digest(paths[0]),"baseline_sha256":digest(paths[1]),"positions":rows,
        "same_full_traces":sum(r["same_trace"] for r in rows),"interpretation":"Changed selective search expected. Every PV/bestmove checked independently, restricted move and node budgets checked, retained history and root restoration checked. Not universal search correctness or playing strength."})
    print(json.dumps({"passed":True,"cases":len(rows),"same_full_traces":sum(r["same_trace"] for r in rows)}))


if __name__ == "__main__": main()
