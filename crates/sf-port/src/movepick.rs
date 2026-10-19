// Rust port of Stockfish 19 `movepick.h/.cpp`.
// Copyright (C) 2004-2026 The Stockfish developers (see AUTHORS file)
// Licensed under the GNU General Public License v3 or later.
//
// Like the C++ original, the picker reads history tables through pointers:
// child searches update those tables while this picker is alive, and quiet
// moves are scored lazily with the then-current values.

use crate::bitboard::*;
use crate::history::*;
use crate::movegen::{CAPTURES, EVASIONS, MoveList, QUIETS, generate};
use crate::position::Position;
use crate::types::*;

#[repr(C)]
#[derive(Copy, Clone, Default)]
pub struct ExtMove {
    pub mv: Move,
    pub value: i32,
}

const MAIN_TT: u8 = 0;
const CAPTURE_INIT: u8 = 1;
const GOOD_CAPTURE: u8 = 2;
const QUIET_INIT: u8 = 3;
const GOOD_QUIET: u8 = 4;
const BAD_CAPTURE: u8 = 5;
const BAD_QUIET: u8 = 6;
const EVASION_TT: u8 = 7;
const EVASION_INIT: u8 = 8;
const EVASION: u8 = 9;
const PROBCUT_TT: u8 = 10;
const PROBCUT_INIT: u8 = 11;
const PROBCUT: u8 = 12;
const QSEARCH_TT: u8 = 13;
const QCAPTURE_INIT: u8 = 14;
const QCAPTURE: u8 = 15;

static SORT512: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);

/// Enables the AVX-512 move sorter when available (same result as the scalar sort).
pub fn init() {
    #[cfg(target_arch = "x86_64")]
    {
        let ok = is_x86_feature_detected!("avx512f");
        let forced = matches!(std::env::var("SF_PORT_SIMD").as_deref(), Ok("scalar") | Ok("avx2"));
        SORT512.store(ok && !forced, std::sync::atomic::Ordering::Relaxed);
    }
}

#[cfg(target_arch = "x86_64")]
mod sorter512 {
    use super::ExtMove;
    use std::arch::x86_64::*;

    /// Insertion-sorts up to 16 moves held in two registers (values, moves).
    /// Equal values keep their arrival order, exactly like the scalar sort.
    #[target_feature(enable = "avx512f")]
    pub unsafe fn sort_prefix(moves: &mut [ExtMove], limit: i32) -> (usize, usize) {
        unsafe {
            let first = moves[0];
            let mut sorted_moves = _mm512_set1_epi32(first.mv.0 as i32);
            let mut sorted_values = _mm512_mask_set1_epi32(_mm512_set1_epi32(first.value), !1, i32::MIN);
            let mut sorted_end = 0usize;
            let mut p = 1usize;
            while p < moves.len() {
                if moves[p].value >= limit {
                    if sorted_end + 1 >= 16 {
                        break;
                    }
                    let m = moves[p];
                    let value = _mm512_set1_epi32(m.value);
                    let mv = _mm512_set1_epi32(m.mv.0 as i32);
                    let lt = _mm512_cmplt_epi32_mask(sorted_values, value);
                    let expand = lt.wrapping_sub(1);
                    sorted_values = _mm512_mask_expand_epi32(value, expand, sorted_values);
                    sorted_moves = _mm512_mask_expand_epi32(mv, expand, sorted_moves);
                    sorted_end += 1;
                    moves[p] = moves[sorted_end];
                }
                p += 1;
            }
            let count = sorted_end + 1;
            let mut v = [0i32; 16];
            let mut m = [0i32; 16];
            _mm512_storeu_si512(v.as_mut_ptr() as *mut _, sorted_values);
            _mm512_storeu_si512(m.as_mut_ptr() as *mut _, sorted_moves);
            for i in 0..count {
                moves[i] = ExtMove { mv: crate::types::Move(m[i] as u16), value: v[i] };
            }
            (sorted_end, p)
        }
    }
}

