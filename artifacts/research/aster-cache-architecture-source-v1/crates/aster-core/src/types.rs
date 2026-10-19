// Aster core. Original attribution and source mapping: types.rs.license.
// SPDX-License-Identifier: GPL-3.0-or-later
// Modified 2026-10-19: source naming and notice layout only.

pub type Key = u64;
pub type Bitboard = u64;
pub type Value = i32;
pub type Depth = i32;

// Small enums are plain integers so they index tables directly, as in C++.
pub type Color = usize;
pub type PieceType = usize;
pub type Piece = usize;
pub type Square = usize;

pub const MAX_MOVES: usize = 256;
pub const MAX_PLY: i32 = 246;

pub const WHITE: Color = 0;
pub const BLACK: Color = 1;
pub const COLOR_NB: usize = 2;

pub const NO_CASTLING: usize = 0;
pub const WHITE_OO: usize = 1;
pub const WHITE_OOO: usize = 2;
pub const BLACK_OO: usize = 4;
pub const BLACK_OOO: usize = 8;
pub const KING_SIDE: usize = WHITE_OO | BLACK_OO;
pub const QUEEN_SIDE: usize = WHITE_OOO | BLACK_OOO;
pub const WHITE_CASTLING: usize = WHITE_OO | WHITE_OOO;
pub const BLACK_CASTLING: usize = BLACK_OO | BLACK_OOO;
pub const ANY_CASTLING: usize = WHITE_CASTLING | BLACK_CASTLING;
pub const CASTLING_RIGHT_NB: usize = 16;

pub type Bound = u8;
pub const BOUND_NONE: Bound = 0;
pub const BOUND_UPPER: Bound = 1;
pub const BOUND_LOWER: Bound = 2;
pub const BOUND_EXACT: Bound = 3;

pub const VALUE_ZERO: Value = 0;
pub const VALUE_DRAW: Value = 0;
pub const VALUE_NONE: Value = 32002;
pub const VALUE_INFINITE: Value = 32001;
pub const VALUE_MATE: Value = 32000;
pub const VALUE_MATE_IN_MAX_PLY: Value = VALUE_MATE - MAX_PLY;
pub const VALUE_MATED_IN_MAX_PLY: Value = -VALUE_MATE_IN_MAX_PLY;
pub const VALUE_TB: Value = VALUE_MATE_IN_MAX_PLY - 1;
pub const VALUE_TB_WIN_IN_MAX_PLY: Value = VALUE_TB - MAX_PLY;
pub const VALUE_TB_LOSS_IN_MAX_PLY: Value = -VALUE_TB_WIN_IN_MAX_PLY;

#[inline(always)]
pub fn is_valid(v: Value) -> bool {
    v != VALUE_NONE
}
#[inline(always)]
pub fn is_win(v: Value) -> bool {
    debug_assert!(is_valid(v));
    v >= VALUE_TB_WIN_IN_MAX_PLY
}
#[inline(always)]
pub fn is_loss(v: Value) -> bool {
    debug_assert!(is_valid(v));
    v <= VALUE_TB_LOSS_IN_MAX_PLY
}
#[inline(always)]
pub fn is_decisive(v: Value) -> bool {
    is_win(v) || is_loss(v)
}
#[inline(always)]
pub fn is_mate(v: Value) -> bool {
    v >= VALUE_MATE_IN_MAX_PLY
}
#[inline(always)]
pub fn is_mated(v: Value) -> bool {
    v <= VALUE_MATED_IN_MAX_PLY
}
#[inline(always)]
pub fn is_mate_or_mated(v: Value) -> bool {
    is_mate(v) || is_mated(v)
}
#[inline(always)]
pub fn mate_in(ply: i32) -> Value {
    VALUE_MATE - ply
}
#[inline(always)]
pub fn mated_in(ply: i32) -> Value {
    -VALUE_MATE + ply
}

pub const PAWN_VALUE: Value = 208;
pub const KNIGHT_VALUE: Value = 781;
pub const BISHOP_VALUE: Value = 825;
pub const ROOK_VALUE: Value = 1276;
pub const QUEEN_VALUE: Value = 2538;

