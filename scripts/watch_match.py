"""Play a live, watchable Aster vs Stockfish match and record it.

Serves a local page (http://127.0.0.1:5190 by default) showing the board, both
engines' current depth, score and principal variation, the clocks, the move
list and a running score. Games are color-swapped pairs from a frozen opening
suite. Every finished game is appended to a PGN and a JSON report that records
the binaries, options, openings and time control.

A handful of watchable games is a demonstration, not a rating: report the
result with its uncertainty and never infer superiority from it.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import http.server
import json
import math
import pathlib
import threading
import time

import chess
import chess.engine
import chess.pgn
import chess.svg

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_ASTER = ROOT / "target" / "release" / ("aster.exe" if __import__("os").name == "nt" else "aster")
DEFAULT_OPENINGS = ROOT / "tests" / "fixtures" / "openings-v4.json"


def default_stockfish() -> pathlib.Path:
    manifest = json.loads((ROOT / "tools" / "stockfish" / "manifest.json").read_text())
    return ROOT / manifest["executable"].replace("\\", "/")


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Aster vs Stockfish live</title>
<style>
:root{--bg:#f6f5f2;--panel:#fff;--ink:#1d1d1f;--muted:#6b6b70;--line:#e3e1dc;--accent:#2f6fde;--win:#1f8a4c;--loss:#c0392b}
@media (prefers-color-scheme:dark){:root{--bg:#141416;--panel:#1d1d21;--ink:#ececf0;--muted:#9a9aa3;--line:#2c2c33;--accent:#6ea0ff;--win:#4cc27e;--loss:#ff6b5c}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
header{padding:14px 20px;border-bottom:1px solid var(--line);display:flex;gap:16px;align-items:baseline;flex-wrap:wrap}
header h1{font-size:18px;margin:0}header .note{color:var(--muted);font-size:13px}
main{display:grid;grid-template-columns:minmax(280px,560px) minmax(280px,1fr);gap:20px;padding:20px;max-width:1200px;margin:auto}
@media (max-width:820px){main{grid-template-columns:1fr;padding:16px}}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}
#board svg{width:100%;height:auto;display:block;border-radius:6px}
.player{display:flex;justify-content:space-between;align-items:center;padding:8px 2px;font-weight:600}
.player .clock{font-variant-numeric:tabular-nums;font-weight:500;color:var(--muted)}.player.tomove .name::before{content:"\25B6  ";color:var(--accent)}
.engine{margin-bottom:12px}.engine h3{margin:0 0 4px;font-size:14px}.engine .stats{color:var(--muted);font-size:13px;font-variant-numeric:tabular-nums}
.pv{font-family:ui-monospace,Consolas,monospace;font-size:13px;word-break:break-word;margin-top:4px}
#moves{font-family:ui-monospace,Consolas,monospace;font-size:13px;max-height:180px;overflow:auto;white-space:normal}
table{width:100%;border-collapse:collapse;font-size:13px}td,th{padding:4px 6px;border-bottom:1px solid var(--line);text-align:left}
.score{font-size:22px;font-weight:700;font-variant-numeric:tabular-nums}.W{color:var(--win)}.L{color:var(--loss)}
.status{color:var(--muted);font-size:13px;margin-top:6px}
</style></head><body>
<header><h1 id="title">Aster vs Stockfish</h1><span class="note" id="tc"></span><span class="note">Live demonstration games, not a rating.</span></header>
<main>
<section><div class="panel"><div class="player" id="top"></div><div id="board"></div><div class="player" id="bottom"></div><div class="status" id="status"></div></div></section>
<section>
<div class="panel" style="margin-bottom:16px"><div class="score" id="score"></div><div class="status" id="scoreNote"></div></div>
<div class="panel" style="margin-bottom:16px" id="engines"></div>
<div class="panel" style="margin-bottom:16px"><h3 style="margin:0 0 6px;font-size:14px">Moves</h3><div id="moves"></div></div>
<div class="panel"><table><thead><tr><th>#</th><th>White</th><th>Black</th><th>Opening</th><th>Result</th></tr></thead><tbody id="games"></tbody></table></div>
</section></main>
<script>
function fmtClock(ms){if(ms==null)return"";const s=Math.max(0,ms)/1000;const m=Math.floor(s/60);return m+":"+(s%60).toFixed(1).padStart(4,"0")}
function esc(t){return String(t).replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]))}
async function tick(){
 try{const r=await fetch("/state",{cache:"no-store"});const s=await r.json();
  document.getElementById("title").textContent=s.title;document.getElementById("tc").textContent=s.time_control;
  document.getElementById("board").innerHTML=s.svg;
  const w={name:s.white,clock:s.clocks.white},b={name:s.black,clock:s.clocks.black};
  const top=s.orientation==="white"?b:w,bottom=s.orientation==="white"?w:b;
  const tm=s.turn;const set=(id,p,isTurn)=>{const e=document.getElementById(id);e.className="player"+(isTurn?" tomove":"");e.innerHTML='<span class="name">'+esc(p.name)+'</span><span class="clock">'+fmtClock(p.clock)+'</span>'};
  set("top",top,(top===w&&tm==="white")||(top===b&&tm==="black"));set("bottom",bottom,(bottom===w&&tm==="white")||(bottom===b&&tm==="black"));
  document.getElementById("status").textContent=s.status;
  document.getElementById("score").innerHTML='Aster <span class="W">'+s.score.aster+'</span> &ndash; <span class="L">'+s.score.opponent+'</span> '+esc(s.opponent_name);
  document.getElementById("scoreNote").textContent=s.score_note;
  document.getElementById("engines").innerHTML=s.engines.map(e=>'<div class="engine"><h3>'+esc(e.name)+'</h3><div class="stats">'+esc(e.stats)+'</div><div class="pv">'+esc(e.pv)+'</div></div>').join("");
  document.getElementById("moves").textContent=s.moves;
  document.getElementById("games").innerHTML=s.games.map(g=>'<tr><td>'+g.n+'</td><td>'+esc(g.white)+'</td><td>'+esc(g.black)+'</td><td>'+esc(g.opening)+'</td><td>'+esc(g.result)+'</td></tr>').join("");
 }catch(e){document.getElementById("status").textContent="Waiting for match host…"}
 setTimeout(tick,350)}
tick();
</script></body></html>"""


