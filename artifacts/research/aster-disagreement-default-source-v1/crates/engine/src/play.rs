//! Rust HTTP host for Aster's native board, search observations and proof certificates.
use crate::chess::{board::Board, piece::Colour};
use serde_json::{Value, json};
use std::{
    collections::VecDeque,
    io::{self, BufRead, BufReader, Read, Write},
    process::{ChildStdin, Command, Stdio},
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, AtomicUsize, Ordering},
    },
    thread,
    time::{Duration, Instant},
};
use tiny_http::{Header, Method, Request, Response, Server, StatusCode};

struct Game {
    board: Board,
    start: String,
    moves: Vec<Value>,
    depths: Vec<Value>,
    trace: Value,
    human: u8,
    budget: u64,
    thinking: bool,
    stop_requested: bool,
    mode: String,
    id: u64,
    revision: u64,
    events: VecDeque<(u64, String, Value)>,
    writer: Option<Arc<Mutex<ChildStdin>>>,
    error: Option<String>,
}
type Shared = Arc<Mutex<Game>>;

fn outcome(board: &Board) -> (&'static str, Option<&'static str>) {
    if board.legal_moves().is_empty() {
        return if board.in_check() {
            (
                "Checkmate",
                Some(if board.turn() == Colour::White {
                    "0-1"
                } else {
                    "1-0"
                }),
            )
        } else {
            ("Draw by stalemate", Some("1/2-1/2"))
        };
    }
    if board.fifty_move_counter() >= 100 {
        return ("Draw by fifty-move rule", Some("1/2-1/2"));
    }
    if board.is_insufficient_material() {
        return ("Draw by insufficient material", Some("1/2-1/2"));
    }
    let mut real = board.clone();
    real.zero_height();
    if real.is_repetition() {
        return ("Draw by threefold repetition", Some("1/2-1/2"));
    }
    (if board.in_check() { "Check" } else { "Playing" }, None)
}

impl Game {
    fn new() -> Self {
        Self {
            board: Board::startpos(),
            start: Board::STARTING_FEN.into(),
            moves: vec![],
            depths: vec![],
            trace: Value::Null,
            human: 0,
            budget: 3000,
            thinking: false,
            stop_requested: false,
            mode: "play".into(),
            id: 0,
            revision: 0,
            events: VecDeque::new(),
            writer: None,
            error: None,
        }
    }
    fn snapshot(&self) -> Value {
        let (status, result) = outcome(&self.board);
        let legal: Vec<_> = self
            .board
            .legal_moves()
            .iter()
            .map(|m| m.display(self.board.rules()).to_string())
            .collect();
        let (material, phase, attacks) = geometry(&self.board.to_string());
        let score = if result == Some("1-0") {
            30000
        } else if result == Some("0-1") {
            -30000
        } else if result == Some("1/2-1/2") {
            0
        } else {
            self.depths
                .last()
                .and_then(|d| d["scoreWhite"].as_i64())
                .unwrap_or(0)
        };
        json!({"fen":self.board.to_string(),"side":self.board.turn() as u8,"inCheck":self.board.in_check(),"humanSide":self.human,
            "thinking":self.thinking,"mode":self.mode,"status":status,"result":result,"milliseconds":self.budget,
            "legal":if result.is_some(){vec![]}else{legal},"moves":self.moves,"scoreWhite":score,
            "materialWhite":material,"pieceSquareWhite":null,"structureActivityWhite":null,"tempoWhite":null,"phase":phase,
            "whiteAttacks":attacks[0].to_vec(),"blackAttacks":attacks[1].to_vec(),"searchId":format!("rust-{}",self.id),"depths":self.depths,
            "trace":self.trace,"error":self.error,"revision":self.revision,"engine":format!("Aster {}", crate::VERSION)})
    }
    fn emit(&mut self, kind: &str, value: Value) {
        self.revision += 1;
        let mut value = value;
        if kind == "state" {
            value["revision"] = self.revision.into();
        }
        self.events.push_back((self.revision, kind.into(), value));
        while self.events.len() > 128 {
            self.events.pop_front();
        }
    }
    fn state(&mut self) {
        self.emit("state", self.snapshot());
    }
    fn cancel(&mut self) {
        self.id += 1;
        self.thinking = false;
        if let Some(writer) = self.writer.take() {
            let _ = writeln!(writer.lock().unwrap(), "stop");
        }
    }
    fn apply(&mut self, text: &str) -> anyhow::Result<()> {
        let m = self.board.parse_uci(text)?;
        anyhow::ensure!(self.board.is_legal(m), "Illegal move");
        let san = self
            .board
            .san(m)
            .ok_or_else(|| anyhow::anyhow!("Illegal SAN"))?
            .to_string();
        let side = self.board.turn() as u8;
        let number = self.board.full_move_number();
        self.board.make_move_simple(m);
        self.board.zero_height();
        self.moves.push(
            json!({"uci":text,"san":san,"fen":self.board.to_string(),"side":side,"number":number}),
        );
        Ok(())
    }
    fn position_command(&self) -> String {
        format!(
            "position fen {} moves {}",
            self.start,
            self.moves
                .iter()
                .map(|m| m["uci"].as_str().unwrap())
                .collect::<Vec<_>>()
                .join(" ")
        )
    }
    fn pgn(&self) -> String {
        let (_, result) = outcome(&self.board);
        let mut pgn = format!(
            "[Event \"Aster Rust local game\"]\n[White \"{}\"]\n[Black \"{}\"]\n[Result \"{}\"]\n",
            if self.human == 0 { "You" } else { "Aster Rust" },
            if self.human == 1 { "You" } else { "Aster Rust" },
            result.unwrap_or("*")
        );
        if self.start != Board::STARTING_FEN {
            pgn += &format!("[SetUp \"1\"]\n[FEN \"{}\"]\n", self.start);
        }
        pgn.push('\n');
        for (i, m) in self.moves.iter().enumerate() {
            if m["side"] == 0 {
                pgn += &format!("{}. ", m["number"]);
            } else if i == 0 {
                pgn += &format!("{}... ", m["number"]);
            }
            pgn += m["san"].as_str().unwrap();
            pgn.push(' ');
        }
        pgn += result.unwrap_or("*");
        pgn.push('\n');
        pgn
    }
}

