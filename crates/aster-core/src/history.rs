// Aster core. Original attribution and source mapping: history.rs.license.
// SPDX-License-Identifier: GPL-3.0-or-later
// Modified 2026-10-19: source naming and notice layout only.

use crate::large_pages::{LargeBox, LargeSlice};
use crate::position::Position;
use crate::types::*;
use std::sync::atomic::{AtomicI16, Ordering::Relaxed};

pub const PAWN_HISTORY_BASE_SIZE: usize = 8192;
pub const UINT_16_HISTORY_SIZE: usize = 65536;
pub const CORRHIST_BASE_SIZE: usize = UINT_16_HISTORY_SIZE;
pub const CORRECTION_HISTORY_LIMIT: i32 = 1024;
pub const LOW_PLY_HISTORY_SIZE: usize = 5;

/// StatsEntry update: keeps values within [-D, D] with a gravity term.
#[inline(always)]
pub fn gravity<const D: i32>(val: i16, bonus: i32) -> i16 {
    let clamped = bonus.clamp(-D, D);
    let v = val as i32;
    (v + clamped - v * clamped.abs() / D) as i16
}

#[inline(always)]
pub fn update<const D: i32>(e: &mut i16, bonus: i32) {
    *e = gravity::<D>(*e, bonus);
}

#[inline(always)]
pub fn update_atomic<const D: i32>(e: &AtomicI16, bonus: i32) {
    let v = e.load(Relaxed);
    e.store(gravity::<D>(v, bonus), Relaxed);
}

#[inline(always)]
pub fn get(e: &AtomicI16) -> i32 {
    e.load(Relaxed) as i32
}

/// Allocates a zero-initialised value of a plain integer/atomic array type in
/// huge-page backed memory (as the upstream reference does for its histories).
pub fn boxed_zeroed<T>() -> LargeBox<T> {
    // SAFETY: only used for integer and atomic integer arrays.
    unsafe { LargeBox::zeroed() }
}

pub const BUTTERFLY_D: i32 = 7183;
pub const LOW_PLY_D: i32 = 7183;
pub const CAPTURE_D: i32 = 10692;
pub const PIECE_TO_D: i32 = 30000;
pub const PAWN_D: i32 = 8192;
pub const TT_MOVE_D: i32 = 8192;

pub type ButterflyHistory = [[i16; UINT_16_HISTORY_SIZE]; COLOR_NB];
pub type LowPlyHistory = [[i16; UINT_16_HISTORY_SIZE]; LOW_PLY_HISTORY_SIZE];
pub type CapturePieceToHistory = [[[i16; PIECE_TYPE_NB]; SQUARE_NB]; PIECE_NB];
pub type PieceToHistory = [[AtomicI16; SQUARE_NB]; PIECE_NB];
pub type ContinuationHistory = [[PieceToHistory; SQUARE_NB]; PIECE_NB];
pub type PieceToCorrectionHistory = [[i16; SQUARE_NB]; PIECE_NB];
pub type ContinuationCorrectionHistory = [[PieceToCorrectionHistory; SQUARE_NB]; PIECE_NB];

#[derive(Default)]
pub struct CorrectionBundle {
    pub pawn: AtomicI16,
    pub minor: AtomicI16,
    pub non_pawn_white: AtomicI16,
    pub non_pawn_black: AtomicI16,
}

/// Histories shared between all search threads (the upstream reference shares them per NUMA node).
pub struct SharedHistories {
    pub correction: LargeSlice<[CorrectionBundle; COLOR_NB]>,
    pub continuation: LargeBox<[[ContinuationHistory; 2]; 2]>,
    pub pawn: LargeSlice<PieceToHistory>,
    size_minus1: usize,
    pawn_size_minus1: usize,
}

impl SharedHistories {
    /// `thread_count` must be a power of two (next power of two of the thread count).
    pub fn new(thread_count: usize) -> Self {
        debug_assert!(thread_count.is_power_of_two());
        let corr_size = thread_count * CORRHIST_BASE_SIZE;
        let pawn_size = thread_count * PAWN_HISTORY_BASE_SIZE;
        // SAFETY: atomic integer arrays; every entry is set by `clear_range`.
        let correction = unsafe { LargeSlice::zeroed(corr_size) };
        let pawn = unsafe { LargeSlice::zeroed(pawn_size) };
        SharedHistories {
            correction,
            continuation: boxed_zeroed(),
            pawn,
            size_minus1: corr_size - 1,
            pawn_size_minus1: pawn_size - 1,
        }
    }

    /// Each thread clears its share of the dynamically-sized tables.
    pub fn clear_range(&self, thread_idx: usize, numa_total: usize) {
        let clear = |len: usize, f: &dyn Fn(usize)| {
            let start = thread_idx * len / numa_total;
            let end = if thread_idx + 1 == numa_total {
                len
            } else {
                (thread_idx + 1) * len / numa_total
            };
            for i in start..end {
                f(i);
            }
        };
        clear(self.correction.len(), &|i| {
            for b in &self.correction[i] {
                b.pawn.store(-5, Relaxed);
                b.minor.store(-5, Relaxed);
                b.non_pawn_white.store(-5, Relaxed);
                b.non_pawn_black.store(-5, Relaxed);
            }
        });
        clear(self.pawn.len(), &|i| {
            for row in &self.pawn[i] {
                for e in row {
                    e.store(-1338, Relaxed);
                }
            }
        });
    }

    pub fn clear_continuation(&self) {
        for in_check in 0..2 {
            for c in 0..2 {
                for to in self.continuation[in_check][c].iter() {
                    for h in to.iter() {
                        for row in h.iter() {
                            for e in row {
                                e.store(-586, Relaxed);
                            }
                        }
                    }
                }
            }
        }
    }

    #[inline(always)]
    pub fn pawn_entry(&self, pos: &Position) -> &PieceToHistory {
        unsafe {
            self.pawn
                .get_unchecked(pos.pawn_key() as usize & self.pawn_size_minus1)
        }
    }
    #[inline(always)]
    pub fn pawn_correction_entry(&self, pos: &Position) -> &[CorrectionBundle; 2] {
        unsafe {
            self.correction
                .get_unchecked(pos.pawn_key() as usize & self.size_minus1)
        }
    }
    #[inline(always)]
    pub fn minor_piece_correction_entry(&self, pos: &Position) -> &[CorrectionBundle; 2] {
        unsafe {
            self.correction
                .get_unchecked(pos.minor_piece_key() as usize & self.size_minus1)
        }
    }
    #[inline(always)]
    pub fn nonpawn_correction_entry(&self, c: Color, pos: &Position) -> &[CorrectionBundle; 2] {
        unsafe {
            self.correction
                .get_unchecked(pos.non_pawn_key(c) as usize & self.size_minus1)
        }
    }
}