class State:
    def __init__(self, title: str, time_control: str, opponent_name: str):
        self.lock = threading.Lock()
        self.board = chess.Board()
        self.lastmove = None
        self.title = title
        self.time_control = time_control
        self.white = self.black = ""
        self.clocks = {"white": None, "black": None}
        self.status = "Starting engines…"
        self.engines: dict[str, dict] = {}
        self.games: list[dict] = []
        self.score = {"aster": 0.0, "opponent": 0.0}
        self.opponent_name = opponent_name
        self.orientation = "white"
        self.moves = ""

    def snapshot(self) -> dict:
        with self.lock:
            check = self.board.king(self.board.turn) if self.board.is_check() else None
            svg = chess.svg.board(self.board, lastmove=self.lastmove, check=check, size=560,
                                  orientation=chess.WHITE if self.orientation == "white" else chess.BLACK)
            n = len(self.games)
            note = ""
            if n:
                p = self.score["aster"] / n
                # Normal-approximation 95% interval for the score, games treated as independent.
                se = math.sqrt(max(p * (1 - p), 1e-9) / n)
                note = f"{n} game{'s' if n != 1 else ''}; Aster score {100 * p:.1f}% (95% interval roughly {100 * max(0, p - 1.96 * se):.0f}–{100 * min(1, p + 1.96 * se):.0f}%)"
            return {"title": self.title, "time_control": self.time_control, "svg": svg, "white": self.white, "black": self.black,
                    "clocks": self.clocks, "turn": "white" if self.board.turn else "black", "status": self.status,
                    "engines": list(self.engines.values()), "games": self.games, "score": self.score,
                    "score_note": note, "opponent_name": self.opponent_name, "orientation": self.orientation, "moves": self.moves}


