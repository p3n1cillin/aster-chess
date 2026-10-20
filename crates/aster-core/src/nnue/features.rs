// Aster core. Original attribution and source mapping: features.rs.license.
// SPDX-License-Identifier: GPL-3.0-or-later
// Modified 2026-10-19: source naming and notice layout; K32Q2 king/queen buckets.

use crate::bitboard::*;
use crate::position::Position;
use crate::types::*;
use std::sync::OnceLock;

// ---------------------------------------------------------------------------
// King-bucketed piece-square features: 32 own-king buckets, each split by
// whether the opponent still has a queen.
// ---------------------------------------------------------------------------

pub const PSQ_DIMENSIONS: usize = 64 * 11 * 64; // 45056
pub const PSQ_HASH: u32 = 0x32b5e284;

const PS_W_PAWN: u16 = 0;
const PS_B_PAWN: u16 = 64;
const PS_W_KNIGHT: u16 = 2 * 64;
const PS_B_KNIGHT: u16 = 3 * 64;
const PS_W_BISHOP: u16 = 4 * 64;
const PS_B_BISHOP: u16 = 5 * 64;
const PS_W_ROOK: u16 = 6 * 64;
const PS_B_ROOK: u16 = 7 * 64;
const PS_W_QUEEN: u16 = 8 * 64;
const PS_B_QUEEN: u16 = 9 * 64;
const PS_KING: u16 = 10 * 64;
const PS_NB: u32 = 11 * 64;

static PIECE_SQUARE_INDEX: [[u16; PIECE_NB]; COLOR_NB] = [
    [
        0,
        PS_W_PAWN,
        PS_W_KNIGHT,
        PS_W_BISHOP,
        PS_W_ROOK,
        PS_W_QUEEN,
        PS_KING,
        0,
        0,
        PS_B_PAWN,
        PS_B_KNIGHT,
        PS_B_BISHOP,
        PS_B_ROOK,
        PS_B_QUEEN,
        PS_KING,
        0,
    ],
    [
        0,
        PS_B_PAWN,
        PS_B_KNIGHT,
        PS_B_BISHOP,
        PS_B_ROOK,
        PS_B_QUEEN,
        PS_KING,
        0,
        0,
        PS_W_PAWN,
        PS_W_KNIGHT,
        PS_W_BISHOP,
        PS_W_ROOK,
        PS_W_QUEEN,
        PS_KING,
        0,
    ],
];

static KING_BUCKETS: [u32; 64] = {
    const B: [u32; 64] = [
        28, 29, 30, 31, 31, 30, 29, 28, //
        24, 25, 26, 27, 27, 26, 25, 24, //
        20, 21, 22, 23, 23, 22, 21, 20, //
        16, 17, 18, 19, 19, 18, 17, 16, //
        12, 13, 14, 15, 15, 14, 13, 12, //
        8, 9, 10, 11, 11, 10, 9, 8, //
        4, 5, 6, 7, 7, 6, 5, 4, //
        0, 1, 2, 3, 3, 2, 1, 0,
    ];
    let mut r = [0u32; 64];
    let mut i = 0;
    while i < 64 {
        r[i] = B[i] * 2 * PS_NB;
        i += 1;
    }
    r
};

// Orient a square according to perspective (king always on files e..h)
static HALFKA_ORIENT: [u32; 64] = {
    let mut r = [0u32; 64];
    let mut i = 0;
    while i < 64 {
        r[i] = if i % 8 < 4 {
            SQ_H1 as u32
        } else {
            SQ_A1 as u32
        };
        i += 1;
    }
    r
};

pub type PsqIndexList = ValueList<u16, 32>;

/// Per (queen half, perspective, king square): the offset added to the
/// oriented square for each piece. Offsets are multiples of 64, so adding the
/// orientation (< 64) to them commutes with XOR-ing it into the square.
struct PsqOffsets([[[[u16; PIECE_NB]; 64]; COLOR_NB]; 2]);