fn launch(shared: &Shared, analyze: bool) {
    let (id, root, command, budget) = {
        let mut g = shared.lock().unwrap();
        if g.thinking || outcome(&g.board).1.is_some() {
            return;
        }
        g.id += 1;
        g.thinking = true;
        g.stop_requested = false;
        g.mode = if analyze { "analyze" } else { "play" }.into();
        g.depths.clear();
        g.trace = Value::Null;
        g.error = None;
        g.state();
        (g.id, g.board.clone(), g.position_command(), g.budget)
    };
    let shared = Arc::clone(shared);
    thread::spawn(move || {
        let result = (|| -> anyhow::Result<()> {
            let mut child = Command::new(std::env::current_exe()?)
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::null())
                .spawn()?;
            let writer = Arc::new(Mutex::new(child.stdin.take().unwrap()));
            {
                let mut g = shared.lock().unwrap();
                if g.id != id {
                    let _ = child.kill();
                    let _ = child.wait();
                    return Ok(());
                }
                g.writer = Some(Arc::clone(&writer));
            }
            let mut reader = BufReader::new(child.stdout.take().unwrap());
            {
                let mut w = writer.lock().unwrap();
                writeln!(
                    w,
                    "uci\nsetoption name Hash value 64\nsetoption name Threads value 1\naster-trace on\n{command}\nisready"
                )?;
            }
            let mut start = Instant::now();
            let mut sent_go = false;
            let mut line = String::new();
            while reader.read_line(&mut line)? > 0 {
                let text = line.trim();
                if text == "readyok" && !sent_go {
                    start = Instant::now();
                    writeln!(writer.lock().unwrap(), "go movetime {budget}")?;
                    sent_go = true;
                    if shared.lock().unwrap().stop_requested {
                        writeln!(writer.lock().unwrap(), "stop")?;
                    }
                }
                let mut g = shared.lock().unwrap();
                if g.id != id {
                    let _ = writeln!(writer.lock().unwrap(), "quit");
                    break;
                }
                if let Some(payload) = text.strip_prefix("info string aster-trace ") {
                    if let Ok(sample) = serde_json::from_str::<Value>(payload) {
                        let view = json!({"depth":sample["depth"],"ply":sample["height"],"fen":sample["fen"],"line":sample["line"],"nodes":sample["nodes"],
                            "mainNodes":sample["mainCalls"],"quiescenceNodes":sample["qCalls"],"betaCutoffs":sample["betaCutoffs"],"tableCutoffs":sample["tableCutoffs"],"nullProbes":sample["nullProbes"],"reducedMoves":sample["reducedMoves"],
                            "milliseconds":start.elapsed().as_millis() as u64,"destinationVisits":sample["destinationVisits"],"rootMoves":sample["rootMoves"],"finished":sample["finished"]});
                        let frame = json!({"searchId":format!("rust-{id}"),"rootFen":root.to_string(),"rootSide":root.turn() as u8,"view":view});
                        g.trace = frame.clone();
                        g.emit("trace", frame);
                    }
                } else if text.starts_with("info depth ") && text.contains(" pv ") {
                    if let Some(analysis) = analysis(text, &root, id) {
                        if g.depths
                            .last()
                            .is_none_or(|d| d["depth"] != analysis["depth"])
                        {
                            g.depths.push(analysis.clone());
                        } else {
                            *g.depths.last_mut().unwrap() = analysis.clone();
                        }
                        g.emit("analysis", analysis);
                    }
                } else if let Some(best) = text.strip_prefix("bestmove ") {
                    g.thinking = false;
                    g.writer = None;
                    if !analyze {
                        if let Err(error) = g.apply(best.split_whitespace().next().unwrap_or("")) {
                            g.error = Some(error.to_string());
                        }
                    }
                    if !g.trace.is_null() {
                        g.trace["view"]["finished"] = true.into();
                    }
                    g.state();
                    let _ = writeln!(writer.lock().unwrap(), "quit");
                    break;
                }
                drop(g);
                line.clear();
            }
            let _ = writeln!(writer.lock().unwrap(), "quit");
            let _ = child.wait();
            Ok(())
        })();
        let mut g = shared.lock().unwrap();
        if g.id == id && g.thinking {
            g.thinking = false;
            g.writer = None;
            g.error = Some(result.err().map_or_else(
                || "Search ended without a best move".into(),
                |e| e.to_string(),
            ));
            g.state();
        }
    });
}