/// Sort moves in descending order up to and including a given limit.
/// The order of moves smaller than the limit is left unspecified.
fn partial_insertion_sort(moves: &mut [ExtMove], limit: i32) {
    if moves.is_empty() {
        return;
    }
    let mut sorted_end = 0usize;
    let mut start = 1usize;
    #[cfg(target_arch = "x86_64")]
    if SORT512.load(std::sync::atomic::Ordering::Relaxed) {
        (sorted_end, start) = unsafe { sorter512::sort_prefix(moves, limit) };
    }
    for p in start..moves.len() {
        if moves[p].value >= limit {
            let tmp = moves[p];
            sorted_end += 1;
            moves[p] = moves[sorted_end];
            let mut q = sorted_end;
            while q != 0 && moves[q - 1].value < tmp.value {
                moves[q] = moves[q - 1];
                q -= 1;
            }
            moves[q] = tmp;
        }
    }
}

pub struct MovePicker {
    pos: *const Position,
    main_history: *const ButterflyHistory,
    low_ply_history: *const LowPlyHistory,
    capture_history: *const CapturePieceToHistory,
    continuation_history: [*const PieceToHistory; 6],
    shared: *const SharedHistories,
    tt_move: Move,
    cur: usize,
    end_cur: usize,
    end_bad_captures: usize,
    end_captures: usize,
    end_generated: usize,
    stage: u8,
    threshold: i32,
    depth: Depth,
    ply: i32,
    skip_quiets: bool,
    // Caller-owned buffer (see MoveBuffer); only slots written by score() are read.
    moves: *mut ExtMove,
}

/// Storage for a MovePicker's scored moves. Kept separate so the picker itself
/// is small and never copied with its buffer.
pub type MoveBuffer = [std::mem::MaybeUninit<ExtMove>; MAX_MOVES];

#[inline(always)]
pub fn new_move_buffer() -> MoveBuffer {
    [const { std::mem::MaybeUninit::uninit() }; MAX_MOVES]
}

impl MovePicker {
    /// Constructor for the main search and for the quiescence search.
    #[allow(clippy::too_many_arguments)]
    #[inline]
    pub fn new(
        buf: &mut MoveBuffer,
        pos: &Position,
        ttm: Move,
        depth: Depth,
        mh: *const ButterflyHistory,
        lph: *const LowPlyHistory,
        cph: *const CapturePieceToHistory,
        ch: [*const PieceToHistory; 6],
        sh: *const SharedHistories,
        ply: i32,
    ) -> Self {
        let valid_tt = ttm.is_some() && pos.pseudo_legal(ttm);
        let stage = if pos.checkers() != 0 {
            EVASION_TT + !valid_tt as u8
        } else {
            (if depth > 0 { MAIN_TT } else { QSEARCH_TT }) + !valid_tt as u8
        };
        MovePicker {
            pos,
            main_history: mh,
            low_ply_history: lph,
            capture_history: cph,
            continuation_history: ch,
            shared: sh,
            tt_move: ttm,
            cur: 0,
            end_cur: 0,
            end_bad_captures: 0,
            end_captures: 0,
            end_generated: 0,
            stage,
            threshold: 0,
            depth,
            ply,
            skip_quiets: false,
            moves: buf.as_mut_ptr() as *mut ExtMove,
        }
    }

    /// Constructor for ProbCut: captures with SEE >= threshold.
    #[inline]
    pub fn new_probcut(buf: &mut MoveBuffer, pos: &Position, ttm: Move, threshold: i32, cph: *const CapturePieceToHistory) -> Self {
        let valid = ttm.is_some() && pos.capture_stage(ttm) && pos.pseudo_legal(ttm);
        MovePicker {
            pos,
            main_history: std::ptr::null(),
            low_ply_history: std::ptr::null(),
            capture_history: cph,
            continuation_history: [std::ptr::null(); 6],
            shared: std::ptr::null(),
            tt_move: ttm,
            cur: 0,
            end_cur: 0,
            end_bad_captures: 0,
            end_captures: 0,
            end_generated: 0,
            stage: PROBCUT_TT + !valid as u8,
            threshold,
            depth: 0,
            ply: 0,
            skip_quiets: false,
            moves: buf.as_mut_ptr() as *mut ExtMove,
        }
    }

