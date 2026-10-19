// Aster core. Original attribution and source mapping: uci.rs.license.
// SPDX-License-Identifier: GPL-3.0-or-later
// Modified 2026-10-19: source naming and notice layout only.

use crate::history::SharedHistories;
use crate::movegen::{GenType, MoveList};
use crate::nnue::network::{DEFAULT_NET_NAME, Network};
use crate::position::{Position, START_FEN, square_to_string};
use crate::search::{LimitsType, RootMove, SearchOptions, SharedRef, SharedState, Worker};
use crate::timeman::now;
use crate::tt::TranspositionTable;
use crate::types::*;
use std::io::{BufRead, Write};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering::Relaxed};
use std::thread::JoinHandle;

pub const ENGINE_NAME: &str = concat!("Aster ", env!("CARGO_PKG_VERSION"));
pub const ENGINE_AUTHOR: &str = "Aster contributors";

static OUT_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

/// Writes complete lines to stdout atomically and flushes.
pub fn emit(s: &str) {
    let _g = OUT_LOCK.lock().unwrap();
    let mut out = std::io::stdout().lock();
    let _ = out.write_all(s.as_bytes());
    let _ = out.flush();
}

pub fn move_to_uci(m: Move, chess960: bool) -> String {
    if m == Move::NONE {
        return "(none)".to_string();
    }
    if m == Move::NULL {
        return "0000".to_string();
    }
    let from = m.from_sq();
    let mut to = m.to_sq();
    if m.type_of() == CASTLING && !chess960 {
        to = make_square(if to > from { FILE_G } else { FILE_C }, rank_of(from));
    }
    let mut s = square_to_string(from) + &square_to_string(to);
    if m.type_of() == PROMOTION {
        s.push(b" pnbrqk"[m.promotion_type()] as char);
    }
    s
}

pub fn to_move(pos: &Position, s: &str) -> Move {
    let s = s.to_ascii_lowercase();
    for &m in MoveList::new(pos, GenType::Legal).as_slice() {
        if s == move_to_uci(m, pos.is_chess960()) {
            return m;
        }
    }
    Move::NONE
}

fn win_rate_params(pos: &Position) -> (f64, f64) {
    let material = pos.count_both(PAWN)
        + 3 * pos.count_both(KNIGHT)
        + 3 * pos.count_both(BISHOP)
        + 5 * pos.count_both(ROOK)
        + 9 * pos.count_both(QUEEN);
    let m = material.clamp(17, 78) as f64 / 58.0;
    let as_ = [-142.72052667, 372.35176398, -340.71073572, 415.23490212];
    let bs = [5.93832785, 15.61267078, -30.57816876, 69.63866711];
    let a = ((as_[0] * m + as_[1]) * m + as_[2]) * m + as_[3];
    let b = ((bs[0] * m + bs[1]) * m + bs[2]) * m + bs[3];
    (a, b)
}

fn win_rate_model(v: Value, pos: &Position) -> i32 {
    let (a, b) = win_rate_params(pos);
    (0.5 + 1000.0 / (1.0 + ((a - v as f64) / b).exp())) as i32
}

pub fn to_cp(v: Value, pos: &Position) -> i32 {
    let (a, _) = win_rate_params(pos);
    (100.0 * v as f64 / a).round() as i32
}

pub fn wdl(v: Value, pos: &Position) -> String {
    let w = win_rate_model(v, pos);
    let l = win_rate_model(-v, pos);
    format!("{} {} {}", w, 1000 - w - l, l)
}

pub fn format_score(v: Value, pos: &Position) -> String {
    const TB_CP: i32 = 20000;
    if !is_decisive(v) {
        format!("cp {}", to_cp(v, pos))
    } else if v.abs() <= VALUE_TB {
        let distance = VALUE_TB - v.abs();
        format!(
            "cp {}",
            if v > 0 {
                TB_CP - distance
            } else {
                -TB_CP + distance
            }
        )
    } else {
        let plies = if v > 0 {
            VALUE_MATE - v
        } else {
            -(VALUE_MATE - v.abs())
        };
        let m = (if plies > 0 { plies + 1 } else { plies }) / 2;
        format!("mate {m}")
    }
}

#[derive(Clone)]
pub struct Options {
    #[cfg(feature = "evaluation-risk")]
    pub evaluation_risk: bool,
    #[cfg(feature = "disagreement-guard")]
    pub disagreement_guard: bool,
    pub threads: usize,
    pub hash: usize,
    pub ponder: bool,
    pub multi_pv: usize,
    pub skill_level: i32,
    pub move_overhead: i64,
    pub nodestime: i64,
    pub chess960: bool,
    pub limit_strength: bool,
    pub elo: i32,
    pub show_wdl: bool,
    pub syzygy_path: String,
    pub syzygy_probe_depth: i32,
    pub syzygy_50_move_rule: bool,
    pub syzygy_probe_limit: i32,
    pub eval_file: String,
    pub numa_policy: String,
    pub debug_log_file: String,
}

impl Default for Options {
    fn default() -> Self {
        Options {
            #[cfg(feature = "evaluation-risk")]
            evaluation_risk: true,
            #[cfg(feature = "disagreement-guard")]
            disagreement_guard: true,
            threads: 1,
            hash: 16,
            ponder: false,
            multi_pv: 1,
            skill_level: 20,
            move_overhead: 10,
            nodestime: 0,
            chess960: false,
            limit_strength: false,
            elo: 1320,
            show_wdl: false,
            syzygy_path: String::new(),
            syzygy_probe_depth: 1,
            syzygy_50_move_rule: true,
            syzygy_probe_limit: 7,
            eval_file: DEFAULT_NET_NAME.to_string(),
            numa_policy: "auto".to_string(),
            debug_log_file: String::new(),
        }
    }
}