fn analysis(text: &str, root: &Board, id: u64) -> Option<Value> {
    let tokens: Vec<_> = text.split_whitespace().collect();
    // Aspiration failures are bounds, not completed-depth evaluations.
    if tokens.contains(&"lowerbound") || tokens.contains(&"upperbound") {
        return None;
    }
    let field = |name: &str| {
        tokens
            .iter()
            .position(|&v| v == name)
            .and_then(|i| tokens.get(i + 1))
            .and_then(|v| v.parse::<i64>().ok())
            .unwrap_or(0)
    };
    let score_index = tokens.iter().position(|&v| v == "score")?;
    let value = tokens.get(score_index + 2)?.parse::<i64>().ok()?;
    let score = if tokens[score_index + 1] == "mate" {
        value.signum() * (30000 - 2 * value.abs().min(499))
    } else {
        value
    };
    let start = tokens.iter().position(|&v| v == "pv")? + 1;
    let mut b = root.clone();
    let mut pv = vec![];
    for &token in &tokens[start..] {
        let m = b.parse_uci(token).ok()?;
        if !b.is_legal(m) {
            return None;
        }
        let san = b.san(m)?.to_string();
        b.make_move_simple(m);
        pv.push(json!({"uci":token,"san":san,"fen":b.to_string()}));
    }
    Some(
        json!({"searchId":format!("rust-{id}"),"rootFen":root.to_string(),"rootSide":root.turn() as u8,"depth":field("depth"),
        "selectiveDepth":field("seldepth"),"scoreWhite":score*if root.turn()==Colour::White{1}else{-1},"nodes":field("nodes"),
        "milliseconds":field("time"),"hashFull":field("hashfull"),"pv":pv}),
    )
}