    #[inline(always)]
    fn at(&self, i: usize) -> ExtMove {
        unsafe { *self.moves.add(i) }
    }
    #[inline(always)]
    fn slice_mut(&mut self, a: usize, b: usize) -> &mut [ExtMove] {
        unsafe { std::slice::from_raw_parts_mut(self.moves.add(a), b - a) }
    }
    #[inline(always)]
    fn pos(&self) -> &Position {
        unsafe { &*self.pos }
    }

    fn score<const T: u8>(&mut self, ml: &MoveList) -> usize {
        let pos = unsafe { &*self.pos };
        let us = pos.side_to_move();
        let them = flip_color(us);

        let mut threat_by_lesser = [0u64; KING + 1];
        if T == QUIETS {
            threat_by_lesser[KNIGHT] = pos.attacks_by(PAWN, them);
            threat_by_lesser[BISHOP] = threat_by_lesser[KNIGHT];
            threat_by_lesser[ROOK] = pos.attacks_by(KNIGHT, them) | pos.attacks_by(BISHOP, them) | threat_by_lesser[KNIGHT];
            threat_by_lesser[QUEEN] = pos.attacks_by(ROOK, them) | threat_by_lesser[ROOK];
        }

        let mut it = self.cur;
        for &mv in ml.as_slice() {
            let from = mv.from_sq();
            let to = mv.to_sq();
            let pc = pos.moved_piece(mv);
            let pt = type_of(pc);
            let captured = pos.piece_on(to);
            let value;
            unsafe {
                if T == CAPTURES {
                    value = (*self.capture_history)[pc][to][type_of(captured)] as i32 + 7 * PIECE_VALUE[captured];
                } else if T == QUIETS {
                    let ch = &self.continuation_history;
                    let mut v = 2 * (*self.main_history)[us][mv.raw() as usize] as i32;
                    v += 2 * get(&(*self.shared).pawn_entry(pos)[pc][to]);
                    v += get(&(*ch[0])[pc][to]);
                    v += get(&(*ch[1])[pc][to]);
                    v += get(&(*ch[2])[pc][to]);
                    v += get(&(*ch[3])[pc][to]);
                    v += get(&(*ch[5])[pc][to]);

                    // bonus for checks
                    v += ((pos.check_squares(pt) & square_bb(to) != 0) && pos.see_ge(mv, -75)) as i32 * 16384;

                    // penalty for moving to a square threatened by a lesser piece
                    // or bonus for escaping an attack by a lesser piece.
                    let t = 20 * ((threat_by_lesser[pt] & square_bb(from) != 0) as i32 - (threat_by_lesser[pt] & square_bb(to) != 0) as i32);
                    v += PIECE_VALUE[pt] * t;

                    if (self.ply as usize) < LOW_PLY_HISTORY_SIZE {
                        v += 8 * (*self.low_ply_history)[self.ply as usize][mv.raw() as usize] as i32 / (1 + self.ply);
                    }
                    value = v;
                } else {
                    // EVASIONS
                    if pos.capture_stage(mv) {
                        value = PIECE_VALUE[captured] + (1 << 28);
                    } else {
                        value = (*self.main_history)[us][mv.raw() as usize] as i32 + get(&(*self.continuation_history[0])[pc][to]);
                    }
                }
            }
            unsafe { *self.moves.add(it) = ExtMove { mv, value } };
            it += 1;
        }
        it
    }

