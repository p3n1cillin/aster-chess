// Rust port of Stockfish 19 `bitboard.h` and `attacks.h/.cpp`.
// Copyright (C) 2004-2026 The Stockfish developers (see AUTHORS file)
// Licensed under the GNU General Public License v3 or later.

use crate::types::*;
use std::sync::OnceLock;

pub const FILE_A_BB: Bitboard = 0x0101010101010101;
pub const FILE_H_BB: Bitboard = FILE_A_BB << 7;
pub const RANK_1_BB: Bitboard = 0xFF;
pub const RANK_2_BB: Bitboard = RANK_1_BB << 8;
pub const RANK_3_BB: Bitboard = RANK_1_BB << 16;
pub const RANK_6_BB: Bitboard = RANK_1_BB << 40;
pub const RANK_7_BB: Bitboard = RANK_1_BB << 48;
pub const RANK_8_BB: Bitboard = RANK_1_BB << 56;

#[inline(always)]
pub const fn square_bb(s: Square) -> Bitboard {
    1u64 << s
}
#[inline(always)]
pub const fn more_than_one(b: Bitboard) -> bool {
    b & b.wrapping_sub(1) != 0
}
#[inline(always)]
pub const fn rank_bb(r: usize) -> Bitboard {
    RANK_1_BB << (8 * r)
}
#[inline(always)]
pub const fn file_bb(f: usize) -> Bitboard {
    FILE_A_BB << f
}

#[inline(always)]
pub const fn shift(b: Bitboard, d: Direction) -> Bitboard {
    match d {
        NORTH => b << 8,
        SOUTH => b >> 8,
        16 => b << 16,
        -16 => b >> 16,
        EAST => (b & !FILE_H_BB) << 1,
        WEST => (b & !FILE_A_BB) >> 1,
        NORTH_EAST => (b & !FILE_H_BB) << 9,
        NORTH_WEST => (b & !FILE_A_BB) << 7,
        SOUTH_EAST => (b & !FILE_H_BB) >> 7,
        SOUTH_WEST => (b & !FILE_A_BB) >> 9,
        _ => 0,
    }
}

#[inline(always)]
pub const fn pawn_attacks_bb(c: Color, b: Bitboard) -> Bitboard {
    if c == WHITE {
        shift(b, NORTH_WEST) | shift(b, NORTH_EAST)
    } else {
        shift(b, SOUTH_WEST) | shift(b, SOUTH_EAST)
    }
}

#[inline(always)]
pub const fn pawn_single_push_bb(c: Color, b: Bitboard) -> Bitboard {
    shift(b, if c == WHITE { NORTH } else { SOUTH })
}

#[inline(always)]
pub fn popcount(b: Bitboard) -> i32 {
    b.count_ones() as i32
}
#[inline(always)]
pub fn lsb(b: Bitboard) -> Square {
    debug_assert!(b != 0);
    b.trailing_zeros() as Square
}
#[inline(always)]
pub fn msb(b: Bitboard) -> Square {
    debug_assert!(b != 0);
    (63 ^ b.leading_zeros()) as Square
}
#[inline(always)]
pub fn least_significant_square_bb(b: Bitboard) -> Bitboard {
    b & b.wrapping_neg()
}
#[inline(always)]
pub fn pop_lsb(b: &mut Bitboard) -> Square {
    let s = lsb(*b);
    *b &= *b - 1;
    s
}

const fn safe_destination(s: Square, step: i32) -> Bitboard {
    let to = s as i32 + step;
    if to >= 0 && to <= 63 {
        let df = (s as i32 & 7) - (to & 7);
        let df = if df < 0 { -df } else { df };
        if df <= 2 {
            return 1u64 << to;
        }
    }
    0
}