pub const NO_PIECE_TYPE: PieceType = 0;
pub const PAWN: PieceType = 1;
pub const KNIGHT: PieceType = 2;
pub const BISHOP: PieceType = 3;
pub const ROOK: PieceType = 4;
pub const QUEEN: PieceType = 5;
pub const KING: PieceType = 6;
pub const ALL_PIECES: PieceType = 0;
pub const PIECE_TYPE_NB: usize = 8;

pub const NO_PIECE: Piece = 0;
pub const W_PAWN: Piece = 1;
pub const W_KNIGHT: Piece = 2;
pub const W_BISHOP: Piece = 3;
pub const W_ROOK: Piece = 4;
pub const W_QUEEN: Piece = 5;
pub const W_KING: Piece = 6;
pub const B_PAWN: Piece = 9;
pub const B_KNIGHT: Piece = 10;
pub const B_BISHOP: Piece = 11;
pub const B_ROOK: Piece = 12;
pub const B_QUEEN: Piece = 13;
pub const B_KING: Piece = 14;
pub const PIECE_NB: usize = 16;

pub static PIECE_VALUE: [Value; PIECE_NB] = [
    0,
    PAWN_VALUE,
    KNIGHT_VALUE,
    BISHOP_VALUE,
    ROOK_VALUE,
    QUEEN_VALUE,
    0,
    0,
    0,
    PAWN_VALUE,
    KNIGHT_VALUE,
    BISHOP_VALUE,
    ROOK_VALUE,
    QUEEN_VALUE,
    0,
    0,
];

pub const DEPTH_QS: Depth = 0;
pub const DEPTH_UNSEARCHED: Depth = -2;
pub const DEPTH_NONE: Depth = -3;

pub const SQ_A1: Square = 0;
pub const SQ_B1: Square = 1;
pub const SQ_C1: Square = 2;
pub const SQ_D1: Square = 3;
pub const SQ_E1: Square = 4;
pub const SQ_F1: Square = 5;
pub const SQ_G1: Square = 6;
pub const SQ_H1: Square = 7;
pub const SQ_A2: Square = 8;
pub const SQ_H7: Square = 55;
pub const SQ_A8: Square = 56;
pub const SQ_H8: Square = 63;
pub const SQ_NONE: Square = 64;
pub const SQUARE_NB: usize = 64;

pub type Direction = i32;
pub const NORTH: Direction = 8;
pub const EAST: Direction = 1;
pub const SOUTH: Direction = -8;
pub const WEST: Direction = -1;
pub const NORTH_EAST: Direction = 9;
pub const SOUTH_EAST: Direction = -7;
pub const SOUTH_WEST: Direction = -9;
pub const NORTH_WEST: Direction = 7;

pub const FILE_A: usize = 0;
pub const FILE_C: usize = 2;
pub const FILE_G: usize = 6;
pub const FILE_H: usize = 7;
pub const RANK_1: usize = 0;
pub const RANK_2: usize = 1;
pub const RANK_6: usize = 5;
pub const RANK_8: usize = 7;

#[inline(always)]
pub fn sq_add(s: Square, d: Direction) -> Square {
    (s as i32 + d) as Square
}
#[inline(always)]
pub fn flip_color(c: Color) -> Color {
    c ^ BLACK
}
#[inline(always)]
pub fn flip_piece(pc: Piece) -> Piece {
    pc ^ 8
}
#[inline(always)]
pub fn color_castling(c: Color, cr: usize) -> usize {
    (if c == WHITE {
        WHITE_CASTLING
    } else {
        BLACK_CASTLING
    }) & cr
}
#[inline(always)]
pub fn make_square(f: usize, r: usize) -> Square {
    (r << 3) + f
}
#[inline(always)]
pub fn make_piece(c: Color, pt: PieceType) -> Piece {
    (c << 3) + pt
}
#[inline(always)]
pub fn type_of(pc: Piece) -> PieceType {
    pc & 7
}
#[inline(always)]
pub fn color_of(pc: Piece) -> Color {
    debug_assert!(pc != NO_PIECE);
    pc >> 3
}
#[inline(always)]
pub fn is_ok_sq(s: i32) -> bool {
    (0..=63).contains(&s)
}
#[inline(always)]
pub fn file_of(s: Square) -> usize {
    s & 7
}
#[inline(always)]
pub fn rank_of(s: Square) -> usize {
    s >> 3
}
#[inline(always)]
pub fn relative_square(c: Color, s: Square) -> Square {
    s ^ (c * 56)
}
#[inline(always)]
pub fn relative_rank(c: Color, r: usize) -> usize {
    r ^ (c * 7)
}
#[inline(always)]
pub fn relative_rank_sq(c: Color, s: Square) -> usize {
    relative_rank(c, rank_of(s))
}
#[inline(always)]
pub fn pawn_push(c: Color) -> Direction {
    if c == WHITE { NORTH } else { SOUTH }
}