static PSQ_OFFSETS: PsqOffsets = {
    let mut t = [[[[0u16; PIECE_NB]; 64]; COLOR_NB]; 2];
    let mut q = 0;
    while q < 2 {
        let mut c = 0;
        while c < COLOR_NB {
            let mut k = 0;
            while k < 64 {
                let flip = 56 * c as u32;
                let orient = HALFKA_ORIENT[k] ^ flip;
                let mut pc = 0;
                while pc < PIECE_NB {
                    t[q][c][k][pc] = (PIECE_SQUARE_INDEX[c][pc] as u32
                        + KING_BUCKETS[k ^ flip as usize]
                        + q as u32 * PS_NB
                        + orient) as u16;
                    pc += 1;
                }
                k += 1;
            }
            c += 1;
        }
        q += 1;
    }
    PsqOffsets(t)
};

#[inline(always)]
pub fn psq_make_index(
    perspective: Color,
    s: Square,
    pc: Piece,
    ksq: Square,
    opponent_has_queen: bool,
) -> u16 {
    debug_assert!(perspective < COLOR_NB && ksq < 64 && pc < PIECE_NB);
    let off = unsafe {
        *PSQ_OFFSETS
            .0
            .get_unchecked(opponent_has_queen as usize)
            .get_unchecked(perspective)
            .get_unchecked(ksq)
            .get_unchecked(pc)
    };
    s as u16 ^ off
}

#[inline(always)]
pub fn psq_append_changed_indices(
    perspective: Color,
    ksq: Square,
    diff: &DirtyPiece,
    opponent_has_queen: bool,
    removed: &mut PsqIndexList,
    added: &mut PsqIndexList,
) {
    let q = opponent_has_queen;
    removed.push(psq_make_index(perspective, diff.from, diff.pc, ksq, q));
    if diff.to != SQ_NONE {
        added.push(psq_make_index(perspective, diff.to, diff.pc, ksq, q));
    }
    if diff.remove_sq != SQ_NONE {
        removed.push(psq_make_index(
            perspective,
            diff.remove_sq,
            diff.remove_pc,
            ksq,
            q,
        ));
    }
    if diff.add_sq != SQ_NONE {
        added.push(psq_make_index(
            perspective,
            diff.add_sq,
            diff.add_pc,
            ksq,
            q,
        ));
    }
}

/// A king move, or the opponent's queen appearing or disappearing (which
/// switches the feature half), requires a full refresh.
#[inline(always)]
pub fn psq_requires_refresh(diff: &DirtyPiece, perspective: Color) -> bool {
    if diff.pc == make_piece(perspective, KING) {
        return true;
    }
    let their_queen = make_piece(flip_color(perspective), QUEEN);
    (diff.remove_sq != SQ_NONE && diff.remove_pc == their_queen)
        || (diff.add_sq != SQ_NONE && diff.add_pc == their_queen)
}

// ---------------------------------------------------------------------------
// FullThreats
// ---------------------------------------------------------------------------

pub const THREAT_DIMENSIONS: u32 = 59808;
pub const THREAT_HASH: u32 = 0x2e6b9d04;

static NUM_VALID_TARGETS: [u32; PIECE_NB] = [0, 4, 10, 8, 8, 10, 0, 0, 0, 4, 10, 8, 8, 10, 0, 0];

static THREAT_ORIENT: [u8; 64] = {
    let mut r = [0u8; 64];
    let mut i = 0;
    while i < 64 {
        r[i] = if i % 8 < 4 { SQ_A1 as u8 } else { SQ_H1 as u8 };
        i += 1;
    }
    r
};

static THREAT_MAP: [[i32; 6]; 6] = [
    [-1, 0, -1, 1, -1, -1],
    [0, 1, 2, 3, 4, -1],
    [0, 1, 2, 3, -1, -1],
    [0, 1, 2, 3, -1, -1],
    [0, 1, 2, 3, 4, -1],
    [-1, -1, -1, -1, -1, -1],
];