pub const fn sliding_attack(pt: PieceType, sq: Square, occupied: Bitboard) -> Bitboard {
    let dirs: [i32; 4] = if pt == ROOK {
        [NORTH, SOUTH, EAST, WEST]
    } else {
        [NORTH_EAST, SOUTH_EAST, SOUTH_WEST, NORTH_WEST]
    };
    let mut attacks = 0;
    let mut i = 0;
    while i < 4 {
        let d = dirs[i];
        let mut s = sq as i32;
        loop {
            let dest = safe_destination(s as Square, d);
            if dest == 0 {
                break;
            }
            attacks |= dest;
            if occupied & dest != 0 {
                break;
            }
            s += d;
        }
        i += 1;
    }
    attacks
}

const fn steps_attack(sq: Square, steps: [i32; 8]) -> Bitboard {
    let mut b = 0;
    let mut i = 0;
    while i < 8 {
        b |= safe_destination(sq, steps[i]);
        i += 1;
    }
    b
}

/// PseudoAttacks[WHITE/BLACK] hold pawn attacks; [KNIGHT..KING] hold piece attacks on an empty board.
pub static PSEUDO_ATTACKS: [[Bitboard; 64]; PIECE_TYPE_NB] = {
    let mut a = [[0u64; 64]; PIECE_TYPE_NB];
    let mut s = 0;
    while s < 64 {
        a[WHITE][s] = pawn_attacks_bb(WHITE, 1u64 << s);
        a[BLACK][s] = pawn_attacks_bb(BLACK, 1u64 << s);
        a[KING][s] = steps_attack(s, [-9, -8, -7, -1, 1, 7, 8, 9]);
        a[KNIGHT][s] = steps_attack(s, [-17, -15, -10, -6, 6, 10, 15, 17]);
        a[BISHOP][s] = sliding_attack(BISHOP, s, 0);
        a[ROOK][s] = sliding_attack(ROOK, s, 0);
        a[QUEEN][s] = a[BISHOP][s] | a[ROOK][s];
        s += 1;
    }
    a
};

pub static PAWN_PAIR_BB: [Bitboard; 64] = {
    let mut r = [0u64; 64];
    let mut s = 0;
    while s < 64 {
        let file = file_bb(s & 7);
        let files = file | shift(file, EAST) | shift(file, WEST);
        r[s] = files & !(RANK_1_BB | RANK_8_BB) & !(1u64 << s);
        s += 1;
    }
    r
};

#[inline(always)]
pub fn pawn_pair_bb(s: Square) -> Bitboard {
    debug_assert!(s < 64);
    unsafe { *PAWN_PAIR_BB.get_unchecked(s) }
}

const fn line_mask(sq: Square, d1: Direction, d2: Direction) -> Bitboard {
    let mut mask = 0;
    let ds = [d1, d2];
    let mut i = 0;
    while i < 2 {
        let mut s = sq as i32;
        loop {
            let dest = safe_destination(s as Square, ds[i]);
            if dest == 0 {
                break;
            }
            mask |= dest;
            s += ds[i];
        }
        i += 1;
    }
    mask
}

/// Aster's AVX2 "dual hyperbola quintessence": bishop and rook attacks
/// computed together without large lookup tables. Selected at compile time
/// for builds that target AVX2 (e.g. `-C target-cpu=native`).
#[cfg(all(target_arch = "x86_64", target_feature = "avx2"))]
mod dual {
    use super::*;
    use std::arch::x86_64::*;

    #[repr(C, align(32))]
    pub struct DualMagic {
        mask_file: u64,
        mask_diag: u64,
        mask_none: u64,
        mask_antidiag: u64,
        r: u64,
        rr: u64,
        file: usize,
        shift: u32,
    }

    static RANK_ATTACKS: [[u8; 64]; 8] = {
        let mut t = [[0u8; 64]; 8];
        let mut f = 0;
        while f < 8 {
            let mut occ6 = 0;
            while occ6 < 64 {
                t[f][occ6] = sliding_attack(ROOK, f, (occ6 as u64) << 1) as u8;
                occ6 += 1;
            }
            f += 1;
        }
        t
    };