#[inline(always)]
pub const fn make_key(seed: u64) -> Key {
    seed.wrapping_mul(6364136223846793005)
        .wrapping_add(1442695040888963407)
}

pub type MoveType = u16;
pub const NORMAL: MoveType = 0;
pub const PROMOTION: MoveType = 1 << 14;
pub const EN_PASSANT: MoveType = 2 << 14;
pub const CASTLING: MoveType = 3 << 14;

/// A move needs 16 bits to be stored
///
/// bit  0- 5: destination square (from 0 to 63)
/// bit  6-11: origin square (from 0 to 63)
/// bit 12-13: promotion piece type - 2 (from KNIGHT-2 to QUEEN-2)
/// bit 14-15: special move flag: promotion (1), en passant (2), castling (3)
#[derive(Copy, Clone, PartialEq, Eq, Default, Hash, Debug)]
#[repr(transparent)]
pub struct Move(pub u16);

impl Move {
    pub const NONE: Move = Move(0);
    pub const NULL: Move = Move(65);

    #[inline(always)]
    pub fn new(from: Square, to: Square) -> Move {
        Move(((from << 6) + to) as u16)
    }
    #[inline(always)]
    pub fn make(t: MoveType, from: Square, to: Square, pt: PieceType) -> Move {
        Move(t + (((pt - KNIGHT) << 12) + (from << 6) + to) as u16)
    }
    #[inline(always)]
    pub fn from_sq(self) -> Square {
        ((self.0 >> 6) & 0x3F) as Square
    }
    #[inline(always)]
    pub fn to_sq(self) -> Square {
        (self.0 & 0x3F) as Square
    }
    #[inline(always)]
    pub fn type_of(self) -> MoveType {
        self.0 & (3 << 14)
    }
    #[inline(always)]
    pub fn promotion_type(self) -> PieceType {
        (((self.0 >> 12) & 3) as usize) + KNIGHT
    }
    #[inline(always)]
    pub fn is_ok(self) -> bool {
        self.0 != 0 && self.0 != 65
    }
    #[inline(always)]
    pub fn is_some(self) -> bool {
        self.0 != 0
    }
    #[inline(always)]
    pub fn is_none(self) -> bool {
        self.0 == 0
    }
    #[inline(always)]
    pub fn raw(self) -> u16 {
        self.0
    }
}

/// Keep track of what a move changes on the board (used by NNUE)
#[derive(Copy, Clone, Default)]
pub struct DirtyPiece {
    pub pc: Piece,
    pub from: Square,
    pub to: Square,
    pub remove_sq: Square,
    pub add_sq: Square,
    pub remove_pc: Piece,
    pub add_pc: Piece,
}

/// Keep track of what threats change on the board (used by NNUE)
#[derive(Copy, Clone, Default)]
#[repr(transparent)]
pub struct DirtyThreat(pub u32);

impl DirtyThreat {
    pub const PC_SQ_OFFSET: u32 = 0;
    pub const THREATENED_SQ_OFFSET: u32 = 8;
    pub const THREATENED_PC_OFFSET: u32 = 16;
    pub const PC_OFFSET: u32 = 20;

