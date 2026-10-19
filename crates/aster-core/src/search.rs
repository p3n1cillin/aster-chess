// Aster core. Original attribution and source mapping: search.rs.license.
// SPDX-License-Identifier: GPL-3.0-or-later
// Modified 2026-10-19: source naming and notice layout; search tuning through 2026-10-17.

use crate::bitboard::*;
use crate::history::*;
use crate::large_pages::LargeBox;
use crate::movegen::{GenType, MoveList};
use crate::movepick::{MovePicker, new_move_buffer};
use crate::nnue;
use crate::nnue::accumulator::{AccumulatorCaches, AccumulatorStack};
use crate::nnue::network::Network;
use crate::position::Position;
use crate::timeman::{TimeManagement, TimePoint, TmOptions, now};
use crate::tt::TranspositionTable;
use crate::types::*;
use crate::uci;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering::Relaxed};

/// History divisor for the LMR depth estimate in shallow-depth pruning.
#[inline(always)]
fn lmr_divisor(depth: Depth) -> i32 {
    let d = depth.min(16);
    3000 + 7 * (d - 8) * (d - 8)
}
const NODES_LIMIT_OUTPUT: u64 = 10_000_000;
const SEARCHEDLIST_CAPACITY: usize = 32;
type SearchedList = ValueList<Move, SEARCHEDLIST_CAPACITY>;

const NON_PV: u8 = 0;
const PV: u8 = 1;
const ROOT: u8 = 2;

pub struct PVMoves {
    moves: [std::mem::MaybeUninit<Move>; MAX_PLY as usize + 1],
    len: usize,
}

impl Default for PVMoves {
    #[inline(always)]
    fn default() -> Self {
        PVMoves {
            moves: [const { std::mem::MaybeUninit::uninit() }; MAX_PLY as usize + 1],
            len: 0,
        }
    }
}

impl PVMoves {
    #[inline(always)]
    pub fn clear(&mut self) {
        self.len = 0;
    }
    #[inline(always)]
    pub fn as_slice(&self) -> &[Move] {
        unsafe { std::slice::from_raw_parts(self.moves.as_ptr() as *const Move, self.len) }
    }
    #[inline(always)]
    fn get(&self, i: usize) -> Move {
        self.as_slice()[i]
    }
    #[inline(always)]
    fn update(&mut self, mv: Move, child: *const PVMoves) {
        if child.is_null() {
            self.len = 0;
        } else {
            let c = unsafe { &*child };
            self.len = c.len;
            self.moves[1..1 + c.len].copy_from_slice(&c.moves[..c.len]);
        }
        self.moves[0] = std::mem::MaybeUninit::new(mv);
        self.len += 1;
    }
    fn assign(&mut self, rhs: &[Move]) {
        self.len = rhs.len().min(MAX_PLY as usize);
        for i in 0..self.len {
            self.moves[i] = std::mem::MaybeUninit::new(rhs[i]);
        }
    }
}

#[derive(Copy, Clone)]
pub struct Stack {
    pub pv: *mut PVMoves,
    pub continuation_history: *const PieceToHistory,
    pub continuation_correction_history: *mut PieceToCorrectionHistory,
    pub ply: i32,
    pub current_move: Move,
    pub excluded_move: Move,
    pub static_eval: Value,
    pub stat_score: i32,
    pub move_count: i32,
    pub in_check: bool,
    pub tt_pv: bool,
    pub tt_hit: bool,
    pub follow_pv: bool,
    pub cutoff_cnt: i32,
    pub reduction: i32,
    pub prior_nmp_fail_high: i32,
}

impl Default for Stack {
    fn default() -> Self {
        Stack {
            pv: std::ptr::null_mut(),
            continuation_history: std::ptr::null(),
            continuation_correction_history: std::ptr::null_mut(),
            ply: 0,
            current_move: Move::NONE,
            excluded_move: Move::NONE,
            static_eval: 0,
            stat_score: 0,
            move_count: 0,
            in_check: false,
            tt_pv: false,
            tt_hit: false,
            follow_pv: false,
            cutoff_cnt: 0,
            reduction: 0,
            prior_nmp_fail_high: 0,
        }
    }
}

#[derive(Clone)]
pub struct RootMove {
    pub effort: u64,
    pub score: Value,
    pub previous_score: Value,
    pub average_score: Value,
    pub mean_squared_score: Value,
    pub uci_score: Value,
    pub inexact_lower: bool,
    pub inexact_upper: bool,
    pub previous_score_exact: bool,
    pub sel_depth: i32,
    pub tb_rank: i32,
    pub tb_score: Value,
    pub pv: Vec<Move>,
    pub previous_pv: Vec<Move>,
}

impl RootMove {
    pub fn new(m: Move) -> Self {
        let mut pv = Vec::with_capacity(MAX_PLY as usize);
        pv.push(m);
        RootMove {
            effort: 0,
            score: -VALUE_INFINITE,
            previous_score: -VALUE_INFINITE,
            average_score: -VALUE_INFINITE,
            mean_squared_score: (-VALUE_INFINITE).wrapping_mul(VALUE_INFINITE),
            uci_score: -VALUE_INFINITE,
            inexact_lower: false,
            inexact_upper: false,
            previous_score_exact: false,
            sel_depth: 0,
            tb_rank: 0,
            tb_score: 0,
            pv,
            previous_pv: Vec::new(),
        }
    }
    pub fn is_inexact(&self) -> bool {
        self.inexact_lower || self.inexact_upper
    }
    pub fn is_exact_loss(&self) -> bool {
        self.score != -VALUE_INFINITE && is_loss(self.score) && !self.is_inexact()
    }
    pub fn unset_inexact(&mut self) {
        self.inexact_lower = false;
        self.inexact_upper = false;
    }
    /// Sort order: descending by score, then by previous score.
    fn less(a: &RootMove, b: &RootMove) -> bool {
        if b.score != a.score {
            b.score < a.score
        } else {
            b.previous_score < a.previous_score
        }
    }
}

fn stable_sort_root(moves: &mut [RootMove]) {
    // std's sort_by is stable; "a < b" in C++ means a ranks before b.
    moves.sort_by(|a, b| {
        if RootMove::less(a, b) {
            std::cmp::Ordering::Less
        } else if RootMove::less(b, a) {
            std::cmp::Ordering::Greater
        } else {
            std::cmp::Ordering::Equal
        }
    });
}

#[derive(Clone, Default)]
pub struct LimitsType {
    pub searchmoves: Vec<String>,
    pub time: [TimePoint; COLOR_NB],
    pub inc: [TimePoint; COLOR_NB],
    pub npmsec: TimePoint,
    pub movetime: TimePoint,
    pub start_time: TimePoint,
    pub movestogo: i32,
    pub depth: i32,
    pub mate: i32,
    pub perft: i32,
    pub infinite: bool,
    pub nodes: u64,
    pub ponder_mode: bool,
}

impl LimitsType {
    pub fn use_time_management(&self) -> bool {
        self.time[WHITE] != 0 || self.time[BLACK] != 0
    }
}

#[derive(Clone)]
pub struct SearchOptions {
    #[cfg(feature = "evaluation-risk")]
    pub evaluation_risk: bool,
    #[cfg(feature = "disagreement-guard")]
    pub disagreement_guard: bool,
    pub multi_pv: usize,
    pub skill_level: i32,
    pub limit_strength: bool,
    pub elo: i32,
    pub move_overhead: i64,
    pub nodestime: i64,
    pub ponder: bool,
    pub show_wdl: bool,
    pub syzygy_50_move_rule: bool,
    pub syzygy_probe_depth: i32,
    pub syzygy_probe_limit: i32,
}

/// Stable pointer to the engine-owned SharedState (outlives every search).
#[derive(Copy, Clone)]
pub struct SharedRef(pub *const SharedState);
unsafe impl Send for SharedRef {}
unsafe impl Sync for SharedRef {}
impl std::ops::Deref for SharedRef {
    type Target = SharedState;
    #[inline(always)]
    fn deref(&self) -> &SharedState {
        unsafe { &*self.0 }
    }
}

/// State shared by all search threads.
pub struct SharedState {
    pub tt: TranspositionTable,
    pub histories: SharedHistories,
    pub network: Arc<Network>,
    pub stop: AtomicBool,
    pub increase_depth: AtomicBool,
    pub ponder: AtomicBool,
    pub nodes: Vec<AtomicU64>,
    pub tb_hits: Vec<AtomicU64>,
    pub best_move_changes: Vec<AtomicU64>,
    pub silent: AtomicBool,
}

impl SharedState {
    pub fn nodes_searched(&self) -> u64 {
        self.nodes.iter().map(|n| n.load(Relaxed)).sum()
    }
    pub fn tb_hits_total(&self) -> u64 {
        self.tb_hits.iter().map(|n| n.load(Relaxed)).sum()
    }
}

struct Skill {
    level: f64,
    best: Move,
}

const LOWEST_ELO: i32 = 1320;
const HIGHEST_ELO: i32 = 3190;

impl Skill {
    fn new(skill_level: i32, uci_elo: i32) -> Self {
        let level = if uci_elo != 0 {
            let e = (uci_elo - LOWEST_ELO) as f64 / (HIGHEST_ELO - LOWEST_ELO) as f64;
            (((37.2473 * e - 40.8525) * e + 22.2943) * e - 0.311438).clamp(0.0, 19.0)
        } else {
            skill_level as f64
        };
        Skill {
            level,
            best: Move::NONE,
        }
    }
    fn enabled(&self) -> bool {
        self.level < 20.0
    }
    fn time_to_pick(&self, depth: Depth) -> bool {
        depth == 1 + self.level as i32
    }
    fn pick_best(&mut self, root_moves: &[RootMove], multi_pv: usize, rng: &mut Prng) -> Move {
        let mut top = root_moves[0].score;
        let mut min = root_moves[0].score;
        for rm in &root_moves[1..multi_pv] {
            top = top.max(rm.score);
            min = min.min(rm.score);
        }
        let delta = (top - min).min(PAWN_VALUE);
        let mut max_score = -VALUE_INFINITE;
        let weakness = 120.0 - 2.0 * self.level;
        for rm in &root_moves[..multi_pv] {
            let push = ((weakness * (top - rm.score) as f64
                + (delta as u64 * (rng.rand64() as u32 as u64 % weakness as u64)) as f64)
                / 128.0) as i32;
            if rm.score + push >= max_score {
                max_score = rm.score + push;
                self.best = rm.pv[0];
            }
        }
        self.best
    }
}

/// Main-thread-only search state.
pub struct SearchManager {
    pub tm: TimeManagement,
    pub original_time_adjust: f64,
    pub calls_cnt: i32,
    pub iter_value: [Value; 4],
    pub previous_time_reduction: f64,
    pub best_previous_score: Value,
    pub best_previous_average_score: Value,
    pub stop_on_ponderhit: bool,
    last_info_time: TimePoint,
}

impl Default for SearchManager {
    fn default() -> Self {
        SearchManager {
            tm: TimeManagement::default(),
            original_time_adjust: -1.0,
            calls_cnt: 0,
            iter_value: [0; 4],
            previous_time_reduction: 0.85,
            best_previous_score: VALUE_INFINITE,
            best_previous_average_score: VALUE_INFINITE,
            stop_on_ponderhit: false,
            last_info_time: 0,
        }
    }
}

impl SearchManager {
    pub fn clear(&mut self) {
        self.best_previous_average_score = VALUE_INFINITE;
        self.previous_time_reduction = 0.85;
        self.calls_cnt = 0;
        self.best_previous_score = VALUE_INFINITE;
        self.original_time_adjust = -1.0;
        self.tm.clear();
    }
}

pub struct Worker {
    pub main_history: LargeBox<ButterflyHistory>,
    pub low_ply_history: LargeBox<LowPlyHistory>,
    pub capture_history: LargeBox<CapturePieceToHistory>,
    pub continuation_correction_history: LargeBox<ContinuationCorrectionHistory>,
    pub tt_move_history: i16,
    #[cfg(feature = "disagreement-guard")]
    guard_budget: crate::disagreement::AuditBudget,
    #[cfg(feature = "evaluation-risk")]
    risk_history: crate::evaluation_risk::RiskHistory,

    pub shared: SharedRef,
    pub limits: LimitsType,
    pub options: SearchOptions,
    pv_idx: usize,
    pv_last: usize,
    sel_depth: i32,
    nmp_min_ply: i32,
    optimism: [Value; COLOR_NB],
    pub root_pos: Position,
    pub root_moves: Vec<RootMove>,
    pub root_depth: Depth,
    seek_mate: bool,
    last_iteration_idx_pv: PVMoves,
    pub thread_idx: usize,
    // This thread's counter in the shared node table, refreshed at each
    // search start (the table is rebuilt only with the thread pool).
    node_counter: *const AtomicU64,
    numa_thread_idx: usize,
    numa_total: usize,
    reductions: [i32; MAX_MOVES],
    pub manager: Option<SearchManager>,
    acc_stack: AccumulatorStack,
    refresh_table: AccumulatorCaches,
    stack: Vec<Stack>,
    rng: Prng,
    // Aster observer (main thread only); never influences search decisions.
    trace_on: bool,
    root_game_ply: i32,
    pub tb_config: crate::syzygy::Config,
    tb: Option<std::sync::Arc<crate::syzygy::Tablebases>>,
}

