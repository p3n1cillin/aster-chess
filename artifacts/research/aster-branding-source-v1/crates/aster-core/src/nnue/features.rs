// Rust port of Stockfish 19 NNUE feature sets:
// `features/half_ka_v2_hm`, `features/full_threats`, `features/pp_3wide`.
// Copyright (C) 2004-2026 The Stockfish developers (see AUTHORS file)
// Licensed under the GNU General Public License v3 or later.

use crate::bitboard::*;
use crate::position::Position;
use crate::types::*;
use std::sync::OnceLock;

// ---------------------------------------------------------------------------
// HalfKAv2_hm
// ---------------------------------------------------------------------------

pub const PSQ_DIMENSIONS: usize = 64 * 11 * 64 / 2; // 22528
pub const PSQ_HASH: u32 = 0x7f234cb8;

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
        r[i] = B[i] * PS_NB;
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

#[inline(always)]
pub fn psq_make_index(perspective: Color, s: Square, pc: Piece, ksq: Square) -> u16 {
    let flip = 56 * perspective as u32;
    ((s as u32 ^ HALFKA_ORIENT[ksq] ^ flip)
        + PIECE_SQUARE_INDEX[perspective][pc] as u32
        + KING_BUCKETS[ksq ^ flip as usize]) as u16
}

#[inline(always)]
pub fn psq_append_changed_indices(
    perspective: Color,
    ksq: Square,
    diff: &DirtyPiece,
    removed: &mut PsqIndexList,
    added: &mut PsqIndexList,
) {
    let push = |list: &mut PsqIndexList, i: u16| list.push(i);
    push(
        removed,
        psq_make_index(perspective, diff.from, diff.pc, ksq),
    );
    if diff.to != SQ_NONE {
        push(added, psq_make_index(perspective, diff.to, diff.pc, ksq));
    }
    if diff.remove_sq != SQ_NONE {
        push(
            removed,
            psq_make_index(perspective, diff.remove_sq, diff.remove_pc, ksq),
        );
    }
    if diff.add_sq != SQ_NONE {
        push(
            added,
            psq_make_index(perspective, diff.add_sq, diff.add_pc, ksq),
        );
    }
}

#[inline(always)]
pub fn psq_requires_refresh(diff: &DirtyPiece, perspective: Color) -> bool {
    diff.pc == make_piece(perspective, KING)
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

struct ThreatLuts {
    // [attacker][attacked][from < to]
    lut1: [[[u32; 2]; PIECE_NB]; PIECE_NB],
    // [attacker][from]
    offsets: [[u32; 64]; PIECE_NB],
    // [attacker][from][to]
    lut2: Box<[[[u8; 64]; 64]; PIECE_NB]>,
}

static LUTS: OnceLock<ThreatLuts> = OnceLock::new();

#[inline(always)]
fn luts() -> &'static ThreatLuts {
    unsafe { LUTS.get().unwrap_unchecked() }
}

pub fn init() {
    LUTS.get_or_init(build_luts);
}

fn build_luts() -> ThreatLuts {
    // index_lut2: popcount of attacks below `to`
    let mut lut2 = Box::new([[[0u8; 64]; 64]; PIECE_NB]);
    for pc in ALL_PIECES_LIST {
        for from in 0..64 {
            let attacks = if type_of(pc) == PAWN {
                PSEUDO_ATTACKS[color_of(pc)][from]
            } else {
                PSEUDO_ATTACKS[type_of(pc)][from]
            };
            for to in 0..64 {
                lut2[pc][from][to] = (((1u64 << to) - 1) & attacks).count_ones() as u8;
            }
        }
    }

    // init_threat_offsets
    let mut helper = [(0u32, 0u32); PIECE_NB]; // (cumulativePieceOffset, cumulativeOffset)
    let mut offsets = [[0u32; 64]; PIECE_NB];
    let mut cumulative_offset = 0u32;
    for pc in ALL_PIECES_LIST {
        let mut cumulative_piece_offset = 0u32;
        for from in 0..64 {
            offsets[pc][from] = cumulative_piece_offset;
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
    let mut lut1 = [[[0u32; 2]; PIECE_NB]; PIECE_NB];
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
            lut1[attacker][attacked][0] = if excluded { THREAT_DIMENSIONS } else { feature };
            lut1[attacker][attacked][1] = if excluded || semi_excluded {
                THREAT_DIMENSIONS
            } else {
                feature
            };
        }
    }

    ThreatLuts {
        lut1,
        offsets,
        lut2,
    }
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
    let att_o = attacker ^ swap;
    let atd_o = attacked ^ swap;
    let l = luts();
    unsafe {
        l.lut1.get_unchecked(att_o).get_unchecked(atd_o)[(from_o < to_o) as usize]
            + *l.offsets.get_unchecked(att_o).get_unchecked(from_o)
            + *l.lut2
                .get_unchecked(att_o)
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
fn prefetch_row(index: u32) {
    let base = WEIGHT_BASE.load(std::sync::atomic::Ordering::Relaxed);
    if !base.is_null() {
        super::kernels::prefetch(base.wrapping_add(index as usize * 1024));
    }
}

#[inline(always)]
fn push_if_lt(list: &mut ThreatIndexList, index: u32) {
    // Mirrors ValueList<u16>::push_back_if_lt(index, Dimensions) (values fit in u16).
    if index < THREAT_DIMENSIONS {
        list.push(index as u16);
    }
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
    for &d in diff.as_slice() {
        let index = threat_make_index(
            perspective,
            d.pc(),
            d.pc_sq(),
            d.threatened_sq(),
            d.threatened_pc(),
            ksq,
        );
        prefetch_row(index);
        if d.add() {
            push_if_lt(added, index);
        } else {
            push_if_lt(removed, index);
        }
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
