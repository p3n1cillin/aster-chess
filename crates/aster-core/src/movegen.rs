// Rust port of Stockfish 19 `movegen.h/.cpp`.
// Copyright (C) 2004-2026 The Stockfish developers (see AUTHORS file)
// Licensed under the GNU General Public License v3 or later.
//
// Move order must match the C++ generator exactly: move ordering ties are
// broken by generation order, and the bench signature depends on it.

use crate::bitboard::*;
use crate::position::Position;
use crate::types::*;

#[derive(Copy, Clone, PartialEq, Eq, Debug)]
pub enum GenType {
    Captures,
    Quiets,
    Evasions,
    NonEvasions,
    Legal,
}

pub const CAPTURES: u8 = 0;
pub const QUIETS: u8 = 1;
pub const EVASIONS: u8 = 2;
pub const NON_EVASIONS: u8 = 3;

pub struct MoveList {
    // 32 slack slots allow unmasked 32-move vector stores near the end.
    moves: [std::mem::MaybeUninit<Move>; MAX_MOVES + 32],
    len: usize,
}

impl MoveList {
    #[inline]
    pub fn empty() -> Self {
        MoveList {
            moves: [const { std::mem::MaybeUninit::uninit() }; MAX_MOVES + 32],
            len: 0,
        }
    }
    #[inline]
    pub fn new(pos: &Position, t: GenType) -> Self {
        let mut ml = Self::empty();
        match t {
            GenType::Captures => generate::<CAPTURES>(pos, &mut ml),
            GenType::Quiets => generate::<QUIETS>(pos, &mut ml),
            GenType::Evasions => generate::<EVASIONS>(pos, &mut ml),
            GenType::NonEvasions => generate::<NON_EVASIONS>(pos, &mut ml),
            GenType::Legal => generate_legal(pos, &mut ml),
        }
        ml
    }
    #[inline(always)]
    pub fn push(&mut self, m: Move) {
        unsafe { *self.moves.get_unchecked_mut(self.len) = std::mem::MaybeUninit::new(m) };
        self.len += 1;
    }
    #[inline(always)]
    pub fn len(&self) -> usize {
        self.len
    }
    #[inline(always)]
    fn tail_ptr(&mut self) -> *mut Move {
        unsafe { self.moves.as_mut_ptr().add(self.len) as *mut Move }
    }
    #[inline(always)]
    fn advance(&mut self, n: usize) {
        self.len += n;
        debug_assert!(self.len <= MAX_MOVES);
    }
    #[inline(always)]
    pub fn is_empty(&self) -> bool {
        self.len == 0
    }
    #[inline(always)]
    pub fn as_slice(&self) -> &[Move] {
        unsafe { std::slice::from_raw_parts(self.moves.as_ptr() as *const Move, self.len) }
    }
    pub fn contains(&self, m: Move) -> bool {
        self.as_slice().contains(&m)
    }
}

static SPLAT_SIMD: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);

/// Enables the AVX-512 VBMI2 move writers when the CPU supports them.
pub fn init() {
    #[cfg(target_arch = "x86_64")]
    {
        let ok = is_x86_feature_detected!("avx512f")
            && is_x86_feature_detected!("avx512bw")
            && is_x86_feature_detected!("avx512vbmi2");
        let forced = matches!(
            std::env::var("ASTER_SIMD").as_deref(),
            Ok("scalar") | Ok("avx2")
        );
        SPLAT_SIMD.store(ok && !forced, std::sync::atomic::Ordering::Relaxed);
    }
}

#[cfg(target_arch = "x86_64")]
mod splat512 {
    use super::MoveList;
    use crate::types::*;
    use std::arch::x86_64::*;

    // Moves for all set squares of `to_bb` in ascending order (same order as pop_lsb).
    #[target_feature(enable = "avx512f,avx512bw,avx512vbmi2")]
    pub unsafe fn splat_moves(ml: &mut MoveList, from: Square, to_bb: u64) {
        unsafe {
            let all = _mm512_set_epi8(
                63, 62, 61, 60, 59, 58, 57, 56, 55, 54, 53, 52, 51, 50, 49, 48, 47, 46, 45, 44, 43,
                42, 41, 40, 39, 38, 37, 36, 35, 34, 33, 32, 31, 30, 29, 28, 27, 26, 25, 24, 23, 22,
                21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0,
            );
            let to = _mm512_cvtepi8_epi16(_mm512_castsi512_si256(_mm512_maskz_compress_epi8(
                to_bb, all,
            )));
            let mv = _mm512_or_si512(_mm512_set1_epi16(((from as u16) << 6) as i16), to);
            _mm512_storeu_si512(ml.tail_ptr() as *mut _, mv);
            ml.advance(to_bb.count_ones() as usize);
        }
    }