unsafe impl Send for Worker {}

#[inline(always)]
fn value_draw(nodes: u64) -> Value {
    VALUE_DRAW - 1 + (nodes & 0x2) as Value
}

#[inline(always)]
fn value_to_tt(v: Value, ply: i32) -> Value {
    if is_win(v) {
        v + ply
    } else if is_loss(v) {
        v - ply
    } else {
        v
    }
}

#[inline(always)]
fn value_from_tt(v: Value, ply: i32, r50c: i32) -> Value {
    if !is_valid(v) {
        return VALUE_NONE;
    }
    if is_win(v) {
        if is_mate(v) && VALUE_MATE - v > 100 - r50c {
            return VALUE_TB_WIN_IN_MAX_PLY - 1;
        }
        if VALUE_TB - v > 100 - r50c {
            return VALUE_TB_WIN_IN_MAX_PLY - 1;
        }
        return v - ply;
    }
    if is_loss(v) {
        if is_mated(v) && VALUE_MATE + v > 100 - r50c {
            return VALUE_TB_LOSS_IN_MAX_PLY + 1;
        }
        if VALUE_TB + v > 100 - r50c {
            return VALUE_TB_LOSS_IN_MAX_PLY + 1;
        }
        return v + ply;
    }
    v
}

#[inline(always)]
fn to_corrected_static_eval(v: Value, cv: i32) -> Value {
    (v + cv / 131072).clamp(VALUE_TB_LOSS_IN_MAX_PLY + 1, VALUE_TB_WIN_IN_MAX_PLY - 1)
}

impl Worker {
    pub fn new(
        shared: SharedRef,
        options: SearchOptions,
        thread_idx: usize,
        numa_thread_idx: usize,
        numa_total: usize,
    ) -> Box<Worker> {
        let refresh_table = AccumulatorCaches::new(&shared.network.ft);
        let mut w = Box::new(Worker {
            main_history: boxed_zeroed(),
            low_ply_history: boxed_zeroed(),
            capture_history: boxed_zeroed(),
            continuation_correction_history: boxed_zeroed(),
            tt_move_history: 0,
            #[cfg(feature = "disagreement-guard")]
            guard_budget: crate::disagreement::AuditBudget::default(),
            #[cfg(feature = "evaluation-risk")]
            risk_history: crate::evaluation_risk::RiskHistory::default(),
            shared,
            limits: LimitsType::default(),
            options,
            pv_idx: 0,
            pv_last: 0,
            sel_depth: 0,
            nmp_min_ply: 0,
            optimism: [0; 2],
            root_pos: Position::default(),
            root_moves: Vec::new(),
            root_depth: 0,
            seek_mate: false,
            last_iteration_idx_pv: PVMoves::default(),
            thread_idx,
            node_counter: std::ptr::null(),
            numa_thread_idx,
            numa_total,
            reductions: [0; MAX_MOVES],
            manager: if thread_idx == 0 {
                Some(SearchManager::default())
            } else {
                None
            },
            acc_stack: AccumulatorStack::default(),
            refresh_table,
            stack: vec![Stack::default(); MAX_PLY as usize + 10],
            rng: Prng::new((now() as u64).max(1)),
            trace_on: false,
            root_game_ply: 0,
            tb_config: crate::syzygy::Config::default(),
            tb: None,
        });
        w.node_counter = &w.shared.nodes[thread_idx] as *const AtomicU64;
        w.clear();
        w
    }

    pub fn reset_nmp(&mut self) {
        self.nmp_min_ply = 0;
    }

    #[inline(always)]
    fn is_mainthread(&self) -> bool {
        self.thread_idx == 0
    }
    #[inline(always)]
    fn nodes(&self) -> u64 {
        self.shared.nodes[self.thread_idx].load(Relaxed)
    }
    #[inline(always)]
    fn inc_nodes(&self) {
        let n = unsafe { &*self.node_counter };
        n.store(n.load(Relaxed) + 1, Relaxed);
    }
    #[inline(always)]
    fn stopped(&self) -> bool {
        self.shared.stop.load(Relaxed)
    }
    #[inline(always)]
    fn ss(&self, i: usize) -> &Stack {
        unsafe { self.stack.get_unchecked(i) }
    }
    #[inline(always)]
    fn ssm(&mut self, i: usize) -> &mut Stack {
        unsafe { self.stack.get_unchecked_mut(i) }
    }
    #[inline(always)]
    fn cont_hist_sentinel(&self) -> *const PieceToHistory {
        &self.shared.histories.continuation[0][0][NO_PIECE][0] as *const _
    }
    #[inline(always)]
    fn cont_corr_sentinel(&mut self) -> *mut PieceToCorrectionHistory {
        &mut self.continuation_correction_history[NO_PIECE][0] as *mut _
    }

    /// Reset histories, usually before a new game.
    pub fn clear(&mut self) {
        #[cfg(feature = "evaluation-risk")]
        {
            self.risk_history = crate::evaluation_risk::RiskHistory::default();
        }
        for c in self.main_history.iter_mut() {
            c.fill(-5);
        }
        for p in self.capture_history.iter_mut() {
            for s in p.iter_mut() {
                s.fill(-742);
            }
        }
        self.shared
            .histories
            .clear_range(self.numa_thread_idx, self.numa_total);
        if self.numa_thread_idx == 0 {
            self.shared.histories.clear_continuation();
        }
        self.tt_move_history = 0;
        for to in self.continuation_correction_history.iter_mut() {
            for h in to.iter_mut() {
                for row in h.iter_mut() {
                    row.fill(5);
                }
            }
        }
        for i in 1..MAX_MOVES {
            self.reductions[i] = (2872.0 / 128.0 * (i as f64).ln()) as i32;
        }
        self.refresh_table.clear(&self.shared.network.ft);
    }

    fn evaluate(&mut self, pos: &Position) -> Value {
        let net = &*self.shared.network as *const Network;
        nnue::evaluate(
            unsafe { &*net },
            pos,
            &mut self.acc_stack,
            &mut self.refresh_table,
            self.optimism[pos.side_to_move() & 1],
        )
    }

    #[inline(always)]
    fn reduction(&self, improving: bool, d: Depth, mn: i32) -> i32 {
        let reduction_scale =
            self.reductions[d as usize % MAX_MOVES] * self.reductions[mn as usize % MAX_MOVES];
        reduction_scale + (!improving) as i32 * reduction_scale * 197 / 512 + 948
    }

    fn elapsed(&self) -> TimePoint {
        let sh = &self.shared;
        self.manager
            .as_ref()
            .unwrap()
            .tm
            .elapsed(|| sh.nodes_searched())
    }

    // ---- Aster observer ------------------------------------------------------

    #[inline(never)]
    fn trace_observe(&self, pos: &Position, ss: usize, quiescence: bool) {
        let prev = self.ss(ss - 1).current_move;
        let ply = self.ss(ss).ply as usize;
        crate::trace::observe(quiescence, prev, || {
            let line: Vec<Move> = (0..ply).map(|i| self.ss(7 + i).current_move).collect();
            Some(crate::trace::render(
                &crate::trace::Frame {
                    pos,
                    line: &line,
                    root_game_ply: self.root_game_ply,
                    depth: self.root_depth,
                    nodes: self.nodes(),
                },
                false,
            ))
        });
    }

    // ---- Move making with search bookkeeping ------------------------------

    #[inline(always)]
    fn do_move(
        &mut self,
        pos: &mut Position,
        mv: Move,
        gives_check: bool,
        capture: bool,
        ss: Option<usize>,
    ) {
        let t = crate::prof::prof_start!();
        self.shared.tt.prefetch(pos.prefetch_key(mv));
        self.inc_nodes();
        if let Some(ss) = ss {
            let pc = pos.moved_piece(mv);
            let to = mv.to_sq();
            unsafe {
                crate::nnue::kernels::prefetch_l1(
                    &(*self.ss(ss - 1).continuation_correction_history)[pc][to],
                );
                crate::nnue::kernels::prefetch_l1(
                    &(*self.ss(ss - 3).continuation_correction_history)[pc][to],
                );
                crate::nnue::kernels::prefetch_l1(
                    &(*self.ss(ss - 5).continuation_correction_history)[pc][to],
                );
            }
        }
        let shared = self.shared;
        let dirties = self.acc_stack.push();
        pos.do_move(mv, gives_check, Some(dirties), Some(&shared.histories));
        if let Some(ss) = ss {
            let pc = self.acc_stack.latest().dirties.dirty_piece.pc;
            let to = mv.to_sq();
            let in_check = self.ss(ss).in_check as usize;
            let ch = &self.shared.histories.continuation[in_check][capture as usize][pc][to]
                as *const PieceToHistory;
            let cch =
                &mut self.continuation_correction_history[pc][to] as *mut PieceToCorrectionHistory;
            let s = self.ssm(ss);
            s.current_move = mv;
            s.continuation_history = ch;
            s.continuation_correction_history = cch;
        }
        crate::prof::prof_end!(4, t);
    }

    #[inline(always)]
    fn undo_move(&mut self, pos: &mut Position, mv: Move) {
        pos.undo_move(mv);
        self.acc_stack.pop();
    }

    #[inline(always)]
    fn do_null_move(&mut self, pos: &mut Position, ss: usize) {
        pos.do_null_move();
        let ch = self.cont_hist_sentinel();
        let cch = self.cont_corr_sentinel();
        let s = self.ssm(ss);
        s.current_move = Move::NULL;
        s.continuation_history = ch;
        s.continuation_correction_history = cch;
    }

    // ---- Histories ----------------------------------------------------------

    fn correction_value(&self, pos: &Position, ss: usize) -> i32 {
        let us = pos.side_to_move();
        let m = self.ss(ss - 1).current_move;
        let sh = &self.shared.histories;
        let pcv = get(&sh.pawn_correction_entry(pos)[us].pawn);
        let micv = get(&sh.minor_piece_correction_entry(pos)[us].minor);
        let wnpcv = get(&sh.nonpawn_correction_entry(WHITE, pos)[us].non_pawn_white);
        let bnpcv = get(&sh.nonpawn_correction_entry(BLACK, pos)[us].non_pawn_black);
        let cntcv = if m.is_ok() {
            let to = m.to_sq();
            let pc = pos.piece_on(to);
            unsafe {
                7885 * ((*self.ss(ss - 2).continuation_correction_history)[pc][to] as i32
                    + (*self.ss(ss - 4).continuation_correction_history)[pc][to] as i32)
                    + 6307 * (*self.ss(ss - 6).continuation_correction_history)[pc][to] as i32
            }
        } else {
            80695
        };
        13806 * pcv + 9512 * micv + 11615 * (wnpcv + bnpcv) + cntcv
    }

    fn update_correction_history(&mut self, pos: &Position, ss: usize, bonus: i32) {
        let m = self.ss(ss - 1).current_move;
        let us = pos.side_to_move();
        const NON_PAWN_WEIGHT: i32 = 186;
        let sh = &self.shared.histories;
        const D: i32 = CORRECTION_HISTORY_LIMIT;
        update_atomic::<D>(&sh.pawn_correction_entry(pos)[us].pawn, bonus);
        update_atomic::<D>(
            &sh.minor_piece_correction_entry(pos)[us].minor,
            bonus * 150 / 128,
        );
        update_atomic::<D>(
            &sh.nonpawn_correction_entry(WHITE, pos)[us].non_pawn_white,
            bonus * NON_PAWN_WEIGHT / 128,
        );
        update_atomic::<D>(
            &sh.nonpawn_correction_entry(BLACK, pos)[us].non_pawn_black,
            bonus * NON_PAWN_WEIGHT / 128,
        );
        if m.is_ok() {
            let to = m.to_sq();
            let pc = pos.piece_on(to);
            unsafe {
                update::<D>(
                    &mut (*self.ss(ss - 2).continuation_correction_history)[pc][to],
                    bonus * 130 / 128,
                );
                update::<D>(
                    &mut (*self.ss(ss - 4).continuation_correction_history)[pc][to],
                    bonus * 70 / 128,
                );
                update::<D>(
                    &mut (*self.ss(ss - 6).continuation_correction_history)[pc][to],
                    bonus * 35 / 128,
                );
            }
        }
    }