const ALL_PIECES_LIST: [Piece; 12] = [
    W_PAWN, W_KNIGHT, W_BISHOP, W_ROOK, W_QUEEN, W_KING, B_PAWN, B_KNIGHT, B_BISHOP, B_ROOK,
    B_QUEEN, B_KING,
];

pub type ThreatIndexList = ValueList<u16, 256>;

/// A threat feature index is lut1[attacker * 16 + attacked][from < to] +
/// lut2[attacker type][from][to], all on oriented squares and pieces. lut2
/// folds the per-square offsets of each attacker into the target rank.
struct ThreatLuts {
    // [attacker * PIECE_NB + attacked][from < to]
    lut1: [[u32; 2]; PIECE_NB * PIECE_NB],
    // [attacker type][from][to]
    lut2: Box<[[[u16; 64]; 64]; PIECE_TYPE_NB]>,
}

static LUTS: OnceLock<ThreatLuts> = OnceLock::new();

#[inline(always)]
fn luts() -> &'static ThreatLuts {
    // SAFETY: set by init() before any evaluation.
    unsafe { &*LUTS_PTR.load(std::sync::atomic::Ordering::Relaxed) }
}

static LUTS_PTR: std::sync::atomic::AtomicPtr<ThreatLuts> =
    std::sync::atomic::AtomicPtr::new(std::ptr::null_mut());

pub fn init() {
    let l = LUTS.get_or_init(build_luts);
    LUTS_PTR.store(
        l as *const ThreatLuts as *mut ThreatLuts,
        std::sync::atomic::Ordering::Release,
    );
}

fn build_luts() -> ThreatLuts {
    // lut2: offset of the attacker's square plus the rank of `to` among its
    // attacks. Pawn attacks go up for white (to > from) and down for black.
    let mut lut2 = Box::new([[[0u16; 64]; 64]; PIECE_TYPE_NB]);
    for pt in PAWN..=KING {
        let mut offset = 0u32;
        for from in 0..64 {
            for to in 0..64 {
                let attacks = if pt != PAWN {
                    PSEUDO_ATTACKS[pt][from]
                } else if to < from {
                    PSEUDO_ATTACKS[BLACK][from]
                } else {
                    PSEUDO_ATTACKS[WHITE][from]
                };
                lut2[pt][from][to] = (offset + (((1u64 << to) - 1) & attacks).count_ones()) as u16;
            }
            if pt != PAWN {
                offset += PSEUDO_ATTACKS[pt][from].count_ones();
            } else if (SQ_A2..=SQ_H7).contains(&from) {
                offset += PSEUDO_ATTACKS[WHITE][from].count_ones();
            }
        }
    }

    // Per-attacker feature block sizes and starts
    let mut helper = [(0u32, 0u32); PIECE_NB]; // (cumulativePieceOffset, cumulativeOffset)
    let mut cumulative_offset = 0u32;
    for pc in ALL_PIECES_LIST {
        let mut cumulative_piece_offset = 0u32;
        for from in 0..64 {
            if type_of(pc) != PAWN {
                cumulative_piece_offset += PSEUDO_ATTACKS[type_of(pc)][from].count_ones();
            } else if (SQ_A2..=SQ_H7).contains(&from) {
                let attacks = if pc < 8 {
                    PSEUDO_ATTACKS[WHITE][from]
                } else {
                    PSEUDO_ATTACKS[BLACK][from]
                };
                cumulative_piece_offset += attacks.count_ones();
            }
        }
        helper[pc] = (cumulative_piece_offset, cumulative_offset);
        cumulative_offset += NUM_VALID_TARGETS[pc] * cumulative_piece_offset;
    }

    // init_index_luts
    let mut lut1 = [[0u32; 2]; PIECE_NB * PIECE_NB];
    for attacker in ALL_PIECES_LIST {
        for attacked in ALL_PIECES_LIST {
            let enemy = (attacker ^ attacked) == 8;
            let at = type_of(attacker);
            let dt = type_of(attacked);
            let map = THREAT_MAP[at - 1][dt - 1];
            let semi_excluded = at == dt && (enemy || at != PAWN);
            let feature = (helper[attacker].1 as i64
                + (color_of(attacked) as i64 * (NUM_VALID_TARGETS[attacker] / 2) as i64
                    + map as i64)
                    * helper[attacker].0 as i64) as u32;
            let excluded = map < 0;
            lut1[attacker * PIECE_NB + attacked][0] =
                if excluded { THREAT_DIMENSIONS } else { feature };
            lut1[attacker * PIECE_NB + attacked][1] = if excluded || semi_excluded {
                THREAT_DIMENSIONS
            } else {
                feature
            };
        }
    }

    ThreatLuts { lut1, lut2 }
}