    #[target_feature(enable = "avx512f,avx512bw,avx512vbmi2")]
    pub unsafe fn splat_pawn_moves(ml: &mut MoveList, offset: Direction, to_bb: u64) {
        unsafe {
            let all = _mm512_set_epi8(
                63, 62, 61, 60, 59, 58, 57, 56, 55, 54, 53, 52, 51, 50, 49, 48, 47, 46, 45, 44, 43,
                42, 41, 40, 39, 38, 37, 36, 35, 34, 33, 32, 31, 30, 29, 28, 27, 26, 25, 24, 23, 22,
                21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0,
            );
            let to = _mm512_cvtepi8_epi16(_mm512_castsi512_si256(_mm512_maskz_compress_epi8(
                to_bb, all,
            )));
            let from = _mm512_sub_epi16(to, _mm512_set1_epi16(offset as i16));
            let mv = _mm512_or_si512(_mm512_slli_epi16::<6>(from), to);
            _mm512_storeu_si512(ml.tail_ptr() as *mut _, mv);
            ml.advance(to_bb.count_ones() as usize);
        }
    }
}

#[inline(always)]
fn splat_pawn_moves(ml: &mut MoveList, offset: Direction, mut to_bb: Bitboard) {
    #[cfg(target_arch = "x86_64")]
    if SPLAT_SIMD.load(std::sync::atomic::Ordering::Relaxed) {
        return unsafe { splat512::splat_pawn_moves(ml, offset, to_bb) };
    }
    while to_bb != 0 {
        let to = pop_lsb(&mut to_bb);
        ml.push(Move::new(sq_add(to, -offset), to));
    }
}

#[inline(always)]
fn splat_moves(ml: &mut MoveList, from: Square, mut to_bb: Bitboard) {
    #[cfg(target_arch = "x86_64")]
    if SPLAT_SIMD.load(std::sync::atomic::Ordering::Relaxed) {
        return unsafe { splat512::splat_moves(ml, from, to_bb) };
    }
    while to_bb != 0 {
        ml.push(Move::new(from, pop_lsb(&mut to_bb)));
    }
}

#[inline(always)]
fn make_promotions<const T: u8>(ml: &mut MoveList, d: Direction, enemy: bool, to: Square) {
    let all = T == EVASIONS || T == NON_EVASIONS;
    let from = sq_add(to, -d);
    if T == CAPTURES || all {
        ml.push(Move::make(PROMOTION, from, to, QUEEN));
    }
    if (T == CAPTURES && enemy) || (T == QUIETS && !enemy) || all {
        ml.push(Move::make(PROMOTION, from, to, ROOK));
        ml.push(Move::make(PROMOTION, from, to, BISHOP));
        ml.push(Move::make(PROMOTION, from, to, KNIGHT));
    }
}

#[inline(always)]
fn generate_pawn_moves<const T: u8>(
    pos: &Position,
    ml: &mut MoveList,
    us: Color,
    target: Bitboard,
) {
    let them = flip_color(us);
    let t_rank7 = if us == WHITE { RANK_7_BB } else { RANK_2_BB };
    let t_rank3 = if us == WHITE { RANK_3_BB } else { RANK_6_BB };
    let up = pawn_push(us);
    let up_right = if us == WHITE { NORTH_EAST } else { SOUTH_WEST };
    let up_left = if us == WHITE { NORTH_WEST } else { SOUTH_EAST };

    let empty_squares = !pos.pieces();
    let enemies = if T == EVASIONS {
        pos.checkers()
    } else {
        pos.pieces_c(them)
    };

    let pawns_on7 = pos.pieces_ct(us, PAWN) & t_rank7;
    let pawns_not_on7 = pos.pieces_ct(us, PAWN) & !t_rank7;

    if T != CAPTURES {
        let mut b1 = shift(pawns_not_on7, up) & empty_squares;
        let mut b2 = shift(b1 & t_rank3, up) & empty_squares;
        if T == EVASIONS {
            b1 &= target;
            b2 &= target;
        }
        splat_pawn_moves(ml, up, b1);
        splat_pawn_moves(ml, up + up, b2);
    }

    if pawns_on7 != 0 {
        let mut b1 = shift(pawns_on7, up_right) & enemies;
        let mut b2 = shift(pawns_on7, up_left) & enemies;
        let mut b3 = shift(pawns_on7, up) & empty_squares;
        if T == EVASIONS {
            b3 &= target;
        }
        while b1 != 0 {
            make_promotions::<T>(ml, up_right, true, pop_lsb(&mut b1));
        }
        while b2 != 0 {
            make_promotions::<T>(ml, up_left, true, pop_lsb(&mut b2));
        }
        while b3 != 0 {
            make_promotions::<T>(ml, up, false, pop_lsb(&mut b3));
        }
    }

    if T == CAPTURES || T == EVASIONS || T == NON_EVASIONS {
        let b1 = shift(pawns_not_on7, up_right) & enemies;
        let b2 = shift(pawns_not_on7, up_left) & enemies;
        splat_pawn_moves(ml, up_right, b1);
        splat_pawn_moves(ml, up_left, b2);

        let ep = pos.ep_square();
        if ep != SQ_NONE {
            // An en passant capture cannot resolve a discovered check
            if T == EVASIONS && target & square_bb(sq_add(ep, up)) != 0 {
                return;
            }
            let mut b1 = pawns_not_on7 & pawn_attacks_from(them, ep);
            while b1 != 0 {
                ml.push(Move::make(EN_PASSANT, pop_lsb(&mut b1), ep, KNIGHT));
            }
        }
    }
}