    fn update_continuation_histories(&self, ss: usize, pc: Piece, to: Square, bonus: i32) {
        const BONUSES: [(usize, i32); 5] = [(1, 520), (2, 390), (3, 145), (4, 251), (6, 209)];
        const CMHC_MULTIPLIERS: [i32; 6] = [94, 103, 110, 106, 119, 126];
        let mut positive_count = 0;
        for (i, weight) in BONUSES {
            if self.ss(ss).in_check && i > 2 {
                break;
            }
            let s = self.ss(ss - i);
            if s.current_move.is_ok() {
                let entry = unsafe { &(*s.continuation_history)[pc][to] };
                if get(entry) > 0 {
                    positive_count += 1;
                }
                let multiplier = CMHC_MULTIPLIERS[positive_count];
                update_atomic::<PIECE_TO_D>(
                    entry,
                    bonus * weight * multiplier / 65536 + 73 * (i < 2) as i32,
                );
            }
        }
    }

    fn update_quiet_histories(&mut self, pos: &Position, ss: usize, mv: Move, bonus: i32) {
        let us = pos.side_to_move();
        update::<BUTTERFLY_D>(&mut self.main_history[us][mv.raw() as usize], bonus);
        let ply = self.ss(ss).ply;
        if (ply as usize) < LOW_PLY_HISTORY_SIZE {
            update::<LOW_PLY_D>(
                &mut self.low_ply_history[ply as usize][mv.raw() as usize],
                bonus * 712 / 1024,
            );
        }
        self.update_continuation_histories(ss, pos.moved_piece(mv), mv.to_sq(), bonus * 750 / 1024);
        let e = &self.shared.histories.pawn_entry(pos)[pos.moved_piece(mv)][mv.to_sq()];
        update_atomic::<PAWN_D>(e, bonus * (if bonus > -4 { 1104 } else { 459 }) / 1024);
    }

    #[allow(clippy::too_many_arguments)]
    fn update_all_stats(
        &mut self,
        pos: &Position,
        ss: usize,
        best_move: Move,
        prev_sq: Square,
        quiets: &SearchedList,
        captures: &SearchedList,
        depth: Depth,
        tt_move: Move,
        pv_node: bool,
    ) {
        let mut moved_piece = pos.moved_piece(best_move);
        let mut bonus = (133 * depth - 81).min(1487)
            + 364 * (best_move == tt_move) as i32
            + self.ss(ss - 1).stat_score / 28;
        let malus = (968 * depth - 235).min(2244);

        if !pv_node {
            // C++: bonus += int(bonus * u64(n) / 256) with unsigned 64-bit arithmetic
            let n = (quiets.len() + captures.len()) as u64;
            bonus = bonus.wrapping_add(((bonus as i64 as u64).wrapping_mul(n) / 256) as i32);
        }

        if !pos.capture_stage(best_move) {
            self.update_quiet_histories(pos, ss, best_move, bonus * 899 / 1024);
            let mut actual_malus = malus * 1159 / 1024;
            for &m in quiets.as_slice() {
                actual_malus = actual_malus * 921 / 1024;
                self.update_quiet_histories(pos, ss, m, -actual_malus);
            }
        } else {
            let captured = type_of(pos.piece_on(best_move.to_sq()));
            update::<CAPTURE_D>(
                &mut self.capture_history[moved_piece][best_move.to_sq()][captured],
                bonus * 1427 / 1024,
            );
        }

        let prev = self.ss(ss - 1);
        if prev_sq != SQ_NONE
            && prev.move_count == 1 + prev.tt_hit as i32
            && pos.captured_piece() == NO_PIECE
        {
            self.update_continuation_histories(
                ss - 1,
                pos.piece_on(prev_sq),
                prev_sq,
                -malus * 713 / 1024,
            );
        }

        for &m in captures.as_slice() {
            moved_piece = pos.moved_piece(m);
            let captured = type_of(pos.piece_on(m.to_sq()));
            update::<CAPTURE_D>(
                &mut self.capture_history[moved_piece][m.to_sq()][captured],
                -malus * 1489 / 1024,
            );
        }
    }

    fn is_shuffling(&self, mv: Move, ss: usize, pos: &Position) -> bool {
        if pos.capture_stage(mv) || pos.rule50_count() < 10 {
            return false;
        }
        if pos.plies_from_null() < 6 || self.ss(ss).ply < 20 {
            return false;
        }
        mv.from_sq() == self.ss(ss - 2).current_move.to_sq()
            && self.ss(ss - 2).current_move.from_sq() == self.ss(ss - 4).current_move.to_sq()
    }

    // ---- Iterative deepening -------------------------------------------------

    /// Main iterative deepening loop. Returns whether the final PV was sent.
    pub fn iterative_deepening(&mut self) -> bool {
        #[cfg(feature = "evaluation-risk")]
        self.risk_history.new_search();
        #[cfg(feature = "disagreement-guard")]
        {
            self.guard_budget = crate::disagreement::AuditBudget::default();
        }
        let main = self.is_mainthread();
        self.tb = if self.tb_config.cardinality > 0 || self.tb_config.root_in_tb {
            crate::syzygy::current()
        } else {
            None
        };
        self.trace_on = main && crate::trace::enabled();
        if self.trace_on {
            crate::trace::reset();
        }
        self.root_game_ply = self.root_pos.game_ply();
        let mut pos = std::mem::take(&mut self.root_pos);
        pos.reserve_states(MAX_PLY as usize + 16);

        self.node_counter = &self.shared.nodes[self.thread_idx] as *const AtomicU64;

        let mut pv = PVMoves::default();
        let mut last_best_move_pv: Vec<Move> = Vec::new();
        let mut last_best_move_depth: Depth = 0;
        let mut last_best_move_score: Value = -VALUE_INFINITE;

        let mut best_value = -VALUE_INFINITE;
        let us = pos.side_to_move();
        let mut time_reduction = 1.0f64;
        let mut tot_best_move_changes = 0.0f64;
        let mut iter_idx = 0usize;

        for s in self.stack.iter_mut() {
            *s = Stack::default();
        }
        let ss = 7usize;
        let sentinel = self.cont_hist_sentinel();
        let corr_sentinel = self.cont_corr_sentinel();
        for i in 1..=7 {
            let s = self.ssm(ss - i);
            s.continuation_history = sentinel;
            s.continuation_correction_history = corr_sentinel;
            s.static_eval = VALUE_NONE;
        }
        for i in 0..=(MAX_PLY as usize + 2) {
            self.ssm(ss + i).ply = i as i32;
        }
        self.ssm(ss).pv = &mut pv as *mut PVMoves;

        if let Some(m) = self.manager.as_mut() {
            let v = if m.best_previous_score == VALUE_INFINITE {
                0
            } else {
                m.best_previous_score
            };
            m.iter_value = [v; 4];
        }

        let mut multi_pv = self.options.multi_pv;
        let mut skill = Skill::new(
            self.options.skill_level,
            if self.options.limit_strength {
                self.options.elo
            } else {
                0
            },
        );
        if skill.enabled() {
            multi_pv = multi_pv.max(4);
        }
        multi_pv = multi_pv.min(self.root_moves.len());

        let mut search_again_counter = 0;
        let mut fail_high_recovery = 0;
        let mut uci_pv_sent = false;

        for row in self.low_ply_history.iter_mut() {
            row.fill(102);
        }
        for c in 0..COLOR_NB {
            for v in self.main_history[c].iter_mut() {
                *v = (*v as i32 * 729 / 1024) as i16;
            }
        }

        while self.root_depth + 1 < MAX_PLY
            && !self.stopped()
            && !(self.limits.depth != 0 && main && self.root_depth >= self.limits.depth)
        {
            self.root_depth += 1;

            if main {
                uci_pv_sent = false;
            }

            for (i, rm) in self.root_moves.iter_mut().enumerate() {
                rm.previous_score = rm.score;
                rm.previous_pv = rm.pv.clone();
                rm.previous_score_exact = i < multi_pv;
            }

            let mut pv_first = 0;
            self.pv_last = 0;

            if !self.shared.increase_depth.load(Relaxed) {
                search_again_counter += 1;
            }

            self.pv_idx = 0;
            while self.pv_idx < multi_pv {
                if self.pv_idx == self.pv_last {
                    pv_first = self.pv_last;
                    self.pv_last += 1;
                    while self.pv_last < self.root_moves.len() {
                        if self.root_moves[self.pv_last].tb_rank
                            != self.root_moves[pv_first].tb_rank
                        {
                            break;
                        }
                        self.pv_last += 1;
                    }
                }

                let prev_pv = self.root_moves[self.pv_idx].previous_pv.clone();
                self.last_iteration_idx_pv.assign(&prev_pv);
                self.sel_depth = 0;

                let mut delta = 5
                    + (self.thread_idx % 8) as i32
                    + self.root_moves[self.pv_idx].mean_squared_score.abs() / 10193;
                let avg = self.root_moves[self.pv_idx].average_score;
                let mut alpha = (avg - delta).max(-VALUE_INFINITE);
                let mut beta = (avg + delta).min(VALUE_INFINITE);

                // Not a playing-strength parameter: switches mate-seeking behaviour.
                self.seek_mate = self.root_moves[self.pv_idx].score.abs()
                    >= 750 + 220000 / (self.root_depth * self.root_depth);

                self.optimism[us] = 114 * avg / (avg.abs() + 85);
                self.optimism[flip_color(us)] = -self.optimism[us];

                let mut failed_high_cnt = 0;
                if self.pv_idx == 0 {
                    fail_high_recovery = (fail_high_recovery - 2).max(0);
                }
                loop {
                    let adjusted_depth = (self.root_depth
                        - failed_high_cnt
                        - fail_high_recovery
                        - 3 * (search_again_counter + 1) / 4)
                        .max(1);
                    best_value =
                        self.search::<ROOT>(&mut pos, ss, alpha, beta, adjusted_depth, false);

                    let (a, b) = (self.pv_idx, self.pv_last);
                    stable_sort_root(&mut self.root_moves[a..b]);

                    if self.stopped() {
                        break;
                    }

                    if main
                        && multi_pv == 1
                        && (best_value <= alpha || best_value >= beta)
                        && self.nodes() > NODES_LIMIT_OUTPUT
                    {
                        self.output_pv(&mut pos, self.root_depth);
                    }

                    if best_value <= alpha {
                        beta = alpha;
                        alpha = (best_value - delta).max(-VALUE_INFINITE);
                        failed_high_cnt = 0;
                        if let Some(m) = self.manager.as_mut() {
                            m.stop_on_ponderhit = false;
                        }
                    } else if best_value >= beta {
                        alpha = (beta - delta).max(alpha);
                        beta = (best_value + delta).min(VALUE_INFINITE);
                        failed_high_cnt += 1;
                    } else {
                        break;
                    }
                    delta += 47 * delta / 128;
                }

                // Gradually increase depth after reduced depth search
                if failed_high_cnt > 0 && self.pv_idx == 0 {
                    fail_high_recovery = (failed_high_cnt + 1) / 2 + 2;
                }

                let pv_idx = self.pv_idx;
                if self.stopped() && pv_idx != 0 {
                    let rms = &mut self.root_moves;
                    if (is_loss(rms[pv_idx - 1].score)
                        && RootMove::less(&rms[pv_idx], &rms[pv_idx - 1]))
                        || rms[pv_idx].is_exact_loss()
                    {
                        let prev_score = rms[pv_idx - 1].score;
                        let rm = &mut rms[pv_idx];
                        if rm.previous_score != -VALUE_INFINITE
                            && rm.previous_score_exact
                            && rm.previous_score <= prev_score
                        {
                            rm.score = rm.previous_score;
                            rm.uci_score = rm.previous_score;
                            rm.previous_score = -VALUE_INFINITE;
                            rm.pv = rm.previous_pv.clone();
                            rm.unset_inexact();
                        } else {
                            if is_loss(prev_score) {
                                rm.score = prev_score;
                                rm.uci_score = prev_score;
                                rm.previous_score = -VALUE_INFINITE;
                                rm.pv.truncate(1);
                                rm.inexact_upper = true;
                            } else {
                                rm.inexact_upper = false;
                            }
                            rm.inexact_lower = !rm.inexact_upper;
                        }
                    }
                    for i in pv_idx + 1..multi_pv {
                        if self.root_moves[i].is_exact_loss() {
                            self.root_moves[i].inexact_lower = true;
                        }
                    }
                }

                stable_sort_root(&mut self.root_moves[pv_first..pv_idx + 1]);

                if main
                    && !self.stopped()
                    && (pv_idx + 1 == multi_pv || self.nodes() > NODES_LIMIT_OUTPUT)
                {
                    self.output_pv(&mut pos, self.root_depth);
                    uci_pv_sent = pv_idx + 1 == multi_pv;
                }

                if self.stopped() {
                    break;
                }
                self.pv_idx += 1;
            }

            let rm0_score = self.root_moves[0].score;
            let forgotten_mate = last_best_move_score != -VALUE_INFINITE
                && is_mate_or_mated(last_best_move_score)
                && (rm0_score.abs() < last_best_move_score.abs()
                    || self.root_moves[0].is_inexact());

            if !self.stopped() {
                if last_best_move_pv.is_empty() || last_best_move_pv[0] != self.root_moves[0].pv[0]
                {
                    last_best_move_depth = self.root_depth;
                }
                if !forgotten_mate {
                    last_best_move_pv = self.root_moves[0].pv.clone();
                    last_best_move_score = self.root_moves[0].score;
                }
            }

            let aborted_loss_search =
                self.stopped() && self.pv_idx == 0 && self.root_moves[0].is_exact_loss();

            if aborted_loss_search
                || (self.root_moves[0].score != -VALUE_INFINITE && forgotten_mate)
            {
                if !last_best_move_pv.is_empty() {
                    if let Some(p) = self
                        .root_moves
                        .iter()
                        .position(|rm| rm.pv[0] == last_best_move_pv[0])
                    {
                        self.root_moves[..=p].rotate_right(1);
                    }
                    let rm = &mut self.root_moves[0];
                    rm.score = last_best_move_score;
                    rm.uci_score = last_best_move_score;
                    rm.pv = last_best_move_pv.clone();
                    rm.unset_inexact();
                    if main {
                        uci_pv_sent = false;
                    }
                } else if aborted_loss_search {
                    self.root_moves[0].inexact_lower = true;
                }
            }

            if self.limits.mate != 0
                && !self.stopped()
                && is_mate_or_mated(self.root_moves[0].score)
                && VALUE_MATE - self.root_moves[0].score.abs() <= 2 * self.limits.mate
            {
                self.shared.stop.store(true, Relaxed);
            }

            if !main {
                continue;
            }

            if skill.enabled() && skill.time_to_pick(self.root_depth) {
                let mut rng = std::mem::replace(&mut self.rng, Prng::new(1));
                skill.pick_best(&self.root_moves, multi_pv, &mut rng);
                self.rng = rng;
            }

            let stop_on_ponderhit = self.manager.as_ref().unwrap().stop_on_ponderhit;
            if self.limits.use_time_management() && !self.stopped() && !stop_on_ponderhit {
                let nodes_effort = self.root_moves[0].effort * 100000 / self.nodes().max(1);
                let mgr = self.manager.as_ref().unwrap();
                let falling_eval = ((11.48
                    + 2.30 * (mgr.best_previous_average_score - best_value) as f64
                    + 1.1 * (mgr.iter_value[iter_idx] - best_value) as f64)
                    / 100.0)
                    .clamp(0.576, 1.728);

                time_reduction = interpolate(
                    (self.root_depth - last_best_move_depth) as f64,
                    4.96,
                    18.79,
                    0.639,
                    1.712,
                )
                .clamp(0.629, 1.544);
                let reduction = (1.468 + mgr.previous_time_reduction) / (2.284 * time_reduction);

                // Age out and update the PV variability metric
                tot_best_move_changes /= 2.0;
                for bmc in &self.shared.best_move_changes {
                    tot_best_move_changes += bmc.load(Relaxed) as f64;
                    bmc.store(0, Relaxed);
                }
                let best_move_instability =
                    1.077 + 2.229 * tot_best_move_changes / self.shared.nodes.len() as f64;
                let high_best_move_effort =
                    interpolate_i64(nodes_effort as i64, 75800, 104510, 0.969, 0.714)
                        .clamp(0.693, 0.838);

                let mut total_time = mgr.tm.optimum() as f64
                    * falling_eval
                    * reduction
                    * best_move_instability
                    * high_best_move_effort;
                if self.root_moves.len() == 1 {
                    total_time = total_time.min(500.0);
                }
                let elapsed_time = self.elapsed();
                let maximum = mgr.tm.maximum();

                if elapsed_time as f64 > total_time.min(maximum as f64)
                    || self.root_moves[multi_pv - 1].score >= mate_in(3)
                    || self.root_moves[0].score == mated_in(2)
                {
                    if self.shared.ponder.load(Relaxed) {
                        self.manager.as_mut().unwrap().stop_on_ponderhit = true;
                    } else {
                        self.shared.stop.store(true, Relaxed);
                    }
                } else {
                    self.shared.increase_depth.store(
                        self.shared.ponder.load(Relaxed)
                            || elapsed_time as f64 <= total_time * 0.50,
                        Relaxed,
                    );
                }
            }

            let mgr = self.manager.as_mut().unwrap();
            mgr.iter_value[iter_idx] = best_value;
            iter_idx = (iter_idx + 1) & 3;
        }

        if self.trace_on {
            let s = crate::trace::render(
                &crate::trace::Frame {
                    pos: &pos,
                    line: &[],
                    root_game_ply: self.root_game_ply,
                    depth: self.root_depth,
                    nodes: self.nodes(),
                },
                true,
            );
            uci::emit(&s);
        }
        self.root_pos = pos;

        if !main {
            return false;
        }
        self.manager.as_mut().unwrap().previous_time_reduction = time_reduction;

        if skill.enabled() {
            let best = if skill.best.is_some() {
                skill.best
            } else {
                let mut rng = std::mem::replace(&mut self.rng, Prng::new(1));
                let b = skill.pick_best(&self.root_moves, multi_pv, &mut rng);
                self.rng = rng;
                b
            };
            if let Some(p) = self.root_moves.iter().position(|rm| rm.pv[0] == best) {
                self.root_moves.swap(0, p);
            }
        }
        uci_pv_sent
    }