#[inline(always)]
pub fn threat_make_index(
    perspective: Color,
    attacker: Piece,
    from: Square,
    to: Square,
    attacked: Piece,
    ksq: Square,
) -> u32 {
    let orientation = THREAT_ORIENT[ksq] as usize ^ (56 * perspective);
    let from_o = from ^ orientation;
    let to_o = to ^ orientation;
    let swap = 8 * perspective;
    let pair = (attacker ^ swap) * PIECE_NB + (attacked ^ swap);
    let l = luts();
    unsafe {
        *l.lut1
            .get_unchecked(pair)
            .get_unchecked((from_o < to_o) as usize)
            + *l.lut2
                .get_unchecked(type_of(attacker))
                .get_unchecked(from_o)
                .get_unchecked(to_o) as u32
    }
}

static WEIGHT_BASE: std::sync::atomic::AtomicPtr<i8> =
    std::sync::atomic::AtomicPtr::new(std::ptr::null_mut());

/// Registers the threat/pawn-pair weight table so new indices can be prefetched.
pub fn set_prefetch_base(p: *const i8) {
    WEIGHT_BASE.store(p as *mut i8, std::sync::atomic::Ordering::Relaxed);
}

#[inline(always)]
fn weight_base() -> *const i8 {
    WEIGHT_BASE.load(std::sync::atomic::Ordering::Relaxed)
}

/// Starts loading a weight row; `base` comes from weight_base() (null: none).
#[inline(always)]
fn prefetch_row_at(base: *const i8, index: u32) {
    if !base.is_null() {
        super::kernels::prefetch(base.wrapping_add(index as usize * 1024));
    }
}

#[inline(always)]
fn prefetch_row(index: u32) {
    prefetch_row_at(weight_base(), index);
}

#[inline(always)]
fn push_if_lt(list: &mut ThreatIndexList, index: u32) {
    // Branchless: store, then keep it only when it is a real feature.
    list.push_if(index as u16, index < THREAT_DIMENSIONS);
}

pub fn threat_append_active_indices(
    perspective: Color,
    pos: &Position,
    active: &mut ThreatIndexList,
) {
    let ksq = pos.king_square(perspective);
    let occupied = pos.pieces();
    let pawn_targets = pos.pieces_tt(KNIGHT, ROOK);
    let minor_slider_targets = pos.pieces_tt(PAWN, KNIGHT) | pos.pieces_tt(BISHOP, ROOK);
    let queen_targets = minor_slider_targets | pos.pieces_t(QUEEN);

    let mut process_pawn = |c: Color, dir: Direction| {
        let c_pawns = pos.pieces_ct(c, PAWN);
        let mut attacks = shift(c_pawns, dir) & pawn_targets;
        while attacks != 0 {
            let to = pop_lsb(&mut attacks);
            let from = sq_add(to, -dir);
            let attacked = pos.piece_on(to);
            let attacker = make_piece(c, PAWN);
            push_if_lt(
                active,
                threat_make_index(perspective, attacker, from, to, attacked, ksq),
            );
        }
    };
    process_pawn(WHITE, NORTH_EAST);
    process_pawn(WHITE, NORTH_WEST);
    process_pawn(BLACK, SOUTH_WEST);
    process_pawn(BLACK, SOUTH_EAST);

    for c in [WHITE, BLACK] {
        for pt in KNIGHT..KING {
            let attacker = make_piece(c, pt);
            let mut bb = pos.pieces_ct(c, pt);
            let targets = if pt == KNIGHT || pt == QUEEN {
                queen_targets
            } else {
                minor_slider_targets
            };
            while bb != 0 {
                let from = pop_lsb(&mut bb);
                let mut attacks = attacks_bb(pt, from, occupied) & targets;
                while attacks != 0 {
                    let to = pop_lsb(&mut attacks);
                    let attacked = pos.piece_on(to);
                    push_if_lt(
                        active,
                        threat_make_index(perspective, attacker, from, to, attacked, ksq),
                    );
                }
            }
        }
    }
}