impl Options {
    fn search_options(&self) -> SearchOptions {
        SearchOptions {
            #[cfg(feature = "evaluation-risk")]
            evaluation_risk: self.evaluation_risk,
            #[cfg(feature = "disagreement-guard")]
            disagreement_guard: self.disagreement_guard,
            multi_pv: self.multi_pv,
            skill_level: self.skill_level,
            limit_strength: self.limit_strength,
            elo: self.elo,
            move_overhead: self.move_overhead,
            nodestime: self.nodestime,
            ponder: self.ponder,
            show_wdl: self.show_wdl,
            syzygy_50_move_rule: self.syzygy_50_move_rule,
            syzygy_probe_depth: self.syzygy_probe_depth,
            syzygy_probe_limit: self.syzygy_probe_limit,
        }
    }

    fn print(&self) -> String {
        let b = |x: bool| if x { "true" } else { "false" };
        let e = |s: &str| {
            if s.is_empty() {
                "<empty>".to_string()
            } else {
                s.to_string()
            }
        };
        let max_threads = 1024.max(
            4 * std::thread::available_parallelism()
                .map(|n| n.get())
                .unwrap_or(1),
        );
        [
            #[cfg(feature = "evaluation-risk")]
            "option name Aster Evaluation Risk type check default true".to_string(),
            #[cfg(feature = "disagreement-guard")]
            "option name Aster Disagreement Guard type check default true".to_string(),
            format!(
                "option name Debug Log File type string default {}",
                e(&Options::default().debug_log_file)
            ),
            format!(
                "option name NumaPolicy type string default {}",
                Options::default().numa_policy
            ),
            format!("option name Threads type spin default 1 min 1 max {max_threads}"),
            "option name Hash type spin default 16 min 1 max 33554432".to_string(),
            "option name Clear Hash type button".to_string(),
            format!("option name Ponder type check default {}", b(false)),
            "option name MultiPV type spin default 1 min 1 max 256".to_string(),
            "option name Skill Level type spin default 20 min 0 max 20".to_string(),
            "option name Move Overhead type spin default 10 min 0 max 5000".to_string(),
            "option name nodestime type spin default 0 min 0 max 10000".to_string(),
            "option name UCI_Chess960 type check default false".to_string(),
            "option name UCI_LimitStrength type check default false".to_string(),
            "option name UCI_Elo type spin default 1320 min 1320 max 3190".to_string(),
            "option name UCI_ShowWDL type check default false".to_string(),
            "option name SyzygyPath type string default <empty>".to_string(),
            "option name SyzygyProbeDepth type spin default 1 min 1 max 100".to_string(),
            "option name Syzygy50MoveRule type check default true".to_string(),
            "option name SyzygyProbeLimit type spin default 7 min 0 max 7".to_string(),
            format!("option name EvalFile type string default {DEFAULT_NET_NAME}"),
        ]
        .join("\n")
    }
}