    // ---- Main search -----------------------------------------------------------

    #[allow(clippy::cognitive_complexity)]
    fn search<const NT: u8>(
        &mut self,
        pos: &mut Position,
        ss: usize,
        mut alpha: Value,
        mut beta: Value,
        mut depth: Depth,
        cut_node: bool,
    ) -> Value {
        let pv_node = NT != NON_PV;
        let root_node = NT == ROOT;
        let all_node = !(pv_node || cut_node);
        let seek_mate = self.seek_mate;

        #[cfg(feature = "evaluation-risk")]
        let risk_window = (alpha, beta);

        // Dive into quiescence search when the depth reaches zero
        if depth <= 0 {
            return if pv_node {
                self.qsearch::<PV>(pos, ss, alpha, beta)
            } else {
                self.qsearch::<NON_PV>(pos, ss, alpha, beta)
            };
        }

        depth = depth.min(MAX_PLY - 1);

        if self.trace_on {
            self.trace_observe(pos, ss, false);
        }

        // Check if we have an upcoming move that draws by repetition
        if !root_node && alpha < VALUE_DRAW && pos.upcoming_repetition(self.ss(ss).ply) {
            alpha = value_draw(self.nodes());
            if alpha >= beta {
                return alpha;
            }
        }

        let mut pv = PVMoves::default();
        let mut captures_searched = SearchedList::new();
        let mut quiets_searched = SearchedList::new();

        // Step 1. Initialize node
        let in_check = pos.checkers() != 0;
        self.ssm(ss).in_check = in_check;
        let prior_capture = pos.captured_piece() != NO_PIECE;
        let us = pos.side_to_move();
        self.ssm(ss).move_count = 0;
        let mut best_value = -VALUE_INFINITE;
        let mut max_value = VALUE_INFINITE;

        let ply = self.ss(ss).ply;
        let follow_pv = root_node
            || (self.ss(ss - 1).follow_pv
                && ((ply - 1) as usize) < self.last_iteration_idx_pv.len
                && self.ss(ss - 1).current_move
                    == self.last_iteration_idx_pv.get((ply - 1) as usize));
        self.ssm(ss).follow_pv = follow_pv;

        if self.is_mainthread() {
            self.check_time();
        }

        if pv_node && self.sel_depth < ply + 1 {
            self.sel_depth = ply + 1;
        }

        if !root_node {
            // Step 2. Check for aborted search or immediate draw
            if self.stopped() || pos.is_draw(ply) || ply >= MAX_PLY {
                return if ply >= MAX_PLY && !in_check {
                    self.evaluate(pos)
                } else {
                    value_draw(self.nodes())
                };
            }
            // Step 3. Mate distance pruning
            alpha = alpha.max(mated_in(ply));
            beta = beta.min(mate_in(ply + 1));
            if alpha >= beta {
                return alpha;
            }
        }

        let prev_move = self.ss(ss - 1).current_move;
        let prev_sq = if prev_move.is_ok() {
            prev_move.to_sq()
        } else {
            SQ_NONE
        };
        let mut best_move = Move::NONE;
        let prior_reduction = self.ss(ss - 1).reduction;
        self.ssm(ss - 1).reduction = 0;
        self.ssm(ss).stat_score = 0;
        self.ssm(ss + 2).cutoff_cnt = 0;
        self.ssm(ss + 1).prior_nmp_fail_high = 0;

        let correction_value = self.correction_value(pos, ss);

        // Step 4. Transposition table lookup
        let excluded_move = self.ss(ss).excluded_move;
        let pos_key = pos.key();
        let cache_owner = self.shared;
        let (tt_hit, mut tt_data, tt_writer) = cache_owner.tt.probe(pos_key);

        self.ssm(ss).tt_hit = tt_hit;
        tt_data.mv = if root_node {
            self.root_moves[self.pv_idx].pv[0]
        } else if tt_hit {
            tt_data.mv
        } else {
            Move::NONE
        };
        tt_data.value = if tt_hit {
            value_from_tt(tt_data.value, ply, pos.rule50_count())
        } else {
            VALUE_NONE
        };
        let tt_pv = if excluded_move.is_some() {
            self.ss(ss).tt_pv
        } else {
            pv_node || (tt_hit && tt_data.is_pv)
        };
        self.ssm(ss).tt_pv = tt_pv;
        let tt_capture = tt_data.mv.is_some() && pos.capture_stage(tt_data.mv);

        // Step 5. Static evaluation of the position
        let mut unadjusted_static_eval = VALUE_NONE;
        let mut eval;
        if in_check {
            eval = self.ss(ss - 2).static_eval;
            self.ssm(ss).static_eval = eval;
        } else if excluded_move.is_some() {
            eval = self.ss(ss).static_eval;
            unadjusted_static_eval = eval;
        } else if tt_hit {
            unadjusted_static_eval = tt_data.eval;
            if !is_valid(unadjusted_static_eval) {
                unadjusted_static_eval = self.evaluate(pos);
            }
            eval = to_corrected_static_eval(unadjusted_static_eval, correction_value);
            self.ssm(ss).static_eval = eval;
            if is_valid(tt_data.value)
                && (tt_data.bound
                    & if tt_data.value > eval {
                        BOUND_LOWER
                    } else {
                        BOUND_UPPER
                    })
                    != 0
            {
                eval = tt_data.value;
            }
        } else {
            unadjusted_static_eval = self.evaluate(pos);
            eval = to_corrected_static_eval(unadjusted_static_eval, correction_value);
            self.ssm(ss).static_eval = eval;
            tt_writer.write(
                pos_key,
                VALUE_NONE,
                tt_pv,
                BOUND_NONE,
                DEPTH_UNSEARCHED,
                Move::NONE,
                unadjusted_static_eval,
                self.shared.tt.generation(),
            );
        }

        let static_eval = self.ss(ss).static_eval;
        let mut improving = static_eval > self.ss(ss - 2).static_eval;
        let opponent_worsening = static_eval > -self.ss(ss - 1).static_eval;

        if prior_reduction >= 3 && !opponent_worsening {
            depth += 1;
        }
        if prior_reduction >= 2 && depth >= 2 && static_eval + self.ss(ss - 1).static_eval > 166 {
            depth -= 1;
        }

        // Step 6. Early TT cutoff at non-PV nodes
        #[cfg(feature = "evaluation-risk")]
        let risk_context = (
            crate::evaluation_risk::bucket(
                pos.pieces().count_ones(),
                pos.pieces_t(QUEEN) != 0,
                us,
                depth,
            ),
            depth,
        );

        if !pv_node
            && excluded_move.is_none()
            && is_valid(tt_data.value)
            && tt_data.depth > depth - (tt_data.value <= beta) as i32
        {
            // Case A: the entry can produce a cutoff
            if (tt_data.bound
                & if tt_data.value >= beta {
                    BOUND_LOWER
                } else {
                    BOUND_UPPER
                })
                != 0
                && (cut_node == (tt_data.value >= beta) || depth > 4)
            {
                if tt_data.mv.is_some() && tt_data.value >= beta {
                    if !tt_capture {
                        self.update_quiet_histories(pos, ss, tt_data.mv, 131 * depth);
                    }
                    if prev_sq != SQ_NONE && self.ss(ss - 1).move_count < 5 && !prior_capture {
                        self.update_continuation_histories(
                            ss - 1,
                            pos.piece_on(prev_sq),
                            prev_sq,
                            -2210,
                        );
                    }
                }

                // Partial workaround for the graph history interaction problem:
                // no cutoffs at high rule50 counts.
                if pos.rule50_count() < 96 {
                    if depth >= 7
                        && tt_data.mv.is_some()
                        && pos.legal(tt_data.mv)
                        && !is_decisive(tt_data.value)
                    {
                        pos.do_move_simple(tt_data.mv);
                        let next_key = pos.key();
                        let (_, tt_data_next, _) = self.shared.tt.probe(next_key);
                        pos.undo_move(tt_data.mv);
                        if !is_valid(tt_data_next.value) {
                            if self.trace_on {
                                crate::trace::event(crate::trace::EVENT_TABLE_CUTOFF);
                            }
                            return tt_data.value;
                        }
                        if (tt_data.value >= beta) == (-tt_data_next.value >= beta) {
                            if self.trace_on {
                                crate::trace::event(crate::trace::EVENT_TABLE_CUTOFF);
                            }
                            return tt_data.value;
                        }
                    } else {
                        if self.trace_on {
                            crate::trace::event(crate::trace::EVENT_TABLE_CUTOFF);
                        }
                        return tt_data.value;
                    }
                }
            }
            // Case B: deep enough, but the bound points the wrong way, so the
            // entry is useless for this window.
            else if depth > 5 {
                tt_writer.penalize(1);
            }
        }

        // Step 7. Tablebases probe
        if !root_node && excluded_move.is_none() && self.tb_config.cardinality != 0 {
            let pieces_count = popcount(pos.pieces());
            if pieces_count <= self.tb_config.cardinality
                && (pieces_count < self.tb_config.cardinality
                    || depth >= self.tb_config.probe_depth)
                && pos.rule50_count() == 0
                && !pos.can_castle(ANY_CASTLING)
            {
                if let Some(tb) = self.tb.clone() {
                    let mut err = crate::syzygy::ProbeState::Ok;
                    let wdl = tb.probe_wdl(pos, &mut err);
                    if let Some(m) = self.manager.as_mut() {
                        m.calls_cnt = 0;
                    }
                    if err != crate::syzygy::ProbeState::Fail {
                        let h = &self.shared.tb_hits[self.thread_idx];
                        h.store(h.load(Relaxed) + 1, Relaxed);
                        let draw_score = self.tb_config.use_rule50 as i32;
                        let tb_value = VALUE_TB - ply;
                        let value = if wdl < -draw_score {
                            -tb_value
                        } else if wdl > draw_score {
                            tb_value
                        } else {
                            VALUE_DRAW + 2 * wdl * draw_score
                        };
                        let b = if wdl < -draw_score {
                            BOUND_UPPER
                        } else if wdl > draw_score {
                            BOUND_LOWER
                        } else {
                            BOUND_EXACT
                        };
                        if b == BOUND_EXACT
                            || (if b == BOUND_LOWER {
                                value >= beta
                            } else {
                                value <= alpha
                            })
                        {
                            tt_writer.write(
                                pos_key,
                                value_to_tt(value, ply),
                                self.ss(ss).tt_pv,
                                b,
                                (MAX_PLY - 1).min(depth + 6),
                                Move::NONE,
                                VALUE_NONE,
                                self.shared.tt.generation(),
                            );
                            return value;
                        }
                        if pv_node {
                            if b == BOUND_LOWER {
                                best_value = value;
                                alpha = alpha.max(best_value);
                            } else {
                                max_value = value;
                            }
                        }
                    }
                }
            }
        }

        let mut skip_to_moves_loop = in_check;

        if !skip_to_moves_loop {
            // Use static evaluation difference to improve quiet move ordering
            if prev_move.is_ok() && !self.ss(ss - 1).in_check && !prior_capture {
                let eval_diff =
                    (-(self.ss(ss - 1).static_eval + static_eval)).clamp(-189, 194) + 60;
                update::<BUTTERFLY_D>(
                    &mut self.main_history[flip_color(us)][prev_move.raw() as usize],
                    eval_diff * 11,
                );
                if !tt_hit
                    && type_of(pos.piece_on(prev_sq)) != PAWN
                    && prev_move.type_of() != PROMOTION
                {
                    update_atomic::<PAWN_D>(
                        &self.shared.histories.pawn_entry(pos)[pos.piece_on(prev_sq)][prev_sq],
                        eval_diff * 13,
                    );
                }
            }

            // Step 8. Razoring
            if all_node && eval < alpha - 342 * depth && !seek_mate {
                return self.qsearch::<NON_PV>(pos, ss, alpha, beta);
            }

            // Step 9. Futility pruning: child node
            if !tt_pv
                && depth < (if seek_mate { 6 } else { 19 })
                && eval >= beta
                && (tt_data.mv.is_none() || tt_capture)
                && !is_loss(beta)
                && !is_win(eval)
            {
                let mut futility_mult = (45 + depth * 4).min(85);
                futility_mult -= 20 * !tt_hit as i32;
                let futility_margin = futility_mult * depth
                    - (2789 * improving as i32 + 335 * opponent_worsening as i32) * futility_mult
                        / 1024
                    + correction_value.abs() / 198435;
                if eval - futility_margin >= beta {
                    #[cfg(feature = "evaluation-risk")]
                    let defer = self.options.evaluation_risk
                        && !seek_mate
                        && (3..=8).contains(&depth)
                        && eval == static_eval
                        && self
                            .risk_history
                            .defer(risk_context.0, eval - futility_margin - beta);
                    #[cfg(not(feature = "evaluation-risk"))]
                    let defer = false;
                    if !defer {
                        return (661 * beta + 363 * eval) / 1024;
                    }
                }
            }

            // Step 10. Null move search with verification search
            if cut_node
                && static_eval + 50 * self.ss(ss).prior_nmp_fail_high
                    >= beta - 13 * depth - 47 * improving as i32 + 365
                && excluded_move.is_none()
                && pos.non_pawn_material_c(us) != 0
                && ply >= self.nmp_min_ply
                && beta >= -2000
            {
                let mut r = 7 + depth / 3 + ((static_eval - beta) / 256).max(0);
                r -= seek_mate as i32 * r / 2;
                if self.trace_on {
                    crate::trace::event(crate::trace::EVENT_NULL_PROBE);
                }
                self.do_null_move(pos, ss);
                let null_value =
                    -self.search::<NON_PV>(pos, ss + 1, -beta, -beta + 1, depth - r, false);
                pos.undo_null_move();

                if null_value >= beta && !is_win(null_value) {
                    if self.nmp_min_ply != 0 || depth < 16 {
                        self.ssm(ss).prior_nmp_fail_high += 1;
                        return null_value;
                    }
                    self.nmp_min_ply = ply + 3 * (depth - r) / 4;
                    let v = self.search::<NON_PV>(pos, ss, beta - 1, beta, depth - r, false);
                    self.nmp_min_ply = 0;
                    if v >= beta {
                        self.ssm(ss).prior_nmp_fail_high += 1;
                        return null_value;
                    }
                }
            }

            improving |= self.ss(ss).static_eval >= beta;

            // Step 11. Internal iterative reductions
            if !self.ss(ss).follow_pv && !all_node && depth >= 6 && tt_data.mv.is_none() {
                depth -= 1;
            }

            // Step 12. ProbCut
            let prob_cut_beta = beta + 241 - 64 * improving as i32;
            if depth >= 3
                && !is_decisive(beta)
                && !(is_valid(tt_data.value) && tt_data.value < prob_cut_beta)
            {
                let cph = &*self.capture_history as *const CapturePieceToHistory;
                let mut pc_buf = new_move_buffer();
                let mut mp = MovePicker::new_probcut(
                    &mut pc_buf,
                    pos,
                    tt_data.mv,
                    prob_cut_beta - self.ss(ss).static_eval,
                    cph,
                );
                let prob_cut_depth = depth - if improving { 5 } else { 3 };
                loop {
                    let mv = mp.next_move();
                    if mv == Move::NONE {
                        break;
                    }
                    if mv == excluded_move {
                        continue;
                    }
                    let capture = pos.capture_stage(mv);
                    debug_assert!(capture);
                    let gc = pos.gives_check(mv);
                    self.do_move(pos, mv, gc, capture, Some(ss));
                    let mut value =
                        -self.qsearch::<NON_PV>(pos, ss + 1, -prob_cut_beta, -prob_cut_beta + 1);
                    if value >= prob_cut_beta && prob_cut_depth > 0 {
                        value = -self.search::<NON_PV>(
                            pos,
                            ss + 1,
                            -prob_cut_beta,
                            -prob_cut_beta + 1,
                            prob_cut_depth,
                            !cut_node,
                        );
                    }
                    self.undo_move(pos, mv);
                    if value >= prob_cut_beta {
                        tt_writer.write(
                            pos_key,
                            value_to_tt(value, ply),
                            self.ss(ss).tt_pv,
                            BOUND_LOWER,
                            prob_cut_depth + 1,
                            mv,
                            unadjusted_static_eval,
                            self.shared.tt.generation(),
                        );
                        if !is_decisive(value) {
                            return value - (prob_cut_beta - beta);
                        }
                    }
                }
            }
            skip_to_moves_loop = true;
        }
        debug_assert!(skip_to_moves_loop);

        // moves_loop: when in check, search starts here

        // Step 13. A small ProbCut idea
        let prob_cut_beta = beta + 428;
        if (tt_data.bound & BOUND_LOWER) != 0
            && tt_data.depth >= depth - 4
            && tt_data.value >= prob_cut_beta
            && !is_decisive(beta)
            && is_valid(tt_data.value)
            && !is_decisive(tt_data.value)
            && !seek_mate
        {
            return prob_cut_beta;
        }

        #[cfg(feature = "disagreement-guard")]
        let guard_node = self.options.disagreement_guard
            && !root_node
            && !in_check
            && !seek_mate
            && excluded_move.is_none()
            && (pv_node || self.ss(ss).tt_pv)
            && tt_hit
            && crate::disagreement::Evidence {
                depth,
                current: self.ss(ss).static_eval,
                previous: self.ss(ss - 2).static_eval,
                cached: tt_data.value,
                cached_depth: tt_data.depth,
                bound: tt_data.bound,
            }
            .disagrees();

        let cont_hist: [*const PieceToHistory; 6] = [
            self.ss(ss - 1).continuation_history,
            self.ss(ss - 2).continuation_history,
            self.ss(ss - 3).continuation_history,
            self.ss(ss - 4).continuation_history,
            self.ss(ss - 5).continuation_history,
            self.ss(ss - 6).continuation_history,
        ];

        let mut mp_buf = new_move_buffer();
        let mut mp = MovePicker::new(
            &mut mp_buf,
            pos,
            tt_data.mv,
            depth,
            &*self.main_history,
            &*self.low_ply_history,
            &*self.capture_history,
            cont_hist,
            &self.shared.histories,
            ply,
        );

        let mut value = best_value;
        let mut move_count = 0;

        // Step 14. Loop through all legal moves
        loop {
            let mv = mp.next_move();
            if mv == Move::NONE {
                break;
            }
            if mv == excluded_move {
                continue;
            }
            if root_node
                && !self.root_moves[self.pv_idx..self.pv_last]
                    .iter()
                    .any(|rm| rm.pv[0] == mv)
            {
                continue;
            }

            move_count += 1;
            self.ssm(ss).move_count = move_count;

            if root_node
                && self.is_mainthread()
                && self.nodes() > NODES_LIMIT_OUTPUT
                && !self.shared.silent.load(Relaxed)
            {
                println!(
                    "info depth {} currmove {} currmovenumber {}",
                    depth,
                    uci::move_to_uci(mv, pos.is_chess960()),
                    move_count as usize + self.pv_idx
                );
            }
            if pv_node {
                self.ssm(ss + 1).pv = std::ptr::null_mut();
            }

            let mut extension = 0;
            let capture = pos.capture_stage(mv);
            let moved_piece = pos.moved_piece(mv);
            let gives_check = pos.gives_check(mv);

            let mut new_depth = depth - 1;
            let mut r = self.reduction(improving, depth, move_count);

            // Decrease reduction for PV nodes
            if pv_node {
                r -= 512;
            }

            if self.ss(ss).tt_pv {
                r += 929;
            }

            // Step 15. Pruning at shallow depths
            if !root_node && pos.non_pawn_material_c(us) != 0 && !is_loss(best_value) {
                if move_count >= (3 + depth * depth) / (2 - improving as i32) {
                    mp.skip_quiet_moves();
                }

                let mut lmr_depth = new_depth - r / 1024;

                if capture || gives_check {
                    let captured = pos.piece_on(mv.to_sq());
                    let capt_hist =
                        self.capture_history[moved_piece][mv.to_sq()][type_of(captured)] as i32;

                    if !gives_check && lmr_depth < 8 {
                        let futility_value = self.ss(ss).static_eval
                            + 234
                            + 247 * lmr_depth
                            + PIECE_VALUE[captured]
                            + 134 * capt_hist / 1024;
                        if futility_value <= alpha {
                            continue;
                        }
                    }

                    let margin = 177 * depth + capt_hist * 34 / 1024;
                    if (alpha >= VALUE_DRAW
                        || pos.non_pawn_material_c(us) != PIECE_VALUE[moved_piece])
                        && !pos.see_ge(mv, -margin)
                    {
                        continue;
                    }
                } else if !self.ss(ss).follow_pv || !pv_node {
                    let to = mv.to_sq();
                    let mut history =
                        unsafe {
                            get(&(*cont_hist[0])[moved_piece][to])
                                + get(&(*cont_hist[1])[moved_piece][to])
                        } + get(&self.shared.histories.pawn_entry(pos)[moved_piece][to]);

                    if history < -4136 * depth {
                        continue;
                    }

                    history += 69 * self.main_history[us][mv.raw() as usize] as i32 / 32;
                    lmr_depth += history / lmr_divisor(depth);

                    let futility_value = self.ss(ss).static_eval
                        + 119 * lmr_depth
                        + 90 * (self.ss(ss).static_eval > alpha) as i32
                        + 164;

                    if !in_check && lmr_depth < 12 && futility_value <= alpha {
                        if best_value <= futility_value
                            && !is_decisive(best_value)
                            && !is_win(futility_value)
                        {
                            best_value = futility_value;
                        }
                        continue;
                    }

                    lmr_depth = lmr_depth.max(0);

                    if !pos.see_ge(mv, -23 * lmr_depth * lmr_depth) {
                        continue;
                    }
                }
            }

            // Step 16. Singular extensions
            if !root_node
                && mv == tt_data.mv
                && excluded_move.is_none()
                && depth >= 6 + self.ss(ss).tt_pv as i32
                && is_valid(tt_data.value)
                && !is_decisive(tt_data.value)
                && (tt_data.bound & BOUND_LOWER) != 0
                && tt_data.depth >= depth - 3
                && !self.is_shuffling(mv, ss, pos)
                && !seek_mate
            {
                let singular_beta =
                    tt_data.value - (59 + 66 * (self.ss(ss).tt_pv && !pv_node) as i32) * depth / 63;
                let singular_depth = new_depth / 2;

                self.ssm(ss).excluded_move = mv;
                value = self.search::<NON_PV>(
                    pos,
                    ss,
                    singular_beta - 1,
                    singular_beta,
                    singular_depth,
                    cut_node,
                );
                self.ssm(ss).excluded_move = Move::NONE;

                if value < singular_beta {
                    let corr_val_adj = correction_value.abs() / 198368;
                    let double_margin = -2 + 204 * pv_node as i32
                        - 152 * !tt_capture as i32
                        - corr_val_adj
                        - 1175 * self.tt_move_history as i32 / 114178
                        - (ply > self.root_depth) as i32 * 38;
                    let triple_margin = 70 + 279 * pv_node as i32 - 188 * !tt_capture as i32
                        + 81 * self.ss(ss).tt_pv as i32
                        - corr_val_adj
                        - (ply > self.root_depth) as i32 * 43;
                    extension = 1
                        + (value < singular_beta - double_margin) as i32
                        + (value < singular_beta - triple_margin) as i32;
                    depth += 1;
                } else if value >= beta && !is_decisive(value) {
                    update::<TT_MOVE_D>(&mut self.tt_move_history, -421 - 110 * depth);
                    if !in_check && value > self.ss(ss).static_eval {
                        let bonus = ((value - self.ss(ss).static_eval) * 664 / 1024)
                            .clamp(-CORRECTION_HISTORY_LIMIT / 4, CORRECTION_HISTORY_LIMIT / 4);
                        self.update_correction_history(pos, ss, bonus);
                    }
                    return value;
                } else if tt_data.value >= beta || cut_node {
                    extension = -3;
                }
            }

            let node_count = if root_node { self.nodes() } else { 0 };
            if root_node && self.trace_on {
                crate::trace::root_begin(self.root_depth, mv, node_count);
            }

            // Step 17. Make the move
            self.do_move(pos, mv, gives_check, capture, Some(ss));

            new_depth += extension;

            // Step 18. Late moves reduction / extension (LMR)
            if self.ss(ss).tt_pv {
                r -= 3023
                    + pv_node as i32 * 1004
                    + (tt_data.value > alpha) as i32 * 885
                    + (tt_data.depth >= depth) as i32 * (816 + cut_node as i32 * 940);
            }
            r += 697;
            r -= move_count * 65;
            r -= correction_value.abs() / 26310;

            if cut_node {
                r += 4026 + 933 * tt_data.mv.is_none() as i32;
            }
            if tt_capture {
                r += 1079;
            }
            let next_cutoff = self.ss(ss + 1).cutoff_cnt;
            if next_cutoff > 1 {
                r += 264 + 1095 * (next_cutoff > 2) as i32 + 1138 * all_node as i32;
            } else if mv == tt_data.mv {
                r -= 2179;
            }

            let stat_score = if capture {
                let cp = pos.captured_piece();
                873 * PIECE_VALUE[cp] / 128
                    + self.capture_history[moved_piece][mv.to_sq()][type_of(cp)] as i32
            } else {
                let to = mv.to_sq();
                unsafe {
                    (2252 * self.main_history[us][mv.raw() as usize] as i32
                        + 1126 * get(&(*cont_hist[0])[moved_piece][to])
                        + 1093 * get(&(*cont_hist[1])[moved_piece][to]))
                        / 1024
                }
            };
            self.ssm(ss).stat_score = stat_score;

            r -= stat_score * 439 / 4096;

            if !capture && !is_decisive(alpha) {
                r += 3 * (alpha - eval).clamp(-64, 96);
            }

            if all_node {
                r += r * 276 / (256 * depth + 268);
            }

            // When seeking a mate, reduce non-checking moves more and checking moves less
            if seek_mate && r > 0 {
                r += (if gives_check { -r } else { r }) / 4;
            }

            if depth >= 2 && move_count > 1 {
                // Limited extensions beyond newDepth, but not deep in the tree
                // relative to rootDepth, to avoid search explosion.
                let d = (new_depth
                    + (-r / 1024).min(if self.ss(ss).ply < 2 * self.root_depth {
                        2
                    } else {
                        0
                    }))
                .max(1)
                    + pv_node as i32;

                #[cfg(feature = "disagreement-guard")]
                let d = self.guard_budget.child_depth(
                    guard_node,
                    new_depth,
                    d,
                    move_count,
                    capture,
                    gives_check,
                );

                self.ssm(ss).reduction = new_depth - d;
                if self.trace_on && d < new_depth {
                    crate::trace::event(crate::trace::EVENT_REDUCED_MOVE);
                }
                value = -self.search::<NON_PV>(pos, ss + 1, -(alpha + 1), -alpha, d, true);
                self.ssm(ss).reduction = 0;

                if value > alpha {
                    let do_deeper_search = d < new_depth && value > best_value + 53;
                    let do_shallower_search = value < best_value + 8;
                    new_depth += do_deeper_search as i32 - do_shallower_search as i32;

                    if new_depth > d {
                        value = -self.search::<NON_PV>(
                            pos,
                            ss + 1,
                            -(alpha + 1),
                            -alpha,
                            new_depth,
                            !cut_node,
                        );
                    }
                    self.update_continuation_histories(ss, moved_piece, mv.to_sq(), 1334);
                }
            } else if !pv_node || move_count > 1 {
                // Step 19. Full-depth search when LMR is skipped
                if tt_data.mv.is_none() {
                    r += 1127;
                }
                value = -self.search::<NON_PV>(
                    pos,
                    ss + 1,
                    -(alpha + 1),
                    -alpha,
                    new_depth - (r > 5234) as i32 - (r > 5487 && new_depth > 2) as i32,
                    !cut_node,
                );
            }

            // Step 20. Full PV search on the first move or after a fail high
            if pv_node && (move_count == 1 || value > alpha) {
                pv.clear();
                self.ssm(ss + 1).pv = &mut pv as *mut PVMoves;

                if mv == tt_data.mv
                    && ((is_valid(tt_data.value)
                        && is_decisive(tt_data.value)
                        && tt_data.depth > 0)
                        || tt_data.depth > 1)
                {
                    new_depth = new_depth.max(1);
                }
                value = -self.search::<PV>(pos, ss + 1, -beta, -alpha, new_depth, false);
            }

            // Step 21. Undo move
            self.undo_move(pos, mv);

            // Step 22. Check for a new best move
            if self.stopped() {
                return VALUE_ZERO;
            }

            if root_node {
                let nodes = self.nodes();
                if self.trace_on {
                    crate::trace::root_end(pos, mv, value, alpha, beta, nodes);
                }
                let sel_depth = self.sel_depth;
                let pv_idx = self.pv_idx;
                let child_pv = self.ss(ss + 1).pv;
                let rm = self
                    .root_moves
                    .iter_mut()
                    .find(|rm| rm.pv[0] == mv)
                    .unwrap();

                rm.effort += nodes - node_count;
                let n = nodes - node_count;
                let e_prev = (rm.effort - n).max(1);

                const SCALE: u64 = 32;
                const CHI_NUM: u64 = 3;
                const CHI_DEN: u64 = 2;
                let w = ((SCALE * n * CHI_DEN) / (n * CHI_DEN + CHI_NUM * e_prev)).clamp(12, 24);
                let w_mss = w.min(16);
                let v2 = value as i64 * value.abs() as i64;

                // The C++ code mixes signed values with u64 weights; emulate the wrap exactly.
                if rm.average_score == -VALUE_INFINITE {
                    rm.average_score = value;
                } else {
                    let s = (value as i64 as u64)
                        .wrapping_mul(w)
                        .wrapping_add((rm.average_score as i64 as u64).wrapping_mul(SCALE - w));
                    rm.average_score = (s / SCALE) as i32;
                }
                if rm.mean_squared_score == (-VALUE_INFINITE).wrapping_mul(VALUE_INFINITE) {
                    rm.mean_squared_score = value * value.abs();
                } else {
                    let s = (v2 as u64).wrapping_mul(w_mss).wrapping_add(
                        (rm.mean_squared_score as i64 as u64).wrapping_mul(SCALE - w_mss),
                    );
                    rm.mean_squared_score = (s / SCALE) as i32;
                }

                if move_count == 1 || value > alpha {
                    rm.score = value;
                    rm.uci_score = value;
                    rm.sel_depth = sel_depth;
                    rm.unset_inexact();
                    if value >= beta {
                        rm.inexact_lower = true;
                        rm.uci_score = beta;
                    } else if value <= alpha {
                        rm.inexact_upper = true;
                        rm.uci_score = alpha;
                    }
                    rm.pv.truncate(1);
                    let child = unsafe { &*child_pv };
                    rm.pv.extend_from_slice(child.as_slice());

                    if move_count > 1 && pv_idx == 0 {
                        let b = &self.shared.best_move_changes[self.thread_idx];
                        b.store(b.load(Relaxed) + 1, Relaxed);
                    }
                } else {
                    rm.score = -VALUE_INFINITE;
                }
            }

            // If we have an alternative move equal in value to the current bestmove,
            // we sometimes promote it to bestmove by pretending it just exceeds alpha.
            let inc = (value == best_value
                && ply + 2 >= self.root_depth
                && (self.nodes() as i32 & 14) == 0
                && !is_win(value.abs() + 1)) as i32;

            if value + inc > best_value {
                best_value = value;
                if value + inc > alpha {
                    best_move = mv;
                    if pv_node && !root_node {
                        let child = self.ss(ss + 1).pv;
                        unsafe { (*self.ss(ss).pv).update(mv, child) };
                    }
                    if value >= beta {
                        if self.trace_on {
                            crate::trace::event(crate::trace::EVENT_BETA_CUTOFF);
                        }
                        let add = ((extension < 2) || pv_node) as i32;
                        self.ssm(ss).cutoff_cnt += add;
                        break;
                    }
                    if depth > 3 && depth < 12 && !is_decisive(value) {
                        depth -= 3;
                    }
                    alpha = value;
                }
            }

            if mv != best_move && move_count as usize <= SEARCHEDLIST_CAPACITY {
                if capture {
                    captures_searched.push(mv);
                } else {
                    quiets_searched.push(mv);
                }
            }
        }

        // Step 23. Check for mate and stalemate
        if best_value >= beta && !is_decisive(best_value) && !is_decisive(alpha) {
            best_value = (best_value * depth + beta) / (depth + 1);
        }

        if move_count == 0 {
            best_value = if excluded_move.is_some() {
                alpha
            } else if in_check {
                mated_in(ply)
            } else {
                VALUE_DRAW
            };
        } else if best_move.is_some() {
            self.update_all_stats(
                pos,
                ss,
                best_move,
                prev_sq,
                &quiets_searched,
                &captures_searched,
                depth,
                tt_data.mv,
                pv_node,
            );
            if !pv_node {
                update::<TT_MOVE_D>(
                    &mut self.tt_move_history,
                    if best_move == tt_data.mv { 918 } else { -747 },
                );
            }
        } else if !prior_capture && prev_sq != SQ_NONE {
            let prev = *self.ss(ss - 1);
            let mut bonus_scale = -241;
            bonus_scale -= prev.stat_score / 98;
            bonus_scale += (59 * depth).min(420);
            bonus_scale += 186 * (prev.move_count > 9) as i32;
            bonus_scale += 142 * (!in_check && best_value <= self.ss(ss).static_eval - 106) as i32;
            bonus_scale += 159 * (!prev.in_check && best_value <= -prev.static_eval - 68) as i32;
            bonus_scale = bonus_scale.max(0);

            let scaled_bonus = (150 * depth - 85).min(1337) * bonus_scale;
            self.update_continuation_histories(
                ss - 1,
                pos.piece_on(prev_sq),
                prev_sq,
                scaled_bonus * 263 / 16384,
            );
            update::<BUTTERFLY_D>(
                &mut self.main_history[flip_color(us)][prev.current_move.raw() as usize],
                scaled_bonus * 215 / 32768,
            );
            if type_of(pos.piece_on(prev_sq)) != PAWN && prev.current_move.type_of() != PROMOTION {
                update_atomic::<PAWN_D>(
                    &self.shared.histories.pawn_entry(pos)[pos.piece_on(prev_sq)][prev_sq],
                    scaled_bonus * 324 / 8192,
                );
            }
        } else if prev_sq != SQ_NONE {
            debug_assert!(prior_capture);
            let captured = pos.captured_piece();
            update::<CAPTURE_D>(
                &mut self.capture_history[pos.piece_on(prev_sq)][prev_sq][type_of(captured)],
                892,
            );
        }

        if pv_node {
            best_value = best_value.min(max_value);
        }

        if best_value <= alpha {
            let prev_tt_pv = self.ss(ss - 1).tt_pv;
            let s = self.ssm(ss);
            s.tt_pv = s.tt_pv || prev_tt_pv;
        }

        // Step 24. Write gathered information in transposition table
        if excluded_move.is_none() && !(root_node && self.pv_idx != 0) {
            let bound = if best_value >= beta {
                BOUND_LOWER
            } else if pv_node && best_move.is_some() {
                BOUND_EXACT
            } else {
                BOUND_UPPER
            };
            let d = if move_count != 0 {
                depth
            } else {
                (MAX_PLY - 1).min(depth + 6)
            };
            tt_writer.write(
                pos_key,
                value_to_tt(best_value, ply),
                self.ss(ss).tt_pv,
                bound,
                d,
                best_move,
                unadjusted_static_eval,
                self.shared.tt.generation(),
            );
        }

        #[cfg(feature = "evaluation-risk")]
        if self.options.evaluation_risk
            && pv_node
            && !root_node
            && !in_check
            && excluded_move.is_none()
            && !self.stopped()
            && (2..=10).contains(&risk_context.1)
            && best_move.is_some()
            && best_move.type_of() == NORMAL
            && !pos.capture(best_move)
            && best_value > risk_window.0
            && best_value < risk_window.1.min(beta)
        {
            self.risk_history
                .observe(risk_context.0, static_eval, best_value);
        }

        // Adjust correction history
        if !in_check
            && !(best_move.is_some() && pos.capture(best_move))
            && (best_value > self.ss(ss).static_eval) == best_move.is_some()
        {
            let bonus = ((best_value - self.ss(ss).static_eval)
                * depth
                * (if best_move.is_some() { 12 } else { 18 })
                / 128)
                .clamp(-CORRECTION_HISTORY_LIMIT / 4, CORRECTION_HISTORY_LIMIT / 4);
            self.update_correction_history(pos, ss, 1061 * bonus / 1024);
        }

        best_value
    }