    static DUAL_MAGICS: [DualMagic; 64] = {
        let mut m = [const {
            DualMagic {
                mask_file: 0,
                mask_diag: 0,
                mask_none: 0,
                mask_antidiag: 0,
                r: 0,
                rr: 0,
                file: 0,
                shift: 0,
            }
        }; 64];
        let mut s = 0;
        while s < 64 {
            m[s].mask_file = line_mask(s, NORTH, SOUTH);
            m[s].mask_diag = line_mask(s, NORTH_EAST, SOUTH_WEST);
            m[s].mask_none = 0;
            m[s].mask_antidiag = line_mask(s, NORTH_WEST, SOUTH_EAST);
            m[s].r = (1u64 << s).wrapping_mul(2);
            m[s].rr = (1u64 << (63 - s)).wrapping_mul(2);
            m[s].file = s & 7;
            m[s].shift = 8 * (s >> 3) as u32;
            s += 1;
        }
        m
    };

    /// Returns (bishop attacks, rook attacks).
    #[inline(always)]
    pub fn both_attacks_bb(s: Square, occupied: Bitboard) -> (Bitboard, Bitboard) {
        unsafe {
            let m = DUAL_MAGICS.get_unchecked(s);
            let bswap = |v: __m256i| {
                _mm256_shuffle_epi8(
                    v,
                    _mm256_set_epi8(
                        0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 0, 1, 2, 3, 4, 5, 6,
                        7, 8, 9, 10, 11, 12, 13, 14, 15,
                    ),
                )
            };
            let mask = _mm256_load_si256(m as *const DualMagic as *const __m256i);
            let rs = _mm256_set1_epi64x(m.r as i64);
            let rrs = _mm256_set1_epi64x(m.rr as i64);
            let o = _mm256_and_si256(mask, _mm256_set1_epi64x(occupied as i64));
            let fwd = _mm256_sub_epi64(o, rs);
            let rev = bswap(_mm256_sub_epi64(bswap(o), rrs));
            let result = _mm256_and_si256(_mm256_xor_si256(fwd, rev), mask);
            let rook_bishop = _mm_or_si128(
                _mm256_extracti128_si256::<1>(result),
                _mm256_castsi256_si128(result),
            );
            let row = *RANK_ATTACKS
                .get_unchecked(m.file)
                .get_unchecked(((occupied >> (m.shift + 1)) & 0x3f) as usize)
                as u64;
            let rank_attacks = row << m.shift;
            (
                _mm_extract_epi64::<1>(rook_bishop) as u64,
                (_mm_cvtsi128_si64(rook_bishop) as u64).wrapping_add(rank_attacks),
            )
        }
    }
}

#[derive(Copy, Clone, Default)]
struct Magic {
    mask: Bitboard,
    magic: Bitboard,
    offset: usize,
    shift: u32,
}

impl Magic {
    #[inline(always)]
    fn index(&self, occupied: Bitboard) -> usize {
        ((occupied & self.mask).wrapping_mul(self.magic) >> self.shift) as usize
    }
}

pub struct Tables {
    magics: [[Magic; 2]; 64],
    attack_table: Vec<Bitboard>,
    pub line: Box<[[Bitboard; 64]; 64]>,
    pub between: Box<[[Bitboard; 64]; 64]>,
    pub ray_pass: Box<[[Bitboard; 64]; 64]>,
    pub zobrist_psq: [[Key; 64]; PIECE_NB],
    pub zobrist_enpassant: [Key; 8],
    pub zobrist_castling: [Key; CASTLING_RIGHT_NB],
    pub zobrist_side: Key,
    pub zobrist_no_pawns: Key,
    pub cuckoo: Box<[Key; 8192]>,
    pub cuckoo_move: Box<[Move; 8192]>,
}

static TABLES: OnceLock<Tables> = OnceLock::new();