fn geometry(fen: &str) -> (i32, i32, [[u32; 64]; 2]) {
    let mut squares = [' '; 64];
    let mut rank = 7;
    let mut file = 0;
    for c in fen.split_whitespace().next().unwrap().chars() {
        if c == '/' {
            rank -= 1;
            file = 0;
        } else if let Some(n) = c.to_digit(10) {
            file += n as usize;
        } else {
            squares[rank * 8 + file] = c;
            file += 1;
        }
    }
    let mut material = 0;
    let mut phase = 0;
    let mut attacks = [[0; 64]; 2];
    for (square, &piece) in squares.iter().enumerate() {
        if piece == ' ' {
            continue;
        }
        let side = usize::from(piece.is_lowercase());
        let p = piece.to_ascii_lowercase();
        let value = match p {
            'p' => 100,
            'n' => 320,
            'b' => 330,
            'r' => 500,
            'q' => 900,
            _ => 0,
        };
        material += value * if side == 0 { 1 } else { -1 };
        phase += match p {
            'n' | 'b' => 1,
            'r' => 2,
            'q' => 4,
            _ => 0,
        };
        let (x, y) = ((square % 8) as i32, (square / 8) as i32);
        let directions: &[(i32, i32)] = match p {
            'p' => {
                if side == 0 {
                    &[(-1, 1), (1, 1)]
                } else {
                    &[(-1, -1), (1, -1)]
                }
            }
            'n' => &[
                (-2, -1),
                (-2, 1),
                (-1, -2),
                (-1, 2),
                (1, -2),
                (1, 2),
                (2, -1),
                (2, 1),
            ],
            'b' => &[(-1, -1), (-1, 1), (1, -1), (1, 1)],
            'r' => &[(-1, 0), (1, 0), (0, -1), (0, 1)],
            _ => &[
                (-1, -1),
                (-1, 1),
                (1, -1),
                (1, 1),
                (-1, 0),
                (1, 0),
                (0, -1),
                (0, 1),
            ],
        };
        for &(dx, dy) in directions {
            for step in 1..8 {
                let (nx, ny) = (x + dx * step, y + dy * step);
                if !(0..8).contains(&nx) || !(0..8).contains(&ny) {
                    break;
                }
                let dest = (ny * 8 + nx) as usize;
                attacks[side][dest] += 1;
                if matches!(p, 'p' | 'n' | 'k') || squares[dest] != ' ' {
                    break;
                }
            }
        }
    }
    (material, phase.min(24), attacks)
}

struct Events {
    shared: Shared,
    after: u64,
    initialized: bool,
    pending: io::Cursor<Vec<u8>>,
    clients: Arc<AtomicUsize>,
}
impl Drop for Events {
    fn drop(&mut self) {
        self.clients.fetch_sub(1, Ordering::Relaxed);
    }
}
impl Read for Events {
    fn read(&mut self, out: &mut [u8]) -> io::Result<usize> {
        if out.is_empty() {
            return Ok(0);
        }
        if self.pending.position() as usize >= self.pending.get_ref().len() {
            let mut text = String::new();
            {
                let g = self.shared.lock().unwrap();
                if !self.initialized || g.events.front().is_some_and(|e| e.0 > self.after + 1) {
                    text = format!(
                        "id: {}\nevent: state\ndata: {}\n\n",
                        g.revision,
                        g.snapshot()
                    );
                    self.after = g.revision;
                    self.initialized = true;
                } else {
                    for (id, kind, value) in &g.events {
                        if *id > self.after {
                            text += &format!("id: {id}\nevent: {kind}\ndata: {value}\n\n");
                            self.after = *id;
                        }
                    }
                }
            }
            if text.is_empty() {
                thread::sleep(Duration::from_millis(80));
                text = ": heartbeat\n\n".into();
            }
            self.pending = io::Cursor::new(text.into_bytes());
        }
        self.pending.read(out)
    }
}

fn header(name: &str, value: &str) -> Header {
    Header::from_bytes(name, value).unwrap()
}
fn respond(request: Request, code: u16, content: &str, body: Vec<u8>) {
    let response=Response::from_data(body).with_status_code(StatusCode(code)).with_header(header("Content-Type",content))
        .with_header(header("X-Content-Type-Options","nosniff"))
        .with_header(header("Content-Security-Policy","default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"));
    let _ = request.respond(response);
}