    // ---- Quiescence search ----------------------------------------------------

    fn qsearch<const NT: u8>(
        &mut self,
        pos: &mut Position,
        ss: usize,
        mut alpha: Value,
        beta: Value,
    ) -> Value {
        let pv_node = NT == PV;
        let ply = self.ss(ss).ply;

        if alpha < VALUE_DRAW && pos.upcoming_repetition(ply) {
            alpha = value_draw(self.nodes());
            if alpha >= beta {
                return alpha;
            }
        }

        let mut pv = PVMoves::default();

        // Step 1. Initialize node
        if pv_node {
            self.ssm(ss + 1).pv = &mut pv as *mut PVMoves;
            unsafe { (*self.ss(ss).pv).clear() };
        }

        if self.trace_on {
            self.trace_observe(pos, ss, true);
        }

        let mut best_move = Move::NONE;
        let in_check = pos.checkers() != 0;
        self.ssm(ss).in_check = in_check;
        let mut move_count = 0;

        if pv_node && self.sel_depth < ply + 1 {
            self.sel_depth = ply + 1;
        }

        // Step 2. Check for an immediate draw or maximum ply reached
        if pos.is_draw(ply) || ply >= MAX_PLY {
            return if ply >= MAX_PLY && !in_check {
                self.evaluate(pos)
            } else {
                VALUE_DRAW
            };
        }

        // Step 3. Transposition table lookup
        let pos_key = pos.key();
        let cache_owner = self.shared;
        let (tt_hit, mut tt_data, tt_writer) = cache_owner.tt.probe(pos_key);
        self.ssm(ss).tt_hit = tt_hit;
        tt_data.mv = if tt_hit { tt_data.mv } else { Move::NONE };
        tt_data.value = if tt_hit {
            value_from_tt(tt_data.value, ply, pos.rule50_count())
        } else {
            VALUE_NONE
        };
        let pv_hit = tt_hit && tt_data.is_pv;

        if !pv_node
            && tt_data.depth >= DEPTH_QS
            && is_valid(tt_data.value)
            && (tt_data.bound
                & if tt_data.value >= beta {
                    BOUND_LOWER
                } else {
                    BOUND_UPPER
                })
                != 0
        {
            if self.trace_on {
                crate::trace::event(crate::trace::EVENT_TABLE_CUTOFF);
            }
            return tt_data.value;
        }

        // Step 4. Static evaluation of the position
        let mut unadjusted_static_eval = VALUE_NONE;
        let mut best_value;
        let futility_base;
        if in_check {
            best_value = -VALUE_INFINITE;
            futility_base = -VALUE_INFINITE;
        } else {
            let correction_value = self.correction_value(pos, ss);
            if tt_hit {
                unadjusted_static_eval = tt_data.eval;
                if !is_valid(unadjusted_static_eval) {
                    unadjusted_static_eval = self.evaluate(pos);
                }
                best_value = to_corrected_static_eval(unadjusted_static_eval, correction_value);
                self.ssm(ss).static_eval = best_value;
                if is_valid(tt_data.value)
                    && !is_decisive(tt_data.value)
                    && (tt_data.bound
                        & if tt_data.value > best_value {
                            BOUND_LOWER
                        } else {
                            BOUND_UPPER
                        })
                        != 0
                {
                    best_value = tt_data.value;
                }
            } else {
                unadjusted_static_eval = self.evaluate(pos);
                best_value = to_corrected_static_eval(unadjusted_static_eval, correction_value);
                self.ssm(ss).static_eval = best_value;
            }

            // Stand pat
            if best_value >= beta {
                debug_assert!(!is_decisive(best_value));
                best_value = (441 * best_value + 583 * beta) / 1024;
                if !tt_hit {
                    tt_writer.write(
                        pos_key,
                        VALUE_NONE,
                        false,
                        BOUND_LOWER,
                        DEPTH_UNSEARCHED,
                        Move::NONE,
                        unadjusted_static_eval,
                        self.shared.tt.generation(),
                    );
                }
                return best_value;
            }
            if best_value > alpha {
                alpha = best_value;
            }
            futility_base = self.ss(ss).static_eval + 306;
        }

        let sentinel = self.ss(ss - 1).continuation_history;
        let cont_hist: [*const PieceToHistory; 6] = [
            sentinel,
            std::ptr::null(),
            std::ptr::null(),
            std::ptr::null(),
            std::ptr::null(),
            std::ptr::null(),
        ];
        let prev_move = self.ss(ss - 1).current_move;
        let prev_sq = if prev_move.is_ok() {
            prev_move.to_sq()
        } else {
            SQ_NONE
        };

        let mut mp_buf = new_move_buffer();
        let mut mp = MovePicker::new(
            &mut mp_buf,
            pos,
            tt_data.mv,
            DEPTH_QS,
            &*self.main_history,
            &*self.low_ply_history,
            &*self.capture_history,
            cont_hist,
            &self.shared.histories,
            ply,
        );

        // Step 5. Loop through all legal moves
        loop {
            let mv = mp.next_move();
            if mv == Move::NONE {
                break;
            }
            let gives_check = pos.gives_check(mv);
            let capture = pos.capture_stage(mv);
            move_count += 1;

            // Step 6. Pruning
            if !is_loss(best_value) {
                if !gives_check
                    && mv.to_sq() != prev_sq
                    && !is_loss(futility_base)
                    && mv.type_of() != PROMOTION
                {
                    if move_count > 2 {
                        continue;
                    }
                    let futility_value = futility_base + PIECE_VALUE[pos.piece_on(mv.to_sq())];
                    if futility_value <= alpha {
                        best_value = best_value.max(futility_value);
                        continue;
                    }
                    if !pos.see_ge(mv, alpha - futility_base) {
                        best_value = best_value.max(alpha.min(futility_base));
                        continue;
                    }
                }
                if !capture {
                    continue;
                }
                if !pos.see_ge(mv, -74) {
                    continue;
                }
            }

            // Step 7. Make and search the move
            self.do_move(pos, mv, gives_check, capture, Some(ss));
            let value = -self.qsearch::<NT>(pos, ss + 1, -beta, -alpha);
            self.undo_move(pos, mv);

            // Step 8. Check for a new best move
            if value > best_value {
                best_value = value;
                if value > alpha {
                    best_move = mv;
                    if pv_node {
                        let child = self.ss(ss + 1).pv;
                        unsafe { (*self.ss(ss).pv).update(mv, child) };
                    }
                    if value < beta {
                        alpha = value;
                    } else {
                        if self.trace_on {
                            crate::trace::event(crate::trace::EVENT_BETA_CUTOFF);
                        }
                        break;
                    }
                }
            }
        }

        // Step 9. Check for mate and stalemate
        if move_count == 0 {
            if in_check {
                return mated_in(ply);
            }
            let us = pos.side_to_move();
            if pawn_single_push_bb(us, pos.pieces_ct(us, PAWN)) & !pos.pieces() == 0
                && pos.non_pawn_material_c(us) == 0
                && type_of(pos.captured_piece()) >= KNIGHT
                && MoveList::new(pos, GenType::Legal).is_empty()
            {
                best_value = VALUE_DRAW;
            }
        }

        if !is_decisive(best_value) && best_value > beta {
            best_value = (462 * best_value + 562 * beta) / 1024;
        }

        // Step 10. Save gathered info in transposition table
        tt_writer.write(
            pos_key,
            value_to_tt(best_value, ply),
            pv_hit,
            if best_value >= beta {
                BOUND_LOWER
            } else {
                BOUND_UPPER
            },
            DEPTH_QS,
            best_move,
            unadjusted_static_eval,
            self.shared.tt.generation(),
        );

        best_value
    }