    #[inline(always)]
    pub fn new(
        pc: Piece,
        threatened_pc: Piece,
        pc_sq: Square,
        threatened_sq: Square,
        add: bool,
    ) -> Self {
        DirtyThreat(
            ((add as u32) << 31)
                | ((pc as u32) << Self::PC_OFFSET)
                | ((threatened_pc as u32) << Self::THREATENED_PC_OFFSET)
                | ((threatened_sq as u32) << Self::THREATENED_SQ_OFFSET)
                | ((pc_sq as u32) << Self::PC_SQ_OFFSET),
        )
    }
    #[inline(always)]
    pub fn pc(self) -> Piece {
        ((self.0 >> Self::PC_OFFSET) & 0xf) as Piece
    }
    #[inline(always)]
    pub fn threatened_pc(self) -> Piece {
        ((self.0 >> Self::THREATENED_PC_OFFSET) & 0xf) as Piece
    }
    #[inline(always)]
    pub fn threatened_sq(self) -> Square {
        ((self.0 >> Self::THREATENED_SQ_OFFSET) & 0xff) as Square
    }
    #[inline(always)]
    pub fn pc_sq(self) -> Square {
        ((self.0 >> Self::PC_SQ_OFFSET) & 0xff) as Square
    }
    #[inline(always)]
    pub fn add(self) -> bool {
        (self.0 >> 31) != 0
    }
}

/// Fixed-capacity list, the Rust counterpart of the upstream `ValueList`.
/// Storage is left uninitialised; only the first `size` slots are ever read.
pub struct ValueList<T: Copy + Default, const N: usize> {
    values: [std::mem::MaybeUninit<T>; N],
    size: usize,
}

impl<T: Copy + Default, const N: usize> Clone for ValueList<T, N> {
    fn clone(&self) -> Self {
        let mut v = Self::default();
        for &x in self.as_slice() {
            v.push(x);
        }
        v
    }
}

impl<T: Copy + Default, const N: usize> Default for ValueList<T, N> {
    #[inline(always)]
    fn default() -> Self {
        Self {
            values: [const { std::mem::MaybeUninit::uninit() }; N],
            size: 0,
        }
    }
}

impl<T: Copy + Default, const N: usize> ValueList<T, N> {
    #[inline(always)]
    pub fn new() -> Self {
        Self::default()
    }
    #[inline(always)]
    pub fn len(&self) -> usize {
        self.size
    }
    #[inline(always)]
    pub fn is_empty(&self) -> bool {
        self.size == 0
    }
    #[inline(always)]
    pub fn clear(&mut self) {
        self.size = 0;
    }
    #[inline(always)]
    pub fn push(&mut self, v: T) {
        assert!(self.size < N);
        self.values[self.size] = std::mem::MaybeUninit::new(v);
        self.size += 1;
    }
    #[inline(always)]
    pub fn as_slice(&self) -> &[T] {
        unsafe { std::slice::from_raw_parts(self.values.as_ptr() as *const T, self.size) }
    }
    #[inline(always)]
    pub fn get(&self, i: usize) -> T {
        self.as_slice()[i]
    }
}

pub type DirtyThreatList = ValueList<DirtyThreat, 96>;

#[derive(Copy, Clone, Default)]
pub struct DirtyPawnPairs {
    pub before: [Bitboard; COLOR_NB],
    pub after: [Bitboard; COLOR_NB],
}

#[derive(Clone, Default)]
pub struct Dirties {
    pub dirty_piece: DirtyPiece,
    pub dirty_threats: DirtyThreatList,
    pub dirty_pawn_pairs: DirtyPawnPairs,
}

/// xorshift64star pseudo-random number generator (Sebastiano Vigna, public domain).
pub struct Prng {
    s: u64,
}

impl Prng {
    pub fn new(seed: u64) -> Self {
        debug_assert!(seed != 0);
        Prng { s: seed }
    }
    #[inline]
    pub fn rand64(&mut self) -> u64 {
        self.s ^= self.s >> 12;
        self.s ^= self.s << 25;
        self.s ^= self.s >> 27;
        self.s.wrapping_mul(2685821657736338717)
    }
    #[inline]
    pub fn sparse_rand(&mut self) -> u64 {
        self.rand64() & self.rand64() & self.rand64()
    }
}

#[inline(always)]
pub fn mul_hi64(a: u64, b: u64) -> u64 {
    ((a as u128 * b as u128) >> 64) as u64
}