def serve(state: State, port: int) -> http.server.ThreadingHTTPServer:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/state"):
                body = json.dumps(state.snapshot()).encode()
                ctype = "application/json"
            elif self.path in ("/", "/index.html"):
                body = PAGE.encode()
                ctype = "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def score_text(score: chess.engine.PovScore | None, turn: chess.Color) -> str:
    if score is None:
        return "?"
    s = score.white()
    if s.is_mate():
        return f"#{s.mate()}"
    return f"{s.score() / 100:+.2f}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--engine", default=str(DEFAULT_ASTER), help="Aster executable")
    parser.add_argument("--opponent", default=None, help="Opponent executable (default: pinned official Stockfish)")
    parser.add_argument("--pairs", type=int, default=2, help="Color-swapped game pairs")
    parser.add_argument("--movetime", type=float, default=1.0, help="Seconds per move (ignored with --clock)")
    parser.add_argument("--clock", help="Game clock BASE+INC in seconds, e.g. 60+0.6")
    parser.add_argument("--hash", type=int, default=64)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--openings", default=str(DEFAULT_OPENINGS))
    parser.add_argument("--first-opening", type=int, default=0)
    parser.add_argument("--max-plies", type=int, default=600, help="Unfinished games stay unresolved")
    parser.add_argument("--port", type=int, default=5190)
    parser.add_argument("--output", help="Output prefix (default artifacts/matches/live-<engine>-vs-<opponent>-<timestamp>)")
    args = parser.parse_args()

    engine_path = pathlib.Path(args.engine).resolve()
    opponent_path = pathlib.Path(args.opponent).resolve() if args.opponent else default_stockfish()
    opening_path = pathlib.Path(args.openings).resolve()
    opening_doc = json.loads(opening_path.read_text())
    openings = opening_doc["openings"]
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")

    clock = None
    if args.clock:
        base, inc = args.clock.split("+")
        clock = (float(base), float(inc))
        tc_text = f"{base}+{inc} s clock per side"
    else:
        tc_text = f"{args.movetime:g} s per move"

    aster = chess.engine.SimpleEngine.popen_uci([str(engine_path)])
    opponent = chess.engine.SimpleEngine.popen_uci([str(opponent_path)])
    try:
        for e in (aster, opponent):
            opts = {}
            if "Hash" in e.options:
                opts["Hash"] = args.hash
            if "Threads" in e.options:
                opts["Threads"] = args.threads
            e.configure(opts)
        aster_name = aster.id.get("name", "Aster")
        opp_name = opponent.id.get("name", "Opponent")
        def slug(name: str) -> str:
            return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")

        prefix = pathlib.Path(args.output) if args.output else ROOT / "artifacts" / "matches" / (
            f"live-{slug(aster_name)}-vs-{slug(opp_name)}-{stamp}")
        prefix.parent.mkdir(parents=True, exist_ok=True)
        # Append extensions (names may contain dots, e.g. version numbers).
        pgn_path = prefix.parent / (prefix.name + ".pgn")
        report_path = prefix.parent / (prefix.name + ".json")

        state = State(f"{aster_name} vs {opp_name}", tc_text, opp_name)
        server = serve(state, args.port)
        print(f"Watch live at http://127.0.0.1:{args.port}  (PGN: {pgn_path})", flush=True)

        report = {
            "kind": "live demonstration match (not a rating)",
            "started": datetime.datetime.now().isoformat(timespec="seconds"),
            "engine": {"name": aster_name, "path": str(engine_path), "sha256": sha256(engine_path)},
            "opponent": {"name": opp_name, "path": str(opponent_path), "sha256": sha256(opponent_path)},
            "options": {"Hash": args.hash, "Threads": args.threads, "Ponder": False},
            "time_control": {"movetime_s": None if clock else args.movetime, "clock_base_s": clock[0] if clock else None,
                             "clock_increment_s": clock[1] if clock else None},
            "openings": {"path": str(opening_path), "sha256": sha256(opening_path), "first_index": args.first_opening},
            "max_plies": args.max_plies,
            "games": [],
        }

        def write_report():
            tmp = report_path.parent / (report_path.name + ".tmp")
            tmp.write_text(json.dumps(report, indent=2) + "\n")
            tmp.replace(report_path)

        game_no = 0
        for pair in range(args.pairs):
            opening = openings[(args.first_opening + pair) % len(openings)]
            for aster_white in (True, False):
                game_no += 1
                board = chess.Board(opening.get("start_fen", chess.STARTING_FEN))
                for uci in opening["moves"].split():
                    board.push_uci(uci)
                players = {chess.WHITE: aster if aster_white else opponent, chess.BLACK: opponent if aster_white else aster}
                names = {chess.WHITE: aster_name if aster_white else opp_name, chess.BLACK: opp_name if aster_white else aster_name}
                clocks = {chess.WHITE: clock[0], chess.BLACK: clock[0]} if clock else None
                with state.lock:
                    state.board = board.copy()
                    state.lastmove = board.peek() if board.move_stack else None
                    state.white, state.black = names[chess.WHITE], names[chess.BLACK]
                    state.orientation = "white" if aster_white else "black"
                    state.engines = {}
                    state.status = f"Game {game_no}: opening {opening['id']}"
                    state.clocks = {"white": clock[0] * 1000, "black": clock[0] * 1000} if clock else {"white": None, "black": None}
                termination = None
                result = "*"
                game_key = f"{stamp}-{game_no}"
                while True:
                    outcome = board.outcome(claim_draw=True)
                    if outcome:
                        result = outcome.result()
                        termination = outcome.termination.name.lower()
                        break
                    if board.ply() >= args.max_plies:
                        termination = "unresolved_max_plies"
                        break
                    side = board.turn
                    eng = players[side]
                    if clock:
                        limit = chess.engine.Limit(white_clock=clocks[chess.WHITE], black_clock=clocks[chess.BLACK],
                                                   white_inc=clock[1], black_inc=clock[1])
                    else:
                        limit = chess.engine.Limit(time=args.movetime)
                    start = time.monotonic()
                    with eng.analysis(board, limit, game=game_key + ("w" if eng is players[chess.WHITE] else "b")) as analysis:
                        for info in analysis:
                            if "depth" in info and "pv" in info:
                                pv_board = board.copy()
                                san = []
                                for m in info["pv"][:12]:
                                    if not pv_board.is_legal(m):
                                        break
                                    san.append(pv_board.san(m))
                                    pv_board.push(m)
                                stats = f"depth {info.get('depth')}/{info.get('seldepth', '?')}  eval {score_text(info.get('score'), side)} (White view)  nodes {info.get('nodes', 0):,}  nps {info.get('nps', 0):,}"
                                with state.lock:
                                    state.engines[names[side]] = {"name": names[side] + " (thinking)", "stats": stats, "pv": " ".join(san)}
                                    if clock:
                                        elapsed = time.monotonic() - start
                                        key = "white" if side == chess.WHITE else "black"
                                        state.clocks[key] = (clocks[side] - elapsed) * 1000
                        best = analysis.wait()
                    elapsed = time.monotonic() - start
                    with state.lock:
                        if names[side] in state.engines:
                            state.engines[names[side]]["name"] = names[side]
                    if clock:
                        clocks[side] -= elapsed
                        if clocks[side] < 0:
                            result = "0-1" if side == chess.WHITE else "1-0"
                            termination = "time_forfeit"
                            break
                        clocks[side] += clock[1]
                    move = best.move
                    if move is None or not board.is_legal(move):
                        result = "0-1" if side == chess.WHITE else "1-0"
                        termination = "illegal_move"
                        break
                    san = board.san(move)
                    board.push(move)
                    with state.lock:
                        state.board = board.copy()
                        state.lastmove = move
                        state.status = f"Game {game_no}: {names[side]} played {san}"
                        if clock:
                            state.clocks = {"white": clocks[chess.WHITE] * 1000, "black": clocks[chess.BLACK] * 1000}
                        game_view = chess.pgn.Game.from_board(board)
                        state.moves = str(game_view.mainline_moves())

                # Record the game
                game = chess.pgn.Game.from_board(board)
                game.headers["Event"] = "Aster vs Stockfish live demonstration"
                game.headers["Site"] = "local"
                game.headers["Date"] = datetime.date.today().strftime("%Y.%m.%d")
                game.headers["Round"] = str(game_no)
                game.headers["White"] = names[chess.WHITE]
                game.headers["Black"] = names[chess.BLACK]
                game.headers["Result"] = result
                game.headers["Opening"] = opening["id"]
                game.headers["TimeControl"] = f"{clock[0]:g}+{clock[1]:g}" if clock else f"movetime {args.movetime:g}s"
                game.headers["Termination"] = termination or "unknown"
                with pgn_path.open("a", encoding="utf-8") as f:
                    print(game, file=f, end="\n\n")

                aster_points = None
                if result != "*":
                    white_points = {"1-0": 1.0, "0-1": 0.0, "1/2-1/2": 0.5}[result]
                    aster_points = white_points if aster_white else 1.0 - white_points
                report["games"].append({"game": game_no, "pair": pair, "opening": opening["id"], "aster_white": aster_white,
                                        "result": result, "termination": termination, "plies": board.ply(),
                                        "aster_points": aster_points})
                write_report()
                with state.lock:
                    if aster_points is not None:
                        state.score["aster"] += aster_points
                        state.score["opponent"] += 1.0 - aster_points
                    state.games.append({"n": game_no, "white": names[chess.WHITE], "black": names[chess.BLACK],
                                        "opening": opening["id"], "result": f"{result} ({(termination or '').replace('_', ' ')})"})
                    state.status = f"Game {game_no} finished: {result} by {(termination or '').replace('_', ' ')}"
                print(f"game {game_no}: {names[chess.WHITE]} - {names[chess.BLACK]} {result} ({termination})", flush=True)

        report["finished"] = datetime.datetime.now().isoformat(timespec="seconds")
        played = [g for g in report["games"] if g["aster_points"] is not None]
        report["summary"] = {"games": len(report["games"]), "resolved": len(played),
                             "aster_points": sum(g["aster_points"] for g in played),
                             "unresolved": len(report["games"]) - len(played),
                             "interpretation": "Demonstration games only; far too few for a rating or a superiority claim."}
        write_report()
        with state.lock:
            state.status = "Match finished. " + state.status
        print(json.dumps(report["summary"]), flush=True)
        print("Match finished; the page stays up for 10 minutes (Ctrl+C to exit).", flush=True)
        try:
            time.sleep(600)
        except KeyboardInterrupt:
            pass
        server.shutdown()
    finally:
        aster.quit()
        opponent.quit()


if __name__ == "__main__":
    main()