    // ---- Time and output ------------------------------------------------------

    fn check_time(&mut self) {
        let shared = self.shared.clone();
        let limits_nodes = self.limits.nodes;
        let use_tm = self.limits.use_time_management();
        let movetime = self.limits.movetime;
        let start_time = self.limits.start_time;
        let mgr = self.manager.as_mut().unwrap();

        mgr.calls_cnt -= 1;
        if mgr.calls_cnt > 0 {
            return;
        }
        mgr.calls_cnt = if limits_nodes != 0 {
            512.min((limits_nodes / 1024) as i32)
        } else {
            512
        };

        let elapsed = mgr.tm.elapsed(|| shared.nodes_searched());
        let tick = start_time + elapsed;
        if mgr.last_info_time == 0 {
            mgr.last_info_time = tick;
        }
        if tick - mgr.last_info_time >= 1000 {
            mgr.last_info_time = tick;
        }

        if shared.ponder.load(Relaxed) {
            return;
        }

        if (use_tm && (elapsed > mgr.tm.maximum() || mgr.stop_on_ponderhit))
            || (movetime != 0 && elapsed >= movetime)
            || (limits_nodes != 0 && shared.nodes_searched() >= limits_nodes)
        {
            shared.stop.store(true, Relaxed);
        }
    }