    #[inline(always)]
    fn select<F: FnMut(&mut Self) -> bool>(&mut self, mut filter: F) -> Move {
        while self.cur < self.end_cur {
            if self.at(self.cur).mv != self.tt_move && filter(self) {
                let m = self.at(self.cur).mv;
                self.cur += 1;
                return m;
            }
            self.cur += 1;
        }
        Move::NONE
    }

    pub fn skip_quiet_moves(&mut self) {
        self.skip_quiets = true;
    }

    /// Emits a new pseudo-legal move on every call until none remain.
    pub fn next_move(&mut self) -> Move {
        let t = crate::prof::prof_start!();
        let m = self.next_move_impl();
        crate::prof::prof_end!(3, t);
        m
    }

    fn next_move_impl(&mut self) -> Move {
        const GOOD_QUIET_THRESHOLD: i32 = -14000;
        loop {
            match self.stage {
                MAIN_TT | EVASION_TT | QSEARCH_TT | PROBCUT_TT => {
                    self.stage += 1;
                    return self.tt_move;
                }
                CAPTURE_INIT | PROBCUT_INIT | QCAPTURE_INIT => {
                    let mut ml = MoveList::empty();
                    generate::<CAPTURES>(self.pos(), &mut ml);
                    self.cur = 0;
                    self.end_bad_captures = 0;
                    let end = self.score::<CAPTURES>(&ml);
                    self.end_cur = end;
                    self.end_captures = end;
                    partial_insertion_sort(self.slice_mut(0, end), i32::MIN);
                    self.stage += 1;
                }
                GOOD_CAPTURE => {
                    let m = self.select(|s| {
                        let cur = s.at(s.cur);
                        if s.pos().see_ge(cur.mv, -cur.value / 18) {
                            return true;
                        }
                        unsafe { std::ptr::swap(s.moves.add(s.end_bad_captures), s.moves.add(s.cur)) };
                        s.end_bad_captures += 1;
                        false
                    });
                    if m != Move::NONE {
                        return m;
                    }
                    self.stage += 1;
                }
                QUIET_INIT => {
                    if !self.skip_quiets {
                        let mut ml = MoveList::empty();
                        generate::<QUIETS>(self.pos(), &mut ml);
                        let end = self.score::<QUIETS>(&ml);
                        self.end_cur = end;
                        self.end_generated = end;
                        let lim = -3560 * self.depth;
                        let cur = self.cur;
                        partial_insertion_sort(self.slice_mut(cur, end), lim);
                    }
                    self.stage += 1;
                }
                GOOD_QUIET => {
                    if !self.skip_quiets {
                        let m = self.select(|s| s.at(s.cur).value > GOOD_QUIET_THRESHOLD);
                        if m != Move::NONE {
                            return m;
                        }
                    }
                    // Prepare the pointers to loop over the bad captures
                    self.cur = 0;
                    self.end_cur = self.end_bad_captures;
                    self.stage += 1;
                }
                BAD_CAPTURE => {
                    let m = self.select(|_| true);
                    if m != Move::NONE {
                        return m;
                    }
                    // Prepare the pointers to loop over quiets again
                    self.cur = self.end_captures;
                    self.end_cur = self.end_generated;
                    self.stage += 1;
                }
                BAD_QUIET => {
                    if !self.skip_quiets {
                        return self.select(|s| s.at(s.cur).value <= GOOD_QUIET_THRESHOLD);
                    }
                    return Move::NONE;
                }
                EVASION_INIT => {
                    let mut ml = MoveList::empty();
                    generate::<EVASIONS>(self.pos(), &mut ml);
                    self.cur = 0;
                    let end = self.score::<EVASIONS>(&ml);
                    self.end_cur = end;
                    self.end_generated = end;
                    partial_insertion_sort(self.slice_mut(0, end), i32::MIN);
                    self.stage += 1;
                }
                EVASION | QCAPTURE => return self.select(|_| true),
                PROBCUT => {
                    let th = self.threshold;
                    return self.select(|s| s.pos().see_ge(s.at(s.cur).mv, th));
                }
                _ => unreachable!(),
            }
        }
    }
}