#[inline(always)]
pub fn tables() -> &'static Tables {
    // SAFETY: init() runs at program start before any table access.
    unsafe { TABLES.get().unwrap_unchecked() }
}

pub fn init() {
    TABLES.get_or_init(build_tables);
}

fn init_magics(pt: PieceType, magics: &mut [[Magic; 2]; 64], table: &mut Vec<Bitboard>) {
    let seeds: [u64; 8] = [728, 10316, 55013, 32803, 12281, 15100, 16645, 255];
    let mut occupancy = vec![0u64; 4096];
    let mut reference = vec![0u64; 4096];
    let mut epoch = vec![0i32; 4096];
    let mut cnt = 0;

    for s in 0..64 {
        let edges = ((RANK_1_BB | RANK_8_BB) & !rank_bb(rank_of(s)))
            | ((FILE_A_BB | FILE_H_BB) & !file_bb(file_of(s)));
        let m = &mut magics[s][pt - BISHOP];
        m.mask = sliding_attack(pt, s, 0) & !edges;
        m.shift = 64 - m.mask.count_ones();
        m.offset = table.len();

        let mut size = 0;
        let mut b: Bitboard = 0;
        loop {
            occupancy[size] = b;
            reference[size] = sliding_attack(pt, s, b);
            size += 1;
            b = b.wrapping_sub(m.mask) & m.mask;
            if b == 0 {
                break;
            }
        }
        table.resize(m.offset + size, 0);

        let mut rng = Prng::new(seeds[rank_of(s)]);
        let mut i = 0;
        while i < size {
            m.magic = 0;
            while (m.magic.wrapping_mul(m.mask) >> 56).count_ones() < 6 {
                m.magic = rng.sparse_rand();
            }
            cnt += 1;
            i = 0;
            while i < size {
                let idx = m.index(occupancy[i]);
                if epoch[idx] < cnt {
                    epoch[idx] = cnt;
                    table[m.offset + idx] = reference[i];
                } else if table[m.offset + idx] != reference[i] {
                    break;
                }
                i += 1;
            }
        }
    }
}

fn build_tables() -> Tables {
    let mut magics = [[Magic::default(); 2]; 64];
    let mut attack_table = Vec::with_capacity(0x19000 + 0x1480);
    init_magics(ROOK, &mut magics, &mut attack_table);
    init_magics(BISHOP, &mut magics, &mut attack_table);

    let mut t = Tables {
        magics,
        attack_table,
        line: Box::new([[0; 64]; 64]),
        between: Box::new([[0; 64]; 64]),
        ray_pass: Box::new([[0; 64]; 64]),
        zobrist_psq: [[0; 64]; PIECE_NB],
        zobrist_enpassant: [0; 8],
        zobrist_castling: [0; CASTLING_RIGHT_NB],
        zobrist_side: 0,
        zobrist_no_pawns: 0,
        cuckoo: Box::new([0; 8192]),
        cuckoo_move: Box::new([Move::NONE; 8192]),
    };

    for s1 in 0..64 {
        for pt in [BISHOP, ROOK] {
            for s2 in 0..64 {
                if PSEUDO_ATTACKS[pt][s1] & square_bb(s2) != 0 {
                    t.line[s1][s2] = (t.attacks(pt, s1, 0) & t.attacks(pt, s2, 0))
                        | square_bb(s1)
                        | square_bb(s2);
                    t.between[s1][s2] =
                        t.attacks(pt, s1, square_bb(s2)) & t.attacks(pt, s2, square_bb(s1));
                    t.ray_pass[s1][s2] =
                        t.attacks(pt, s1, 0) & (t.attacks(pt, s2, square_bb(s1)) | square_bb(s2));
                }
                t.between[s1][s2] |= square_bb(s2);
            }
        }
    }

    // Zobrist keys (Position::init)
    let mut rng = Prng::new(1070372);
    const PIECES: [Piece; 12] = [
        W_PAWN, W_KNIGHT, W_BISHOP, W_ROOK, W_QUEEN, W_KING, B_PAWN, B_KNIGHT, B_BISHOP, B_ROOK,
        B_QUEEN, B_KING,
    ];
    for pc in PIECES {
        for s in 0..64 {
            t.zobrist_psq[pc][s] = rng.rand64();
        }
    }
    for s in SQ_A8..64 {
        t.zobrist_psq[W_PAWN][s] = 0;
    }
    for s in 0..8 {
        t.zobrist_psq[B_PAWN][s] = 0;
    }
    for f in 0..8 {
        t.zobrist_enpassant[f] = rng.rand64();
    }
    for cr in 0..CASTLING_RIGHT_NB {
        t.zobrist_castling[cr] = rng.rand64();
    }
    t.zobrist_side = rng.rand64();
    t.zobrist_no_pawns = rng.rand64();

    // Cuckoo tables
    let mut count = 0;
    for pc in PIECES {
        for s1 in 0..64 {
            for s2 in s1 + 1..64 {
                if type_of(pc) != PAWN && t.attacks(type_of(pc), s1, 0) & square_bb(s2) != 0 {
                    let mut mv = Move::new(s1, s2);
                    let mut key = t.zobrist_psq[pc][s1] ^ t.zobrist_psq[pc][s2] ^ t.zobrist_side;
                    let mut i = h1(key);
                    loop {
                        std::mem::swap(&mut t.cuckoo[i], &mut key);
                        std::mem::swap(&mut t.cuckoo_move[i], &mut mv);
                        if mv == Move::NONE {
                            break;
                        }
                        i = if i == h1(key) { h2(key) } else { h1(key) };
                    }
                    count += 1;
                }
            }
        }
    }
    assert_eq!(count, 3668);
    t
}