    pub fn output_pv(&mut self, pos: &mut Position, depth: Depth) {
        if self.shared.silent.load(Relaxed) {
            return;
        }
        let nodes = self.shared.nodes_searched();
        let multi_pv = self.options.multi_pv.min(self.root_moves.len());
        let tb_hits = self.shared.tb_hits_total()
            + if self.tb_config.root_in_tb {
                self.root_moves.len() as u64
            } else {
                0
            };
        let mut out = String::new();

        for i in 0..multi_pv {
            let use_previous = self.root_moves[i].score == -VALUE_INFINITE;
            if depth == 1 && use_previous && i > 0 {
                continue;
            }
            let d = if use_previous {
                (depth - 1).max(1)
            } else {
                depth
            };
            let mut v = if use_previous {
                self.root_moves[i].previous_score
            } else {
                self.root_moves[i].uci_score
            };
            if v == -VALUE_INFINITE {
                v = VALUE_ZERO;
            }
            let is_tb_score = self.tb_config.root_in_tb && !is_mate_or_mated(v);
            if is_tb_score {
                v = self.root_moves[i].tb_score;
            }
            if is_decisive(v)
                && !is_mate_or_mated(v)
                && !use_previous
                && (!self.root_moves[i].is_inexact() || is_tb_score)
            {
                let opts = self.tb_options();
                let mut rm = std::mem::replace(&mut self.root_moves[i], RootMove::new(Move::NONE));
                syzygy_extend_pv(
                    opts,
                    &self.limits,
                    self.options.move_overhead,
                    pos,
                    &mut rm,
                    &mut v,
                    multi_pv,
                );
                self.root_moves[i] = rm;
            }
            let rm = &self.root_moves[i];
            let pv_moves = if use_previous {
                &rm.previous_pv
            } else {
                &rm.pv
            };
            let pv: Vec<String> = pv_moves
                .iter()
                .map(|&m| uci::move_to_uci(m, pos.is_chess960()))
                .collect();
            let bound = if is_tb_score || use_previous {
                ""
            } else if rm.inexact_lower {
                " lowerbound"
            } else if rm.inexact_upper {
                " upperbound"
            } else {
                ""
            };
            let time = self.manager.as_ref().unwrap().tm.elapsed_time().max(1);
            let wdl = if self.options.show_wdl {
                format!(" wdl {}", uci::wdl(v, pos))
            } else {
                String::new()
            };
            out.push_str(&format!(
                "info depth {} seldepth {} multipv {} score {}{}{} nodes {} nps {} hashfull {} tbhits {} time {} pv {}\n",
                d,
                rm.sel_depth,
                i + 1,
                uci::format_score(v, pos),
                bound,
                wdl,
                nodes,
                nodes * 1000 / time as u64,
                self.shared.tt.hashfull(0),
                tb_hits,
                time,
                pv.join(" ")
            ));
        }
        uci::emit(&out);
    }

