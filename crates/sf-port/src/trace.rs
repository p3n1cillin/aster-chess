// Aster search observer: optional samples of genuine search positions for the
// browser view. Observation only; it never changes a search decision.
// Rust port additions copyright (C) 2026 Aster contributors (GPL-3.0-or-later).

use crate::position::Position;
use crate::types::*;
use crate::uci::{format_score, move_to_uci};
use std::sync::Mutex;
use std::sync::atomic::{AtomicBool, Ordering::Relaxed};
use std::time::{Duration, Instant};

static ENABLED: AtomicBool = AtomicBool::new(false);
static DATA: Mutex<Option<Trace>> = Mutex::new(None);

pub const EVENT_BETA_CUTOFF: usize = 0;
pub const EVENT_TABLE_CUTOFF: usize = 1;
pub const EVENT_NULL_PROBE: usize = 2;
pub const EVENT_REDUCED_MOVE: usize = 3;

struct RootRow {
    mv: Move,
    score: Option<i64>,
    bound: &'static str,
    nodes_start: u64,
    nodes: u64,
    searching: bool,
}

struct Trace {
    calls: u64,
    last: Instant,
    main: u64,
    q: u64,
    dest: [u64; 64],
    events: [u64; 4],
    roots: Vec<RootRow>,
    depth: i32,
}

impl Trace {
    fn new() -> Self {
        Trace { calls: 0, last: Instant::now(), main: 0, q: 0, dest: [0; 64], events: [0; 4], roots: Vec::new(), depth: 0 }
    }
}

pub fn enable(on: bool) {
    ENABLED.store(on, Relaxed);
    *DATA.lock().unwrap() = Some(Trace::new());
}

#[inline(always)]
pub fn enabled() -> bool {
    ENABLED.load(Relaxed)
}

/// Resets per-search counters (called when a search starts).
pub fn reset() {
    if enabled() {
        *DATA.lock().unwrap() = Some(Trace::new());
    }
}

fn with<R>(f: impl FnOnce(&mut Trace) -> R) -> R {
    let mut g = DATA.lock().unwrap();
    f(g.get_or_insert_with(Trace::new))
}

pub fn event(index: usize) {
    with(|t| t.events[index] += 1);
}

pub fn root_begin(depth: i32, mv: Move, nodes: u64) {
    with(|t| {
        if t.depth != depth {
            t.depth = depth;
            t.roots.clear();
        }
        t.roots.retain(|r| r.mv != mv);
        t.roots.push(RootRow { mv, score: None, bound: "pending", nodes_start: nodes, nodes: 0, searching: true });
    });
}

pub fn root_end(pos: &Position, mv: Move, score: Value, alpha: Value, beta: Value, nodes: u64) {
    with(|t| {
        if let Some(r) = t.roots.iter_mut().find(|r| r.mv == mv) {
            r.nodes = nodes - r.nodes_start;
            r.score = Some(score_value(score, pos));
            r.bound = if score >= beta {
                "lower"
            } else if score <= alpha {
                "upper"
            } else {
                "exact"
            };
            r.searching = false;
        }
    });
}

/// Score as the host expects it: centipawns, or ±(30000 - 2·mate distance in moves).
fn score_value(v: Value, pos: &Position) -> i64 {
    let s = format_score(v, pos);
    let mut parts = s.split_whitespace();
    let kind = parts.next().unwrap_or("cp");
    let value: i64 = parts.next().and_then(|x| x.parse().ok()).unwrap_or(0);
    if kind == "mate" { value.signum() * (30000 - 2 * value.abs()) } else { value }
}

/// Context needed to describe the current search position.
pub struct Frame<'a> {
    pub pos: &'a Position,
    pub line: &'a [Move],
    pub root_game_ply: i32,
    pub depth: i32,
    pub nodes: u64,
}

pub fn observe(quiescence: bool, prev: Move, frame: impl FnOnce() -> Option<String>) {
    let emit = with(|t| {
        t.calls += 1;
        if quiescence {
            t.q += 1;
        } else {
            t.main += 1;
        }
        if prev.is_ok() {
            let dest = if prev.type_of() == CASTLING {
                (prev.from_sq() & !7) + if prev.to_sq() > prev.from_sq() { 6 } else { 2 }
            } else {
                prev.to_sq()
            };
            t.dest[dest] += 1;
        }
        if t.calls % 512 == 0 && t.last.elapsed() >= Duration::from_millis(80) {
            t.last = Instant::now();
            true
        } else {
            false
        }
    });
    if emit {
        if let Some(s) = frame() {
            crate::uci::emit(&s);
        }
    }
}

pub fn render(f: &Frame, finished: bool) -> String {
    let line: Vec<String> = f.line.iter().map(|&m| if m == Move::NULL { "null".to_string() } else { move_to_uci(m, f.pos.is_chess960()) }).collect();
    // Null moves do not advance Stockfish's game ply; report the fullmove number
    // as if every ply of the line (including null moves) were played.
    let mut fen = f.pos.fen();
    if let Some(i) = fen.rfind(' ') {
        let ply = f.root_game_ply + f.line.len() as i32;
        let full = 1 + (ply - (f.pos.side_to_move() == BLACK) as i32) / 2;
        fen.truncate(i + 1);
        fen.push_str(&full.to_string());
    }
    with(|t| {
        let roots: Vec<String> = t
            .roots
            .iter()
            .map(|r| {
                let (nodes, searching, bound) = if r.searching {
                    ((f.nodes.saturating_sub(r.nodes_start)), !finished, if finished { "unfinished" } else { r.bound })
                } else {
                    (r.nodes, false, r.bound)
                };
                format!(
                    "{{\"move\":\"{}\",\"score\":{},\"bound\":\"{}\",\"nodes\":{},\"searching\":{}}}",
                    move_to_uci(r.mv, f.pos.is_chess960()),
                    r.score.map_or("null".to_string(), |s| s.to_string()),
                    bound,
                    nodes,
                    searching
                )
            })
            .collect();
        let dest: Vec<String> = t.dest.iter().map(|d| d.to_string()).collect();
        let line_json: Vec<String> = line.iter().map(|m| format!("\"{m}\"")).collect();
        format!(
            "info string aster-trace {{\"fen\":\"{}\",\"line\":[{}],\"depth\":{},\"height\":{},\"nodes\":{},\"mainCalls\":{},\"qCalls\":{},\"destinationVisits\":[{}],\"betaCutoffs\":{},\"tableCutoffs\":{},\"nullProbes\":{},\"reducedMoves\":{},\"rootMoves\":[{}],\"finished\":{}}}\n",
            fen,
            line_json.join(","),
            f.depth,
            f.line.len(),
            f.nodes,
            t.main,
            t.q,
            dest.join(","),
            t.events[0],
            t.events[1],
            t.events[2],
            t.events[3],
            roots.join(","),
            finished
        )
    })
}