fn handle(mut request: Request, shared: Shared, clients: Arc<AtomicUsize>, port: u16) {
    let path = request.url().split('?').next().unwrap_or("").to_string();
    if request.method() == &Method::Get && path == "/api/events" {
        if clients.fetch_add(1, Ordering::Relaxed) >= 12 {
            clients.fetch_sub(1, Ordering::Relaxed);
            respond(
                request,
                429,
                "application/json",
                b"{\"error\":\"Too many views\"}".to_vec(),
            );
            return;
        }
        let reader = Events {
            shared,
            after: 0,
            initialized: false,
            pending: io::Cursor::new(vec![]),
            clients,
        };
        let mut reader = reader;
        let mut writer = request.into_writer();
        let sent = (|| -> io::Result<()> {
            writer.write_all(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nCache-Control: no-cache\r\nX-Content-Type-Options: nosniff\r\nTransfer-Encoding: chunked\r\n\r\n")?;
            writer.flush()?;
            let mut buffer = [0u8; 8192];
            loop {
                let count = reader.read(&mut buffer)?;
                if count == 0 {
                    break;
                }
                write!(writer, "{count:x}\r\n")?;
                writer.write_all(&buffer[..count])?;
                writer.write_all(b"\r\n")?;
                writer.flush()?;
            }
            Ok(())
        })();
        let _ = sent;
        return;
    }
    if request.method() == &Method::Get {
        match path.as_str() {
            "/api/state" => {
                let body = shared.lock().unwrap().snapshot().to_string().into_bytes();
                respond(request, 200, "application/json", body);
            }
            "/api/pgn" => {
                let body = shared.lock().unwrap().pgn().into_bytes();
                respond(request, 200, "application/x-chess-pgn", body);
            }
            "/" | "/index.html" => respond(
                request,
                200,
                "text/html; charset=utf-8",
                include_bytes!("../assets/play/index.html").to_vec(),
            ),
            "/app.js" => respond(
                request,
                200,
                "application/javascript; charset=utf-8",
                include_bytes!("../assets/play/app.js").to_vec(),
            ),
            "/app.css" => respond(
                request,
                200,
                "text/css; charset=utf-8",
                include_bytes!("../assets/play/app.css").to_vec(),
            ),
            _ => respond(request, 404, "application/json", b"{}".to_vec()),
        }
        return;
    }
    if request.method() != &Method::Post {
        respond(request, 405, "application/json", b"{}".to_vec());
        return;
    }
    if request.headers().iter().any(|h| {
        h.field.equiv("Origin")
            && h.value.as_str() != format!("http://127.0.0.1:{port}")
            && h.value.as_str() != format!("http://localhost:{port}")
    }) {
        respond(
            request,
            403,
            "application/json",
            b"{\"error\":\"Origin rejected\"}".to_vec(),
        );
        return;
    }
    let result = (|| -> anyhow::Result<Value> {
        let mut bytes = vec![];
        request.as_reader().take(32769).read_to_end(&mut bytes)?;
        anyhow::ensure!(bytes.len() <= 32768, "Request too large");
        let data: Value = if bytes.is_empty() {
            json!({})
        } else {
            serde_json::from_slice(&bytes)?
        };
        if path == "/api/proof" {
            let board = shared.lock().unwrap().board.clone();
            let bound = data["maxPlies"].as_u64().unwrap_or(5);
            anyhow::ensure!(bound <= 7, "Choose at most seven plies");
            return Ok(serde_json::to_value(crate::aster_proof::build(
                &board,
                board.turn(),
                bound as u8,
                50_000,
                &AtomicBool::new(false),
            ))?);
        }
        let mut start = false;
        {
            let mut g = shared.lock().unwrap();
            match path.as_str() {
                "/api/new" => {
                    let budget = data["milliseconds"].as_u64().unwrap_or(3000);
                    anyhow::ensure!((300..=15000).contains(&budget), "Choose 300..15000 ms");
                    let human = match data["side"].as_str().unwrap_or("white") {
                        "white" => 0,
                        "black" => 1,
                        _ => anyhow::bail!("Choose white or black"),
                    };
                    let fen = data["fen"].as_str().unwrap_or(Board::STARTING_FEN);
                    let board = crate::aster_rules::parse_standard(fen)?;
                    g.cancel();
                    g.board = board;
                    g.start = g.board.to_string();
                    g.human = human;
                    g.budget = budget;
                    g.moves.clear();
                    g.depths.clear();
                    g.trace = Value::Null;
                    g.error = None;
                    start = g.board.turn() as u8 != human;
                }
                "/api/move" => {
                    anyhow::ensure!(
                        !g.thinking
                            && g.board.turn() as u8 == g.human
                            && outcome(&g.board).1.is_none(),
                        "It is not your turn"
                    );
                    g.apply(
                        data["move"]
                            .as_str()
                            .ok_or_else(|| anyhow::anyhow!("Move required"))?,
                    )?;
                    start = true;
                }
                "/api/undo" => {
                    g.cancel();
                    let human = g.human;
                    if !g.moves.is_empty() {
                        g.moves.pop();
                    }
                    while g
                        .moves
                        .last()
                        .is_some_and(|m| m["side"].as_u64() == Some(u64::from(human)))
                    {
                        g.moves.pop();
                    }
                    let moves: Vec<_> = g
                        .moves
                        .iter()
                        .map(|m| m["uci"].as_str().unwrap().to_string())
                        .collect();
                    g.board = Board::from_fen(&g.start)?;
                    g.moves.clear();
                    for m in moves {
                        g.apply(&m)?;
                    }
                    g.depths.clear();
                    g.trace = Value::Null;
                }
                "/api/stop" => {
                    g.stop_requested = true;
                    if let Some(w) = &g.writer {
                        writeln!(w.lock().unwrap(), "stop")?;
                    }
                }
                "/api/settings" => {
                    let budget = data["milliseconds"].as_u64().unwrap_or(0);
                    anyhow::ensure!((300..=15000).contains(&budget), "Choose 300..15000 ms");
                    g.budget = budget;
                }
                "/api/analyze" => {
                    anyhow::ensure!(!g.thinking, "Search already running");
                    start = true;
                }
                _ => anyhow::bail!("Unknown command"),
            }
            g.state();
        }
        if start {
            launch(&shared, path == "/api/analyze");
        }
        Ok(shared.lock().unwrap().snapshot())
    })();
    match result {
        Ok(value) => respond(
            request,
            200,
            "application/json",
            value.to_string().into_bytes(),
        ),
        Err(error) => respond(
            request,
            400,
            "application/json",
            json!({"error":error.to_string()}).to_string().into_bytes(),
        ),
    }
}

pub(crate) fn run(port: u16) -> anyhow::Result<()> {
    anyhow::ensure!(port >= 1024, "Choose port 1024..65535");
    let server = Server::http(("127.0.0.1", port)).map_err(|e| anyhow::anyhow!("{e}"))?;
    let shared = Arc::new(Mutex::new(Game::new()));
    let clients = Arc::new(AtomicUsize::new(0));
    println!("Play Aster Rust: http://127.0.0.1:{port}");
    for request in server.incoming_requests() {
        let g = Arc::clone(&shared);
        let c = Arc::clone(&clients);
        thread::spawn(move || handle(request, g, c, port));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn native_game_roundtrip() {
        let mut g = Game::new();
        g.apply("e2e4").unwrap();
        g.apply("e7e5").unwrap();
        assert_eq!(g.moves[0]["san"], "e4");
        assert_eq!(g.board.turn(), Colour::White);
        assert!(g.pgn().contains("1. e4 e5"));
    }
    #[test]
    fn terminal_mate_precedes_draw() {
        let b = Board::from_fen("7k/6Q1/6K1/8/8/8/8/8 b - - 150 1").unwrap();
        assert_eq!(outcome(&b), ("Checkmate", Some("1-0")));
    }
    #[test]
    fn initial_geometry() {
        let (material, phase, attacks) = geometry(Board::STARTING_FEN);
        assert_eq!((material, phase), (0, 24));
        assert!(attacks[0][18] > 0);
        assert!(attacks[1][42] > 0);
    }
    #[test]
    fn aspiration_bounds_are_not_completed_scores() {
        let root = Board::startpos();
        assert!(
            analysis(
                "info depth 8 score cp 40 lowerbound nodes 100 pv e2e4",
                &root,
                1
            )
            .is_none()
        );
        assert!(
            analysis(
                "info depth 8 score cp 40 upperbound nodes 100 pv e2e4",
                &root,
                1
            )
            .is_none()
        );
        assert!(analysis("info depth 8 score cp 40 nodes 100 pv e2e4", &root, 1).is_some());
        assert_eq!(
            analysis("info depth 8 score mate 3 nodes 100 pv e2e4", &root, 1).unwrap()["scoreWhite"],
            29994
        );
        assert_eq!(
            analysis("info depth 8 score mate -3 nodes 100 pv e2e4", &root, 1).unwrap()["scoreWhite"],
            -29994
        );
    }
}