#[inline]
pub fn threat_append_changed_indices(
    perspective: Color,
    ksq: Square,
    diff: &DirtyThreatList,
    removed: &mut ThreatIndexList,
    added: &mut ThreatIndexList,
) {
    // Decode the packed threat directly: byte 0 attacker square, byte 1
    // target square, byte 2 attacker << 4 | target piece, bit 31 added.
    let orient = THREAT_ORIENT[ksq] as u32 ^ (56 * perspective as u32);
    let pair_swap = 0x88 * perspective as u32;
    let l = luts();
    let base = weight_base();
    for &d in diff.as_slice() {
        let raw = d.0;
        let from = (raw & 0xff) ^ orient;
        let to = ((raw >> 8) & 0xff) ^ orient;
        let pair = (raw >> 16) & 0xff;
        let index = unsafe {
            *l.lut1
                .get_unchecked((pair ^ pair_swap) as usize)
                .get_unchecked((from < to) as usize)
                + *l.lut2
                    .get_unchecked(((pair >> 4) & 7) as usize)
                    .get_unchecked(from as usize)
                    .get_unchecked(to as usize) as u32
        };
        prefetch_row_at(base, index);
        if raw >> 31 != 0 {
            push_if_lt(added, index);
        } else {
            push_if_lt(removed, index);
        }
    }
}

/// Both perspectives in one pass over the changed threats (white, then black
/// lists, in the same order as two single-perspective passes).
pub fn threat_append_changed_indices_both(
    kings: [Square; COLOR_NB],
    diff: &DirtyThreatList,
    removed: &mut [ThreatIndexList; COLOR_NB],
    added: &mut [ThreatIndexList; COLOR_NB],
) {
    let w_orient = THREAT_ORIENT[kings[WHITE]] as u32;
    let b_orient = THREAT_ORIENT[kings[BLACK]] as u32 ^ 56;
    let l = luts();
    let base = weight_base();
    let index = |pair: u32, from: u32, to: u32| unsafe {
        *l.lut1
            .get_unchecked(pair as usize)
            .get_unchecked((from < to) as usize)
            + *l.lut2
                .get_unchecked(((pair >> 4) & 7) as usize)
                .get_unchecked(from as usize)
                .get_unchecked(to as usize) as u32
    };
    for &d in diff.as_slice() {
        let raw = d.0;
        let (from, to, pair) = (raw & 0xff, (raw >> 8) & 0xff, (raw >> 16) & 0xff);
        let wi = index(pair, from ^ w_orient, to ^ w_orient);
        let bi = index(pair ^ 0x88, from ^ b_orient, to ^ b_orient);
        prefetch_row_at(base, wi);
        prefetch_row_at(base, bi);
        let lists = if raw >> 31 != 0 {
            &mut *added
        } else {
            &mut *removed
        };
        push_if_lt(&mut lists[WHITE], wi);
        push_if_lt(&mut lists[BLACK], bi);
    }
}

// ---------------------------------------------------------------------------
// PP_3Wide (pawn pairs); indices are concatenated after the threat features
// ---------------------------------------------------------------------------