#[inline(always)]
fn generate_moves(pos: &Position, ml: &mut MoveList, us: Color, pt: PieceType, target: Bitboard) {
    let mut bb = pos.pieces_ct(us, pt);
    while bb != 0 {
        let from = pop_lsb(&mut bb);
        let b = attacks_bb(pt, from, pos.pieces()) & target;
        splat_moves(ml, from, b);
    }
}

#[inline(always)]
fn generate_all<const T: u8>(pos: &Position, ml: &mut MoveList, us: Color) {
    let ksq = pos.king_square(us);
    let mut target = 0;

    if T != EVASIONS || !more_than_one(pos.checkers()) {
        target = match T {
            EVASIONS => between_bb(ksq, lsb(pos.checkers())),
            NON_EVASIONS => !pos.pieces_c(us),
            CAPTURES => pos.pieces_c(flip_color(us)),
            _ => !pos.pieces(),
        };
        generate_pawn_moves::<T>(pos, ml, us, target);
        generate_moves(pos, ml, us, KNIGHT, target);
        generate_moves(pos, ml, us, BISHOP, target);
        generate_moves(pos, ml, us, ROOK, target);
        generate_moves(pos, ml, us, QUEEN, target);
    }

    let b = pa(KING, ksq)
        & if T == EVASIONS {
            !pos.pieces_c(us)
        } else {
            target
        };
    splat_moves(ml, ksq, b);

    if (T == QUIETS || T == NON_EVASIONS) && pos.can_castle(color_castling(us, ANY_CASTLING)) {
        for cr in [
            color_castling(us, KING_SIDE),
            color_castling(us, QUEEN_SIDE),
        ] {
            if !pos.castling_impeded(cr) && pos.can_castle(cr) {
                ml.push(Move::make(
                    CASTLING,
                    ksq,
                    pos.castling_rook_square(cr),
                    KNIGHT,
                ));
            }
        }
    }
}

/// Generates pseudo-legal moves of the given type, appending to `ml`.
#[inline]
pub fn generate<const T: u8>(pos: &Position, ml: &mut MoveList) {
    debug_assert!((T == EVASIONS) == (pos.checkers() != 0));
    generate_all::<T>(pos, ml, pos.side_to_move());
}

/// Generates all the legal moves in the given position.
pub fn generate_legal(pos: &Position, ml: &mut MoveList) {
    let us = pos.side_to_move();
    let pinned = pos.blockers_for_king(us) & pos.pieces_c(us);
    let ksq = pos.king_square(us);
    let start = ml.len;
    if pos.checkers() != 0 {
        generate::<EVASIONS>(pos, ml);
    } else {
        generate::<NON_EVASIONS>(pos, ml);
    }
    let mut cur = start;
    while cur != ml.len {
        let m = ml.as_slice()[cur];
        if ((pinned & square_bb(m.from_sq())) != 0
            || m.from_sq() == ksq
            || m.type_of() == EN_PASSANT)
            && !pos.legal(m)
        {
            ml.len -= 1;
            ml.moves[cur] = ml.moves[ml.len];
        } else {
            cur += 1;
        }
    }
}