#[inline(always)]
pub fn h1(h: Key) -> usize {
    (h & 0x1fff) as usize
}
#[inline(always)]
pub fn h2(h: Key) -> usize {
    ((h >> 16) & 0x1fff) as usize
}

impl Tables {
    #[inline(always)]
    pub fn psq(&self, pc: Piece, s: Square) -> Key {
        debug_assert!(pc < PIECE_NB && s < 64);
        unsafe { *self.zobrist_psq.get_unchecked(pc).get_unchecked(s) }
    }
    #[inline(always)]
    pub fn bishop_attacks(&self, s: Square, occupied: Bitboard) -> Bitboard {
        let m = unsafe { self.magics.get_unchecked(s).get_unchecked(0) };
        unsafe {
            *self
                .attack_table
                .get_unchecked(m.offset + m.index(occupied))
        }
    }
    #[inline(always)]
    pub fn rook_attacks(&self, s: Square, occupied: Bitboard) -> Bitboard {
        let m = unsafe { self.magics.get_unchecked(s).get_unchecked(1) };
        unsafe {
            *self
                .attack_table
                .get_unchecked(m.offset + m.index(occupied))
        }
    }
    #[inline(always)]
    pub fn attacks(&self, pt: PieceType, s: Square, occupied: Bitboard) -> Bitboard {
        match pt {
            BISHOP => self.bishop_attacks(s, occupied),
            ROOK => self.rook_attacks(s, occupied),
            QUEEN => self.bishop_attacks(s, occupied) | self.rook_attacks(s, occupied),
            _ => pa(pt, s),
        }
    }
}