pub const PP_HASH: u32 = 0x86f2b1dd;
pub const PP_PAWN_IDS: u32 = 2 * 48;
pub const PP_DIMENSIONS: u32 = PP_PAWN_IDS * (PP_PAWN_IDS - 1) / 2; // 4560
pub const PP_INDEX_BASE: u32 = THREAT_DIMENSIONS;

#[inline(always)]
fn make_pawn_id(color: Color, sq: usize) -> u32 {
    (48 * color + sq - SQ_A2) as u32
}

#[inline(always)]
pub fn pp_make_index(
    perspective: Color,
    color: Color,
    from: Square,
    to: Square,
    paired_color: Color,
    ksq: Square,
) -> u16 {
    let orientation = THREAT_ORIENT[ksq] as usize ^ (56 * perspective);
    let from_o = from ^ orientation;
    let to_o = to ^ orientation;
    let id_a = make_pawn_id(color ^ perspective, from_o);
    let id_b = make_pawn_id(paired_color ^ perspective, to_o);
    let hi = id_a.max(id_b);
    let lo = id_a.min(id_b);
    (hi * (hi - 1) / 2 + lo + PP_INDEX_BASE) as u16
}

pub fn pp_append_active_indices(perspective: Color, pos: &Position, active: &mut ThreatIndexList) {
    let ksq = pos.king_square(perspective);
    let white = pos.pieces_ct(WHITE, PAWN);
    let black = pos.pieces_ct(BLACK, PAWN);

    let mut bb = white;
    while bb != 0 {
        let from = pop_lsb(&mut bb);
        let band = pawn_pair_bb(from);
        let mut ww = band & bb;
        while ww != 0 {
            active.push(pp_make_index(
                perspective,
                WHITE,
                from,
                pop_lsb(&mut ww),
                WHITE,
                ksq,
            ));
        }
        let mut wb = band & black;
        while wb != 0 {
            active.push(pp_make_index(
                perspective,
                WHITE,
                from,
                pop_lsb(&mut wb),
                BLACK,
                ksq,
            ));
        }
    }
    let mut bb = black;
    while bb != 0 {
        let from = pop_lsb(&mut bb);
        let band = pawn_pair_bb(from);
        let mut bk = band & bb;
        while bk != 0 {
            active.push(pp_make_index(
                perspective,
                BLACK,
                from,
                pop_lsb(&mut bk),
                BLACK,
                ksq,
            ));
        }
    }
}

pub fn pp_append_changed_indices(
    perspective: Color,
    ksq: Square,
    diff: &DirtyPawnPairs,
    removed: &mut ThreatIndexList,
    added: &mut ThreatIndexList,
) {
    let wb = diff.before[WHITE];
    let bb_ = diff.before[BLACK];
    let wa = diff.after[WHITE];
    let ba = diff.after[BLACK];
    if wb == wa && bb_ == ba {
        return;
    }
    let generate = |updated_w: Bitboard,
                    updated_b: Bitboard,
                    pawns_w: Bitboard,
                    pawns_b: Bitboard,
                    out: &mut ThreatIndexList| {
        let unchanged = (pawns_w | pawns_b) & !(updated_w | updated_b);
        let mut u = updated_w | updated_b;
        while u != 0 {
            let a = pop_lsb(&mut u);
            let mask = pawn_pair_bb(a) & (unchanged | u);
            let a_col = if pawns_b & square_bb(a) != 0 {
                BLACK
            } else {
                WHITE
            };
            let mut pb = pawns_b & mask;
            while pb != 0 {
                let i = pp_make_index(perspective, a_col, a, pop_lsb(&mut pb), BLACK, ksq);
                prefetch_row(i as u32);
                out.push(i);
            }
            let mut pw = pawns_w & mask;
            while pw != 0 {
                let i = pp_make_index(perspective, a_col, a, pop_lsb(&mut pw), WHITE, ksq);
                prefetch_row(i as u32);
                out.push(i);
            }
        }
    };
    generate(wa & !wb, ba & !bb_, wa, ba, added);
    generate(wb & !wa, bb_ & !ba, wb, bb_, removed);
}