fn find_network(name: &str) -> Option<std::path::PathBuf> {
    let p = std::path::PathBuf::from(name);
    if p.is_absolute() {
        return p.exists().then_some(p);
    }
    let mut dirs = vec![std::path::PathBuf::from(".")];
    if let Ok(exe) = std::env::current_exe() {
        if let Some(d) = exe.parent() {
            dirs.push(d.to_path_buf());
        }
    }
    dirs.push(std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")));
    dirs.into_iter().map(|d| d.join(name)).find(|p| p.exists())
}

#[cfg(feature = "embed-net")]
static EMBEDDED_NET: &[u8] =
    include_bytes!(concat!(env!("CARGO_MANIFEST_DIR"), "/nn-c9e480e92425.nnue"));

/// Loads the default network: embedded when built with `embed-net`, otherwise
/// from the working directory, the executable's directory or the crate directory.
fn load_default_network(name: &str) -> Result<Network, String> {
    #[cfg(feature = "embed-net")]
    if name == DEFAULT_NET_NAME {
        return Network::load_bytes(EMBEDDED_NET);
    }
    let path = find_network(name).ok_or_else(|| format!("ERROR: The network file {name} was not found. Run python scripts/fetch_aster_network.py"))?;
    Network::load_file(&path)
}

fn next_power_of_two(n: usize) -> usize {
    n.max(1).next_power_of_two()
}

pub struct Engine {
    pub options: Options,
    pos: Position,
    network: Arc<Network>,
    shared: Box<SharedState>,
    workers: Option<Vec<Box<Worker>>>,
    search: Option<JoinHandle<Vec<Box<Worker>>>>,
    pub on_bestmove: Arc<dyn Fn(&str, &str) + Send + Sync>,
    pub identity: crate::Identity,
}

impl Engine {
    pub fn new(identity: crate::Identity) -> Result<Engine, String> {
        let options = Options::default();
        let network = Arc::new(load_default_network(&options.eval_file)?);
        let shared = Box::new(Self::make_shared(&options, network.clone()));
        let mut pos = Position::default();
        pos.set(START_FEN, false).unwrap();
        let mut e = Engine {
            options,
            pos,
            network,
            shared,
            workers: None,
            search: None,
            identity,
            on_bestmove: Arc::new(|bm: &str, ponder: &str| {
                if ponder.is_empty() {
                    emit(&format!("bestmove {bm}\n"));
                } else {
                    emit(&format!("bestmove {bm} ponder {ponder}\n"));
                }
            }),
        };
        e.resize_threads();
        Ok(e)
    }

    fn make_shared(options: &Options, network: Arc<Network>) -> SharedState {
        let n = options.threads;
        SharedState {
            tt: TranspositionTable::new(options.hash),
            histories: SharedHistories::new(next_power_of_two(n)),
            network,
            stop: AtomicBool::new(false),
            increase_depth: AtomicBool::new(true),
            ponder: AtomicBool::new(false),
            nodes: (0..n).map(|_| AtomicU64::new(0)).collect(),
            tb_hits: (0..n).map(|_| AtomicU64::new(0)).collect(),
            best_move_changes: (0..n).map(|_| AtomicU64::new(0)).collect(),
            silent: AtomicBool::new(false),
        }
    }

    fn resize_threads(&mut self) {
        self.wait_for_search_finished();
        self.workers = None;
        let silent = self.shared.silent.load(Relaxed);
        self.shared = Box::new(Self::make_shared(&self.options, self.network.clone()));
        self.shared.silent.store(silent, Relaxed);
        let sref = SharedRef(&*self.shared as *const SharedState);
        let n = self.options.threads;
        let workers: Vec<Box<Worker>> = (0..n)
            .map(|i| Worker::new(sref, self.options.search_options(), i, i, n))
            .collect();
        self.workers = Some(workers);
        self.clear_threads();
    }

    fn clear_threads(&mut self) {
        if let Some(ws) = self.workers.as_mut() {
            for w in ws.iter_mut() {
                w.clear();
            }
            if let Some(m) = ws[0].manager.as_mut() {
                m.clear();
            }
        }
    }

    pub fn set_silent(&self, silent: bool) {
        self.shared.silent.store(silent, Relaxed);
    }

    pub fn wait_for_search_finished(&mut self) {
        if let Some(h) = self.search.take() {
            self.workers = Some(h.join().expect("search thread panicked"));
        }
    }

    pub fn stop(&self) {
        self.shared.stop.store(true, Relaxed);
    }

    pub fn ponderhit(&self) {
        self.shared.ponder.store(false, Relaxed);
    }

    pub fn search_clear(&mut self) {
        self.wait_for_search_finished();
        self.shared.tt.clear();
        self.clear_threads();
        // Re-open the tables (frees memory-mapped files, as in the upstream reference).
        if !self.options.syzygy_path.is_empty() {
            if let Some(msg) = crate::syzygy::init(&self.options.syzygy_path) {
                emit(&format!(
                    "info string {msg}
"
                ));
            }
        }
    }

    pub fn fen(&self) -> String {
        self.pos.fen()
    }

    pub fn position(&self) -> &Position {
        &self.pos
    }

    pub fn set_position(&mut self, fen: &str, moves: &[String]) -> Result<(), String> {
        let mut p = Position::default();
        p.set(fen, self.options.chess960).map_err(|e| e.0)?;
        for mv in moves {
            let m = to_move(&p, mv);
            if m == Move::NONE {
                return Err(format!("Illegal move: {mv}"));
            }
            p.do_move_simple(m);
        }
        self.pos = p;
        Ok(())
    }

    pub fn go(&mut self, limits: LimitsType) {
        self.wait_for_search_finished();
        let mut workers = self.workers.take().expect("workers available");

        self.shared.stop.store(false, Relaxed);
        self.shared.ponder.store(limits.ponder_mode, Relaxed);
        self.shared.increase_depth.store(true, Relaxed);
        if let Some(m) = workers[0].manager.as_mut() {
            m.stop_on_ponderhit = false;
        }

        let mut root_moves = Vec::new();
        for s in &limits.searchmoves {
            let m = to_move(&self.pos, s);
            if m != Move::NONE {
                root_moves.push(RootMove::new(m));
            }
        }
        if root_moves.is_empty() {
            for &m in MoveList::new(&self.pos, GenType::Legal).as_slice() {
                root_moves.push(RootMove::new(m));
            }
        }

        let tb_opts = crate::syzygy::TbOptions {
            rule50: self.options.syzygy_50_move_rule,
            probe_depth: self.options.syzygy_probe_depth,
            probe_limit: self.options.syzygy_probe_limit,
        };
        let tb_config =
            crate::syzygy::rank_root_moves(tb_opts, &mut self.pos, &mut root_moves, false, &|| {
                false
            });

        let so = self.options.search_options();
        for (i, w) in workers.iter_mut().enumerate() {
            w.limits = limits.clone();
            self.shared.nodes[i].store(0, Relaxed);
            self.shared.tb_hits[i].store(0, Relaxed);
            self.shared.best_move_changes[i].store(0, Relaxed);
            w.root_depth = 0;
            w.root_moves = root_moves.clone();
            w.root_pos = self.pos.clone();
            w.options = so.clone();
            w.tb_config = tb_config;
            w.reset_nmp();
        }

        let chess960 = self.pos.is_chess960();
        let on_bestmove = self.on_bestmove.clone();
        self.search = Some(
            std::thread::Builder::new()
                .stack_size(64 * 1024 * 1024)
                .spawn(move || {
                    #[cfg(all(feature = "sampler", windows))]
                    let sampler = crate::sampler::start();
                    let (main, helpers) = workers.split_at_mut(1);
                    let (best, ponder) = main[0].start_searching(helpers);
                    #[cfg(all(feature = "sampler", windows))]
                    crate::sampler::stop(sampler);
                    let ponder_s = if ponder == Move::NONE {
                        String::new()
                    } else {
                        move_to_uci(ponder, chess960)
                    };
                    on_bestmove(&move_to_uci(best, chess960), &ponder_s);
                    workers
                })
                .expect("spawn search thread"),
        );
    }

    pub fn nodes_searched(&self) -> u64 {
        self.shared.nodes_searched()
    }

    pub fn hashfull(&self, max_age: i32) -> i32 {
        self.shared.tt.hashfull(max_age)
    }

    pub fn setoption(&mut self, name: &str, value: &str) -> Option<String> {
        self.wait_for_search_finished();
        let lname = name.to_ascii_lowercase();
        let parse_i = |v: &str| v.trim().parse::<i64>().ok();
        let parse_b = |v: &str| v.trim().eq_ignore_ascii_case("true");
        match lname.as_str() {
            #[cfg(feature = "evaluation-risk")]
            "aster evaluation risk" => self.options.evaluation_risk = parse_b(value),
            #[cfg(feature = "disagreement-guard")]
            "aster disagreement guard" => self.options.disagreement_guard = parse_b(value),
            "threads" => {
                if let Some(v) = parse_i(value) {
                    self.options.threads = v.clamp(1, 1024) as usize;
                    self.resize_threads();
                    return Some(format!(
                        "Using {} thread{}",
                        self.options.threads,
                        if self.options.threads > 1 { "s" } else { "" }
                    ));
                }
            }
            "hash" => {
                if let Some(v) = parse_i(value) {
                    self.options.hash = v.clamp(1, 33554432) as usize;
                    self.shared.tt.resize(self.options.hash);
                }
            }
            "clear hash" => self.search_clear(),
            "ponder" => self.options.ponder = parse_b(value),
            "multipv" => self.options.multi_pv = parse_i(value).unwrap_or(1).clamp(1, 256) as usize,
            "skill level" => {
                self.options.skill_level = parse_i(value).unwrap_or(20).clamp(0, 20) as i32
            }
            "move overhead" => {
                self.options.move_overhead = parse_i(value).unwrap_or(10).clamp(0, 5000)
            }
            "nodestime" => self.options.nodestime = parse_i(value).unwrap_or(0).clamp(0, 10000),
            "uci_chess960" => self.options.chess960 = parse_b(value),
            "uci_limitstrength" => self.options.limit_strength = parse_b(value),
            "uci_elo" => self.options.elo = parse_i(value).unwrap_or(1320).clamp(1320, 3190) as i32,
            "uci_showwdl" => self.options.show_wdl = parse_b(value),
            "syzygypath" => {
                self.options.syzygy_path = value.to_string();
                return crate::syzygy::init(value);
            }
            "syzygyprobedepth" => {
                self.options.syzygy_probe_depth = parse_i(value).unwrap_or(1).clamp(1, 100) as i32
            }
            "syzygy50moverule" => self.options.syzygy_50_move_rule = parse_b(value),
            "syzygyprobelimit" => {
                self.options.syzygy_probe_limit = parse_i(value).unwrap_or(7).clamp(0, 7) as i32
            }
            "numapolicy" => self.options.numa_policy = value.to_string(),
            "debug log file" => self.options.debug_log_file = value.to_string(),
            "evalfile" => {
                let v = if value.is_empty() {
                    DEFAULT_NET_NAME
                } else {
                    value
                };
                match load_default_network(v) {
                    Ok(net) => {
                        self.options.eval_file = v.to_string();
                        self.network = Arc::new(net);
                        self.resize_threads();
                        return Some(format!("NNUE evaluation using {v}"));
                    }
                    Err(e) => return Some(format!("ERROR: {e}")),
                }
            }
            _ => return Some(format!("No such option: {name}")),
        }
        None
    }

    pub fn trace_eval(&mut self) -> String {
        self.wait_for_search_finished();
        let pos = &self.pos;
        if pos.checkers() != 0 {
            return "Final evaluation: none (in check)".to_string();
        }
        let mut stack = crate::nnue::accumulator::AccumulatorStack::default();
        let mut caches = crate::nnue::accumulator::AccumulatorCaches::new(&self.network.ft);
        let v = self.network.evaluate(pos, &mut stack, &mut caches);
        let white = |x: Value| if pos.side_to_move() == WHITE { x } else { -x };
        let fin = crate::nnue::evaluate(&self.network, pos, &mut stack, &mut caches, 0);
        format!(
            "NNUE evaluation        {:+} (side to move, internal units)\nNNUE evaluation        {:+.2} (white side)\nFinal evaluation       {:+.2} (white side) [with scaled NNUE, ...]",
            v,
            0.01 * to_cp(white(v), pos) as f64,
            0.01 * to_cp(white(fin), pos) as f64
        )
    }
}

pub fn parse_limits(tokens: &mut std::iter::Peekable<std::str::SplitWhitespace>) -> LimitsType {
    let mut l = LimitsType {
        start_time: now(),
        ..Default::default()
    };
    while let Some(tok) = tokens.next() {
        let mut num = || {
            tokens
                .next()
                .and_then(|t| t.parse::<i64>().ok())
                .unwrap_or(0)
        };
        match tok {
            "searchmoves" => {
                for t in tokens.by_ref() {
                    l.searchmoves.push(t.to_ascii_lowercase());
                }
                break;
            }
            "wtime" => l.time[WHITE] = num(),
            "btime" => l.time[BLACK] = num(),
            "winc" => l.inc[WHITE] = num(),
            "binc" => l.inc[BLACK] = num(),
            "movestogo" => l.movestogo = num() as i32,
            "depth" => l.depth = num() as i32,
            "nodes" => l.nodes = num() as u64,
            "movetime" => l.movetime = num(),
            "mate" => l.mate = num() as i32,
            "perft" => l.perft = num() as i32,
            "infinite" => l.infinite = true,
            "ponder" => l.ponder_mode = true,
            _ => {}
        }
    }
    l
}

const BENCH_DEFAULTS: &[&str] = &[
    "setoption name UCI_Chess960 value false",
    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
    "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 10",
    "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 11",
    "4rrk1/pp1n3p/3q2pQ/2p1pb2/2PP4/2P3N1/P2B2PP/4RRK1 b - - 7 19",
    "rq3rk1/ppp2ppp/1bnpb3/3N2B1/3NP3/7P/PPPQ1PP1/2KR3R w - - 7 14 moves d4e6",
    "r1bq1r1k/1pp1n1pp/1p1p4/4p2Q/4Pp2/1BNP4/PPP2PPP/3R1RK1 w - - 2 14 moves g2g4",
    "r3r1k1/2p2ppp/p1p1bn2/8/1q2P3/2NPQN2/PPP3PP/R4RK1 b - - 2 15",
    "r1bbk1nr/pp3p1p/2n5/1N4p1/2Np1B2/8/PPP2PPP/2KR1B1R w kq - 0 13",
    "r1bq1rk1/ppp1nppp/4n3/3p3Q/3P4/1BP1B3/PP1N2PP/R4RK1 w - - 1 16",
    "4r1k1/r1q2ppp/ppp2n2/4P3/5Rb1/1N1BQ3/PPP3PP/R5K1 w - - 1 17",
    "2rqkb1r/ppp2p2/2npb1p1/1N1Nn2p/2P1PP2/8/PP2B1PP/R1BQK2R b KQ - 0 11",
    "r1bq1r1k/b1p1npp1/p2p3p/1p6/3PP3/1B2NN2/PP3PPP/R2Q1RK1 w - - 1 16",
    "3r1rk1/p5pp/bpp1pp2/8/q1PP1P2/b3P3/P2NQRPP/1R2B1K1 b - - 6 22",
    "r1q2rk1/2p1bppp/2Pp4/p6b/Q1PNp3/4B3/PP1R1PPP/2K4R w - - 2 18",
    "4k2r/1pb2ppp/1p2p3/1R1p4/3P4/2r1PN2/P4PPP/1R4K1 b - - 3 22",
    "3q2k1/pb3p1p/4pbp1/2r5/PpN2N2/1P2P2P/5PP1/Q2R2K1 b - - 4 26",
    "6k1/6p1/6Pp/ppp5/3pn2P/1P3K2/1PP2P2/3N4 b - - 0 1",
    "3b4/5kp1/1p1p1p1p/pP1PpP1P/P1P1P3/3KN3/8/8 w - - 0 1",
    "2K5/p7/7P/5pR1/8/5k2/r7/8 w - - 0 1 moves g5g6 f3e3 g6g5 e3f3",
    "8/6pk/1p6/8/PP3p1p/5P2/4KP1q/3Q4 w - - 0 1",
    "7k/3p2pp/4q3/8/4Q3/5Kp1/P6b/8 w - - 0 1",
    "8/2p5/8/2kPKp1p/2p4P/2P5/3P4/8 w - - 0 1",
    "8/1p3pp1/7p/5P1P/2k3P1/8/2K2P2/8 w - - 0 1",
    "8/pp2r1k1/2p1p3/3pP2p/1P1P1P1P/P5KR/8/8 w - - 0 1",
    "8/3p4/p1bk3p/Pp6/1Kp1PpPp/2P2P1P/2P5/5B2 b - - 0 1",
    "5k2/7R/4P2p/5K2/p1r2P1p/8/8/8 b - - 0 1",
    "6k1/6p1/P6p/r1N5/5p2/7P/1b3PP1/4R1K1 w - - 0 1",
    "1r3k2/4q3/2Pp3b/3Bp3/2Q2p2/1p1P2P1/1P2KP2/3N4 w - - 0 1",
    "6k1/4pp1p/3p2p1/P1pPb3/R7/1r2P1PP/3B1P2/6K1 w - - 0 1",
    "8/3p3B/5p2/5P2/p7/PP5b/k7/6K1 w - - 0 1",
    "5rk1/q6p/2p3bR/1pPp1rP1/1P1Pp3/P3B1Q1/1K3P2/R7 w - - 93 90",
    "4rrk1/1p1nq3/p7/2p1P1pp/3P2bp/3Q1Bn1/PPPB4/1K2R1NR w - - 40 21",
    "r3k2r/3nnpbp/q2pp1p1/p7/Pp1PPPP1/4BNN1/1P5P/R2Q1RK1 w kq - 0 16",
    "3Qb1k1/1r2ppb1/pN1n2q1/Pp1Pp1Pr/4P2p/4BP2/4B1R1/1R5K b - - 11 40",
    "4k3/3q1r2/1N2r1b1/3ppN2/2nPP3/1B1R2n1/2R1Q3/3K4 w - - 5 1",
    "1r6/1P4bk/3qr1p1/N6p/3pp2P/6R1/3Q1PP1/1R4K1 w - - 1 42",
    "k7/2n1n3/1nbNbn2/2NbRBn1/1nbRQR2/2NBRBN1/3N1N2/7K w - - 0 1",
    "K7/8/8/BNQNQNB1/N5N1/R1Q1q2r/n5n1/bnqnqnbk w - - 0 1",
    "8/8/8/8/5kp1/P7/8/1K1N4 w - - 0 1",
    "8/8/8/5N2/8/p7/8/2NK3k w - - 0 1",
    "8/3k4/8/8/8/4B3/4KB2/2B5 w - - 0 1",
    "8/8/1P6/5pr1/8/4R3/7k/2K5 w - - 0 1",
    "8/2p4P/8/kr6/6R1/8/8/1K6 w - - 0 1",
    "8/8/3P3k/8/1p6/8/1P6/1K3n2 b - - 0 1",
    "8/R7/2q5/8/6k1/8/1P5p/K6R w - - 0 124",
    "6k1/3b3r/1p1p4/p1n2p2/1PPNpP1q/P3Q1p1/1R1RB1P1/5K2 b - - 0 1",
    "r2r1n2/pp2bk2/2p1p2p/3q4/3PN1QP/2P3R1/P4PP1/5RK1 w - - 0 1",
    "8/8/8/8/8/6k1/6p1/6K1 w - -",
    "7k/7P/6K1/8/3B4/8/8/8 b - -",
    "setoption name UCI_Chess960 value true",
    "bbqnnrkr/pppppppp/8/8/8/8/PPPPPPPP/BBQNNRKR w HFhf - 0 1 moves g2g3 d7d5 d2d4 c8h3 c1g5 e8d6 g5e7 f7f6",
    "nqbnrkrb/pppppppp/8/8/8/8/PPPPPPPP/NQBNRKRB w KQkq - 0 1",
    "setoption name UCI_Chess960 value false",
];

fn setup_bench(current_fen: &str, args: &[&str]) -> Vec<String> {
    let tt_size = args.first().copied().unwrap_or("16");
    let threads = args.get(1).copied().unwrap_or("1");
    let limit = args.get(2).copied().unwrap_or("13");
    let fen_file = args.get(3).copied().unwrap_or("default");
    let limit_type = args.get(4).copied().unwrap_or("depth");
    let go = if limit_type == "eval" {
        "eval".to_string()
    } else {
        format!("go {limit_type} {limit}")
    };

    let fens: Vec<String> = if fen_file == "default" {
        BENCH_DEFAULTS.iter().map(|s| s.to_string()).collect()
    } else if fen_file == "current" {
        vec![current_fen.to_string()]
    } else {
        match std::fs::read_to_string(fen_file) {
            Ok(s) => s
                .lines()
                .filter(|l| !l.is_empty())
                .map(String::from)
                .collect(),
            Err(_) => {
                eprintln!("Unable to open file {fen_file}");
                std::process::exit(1);
            }
        }
    };

    let mut list = vec![
        format!("setoption name Threads value {threads}"),
        format!("setoption name Hash value {tt_size}"),
        "ucinewgame".to_string(),
    ];
    for fen in fens {
        if fen.contains("setoption") {
            list.push(fen);
        } else {
            list.push(format!("position fen {fen}"));
            list.push(go.clone());
        }
    }
    list
}

pub struct Uci {
    pub engine: Engine,
}

impl Uci {
    fn setoption(&mut self, rest: &str) {
        // "name <id> [value <x>]"
        let rest = rest.trim();
        let rest = rest.strip_prefix("name").unwrap_or(rest).trim();
        let (name, value) = match rest.find(" value") {
            Some(i) => (rest[..i].trim(), rest[i + 6..].trim()),
            None => (rest, ""),
        };
        if let Some(msg) = self.engine.setoption(name, value) {
            emit(&format!("info string {msg}\n"));
        }
    }

    fn position(&mut self, rest: &str) {
        let mut it = rest.split_whitespace();
        let fen;
        match it.next() {
            Some("startpos") => {
                fen = START_FEN.to_string();
                it.next(); // consume "moves"
            }
            Some("fen") => {
                let mut f = Vec::new();
                for t in it.by_ref() {
                    if t == "moves" {
                        break;
                    }
                    f.push(t);
                }
                fen = f.join(" ");
            }
            _ => return,
        }
        let moves: Vec<String> = it.map(String::from).collect();
        if let Err(e) = self.engine.set_position(&fen, &moves) {
            emit(&format!(
                "info string CRITICAL ERROR: Command `position {rest}` failed. Reason: {e}\n"
            ));
        }
    }

    fn perft(&mut self, depth: i32) -> u64 {
        let mut p = self.engine.position().clone();
        let start = now();
        let n = crate::perft::perft(&mut p, depth, true);
        emit(&format!("\nNodes searched: {n}\n\n"));
        if self.engine.identity.aster_extensions {
            let ms = (now() - start).max(1);
            emit(&format!(
                "info depth {depth} nodes {n} time {ms} nps {}\n",
                n as i64 * 1000 / ms
            ));
        }
        n
    }

    /// Aster debugging and observer commands (only with `Identity::aster_extensions`).
    fn aster_command(&mut self, cmd: &str) -> bool {
        match cmd {
            "legal" => {
                let p = self.engine.position();
                let moves: Vec<String> = MoveList::new(p, GenType::Legal)
                    .as_slice()
                    .iter()
                    .map(|&m| move_to_uci(m, p.is_chess960()))
                    .collect();
                emit(&format!("info string legal {}\n", moves.join(" ")));
            }
            "legal-exists" => {
                let exists = !MoveList::new(self.engine.position(), GenType::Legal).is_empty();
                emit(&format!("info string legal-exists {exists}\n"));
            }
            "d" => emit(&format!("info string fen {}\n", self.engine.fen())),
            "aster-trace on" => crate::trace::enable(true),
            "aster-trace off" => crate::trace::enable(false),
            _ => return false,
        }
        true
    }

    pub fn bench(&mut self, args: &[&str]) {
        let list = setup_bench(&self.engine.fen(), args);
        let num = list
            .iter()
            .filter(|s| s.starts_with("go ") || s.starts_with("eval"))
            .count();
        let mut nodes: u64 = 0;
        let mut cnt = 1;
        let mut elapsed = now();

        for cmd in &list {
            let mut it = cmd.split_whitespace().peekable();
            let token = it.next().unwrap_or("");
            match token {
                "go" | "eval" => {
                    eprintln!("\nPosition: {}/{} ({})", cnt, num, self.engine.fen());
                    cnt += 1;
                    if token == "go" {
                        let limits = parse_limits(&mut it);
                        if limits.perft != 0 {
                            nodes += self.perft(limits.perft);
                        } else {
                            self.engine.go(limits);
                            self.engine.wait_for_search_finished();
                            nodes += self.engine.nodes_searched();
                        }
                    } else {
                        emit(&format!("\n{}\n", self.engine.trace_eval()));
                    }
                }
                "setoption" => self.setoption(&cmd["setoption".len()..]),
                "position" => self.position(&cmd["position".len()..]),
                "ucinewgame" => {
                    self.engine.search_clear();
                    elapsed = now();
                }
                _ => {}
            }
        }
        let elapsed = now() - elapsed + 1;
        #[cfg(feature = "prof")]
        crate::prof::imp::report();
        #[cfg(all(feature = "sampler", windows))]
        crate::sampler::write("samples.txt");
        eprintln!(
            "\n===========================\nTotal time (ms) : {}\nNodes searched  : {}\nNodes/second    : {}",
            elapsed,
            nodes,
            1000 * nodes / elapsed as u64
        );
    }

    /// Aster's `speedtest [threads] [hash MB] [seconds]`: replays positions from
    /// five games with time budgets scaled to the requested duration.
    pub fn speedtest(&mut self, args: &[&str]) {
        const NUM_WARMUP_POSITIONS: usize = 3;
        let hw = std::thread::available_parallelism()
            .map(|n| n.get())
            .unwrap_or(1);
        let threads = args
            .first()
            .and_then(|v| v.parse::<i64>().ok())
            .map_or(hw as i64, |v| v.clamp(1, 1024)) as usize;
        let hash = args
            .get(1)
            .and_then(|v| v.parse::<i64>().ok())
            .map_or((128 * threads) as i64, |v| v.clamp(1, 33554432));
        let secs = args
            .get(2)
            .and_then(|v| v.parse::<i64>().ok())
            .map_or(150, |v| v.clamp(1, i32::MAX as i64 / 1000));

        let corrected = |ply: usize| 50000.0f64 / (ply as f64 + 15.0);
        let mut total_time: f32 = 0.0;
        for game in crate::speedtest_positions::BENCHMARK_POSITIONS {
            for i in 0..game.len() {
                total_time += corrected(i + 1) as f32;
            }
        }
        let scale = (secs * 1000) as f32 / total_time;
        let mut commands = Vec::new();
        for game in crate::speedtest_positions::BENCHMARK_POSITIONS {
            commands.push("ucinewgame".to_string());
            for (i, fen) in game.iter().enumerate() {
                commands.push(format!("position fen {fen}"));
                commands.push(format!(
                    "go movetime {}",
                    (corrected(i + 1) * scale as f64) as i32
                ));
            }
        }
        let go_count = commands.iter().filter(|c| c.starts_with("go ")).count();

        self.setoption(&format!("name Threads value {threads}"));
        self.setoption(&format!("name Hash value {hash}"));
        self.setoption("name UCI_Chess960 value false");
        let saved_cb = self.engine.on_bestmove.clone();
        self.engine.on_bestmove = Arc::new(|_: &str, _: &str| {});
        self.engine.set_silent(true);

        let run = |this: &mut Self, cmd: &str| -> Option<(u64, std::time::Duration)> {
            let mut it = cmd.split_whitespace().peekable();
            match it.next() {
                Some("go") => {
                    let limits = parse_limits(&mut it);
                    let t = std::time::Instant::now();
                    this.engine.go(limits);
                    this.engine.wait_for_search_finished();
                    Some((this.engine.nodes_searched(), t.elapsed()))
                }
                Some("position") => {
                    this.position(&cmd["position".len()..]);
                    None
                }
                Some("ucinewgame") => {
                    this.engine.search_clear();
                    None
                }
                _ => None,
            }
        };

        let mut warm = 0;
        for cmd in &commands {
            if run(self, cmd).is_some() {
                warm += 1;
                eprint!(
                    "
Warmup position {warm}/{NUM_WARMUP_POSITIONS}"
                );
                if warm >= NUM_WARMUP_POSITIONS {
                    break;
                }
            }
        }
        eprintln!();
        self.engine.search_clear();

        let (mut nodes, mut total, mut cnt) = (0u64, std::time::Duration::ZERO, 0);
        let (mut max_hf, mut sum_hf, mut max_hf_all, mut sum_hf_all) = (0, 0i64, 0, 0i64);
        for cmd in &commands {
            if let Some((n, t)) = run(self, cmd) {
                cnt += 1;
                eprint!(
                    "
Position {cnt}/{go_count}"
                );
                nodes += n;
                total += t;
                let (h0, h999) = (self.engine.hashfull(0), self.engine.hashfull(999));
                max_hf = max_hf.max(h0);
                sum_hf += h0 as i64;
                max_hf_all = max_hf_all.max(h999);
                sum_hf_all += h999 as i64;
            }
        }
        let ms = (total.as_millis() as u64).max(1);
        eprintln!(
            "
===========================
Version                    : {}
User invocation            : speedtest {}
Filled invocation          : speedtest {threads} {hash} {secs}
Thread count               : {threads}
TT size [MiB]              : {hash}
Hash max, avg [per mille]  : 
    single search          : {max_hf}, {}
    single game            : {max_hf_all}, {}
Total nodes searched       : {nodes}
Total search time [s]      : {}
Nodes/second               : {}",
            self.engine.identity.name,
            args.join(" "),
            sum_hf / cnt.max(1) as i64,
            sum_hf_all / cnt.max(1) as i64,
            ms as f64 / 1000.0,
            1000 * nodes / ms
        );
        self.engine.set_silent(false);
        self.engine.on_bestmove = saved_cb;
    }

    pub fn loop_(&mut self, cli: Vec<String>) {
        let one_shot = !cli.is_empty();
        let stdin = std::io::stdin();
        let mut lines = stdin.lock().lines();
        loop {
            let cmd = if one_shot {
                cli.join(" ")
            } else {
                match lines.next() {
                    Some(Ok(l)) => l,
                    _ => "quit".to_string(),
                }
            };
            let trimmed = cmd.trim_start();
            let mut it = trimmed.split_whitespace().peekable();
            let token = it.next().unwrap_or("").to_string();
            let rest = trimmed[token.len()..].trim().to_string();

            if self.engine.identity.aster_extensions && self.aster_command(trimmed.trim_end()) {
                if one_shot {
                    break;
                }
                continue;
            }

            match token.as_str() {
                "quit" | "stop" => self.engine.stop(),
                "ponderhit" => self.engine.ponderhit(),
                "uci" => emit(&format!(
                    "id name {}\nid author {}\n\n{}\nuciok\n",
                    self.engine.identity.name,
                    self.engine.identity.author,
                    self.engine.options.print()
                )),
                "setoption" => self.setoption(&rest),
                "go" => {
                    emit(&format!(
                        "info string Using {} thread{}\n",
                        self.engine.options.threads,
                        if self.engine.options.threads > 1 {
                            "s"
                        } else {
                            ""
                        }
                    ));
                    let limits = parse_limits(&mut it);
                    if limits.perft != 0 {
                        self.perft(limits.perft);
                    } else {
                        self.engine.go(limits);
                    }
                }
                "position" => self.position(&rest),
                "ucinewgame" => self.engine.search_clear(),
                "isready" => emit("readyok\n"),
                "bench" => {
                    let args: Vec<&str> = it.collect();
                    self.bench(&args);
                }
                "speedtest" => {
                    let args: Vec<&str> = it.collect();
                    self.speedtest(&args);
                }
                "d" => emit(&format!("{}\n", self.engine.position().pretty())),
                "tbprobe" => {
                    // Debugging aid: raw Syzygy WDL/DTZ probe of the current position.
                    let mut p = self.engine.position().clone();
                    match crate::syzygy::current() {
                        Some(tb) => {
                            let (mut s1, mut s2) =
                                (crate::syzygy::ProbeState::Ok, crate::syzygy::ProbeState::Ok);
                            let wdl = tb.probe_wdl(&mut p, &mut s1);
                            let dtz = tb.probe_dtz(&mut p, &mut s2);
                            emit(&format!(
                                "info string tbprobe wdl {wdl} {s1:?} dtz {dtz} {s2:?}\n"
                            ));
                        }
                        None => emit("info string tbprobe no tablebases\n"),
                    }
                }
                "eval" => {
                    let s = self.engine.trace_eval();
                    emit(&format!("\n{s}\n"));
                }
                "flip" => {}
                "compiler" => emit(&format!(
                    "Compiled by rustc for {}\n",
                    std::env::consts::ARCH
                )),
                "help" | "--help" | "license" | "--license" => emit(
                    "\nAster is a native Rust chess engine for playing and analysis.\nLicensed under the GNU General Public License, version 3 or later.\nCopyright and upstream attribution: see AUTHORS, Copying.txt and THIRD_PARTY_NOTICES.md in the source distribution.\n\n",
                ),
                "" => {}
                t if t.starts_with('#') => {}
                _ => emit(&format!(
                    "Unknown command: '{cmd}'. Type help for more information.\n"
                )),
            }

            if token == "quit" || one_shot {
                break;
            }
        }
        self.engine.wait_for_search_finished();
    }
}