    fn tb_options(&self) -> crate::syzygy::TbOptions {
        crate::syzygy::TbOptions {
            rule50: self.options.syzygy_50_move_rule,
            probe_depth: self.options.syzygy_probe_depth,
            probe_limit: self.options.syzygy_probe_limit,
        }
    }

    /// Called when the program receives the UCI 'go' command (main thread only).
    pub fn start_searching(&mut self, helpers: &mut [Box<Worker>]) -> (Move, Move) {
        self.acc_stack.reset();
        let tm_opts = TmOptions {
            nodestime: self.options.nodestime,
            move_overhead: self.options.move_overhead,
            ponder: self.options.ponder,
        };
        {
            let us = self.root_pos.side_to_move();
            let ply = self.root_pos.game_ply();
            let mgr = self.manager.as_mut().unwrap();
            let mut ota = mgr.original_time_adjust;
            mgr.tm.init(&mut self.limits, us, ply, &tm_opts, &mut ota);
            mgr.original_time_adjust = ota;
        }
        self.shared.tt.new_search();

        if self.root_moves.is_empty() {
            let v = if self.root_pos.checkers() != 0 {
                -VALUE_MATE
            } else {
                VALUE_DRAW
            };
            if !self.shared.silent.load(Relaxed) {
                uci::emit(&format!(
                    "info depth 0 score {}\n",
                    uci::format_score(v, &self.root_pos)
                ));
            }
            return (Move::NONE, Move::NONE);
        }

        let mut uci_pv_sent = false;
        std::thread::scope(|s| {
            for h in helpers.iter_mut() {
                h.acc_stack.reset();
                s.spawn(move || {
                    h.iterative_deepening();
                });
            }
            uci_pv_sent = self.iterative_deepening();

            // Wait for stop/ponderhit when pondering or in an infinite search.
            while !self.stopped() && (self.shared.ponder.load(Relaxed) || self.limits.infinite) {
                std::thread::sleep(std::time::Duration::from_millis(1));
            }
            self.shared.stop.store(true, Relaxed);
        });

        if self.limits.npmsec != 0 {
            let n =
                self.shared.nodes_searched() as i64 - self.limits.inc[self.root_pos.side_to_move()];
            self.manager.as_mut().unwrap().tm.advance_nodes_time(n);
        }

        let skill = Skill::new(
            self.options.skill_level,
            if self.options.limit_strength {
                self.options.elo
            } else {
                0
            },
        );
        let best_idx = if self.limits.depth == 0 && !skill.enabled() {
            get_best_thread(self, helpers)
        } else {
            0
        };

        let (best_score, best_avg) = {
            let bt: &Worker = if best_idx == 0 {
                self
            } else {
                &helpers[best_idx - 1]
            };
            (bt.root_moves[0].score, bt.root_moves[0].average_score)
        };
        {
            let mgr = self.manager.as_mut().unwrap();
            mgr.best_previous_score = best_score;
            mgr.best_previous_average_score = best_avg;
        }

        let tt = &self.shared.tt as *const TranspositionTable;
        let mut root_pos = std::mem::take(&mut self.root_pos);
        {
            let bt: &mut Worker = if best_idx == 0 {
                self
            } else {
                &mut helpers[best_idx - 1]
            };
            if bt.root_moves[0].pv.len() == 1
                && extract_ponder_from_tt(&mut bt.root_moves[0], unsafe { &*tt }, &mut root_pos)
            {
                uci_pv_sent = false;
            }
        }
        if !uci_pv_sent || best_idx != 0 {
            let rd = if best_idx == 0 {
                self.root_depth
            } else {
                helpers[best_idx - 1].root_depth
            };
            // output_pv uses the main thread's clock and options, as in C++.
            if best_idx == 0 {
                self.output_pv(&mut root_pos, rd);
            } else {
                let saved = std::mem::take(&mut self.root_moves);
                self.root_moves = std::mem::take(&mut helpers[best_idx - 1].root_moves);
                self.output_pv(&mut root_pos, rd);
                helpers[best_idx - 1].root_moves = std::mem::replace(&mut self.root_moves, saved);
            }
        }
        self.root_pos = root_pos;

        let bt: &Worker = if best_idx == 0 {
            self
        } else {
            &helpers[best_idx - 1]
        };
        let best = bt.root_moves[0].pv[0];
        let ponder = if bt.root_moves[0].pv.len() > 1 {
            bt.root_moves[0].pv[1]
        } else {
            Move::NONE
        };
        #[cfg(feature = "disagreement-guard")]
        if self.options.disagreement_guard && !self.shared.silent.load(Relaxed) {
            let audits = self.guard_budget.spent as u64
                + helpers
                    .iter()
                    .map(|w| w.guard_budget.spent as u64)
                    .sum::<u64>();
            uci::emit(&format!(
                "info string Aster disagreement guard audits {audits} max_per_thread {}\n",
                crate::disagreement::AUDIT_LIMIT
            ));
        }
        #[cfg(feature = "evaluation-risk")]
        if self.options.evaluation_risk && !self.shared.silent.load(Relaxed) {
            let samples = self.risk_history.observations as u64
                + helpers
                    .iter()
                    .map(|w| w.risk_history.observations as u64)
                    .sum::<u64>();
            let deferred = self.risk_history.deferred as u64
                + helpers
                    .iter()
                    .map(|w| w.risk_history.deferred as u64)
                    .sum::<u64>();
            uci::emit(&format!(
                "info string Aster evaluation risk samples {samples} deferred {deferred} max_per_thread {}\n",
                crate::evaluation_risk::DEFER_LIMIT
            ));
        }
        (best, ponder)
    }
}

/// Corrects and extends PVs of moves with a TB (not mate) score, as in the upstream reference.
fn syzygy_extend_pv(
    opts: crate::syzygy::TbOptions,
    limits: &LimitsType,
    move_overhead: i64,
    pos: &mut Position,
    rm: &mut RootMove,
    v: &mut Value,
    multi_pv: usize,
) {
    let t_start = std::time::Instant::now();
    let rule50 = opts.rule50;
    let time_abort = || {
        limits.npmsec == 0
            && limits.use_time_management()
            && 2.0 * multi_pv as f64 * t_start.elapsed().as_secs_f64() * 1000.0
                >= move_overhead as f64
    };
    if time_abort() {
        return;
    }
    pos.do_move_simple(rm.pv[0]);
    let mut ply: i32 = 1;

    while (ply as usize) < rm.pv.len() {
        let pv_move = rm.pv[ply as usize];
        let mut legal: Vec<RootMove> = MoveList::new(pos, GenType::Legal)
            .as_slice()
            .iter()
            .map(|&m| RootMove::new(m))
            .collect();
        let config = crate::syzygy::rank_root_moves(opts, pos, &mut legal, false, &time_abort);
        let Some(rank) = legal.iter().find(|r| r.pv[0] == pv_move).map(|r| r.tb_rank) else {
            break;
        };
        if legal[0].tb_rank != rank {
            break;
        }
        ply += 1;
        pos.do_move_simple(pv_move);
        if config.root_in_tb && ((rule50 && pos.is_draw(ply)) || pos.is_repetition(ply)) {
            pos.undo_move(pv_move);
            ply -= 1;
            break;
        }
        if config.root_in_tb && time_abort() {
            break;
        }
    }
    rm.pv.truncate(ply as usize);

    while !(rule50 && pos.is_draw(0)) {
        if time_abort() {
            break;
        }
        let mut legal: Vec<RootMove> = Vec::new();
        for &m in MoveList::new(pos, GenType::Legal).as_slice() {
            let mut r = RootMove::new(m);
            pos.do_move_simple(m);
            for &opp in MoveList::new(pos, GenType::Legal).as_slice() {
                r.tb_rank -= if pos.capture(opp) { 100 } else { 1 };
            }
            pos.undo_move(m);
            legal.push(r);
        }
        if legal.is_empty() {
            break;
        }
        legal.sort_by(|a, b| b.tb_rank.cmp(&a.tb_rank));
        let config = crate::syzygy::rank_root_moves(opts, pos, &mut legal, true, &time_abort);
        if !config.root_in_tb || config.cardinality > 0 {
            break;
        }
        let pv_move = legal[0].pv[0];
        rm.pv.push(pv_move);
        pos.do_move_simple(pv_move);
    }

    if pos.is_draw(0) {
        *v = VALUE_DRAW;
    }
    for i in (0..rm.pv.len()).rev() {
        pos.undo_move(rm.pv[i]);
    }
    if time_abort() {
        uci::emit(
            "info string Syzygy based PV extension requires more time, increase Move Overhead as needed.\n",
        );
    }
}

fn extract_ponder_from_tt(rm: &mut RootMove, tt: &TranspositionTable, pos: &mut Position) -> bool {
    pos.do_move_simple(rm.pv[0]);
    if !pos.is_draw(1) {
        let (hit, data, _) = tt.probe(pos.key());
        if hit && data.mv.is_some() && pos.legal(data.mv) {
            rm.pv.push(data.mv);
        }
    }
    pos.undo_move(rm.pv[0]);
    rm.pv.len() > 1
}

/// Returns the index of the best thread (0 = main, i = helpers[i - 1]).
fn get_best_thread(main: &Worker, helpers: &[Box<Worker>]) -> usize {
    let all: Vec<&Worker> = std::iter::once(main)
        .chain(helpers.iter().map(|b| &**b))
        .collect();
    let mut best = 0usize;
    let min_score = all.iter().map(|w| w.root_moves[0].score).min().unwrap();
    let mut votes: std::collections::HashMap<Move, i64> = std::collections::HashMap::new();
    for w in &all {
        *votes.entry(w.root_moves[0].pv[0]).or_insert(0) +=
            (w.root_moves[0].score - min_score + 14) as i64;
    }
    for (i, w) in all.iter().enumerate() {
        let bm = &all[best].root_moves[0];
        let nm = &w.root_moves[0];
        let best_vote = votes[&bm.pv[0]];
        let new_vote = votes[&nm.pv[0]];
        let best_decisive =
            bm.score != -VALUE_INFINITE && is_decisive(bm.score) && !bm.is_inexact();
        let new_decisive = nm.score != -VALUE_INFINITE && is_decisive(nm.score) && !nm.is_inexact();
        if best_decisive {
            if new_decisive && nm.score.abs() > bm.score.abs() {
                best = i;
            }
        } else if new_decisive
            || (!is_loss(nm.score)
                && (new_vote > best_vote || (new_vote == best_vote && nm.pv.len() > bm.pv.len())))
        {
            best = i;
        }
    }
    best
}

fn interpolate(x: f64, x0: f64, x1: f64, y0: f64, y1: f64) -> f64 {
    y0 + (y1 - y0) * (x - x0) / (x1 - x0)
}

fn interpolate_i64(x: i64, x0: i64, x1: i64, y0: f64, y1: f64) -> f64 {
    y0 + (y1 - y0) * (x - x0) as f64 / (x1 - x0) as f64
}