#[cfg(all(target_arch = "x86_64", target_feature = "avx2"))]
#[inline(always)]
pub fn attacks_bb(pt: PieceType, s: Square, occupied: Bitboard) -> Bitboard {
    match pt {
        BISHOP => dual::both_attacks_bb(s, occupied).0,
        ROOK => dual::both_attacks_bb(s, occupied).1,
        QUEEN => {
            let (b, r) = dual::both_attacks_bb(s, occupied);
            b | r
        }
        _ => pa(pt, s),
    }
}
#[cfg(all(target_arch = "x86_64", target_feature = "avx2"))]
#[inline(always)]
pub fn bishop_attacks(s: Square, occupied: Bitboard) -> Bitboard {
    dual::both_attacks_bb(s, occupied).0
}
#[cfg(all(target_arch = "x86_64", target_feature = "avx2"))]
#[inline(always)]
pub fn rook_attacks(s: Square, occupied: Bitboard) -> Bitboard {
    dual::both_attacks_bb(s, occupied).1
}
/// Returns (bishop attacks, rook attacks).
#[cfg(all(target_arch = "x86_64", target_feature = "avx2"))]
#[inline(always)]
pub fn both_attacks_bb(s: Square, occupied: Bitboard) -> (Bitboard, Bitboard) {
    dual::both_attacks_bb(s, occupied)
}

#[cfg(not(all(target_arch = "x86_64", target_feature = "avx2")))]
#[inline(always)]
pub fn attacks_bb(pt: PieceType, s: Square, occupied: Bitboard) -> Bitboard {
    tables().attacks(pt, s, occupied)
}
#[cfg(not(all(target_arch = "x86_64", target_feature = "avx2")))]
#[inline(always)]
pub fn bishop_attacks(s: Square, occupied: Bitboard) -> Bitboard {
    tables().bishop_attacks(s, occupied)
}
#[cfg(not(all(target_arch = "x86_64", target_feature = "avx2")))]
#[inline(always)]
pub fn rook_attacks(s: Square, occupied: Bitboard) -> Bitboard {
    tables().rook_attacks(s, occupied)
}
/// Returns (bishop attacks, rook attacks).
#[cfg(not(all(target_arch = "x86_64", target_feature = "avx2")))]
#[inline(always)]
pub fn both_attacks_bb(s: Square, occupied: Bitboard) -> (Bitboard, Bitboard) {
    let t = tables();
    (t.bishop_attacks(s, occupied), t.rook_attacks(s, occupied))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn slider_attacks_match_reference() {
        init();
        let mut rng = Prng::new(0x9E3779B97F4A7C15);
        for s in 0..64 {
            for i in 0..20000 {
                let occ = match i % 3 {
                    0 => rng.rand64(),
                    1 => rng.sparse_rand(),
                    _ => rng.rand64() & rng.rand64(),
                };
                let (b, r) = both_attacks_bb(s, occ);
                assert_eq!(b, sliding_attack(BISHOP, s, occ), "bishop {s} {occ:#x}");
                assert_eq!(r, sliding_attack(ROOK, s, occ), "rook {s} {occ:#x}");
                assert_eq!(tables().bishop_attacks(s, occ), b);
                assert_eq!(tables().rook_attacks(s, occ), r);
            }
        }
    }
}
/// Table lookup without bounds checks (debug builds still check).
#[inline(always)]
pub fn pa(pt: usize, s: Square) -> Bitboard {
    debug_assert!(pt < PIECE_TYPE_NB && s < 64);
    unsafe { *PSEUDO_ATTACKS.get_unchecked(pt).get_unchecked(s) }
}
#[inline(always)]
pub fn pawn_attacks_from(c: Color, s: Square) -> Bitboard {
    pa(c, s)
}
#[inline(always)]
pub fn pseudo_attacks(pt: PieceType, s: Square) -> Bitboard {
    pa(pt, s)
}
#[inline(always)]
pub fn line_bb(s1: Square, s2: Square) -> Bitboard {
    unsafe { *tables().line.get_unchecked(s1).get_unchecked(s2) }
}
#[inline(always)]
pub fn between_bb(s1: Square, s2: Square) -> Bitboard {
    unsafe { *tables().between.get_unchecked(s1).get_unchecked(s2) }
}
#[inline(always)]
pub fn ray_pass_bb(s1: Square, s2: Square) -> Bitboard {
    unsafe { *tables().ray_pass.get_unchecked(s1).get_unchecked(s2) }
}
