"""Exercise the actual local HTTP/SSE host; python-chess is a test oracle only."""
import argparse
import hashlib
import json
import pathlib
import queue
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request

import chess
import chess.pgn
import io
from uci_client import DEFAULT_ENGINE, engine_command
from verify_mate_proof import verify as verify_proof

def same_fen(a,b): return chess.Board(a).fen()==chess.Board(b).fen()

ROOT = pathlib.Path(__file__).resolve().parents[1]


def replay_branch(fen, line):
    replay = chess.Board(fen)
    for move in line:
        if move == "null":
            # Aster's hypothetical pass changes turn/EP, not the halfmove clock.
            # python-chess treats a pushed null as a move and advances its clocks.
            halfmove = replay.halfmove_clock
            replay.push(chess.Move.null())
            replay.halfmove_clock = halfmove
        else:
            parsed = chess.Move.from_uci(move)
            assert parsed in replay.legal_moves, (fen, line, move)
            replay.push(parsed)
    return replay


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output")
    args = parser.parse_args()
    assert replay_branch(chess.STARTING_FEN, ["e2e4", "null", "g1f3"]).fen(en_passant="fen") == "rnbqkbnr/pppppppp/8/8/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2"
    assert replay_branch(chess.STARTING_FEN, ["null", "e7e5", "null", "g8f6"]).fen(en_passant="fen") == "rnbqkb1r/pppp1ppp/5n2/4p3/8/8/PPPPPPPP/RNBQKBNR w KQkq - 1 3"
    binary = DEFAULT_ENGINE
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0)); port = listener.getsockname()[1]
    address = f"http://127.0.0.1:{port}"
    events = queue.Queue()
    process = subprocess.Popen([*engine_command(binary), "play", str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def request(path, data=None, origin=None):
        headers = {"Content-Type": "application/json"}
        if origin: headers["Origin"] = origin
        body = json.dumps(data).encode() if data is not None else None
        return urllib.request.urlopen(urllib.request.Request(address + path, data=body, headers=headers), timeout=10)

    def get_state():
        with request("/api/state") as response: return json.load(response)

    def post(path, body=None):
        with request("/api/" + path, body or {}) as response: return json.load(response)

    def idle():
        for _ in range(300):
            state = get_state()
            if not state["thinking"]:
                assert state["error"] is None, state["error"]
                return state
            time.sleep(.01)
        raise AssertionError("Search failed to finish")

    def listen():
        try:
            with request("/api/events") as response:
                kind = ""; sequence = 0
                for raw in response:
                    line = raw.decode().rstrip()
                    if line.startswith("id: "): sequence = int(line[4:])
                    elif line.startswith("event: "): kind = line[7:]
                    elif line.startswith("data: "): events.put((sequence, kind, json.loads(line[6:])))
        except (OSError, TimeoutError): pass

    try:
        for _ in range(100):
            assert process.poll() is None, "Play server exited during startup"
            try: state = get_state(); break
            except urllib.error.URLError: time.sleep(.05)
        else: raise AssertionError("Play server did not start")
        with request("/") as response:
            assert "script-src 'self'" in response.headers["Content-Security-Policy"]
            assert "Your move. See its thinking." in response.read().decode()
        for asset in ("/app.js", "/app.css"):
            with request(asset) as response: response.read().decode("utf-8")
        for path, body, origin, status in [
            ("/api/new", {"side": "purple"}, None, 400),
            ("/api/new", {"fen": "bad"}, None, 400),
            ("/api/move", {"move": "e2e5"}, None, 400),
            ("/api/new", {}, "https://example.invalid", 403)]:
            try: request(path, body, origin); raise AssertionError("Bad request was accepted")
            except urllib.error.HTTPError as error: assert error.code == status, (path, error.code)
        assert get_state()["fen"] == chess.STARTING_FEN
        threading.Thread(target=listen, daemon=True).start()
        assert events.get(timeout=5)[1] == "state"
        post("new", {"milliseconds": 700})
        post("move", {"move": "e2e4"})
        state = idle(); assert len(state["moves"]) == 2
        board = chess.Board()
        for move in state["moves"]:
            parsed = chess.Move.from_uci(move["uci"])
            assert parsed in board.legal_moves and board.san(parsed) == move["san"]
            board.push(parsed); assert same_fen(board.fen(),move["fen"])
        assert same_fen(board.fen(),state["fen"])
        for color,key in [(chess.WHITE,"whiteAttacks"),(chess.BLACK,"blackAttacks")]:
            assert state[key]==[len(board.attackers(color,square))for square in chess.SQUARES]

        frames = []; analyses = []; previous = -1
        while True:
            sequence, kind, value = events.get(timeout=5)
            assert sequence > previous; previous = sequence
            if kind == "trace":
                frames.append(value)
                replay = replay_branch(value["rootFen"], value["view"]["line"])
                assert same_fen(replay.fen(),value["view"]["fen"]), (value, replay.fen(en_passant="fen"))
                view = value["view"]
                assert view["mainNodes"] + view["quiescenceNodes"] > 0
            elif kind == "analysis":
                analyses.append(value); replay = chess.Board(value["rootFen"])
                for move in value["pv"]:
                    parsed = chess.Move.from_uci(move["uci"])
                    assert parsed in replay.legal_moves and replay.san(parsed) == move["san"]
                    replay.push(parsed); assert same_fen(replay.fen(),move["fen"])
            elif kind == "state" and len(value["moves"]) == 2 and not value["thinking"]: break
        assert len(frames) >= 2 and analyses and frames[-1]["view"]["finished"]
        with request("/api/pgn") as response: pgn = chess.pgn.read_game(io.StringIO(response.read().decode()))
        assert pgn and not pgn.errors and same_fen(pgn.end().board().fen(),state["fen"])
        assert post("undo")["fen"] == chess.STARTING_FEN
        post("analyze"); post("stop"); stopped = idle()
        assert stopped["fen"] == chess.STARTING_FEN and not stopped["moves"] and not stopped["thinking"]
        post("new", {"side": "black", "milliseconds": 300}); state = idle()
        assert state["side"] == state["humanSide"] == 1 and len(state["moves"]) == 1
        mate=post("new",{"fen":"7k/6Q1/6K1/8/8/8/8/8 b - - 150 1","side":"white"})
        assert mate["result"]=="1-0" and mate["scoreWhite"]==30000
        post("new",{"fen":"7k/8/5KQ1/8/8/8/8/8 w - - 0 1","side":"white"})
        proof=post("proof",{"maxPlies":5});verified=verify_proof(proof)
        result = {"proof_positions_checked":verified["positions"],"status": "passed", "play_binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                  "engine_binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                  "real_sse_samples_checked": len(frames), "completed_depths_checked": len(analyses),
                  "null_pass_clock_fixtures": 2,
                  "checks": "HTTP errors, assets UTF-8, SSE ordering, legal moves, independent SAN/PV/branch replay, PGN, undo, stop, Black opening"}
        if args.output:
            output = pathlib.Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
            assert not output.exists(), "Preserve prior smoke reports"
            output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result))
    finally:
        process.terminate()
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired: process.kill(); process.wait()


if __name__ == "__main__": main()
