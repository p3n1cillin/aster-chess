// Aster core. Original attribution and source mapping: position.rs.license.
// SPDX-License-Identifier: GPL-3.0-or-later
// Modified 2026-10-19: source naming and notice layout only.

use crate::bitboard::*;
use crate::movegen::{GenType, MoveList};
use crate::types::*;

const PIECE_TO_CHAR: &[u8] = b" PNBRQK  pnbrqk";
const PIECES: [Piece; 12] = [
    W_PAWN, W_KNIGHT, W_BISHOP, W_ROOK, W_QUEEN, W_KING, B_PAWN, B_KNIGHT, B_BISHOP, B_ROOK,
    B_QUEEN, B_KING,
];

pub const START_FEN: &str = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";

/// StateInfo stores the information needed to restore a Position to its
/// previous state when a move is retracted.
#[repr(C)]
#[derive(Copy, Clone, Default)]
pub struct StateInfo {
    // Copied when making a move
    pub material_key: Key,
    pub pawn_key: Key,
    pub minor_piece_key: Key,
    pub non_pawn_key: [Key; COLOR_NB],
    pub non_pawn_material: [Value; COLOR_NB],
    pub castling_rights: usize,
    pub rule50: i32,
    pub plies_from_null: i32,
    pub ep_square: Square,

    // Not copied when making a move (will be recomputed anyhow)
    pub key: Key,
    pub checkers_bb: Bitboard,
    pub blockers_for_king: [Bitboard; COLOR_NB],
    pub pinners: [Bitboard; COLOR_NB],
    pub check_squares: [Bitboard; PIECE_TYPE_NB],
    pub captured_piece: Piece,
    pub repetition: i32,
}

#[derive(Debug)]
pub struct PositionSetError(pub String);

#[derive(Clone)]
pub struct Position {
    board: [u8; 64],
    by_type_bb: [Bitboard; PIECE_TYPE_NB],
    by_color_bb: [Bitboard; COLOR_NB],
    piece_count: [i32; PIECE_NB],
    castling_rights_mask: [usize; 64],
    castling_rook_square: [Square; CASTLING_RIGHT_NB],
    castling_path: [Bitboard; CASTLING_RIGHT_NB],
    // states.last() is the current state; earlier entries form the `previous` chain.
    states: Vec<StateInfo>,
    game_ply: i32,
    side_to_move: Color,
    chess960: bool,
}

impl Default for Position {
    fn default() -> Self {
        Position {
            board: [0; 64],
            by_type_bb: [0; PIECE_TYPE_NB],
            by_color_bb: [0; COLOR_NB],
            piece_count: [0; PIECE_NB],
            castling_rights_mask: [0; 64],
            castling_rook_square: [0; CASTLING_RIGHT_NB],
            castling_path: [0; CASTLING_RIGHT_NB],
            states: Vec::with_capacity(1024),
            game_ply: 0,
            side_to_move: WHITE,
            chess960: false,
        }
    }
}

struct Cursor<'a> {
    b: &'a [u8],
    i: usize,
}
impl Cursor<'_> {
    fn get(&mut self) -> Option<u8> {
        let c = self.b.get(self.i).copied();
        if c.is_some() {
            self.i += 1;
        }
        c
    }
    fn skip_ws(&mut self) {
        while self.i < self.b.len() && self.b[self.i].is_ascii_whitespace() {
            self.i += 1;
        }
    }
    fn int(&mut self) -> Option<i32> {
        self.skip_ws();
        let start = self.i;
        if self.i < self.b.len() && (self.b[self.i] == b'-' || self.b[self.i] == b'+') {
            self.i += 1;
        }
        let ds = self.i;
        while self.i < self.b.len() && self.b[self.i].is_ascii_digit() {
            self.i += 1;
        }
        if self.i == ds {
            self.i = start;
            return None;
        }
        std::str::from_utf8(&self.b[start..self.i])
            .ok()?
            .parse::<i64>()
            .ok()
            .map(|v| v.clamp(i32::MIN as i64, i32::MAX as i64) as i32)
    }
}

impl Position {
    #[inline(always)]
    pub fn st(&self) -> &StateInfo {
        unsafe { self.states.get_unchecked(self.states.len() - 1) }
    }
    #[inline(always)]
    fn st_mut(&mut self) -> &mut StateInfo {
        let n = self.states.len() - 1;
        unsafe { self.states.get_unchecked_mut(n) }
    }
    #[inline(always)]
    fn prev_st(&self, back: usize) -> &StateInfo {
        &self.states[self.states.len() - 1 - back]
    }
    pub fn state_count(&self) -> usize {
        self.states.len()
    }
    pub fn reserve_states(&mut self, n: usize) {
        self.states.reserve(n);
    }

    /// Initializes the position from the given FEN string, strictly validated.
    pub fn set(&mut self, fen: &str, is_chess960: bool) -> Result<(), PositionSetError> {
        *self = Position::default();
        self.states.push(StateInfo::default());
        let err = |s: &str| Err(PositionSetError(s.to_string()));
        let mut ss = Cursor {
            b: fen.as_bytes(),
            i: 0,
        };

        let mut num_pieces = 0;
        let mut file: i32 = 0;
        let mut rank: i32 = 7;

        // 1. Piece placement
        loop {
            let Some(token) = ss.get() else {
                return err("Invalid FEN. Unexpected end of stream.");
            };
            if token.is_ascii_whitespace() {
                break;
            }
            if token.is_ascii_digit() {
                let diff = (token - b'0') as i32;
                if !(1..=8).contains(&diff) {
                    return err("Invalid FEN. Invalid number of squares to skip.");
                }
                file += diff;
                if file > 8 {
                    return err("Invalid FEN. Invalid file reached.");
                }
            } else if token == b'/' {
                if file != 8 {
                    return err("Invalid FEN. Trying to end rank when not at the end of it.");
                }
                rank -= 1;
                file = 0;
                if rank < 0 {
                    return err("Invalid FEN. Invalid rank reached.");
                }
            } else {
                if file >= 8 {
                    return err("Invalid FEN. Invalid file reached.");
                }
                let Some(idx) = PIECE_TO_CHAR.iter().position(|&c| c == token) else {
                    return Err(PositionSetError(format!(
                        "Invalid FEN. Invalid piece: {}",
                        token as char
                    )));
                };
                num_pieces += 1;
                if num_pieces > 32 {
                    return err("Invalid FEN. More than 32 pieces on the board.");
                }
                self.put_piece(idx, make_square(file as usize, rank as usize));
                file += 1;
            }
        }

        if rank != 0 || file != 8 {
            return err("Invalid FEN. Board state encoding ended but cursor not at end.");
        }
        if self.pieces_t(PAWN) & (RANK_1_BB | RANK_8_BB) != 0 {
            return err("Unsupported position. Pawns on the first or eighth rank.");
        }
        if self.count(WHITE, KING) != 1 || self.count(BLACK, KING) != 1 {
            return err("Unsupported position. Incorrect number of kings.");
        }
        for c in [WHITE, BLACK] {
            let name = if c == WHITE { "WHITE" } else { "BLACK" };
            if self.count(c, PAWN) > 8 {
                return Err(PositionSetError(format!(
                    "Unsupported position. {name} has more than 8 pawns."
                )));
            }
            let additional = (self.count(c, KNIGHT) - 2).max(0)
                + (self.count(c, BISHOP) - 2).max(0)
                + (self.count(c, ROOK) - 2).max(0)
                + (self.count(c, QUEEN) - 1).max(0);
            if additional > 8 - self.count(c, PAWN) {
                return Err(PositionSetError(format!(
                    "Unsupported position. Too many pieces for {name}."
                )));
            }
        }

        // 2. Active color
        let Some(token) = ss.get() else {
            return err("Invalid FEN. Unexpected end of stream.");
        };
        if token != b'w' && token != b'b' {
            return Err(PositionSetError(format!(
                "Invalid FEN. Invalid side to move: {}",
                token as char
            )));
        }
        self.side_to_move = if token == b'w' { WHITE } else { BLACK };
        match ss.get() {
            Some(t) if t.is_ascii_whitespace() => {}
            _ => return err("Invalid FEN. Expected whitespace after side to move."),
        }

        // 3. Castling availability (FEN, Shredder-FEN and X-FEN)
        let mut num_castling_rights = 0;
        loop {
            let Some(mut token) = ss.get() else { break };
            if token.is_ascii_whitespace() {
                break;
            }
            if num_castling_rights == 0 && token == b'-' {
                ss.skip_ws();
                break;
            }
            num_castling_rights += 1;
            if num_castling_rights > 4 {
                return err("Invalid FEN. Maximum of 4 castling rights can be specified.");
            }
            let mut rsq = SQ_NONE;
            let mut ksq = SQ_NONE;
            let c = if token.is_ascii_lowercase() {
                BLACK
            } else {
                WHITE
            };
            let rook = make_piece(c, ROOK);
            let king = make_piece(c, KING);
            token = token.to_ascii_uppercase();

            if token == b'K' || token == b'Q' {
                let dir: i32 = if token == b'K' { -1 } else { 1 };
                let mut sq = relative_square(c, if token == b'K' { SQ_H1 } else { SQ_A1 }) as i32;
                for _ in 0..7 {
                    let pc = self.piece_on(sq as Square);
                    if pc == king {
                        ksq = sq as Square;
                        break;
                    } else if pc == rook && rsq == SQ_NONE {
                        rsq = sq as Square;
                    }
                    sq += dir;
                }
            } else if (b'A'..=b'H').contains(&token) {
                let cand = make_square((token - b'A') as usize, relative_rank(c, RANK_1));
                if self.piece_on(cand) == rook {
                    rsq = cand;
                }
                let mut sq = relative_square(c, SQ_B1);
                for _ in 0..6 {
                    if self.piece_on(sq) == king {
                        ksq = sq;
                    }
                    sq += 1;
                }
            } else {
                return Err(PositionSetError(format!(
                    "Invalid FEN. Expected castling rights. Got: {}",
                    token as char
                )));
            }
            if ksq != SQ_NONE && rsq != SQ_NONE {
                self.set_castling_right(c, rsq);
            }
        }

        // 4. En passant square
        let mut enpassant = false;
        let mut legal_ep = false;
        let col = ss.get().unwrap_or(b'-');
        if col != b'-' {
            let Some(row) = ss.get() else {
                return err("Invalid FEN. Unexpected end of stream.");
            };
            let stm = self.side_to_move;
            if (b'a'..=b'h').contains(&col) && row == (if stm == WHITE { b'6' } else { b'3' }) {
                let ep = make_square((col - b'a') as usize, (row - b'1') as usize);
                self.st_mut().ep_square = ep;
                let mut pawns = pawn_attacks_from(flip_color(stm), ep) & self.pieces_ct(stm, PAWN);
                let target = self.pieces_ct(flip_color(stm), PAWN)
                    & square_bb(sq_add(ep, pawn_push(flip_color(stm))));
                let occ = self.pieces() ^ target ^ square_bb(ep);
                enpassant = pawns != 0
                    && target != 0
                    && self.pieces() & (square_bb(ep) | square_bb(sq_add(ep, pawn_push(stm)))) == 0;
                while pawns != 0 {
                    let p = pop_lsb(&mut pawns);
                    legal_ep |= self.attackers_to_occ(self.king_square(stm), occ ^ square_bb(p))
                        & self.pieces_c(flip_color(stm))
                        & !target
                        == 0;
                }
            } else {
                return err("Invalid FEN. Invalid en-passant square.");
            }
        }
        if !enpassant || !legal_ep {
            self.st_mut().ep_square = SQ_NONE;
        }

        // 5-6. Halfmove clock and fullmove number
        let rule50 = ss.int();
        let game_ply = if rule50.is_some() { ss.int() } else { None };
        self.st_mut().rule50 = rule50.unwrap_or(0);
        self.game_ply = game_ply.unwrap_or(0);

        if !(0..=32767).contains(&self.st().rule50) {
            return err("Unsupported position. Rule50 counter out of range.");
        }
        if !(0..=100000).contains(&self.game_ply) {
            return err("Unsupported position. Game ply out of range.");
        }
        self.game_ply = (2 * (self.game_ply - 1)).max(0) + (self.side_to_move == BLACK) as i32;

        self.chess960 = is_chess960;
        self.set_state();

        if self.attackers_to_exist(
            self.king_square(flip_color(self.side_to_move)),
            self.pieces(),
            self.side_to_move,
        ) {
            return err("Unsupported position. King can be captured.");
        }
        Ok(())
    }

    fn set_castling_right(&mut self, c: Color, rfrom: Square) {
        let kfrom = self.king_square(c);
        let cr = color_castling(c, if kfrom < rfrom { KING_SIDE } else { QUEEN_SIDE });
        self.st_mut().castling_rights |= cr;
        self.castling_rights_mask[kfrom] |= cr;
        self.castling_rights_mask[rfrom] |= cr;
        self.castling_rook_square[cr] = rfrom;
        let kto = relative_square(c, if cr & KING_SIDE != 0 { SQ_G1 } else { SQ_C1 });
        let rto = relative_square(c, if cr & KING_SIDE != 0 { SQ_F1 } else { SQ_D1 });
        self.castling_path[cr] = (between_bb(rfrom, rto) | between_bb(kfrom, kto))
            & !(square_bb(kfrom) | square_bb(rfrom));
    }

    fn set_check_info(&mut self) {
        self.update_slider_blockers(WHITE);
        self.update_slider_blockers(BLACK);
        let them = flip_color(self.side_to_move);
        let ksq = self.king_square(them);
        let (b, r) = both_attacks_bb(ksq, self.pieces());
        let st = self.st_mut();
        st.check_squares[PAWN] = pawn_attacks_from(them, ksq);
        st.check_squares[KNIGHT] = pa(KNIGHT, ksq);
        st.check_squares[BISHOP] = b;
        st.check_squares[ROOK] = r;
        st.check_squares[QUEEN] = b | r;
        st.check_squares[KING] = 0;
        st.check_squares[0] = 0;
        st.check_squares[7] = 0;
    }

    fn set_state(&mut self) {
        let t = tables();
        let stm = self.side_to_move;
        let checkers = self.attackers_to(self.king_square(stm)) & self.pieces_c(flip_color(stm));
        {
            let st = self.st_mut();
            st.key = 0;
            st.minor_piece_key = 0;
            st.non_pawn_key = [0, 0];
            st.pawn_key = t.zobrist_no_pawns;
            st.non_pawn_material = [0, 0];
            st.checkers_bb = checkers;
        }
        self.set_check_info();

        let mut b = self.pieces();
        while b != 0 {
            let s = pop_lsb(&mut b);
            let pc = self.piece_on(s);
            let st = self.st_mut();
            st.key ^= t.psq(pc, s);
            if type_of(pc) == PAWN {
                st.pawn_key ^= t.psq(pc, s);
            } else {
                st.non_pawn_key[color_of(pc)] ^= t.psq(pc, s);
                if type_of(pc) != KING {
                    st.non_pawn_material[color_of(pc)] += PIECE_VALUE[pc];
                    if type_of(pc) <= BISHOP {
                        st.minor_piece_key ^= t.psq(pc, s);
                    }
                }
            }
        }
        let mk = self.compute_material_key();
        let st = self.st_mut();
        if st.ep_square != SQ_NONE {
            st.key ^= t.zobrist_enpassant[file_of(st.ep_square)];
        }
        if stm == BLACK {
            st.key ^= t.zobrist_side;
        }
        st.key ^= t.zobrist_castling[st.castling_rights];
        st.material_key = mk;
    }

    fn compute_material_key(&self) -> Key {
        let t = tables();
        let mut k = 0;
        for pc in PIECES {
            for cnt in 0..self.piece_count[pc] {
                k ^= t.psq(pc, 8 + cnt as usize);
            }
        }
        k
    }

    /// Returns a FEN representation of the position (Shredder-FEN for Chess960).
    pub fn fen(&self) -> String {
        let mut s = String::new();
        for r in (0..8).rev() {
            let mut f = 0;
            while f < 8 {
                let mut empty = 0;
                while f < 8 && self.empty(make_square(f, r)) {
                    empty += 1;
                    f += 1;
                }
                if empty > 0 {
                    s.push((b'0' + empty) as char);
                }
                if f < 8 {
                    s.push(PIECE_TO_CHAR[self.piece_on(make_square(f, r))] as char);
                    f += 1;
                }
            }
            if r > 0 {
                s.push('/');
            }
        }
        s.push_str(if self.side_to_move == WHITE {
            " w "
        } else {
            " b "
        });
        if self.can_castle(WHITE_OO) {
            s.push(if self.chess960 {
                (b'A' + file_of(self.castling_rook_square(WHITE_OO)) as u8) as char
            } else {
                'K'
            });
        }
        if self.can_castle(WHITE_OOO) {
            s.push(if self.chess960 {
                (b'A' + file_of(self.castling_rook_square(WHITE_OOO)) as u8) as char
            } else {
                'Q'
            });
        }
        if self.can_castle(BLACK_OO) {
            s.push(if self.chess960 {
                (b'a' + file_of(self.castling_rook_square(BLACK_OO)) as u8) as char
            } else {
                'k'
            });
        }
        if self.can_castle(BLACK_OOO) {
            s.push(if self.chess960 {
                (b'a' + file_of(self.castling_rook_square(BLACK_OOO)) as u8) as char
            } else {
                'q'
            });
        }
        if !self.can_castle(ANY_CASTLING) {
            s.push('-');
        }
        if self.ep_square() == SQ_NONE {
            s.push_str(" - ");
        } else {
            s.push(' ');
            s.push_str(&square_to_string(self.ep_square()));
            s.push(' ');
        }
        s.push_str(&format!(
            "{} {}",
            self.st().rule50,
            1 + (self.game_ply - (self.side_to_move == BLACK) as i32) / 2
        ));
        s
    }

    fn update_slider_blockers(&mut self, c: Color) {
        let ksq = self.king_square(c);
        let them = flip_color(c);
        let mut snipers = ((pa(ROOK, ksq) & self.pieces_tt(QUEEN, ROOK))
            | (pa(BISHOP, ksq) & self.pieces_tt(QUEEN, BISHOP)))
            & self.pieces_c(them);
        let occupancy = self.pieces() ^ snipers;
        let mut blockers = 0;
        let mut pinners = 0;
        while snipers != 0 {
            let sniper_sq = pop_lsb(&mut snipers);
            let b = between_bb(ksq, sniper_sq) & occupancy;
            if b != 0 && !more_than_one(b) {
                blockers |= b;
                if b & self.pieces_c(c) != 0 {
                    pinners |= square_bb(sniper_sq);
                }
            }
        }
        let st = self.st_mut();
        st.blockers_for_king[c] = blockers;
        st.pinners[them] = pinners;
    }

    #[inline(always)]
    pub fn attackers_to_occ(&self, s: Square, occupied: Bitboard) -> Bitboard {
        let (b, r) = both_attacks_bb(s, occupied);
        (r & self.pieces_tt(ROOK, QUEEN))
            | (b & self.pieces_tt(BISHOP, QUEEN))
            | (pawn_attacks_from(BLACK, s) & self.pieces_ct(WHITE, PAWN))
            | (pawn_attacks_from(WHITE, s) & self.pieces_ct(BLACK, PAWN))
            | (pa(KNIGHT, s) & self.pieces_t(KNIGHT))
            | (pa(KING, s) & self.pieces_t(KING))
    }
    #[inline(always)]
    pub fn attackers_to(&self, s: Square) -> Bitboard {
        self.attackers_to_occ(s, self.pieces())
    }

    #[inline(always)]
    pub fn attackers_to_exist(&self, s: Square, occupied: Bitboard, c: Color) -> bool {
        (rook_attacks(s, occupied) & self.pieces_ctt(c, ROOK, QUEEN)) != 0
            || (bishop_attacks(s, occupied) & self.pieces_ctt(c, BISHOP, QUEEN)) != 0
            || (pawn_attacks_from(flip_color(c), s) & self.pieces_ct(c, PAWN)) != 0
            || (pa(KNIGHT, s) & self.pieces_ct(c, KNIGHT)) != 0
            || (pa(KING, s) & self.pieces_ct(c, KING)) != 0
    }

    /// Tests whether a pseudo-legal move is legal
    pub fn legal(&self, m: Move) -> bool {
        let us = self.side_to_move;
        let from = m.from_sq();
        let mut to = m.to_sq();

        if m.type_of() == CASTLING {
            to = relative_square(us, if to > from { SQ_G1 } else { SQ_C1 });
            let step: i32 = if to > from { WEST } else { EAST };
            let mut s = to;
            while s != from {
                if self.attackers_to_exist(s, self.pieces(), flip_color(us)) {
                    return false;
                }
                s = sq_add(s, step);
            }
            return !self.chess960 || self.blockers_for_king(us) & square_bb(m.to_sq()) == 0;
        }

        if type_of(self.piece_on(from)) == KING {
            return !self.attackers_to_exist(to, self.pieces() ^ square_bb(from), flip_color(us));
        }

        self.blockers_for_king(us) & square_bb(from) == 0
            || line_bb(from, to) & self.pieces_ct(us, KING) != 0
    }

    /// Tests whether a random move (e.g. from the TT) is pseudo-legal.
    pub fn pseudo_legal(&self, m: Move) -> bool {
        let us = self.side_to_move;
        let from = m.from_sq();
        let to = m.to_sq();
        let pc = self.moved_piece(m);

        if m.type_of() != NORMAL {
            return if self.checkers() != 0 {
                MoveList::new(self, GenType::Evasions).contains(m)
            } else {
                MoveList::new(self, GenType::NonEvasions).contains(m)
            };
        }

        if pc == NO_PIECE || color_of(pc) != us {
            return false;
        }
        if self.pieces_c(us) & square_bb(to) != 0 {
            return false;
        }

        if type_of(pc) == PAWN {
            if (RANK_8_BB | RANK_1_BB) & square_bb(to) != 0 {
                return false;
            }
            let push = pawn_push(us);
            let is_capture =
                pawn_attacks_from(us, from) & self.pieces_c(flip_color(us)) & square_bb(to) != 0;
            let is_single = sq_add(from, push) == to && self.empty(to);
            let is_double = from as i32 + 2 * push == to as i32
                && relative_rank_sq(us, from) == RANK_2
                && self.empty(to)
                && self.empty(sq_add(to, -push));
            if !(is_capture || is_single || is_double) {
                return false;
            }
        } else if attacks_bb(type_of(pc), from, self.pieces()) & square_bb(to) == 0 {
            return false;
        }

        if self.checkers() != 0 && type_of(pc) != KING {
            if more_than_one(self.checkers()) {
                return false;
            }
            if between_bb(self.king_square(us), lsb(self.checkers())) & square_bb(to) == 0 {
                return false;
            }
        }
        true
    }

    /// Tests whether a pseudo-legal move gives a check
    pub fn gives_check(&self, m: Move) -> bool {
        let from = m.from_sq();
        let to = m.to_sq();
        let stm = self.side_to_move;
        let them = flip_color(stm);

        if self.check_squares(type_of(self.piece_on(from))) & square_bb(to) != 0 {
            return true;
        }
        if self.blockers_for_king(them) & square_bb(from) != 0 {
            return line_bb(from, to) & self.pieces_ct(them, KING) == 0 || m.type_of() == CASTLING;
        }
        match m.type_of() {
            NORMAL => false,
            PROMOTION => {
                attacks_bb(m.promotion_type(), to, self.pieces() ^ square_bb(from))
                    & self.pieces_ct(them, KING)
                    != 0
            }
            EN_PASSANT => {
                let capsq = make_square(file_of(to), rank_of(from));
                let b = (self.pieces() ^ square_bb(from) ^ square_bb(capsq)) | square_bb(to);
                let (ba, ra) = both_attacks_bb(self.king_square(them), b);
                (ra & self.pieces_ctt(stm, QUEEN, ROOK))
                    | (ba & self.pieces_ctt(stm, QUEEN, BISHOP))
                    != 0
            }
            _ => {
                let rto = relative_square(stm, if to > from { SQ_F1 } else { SQ_D1 });
                self.check_squares(ROOK) & square_bb(rto) != 0
            }
        }
    }

    /// Makes a move without NNUE bookkeeping (used outside the search tree).
    pub fn do_move_simple(&mut self, m: Move) {
        let gc = self.gives_check(m);
        self.do_move(m, gc, None);
    }

    /// Makes a move, saving all information necessary for undo_move().
    /// When `dirties` is given, records what changed for the NNUE accumulators.
    pub fn do_move(&mut self, m: Move, gives_check: bool, mut dirties: Option<&mut Dirties>) {
        let t = tables();
        let mut k = self.st().key ^ t.zobrist_side;

        // Copy only the "copied" fields (those before `key`); every other field
        // is written below before it can be read.
        {
            const PREFIX: usize = std::mem::offset_of!(StateInfo, key);
            self.states.reserve(1);
            let len = self.states.len();
            unsafe {
                let base = self.states.as_mut_ptr();
                std::ptr::copy_nonoverlapping(
                    base.add(len - 1) as *const u8,
                    base.add(len) as *mut u8,
                    PREFIX,
                );
                self.states.set_len(len + 1);
            }
        }

        self.game_ply += 1;
        {
            let st = self.st_mut();
            st.rule50 += 1;
            st.plies_from_null += 1;
        }

        let us = self.side_to_move;
        let them = flip_color(us);
        let from = m.from_sq();
        let mut to = m.to_sq();
        let pc = self.piece_on(from);
        let mut captured = if m.type_of() == EN_PASSANT {
            make_piece(them, PAWN)
        } else {
            self.piece_on(to)
        };

        if let Some(d) = dirties.as_deref_mut() {
            d.dirty_pawn_pairs.before = [self.pieces_ct(WHITE, PAWN), self.pieces_ct(BLACK, PAWN)];
            d.dirty_piece.pc = pc;
            d.dirty_piece.from = from;
            d.dirty_piece.to = to;
            d.dirty_piece.add_sq = SQ_NONE;
        }

        if m.type_of() == CASTLING {
            let (rfrom, rto) = self.do_castling::<true>(us, from, &mut to, dirties.as_deref_mut());
            k ^= t.psq(captured, rfrom) ^ t.psq(captured, rto);
            self.st_mut().non_pawn_key[us] ^= t.psq(captured, rfrom) ^ t.psq(captured, rto);
            captured = NO_PIECE;
        } else if captured != NO_PIECE {
            let mut capsq = to;
            if type_of(captured) == PAWN {
                if m.type_of() == EN_PASSANT {
                    capsq = sq_add(capsq, -pawn_push(us));
                    self.remove_piece(capsq, dirties.as_deref_mut().map(|d| &mut d.dirty_threats));
                }
                self.st_mut().pawn_key ^= t.psq(captured, capsq);
            } else {
                let st = self.st_mut();
                st.non_pawn_material[them] -= PIECE_VALUE[captured];
                st.non_pawn_key[them] ^= t.psq(captured, capsq);
                if type_of(captured) <= BISHOP {
                    st.minor_piece_key ^= t.psq(captured, capsq);
                }
            }
            if let Some(d) = dirties.as_deref_mut() {
                d.dirty_piece.remove_pc = captured;
                d.dirty_piece.remove_sq = capsq;
            }
            k ^= t.psq(captured, capsq);
            let idx =
                8 + self.piece_count[captured] as usize - (m.type_of() != EN_PASSANT) as usize;
            let st = self.st_mut();
            st.material_key ^= t.psq(captured, idx);
            st.rule50 = 0;
        } else if let Some(d) = dirties.as_deref_mut() {
            d.dirty_piece.remove_sq = SQ_NONE;
        }

        k ^= t.psq(pc, from) ^ t.psq(pc, to);

        if self.st().ep_square != SQ_NONE {
            k ^= t.zobrist_enpassant[file_of(self.st().ep_square)];
            self.st_mut().ep_square = SQ_NONE;
        }

        let cr_old = self.st().castling_rights;
        k ^= t.zobrist_castling[cr_old];
        let cr_new = cr_old
            & !(unsafe {
                *self.castling_rights_mask.get_unchecked(from)
                    | *self.castling_rights_mask.get_unchecked(to)
            });
        self.st_mut().castling_rights = cr_new;
        k ^= t.zobrist_castling[cr_new];

        if type_of(pc) == PAWN {
            if (to ^ from) == 16 {
                let ep_square = sq_add(to, -pawn_push(us));
                let pawns = pawn_attacks_from(us, ep_square) & self.pieces_ct(them, PAWN);
                if pawns != 0 {
                    let ksq = self.king_square(them);
                    let not_blockers = !self.prev_st(1).blockers_for_king[them];
                    let no_discovery =
                        (square_bb(from) & not_blockers) != 0 || file_of(from) == file_of(ksq);
                    if no_discovery && (pawns & (not_blockers | line_bb(ep_square, ksq))) != 0 {
                        self.st_mut().ep_square = ep_square;
                        k ^= t.zobrist_enpassant[file_of(ep_square)];
                    }
                }
            } else if m.type_of() == PROMOTION {
                let pt = m.promotion_type();
                let promotion = make_piece(us, pt);
                if let Some(d) = dirties.as_deref_mut() {
                    d.dirty_piece.add_pc = promotion;
                    d.dirty_piece.add_sq = to;
                    d.dirty_piece.to = SQ_NONE;
                }
                k ^= t.psq(promotion, to);
                let mk = t.psq(promotion, 8 + self.piece_count[promotion] as usize)
                    ^ t.psq(pc, 8 + self.piece_count[pc] as usize - 1);
                let st = self.st_mut();
                st.material_key ^= mk;
                st.non_pawn_key[us] ^= t.psq(promotion, to);
                if pt <= BISHOP {
                    st.minor_piece_key ^= t.psq(promotion, to);
                }
                st.non_pawn_material[us] += PIECE_VALUE[promotion];
            }
            let st = self.st_mut();
            st.pawn_key ^= t.psq(pc, from) ^ t.psq(pc, to);
            st.rule50 = 0;
        } else {
            let st = self.st_mut();
            st.non_pawn_key[us] ^= t.psq(pc, from) ^ t.psq(pc, to);
            if type_of(pc) <= BISHOP {
                st.minor_piece_key ^= t.psq(pc, from) ^ t.psq(pc, to);
            }
        }

        self.st_mut().key = k;

        if m.type_of() != CASTLING {
            let to_pc = if m.type_of() == PROMOTION {
                make_piece(us, m.promotion_type())
            } else {
                pc
            };
            let mut dts = dirties.as_deref_mut().map(|d| &mut d.dirty_threats);
            if captured != NO_PIECE && m.type_of() != EN_PASSANT {
                self.remove_piece(from, dts.as_deref_mut());
                self.swap_piece(to, to_pc, dts.as_deref_mut());
            } else if pc == to_pc {
                self.move_piece(from, to, dts.as_deref_mut());
            } else {
                self.remove_piece(from, dts.as_deref_mut());
                self.put_piece_d(to_pc, to, dts.as_deref_mut());
            }
        }

        let checkers = if gives_check {
            self.attackers_to(self.king_square(them)) & self.pieces_c(us)
        } else {
            0
        };
        {
            let st = self.st_mut();
            st.captured_piece = captured;
            st.checkers_bb = checkers;
        }
        self.side_to_move = them;
        self.set_check_info();

        // Repetition info: ply distance from the previous occurrence of the same
        // position, negative in the 3-fold case, or zero if not repeated.
        let mut repetition = 0;
        let end = self.st().rule50.min(self.st().plies_from_null);
        if end >= 4 {
            let cur = self.states.len() - 1;
            let key = self.st().key;
            let mut stp = cur - 2;
            let mut i = 4;
            while i <= end {
                stp -= 2;
                let s = &self.states[stp];
                if s.key == key {
                    repetition = if s.repetition != 0 { -i } else { i };
                    break;
                }
                i += 2;
            }
        }
        self.st_mut().repetition = repetition;

        if let Some(d) = dirties {
            d.dirty_pawn_pairs.after = [self.pieces_ct(WHITE, PAWN), self.pieces_ct(BLACK, PAWN)];
        }
    }

    /// Unmakes a move, restoring the position exactly.
    pub fn undo_move(&mut self, m: Move) {
        self.side_to_move = flip_color(self.side_to_move);
        let us = self.side_to_move;
        let from = m.from_sq();
        let mut to = m.to_sq();

        if m.type_of() == PROMOTION {
            self.swap_piece(to, make_piece(us, PAWN), None);
        }

        if m.type_of() == CASTLING {
            self.do_castling::<false>(us, from, &mut to, None);
        } else {
            self.move_piece(to, from, None);
            let captured = self.st().captured_piece;
            if captured != NO_PIECE {
                let mut capsq = to;
                if m.type_of() == EN_PASSANT {
                    capsq = sq_add(capsq, -pawn_push(us));
                }
                self.put_piece(captured, capsq);
            }
        }
        self.states.pop();
        self.game_ply -= 1;
    }

    fn do_castling<const DO: bool>(
        &mut self,
        us: Color,
        from: Square,
        to: &mut Square,
        dirties: Option<&mut Dirties>,
    ) -> (Square, Square) {
        let king_side = *to > from;
        let rfrom = *to;
        let rto = relative_square(us, if king_side { SQ_F1 } else { SQ_D1 });
        *to = relative_square(us, if king_side { SQ_G1 } else { SQ_C1 });

        let mut dts = None;
        if let Some(d) = dirties {
            if DO {
                d.dirty_piece.to = *to;
                d.dirty_piece.remove_pc = make_piece(us, ROOK);
                d.dirty_piece.add_pc = make_piece(us, ROOK);
                d.dirty_piece.remove_sq = rfrom;
                d.dirty_piece.add_sq = rto;
            }
            dts = Some(&mut d.dirty_threats);
        }

        self.remove_piece(if DO { from } else { *to }, dts.as_deref_mut());
        self.remove_piece(if DO { rfrom } else { rto }, dts.as_deref_mut());
        self.put_piece_d(
            make_piece(us, KING),
            if DO { *to } else { from },
            dts.as_deref_mut(),
        );
        self.put_piece_d(
            make_piece(us, ROOK),
            if DO { rto } else { rfrom },
            dts.as_deref_mut(),
        );
        (rfrom, rto)
    }

    /// Flips the side to move without executing any move on the board.
    pub fn do_null_move(&mut self) {
        let t = tables();
        let new_st = *self.st();
        self.states.push(new_st);
        let st = self.st_mut();
        if st.ep_square != SQ_NONE {
            st.key ^= t.zobrist_enpassant[file_of(st.ep_square)];
            st.ep_square = SQ_NONE;
        }
        st.key ^= t.zobrist_side;
        st.plies_from_null = 0;
        st.captured_piece = NO_PIECE;
        self.side_to_move = flip_color(self.side_to_move);
        self.set_check_info();
        self.st_mut().repetition = 0;
    }

    pub fn undo_null_move(&mut self) {
        self.states.pop();
        self.side_to_move = flip_color(self.side_to_move);
    }

    /// Key of the position after a (non-special) move, used for TT prefetching.
    #[inline]
    pub fn prefetch_key(&self, m: Move) -> Key {
        let t = tables();
        let from = m.from_sq();
        let to = m.to_sq();
        let pc = self.piece_on(from);
        let captured = self.piece_on(to);
        let mut k = self.st().key ^ t.zobrist_side;
        k ^= t.psq(captured, to) ^ t.psq(pc, to) ^ t.psq(pc, from);
        if captured != NO_PIECE || type_of(pc) == PAWN {
            return k;
        }
        self.adjust_key50::<true>(k)
    }

    /// Static Exchange Evaluation: is the SEE value of the move >= threshold?
    pub fn see_ge(&self, m: Move, threshold: i32) -> bool {
        if m.type_of() != NORMAL {
            return VALUE_ZERO >= threshold;
        }
        let from = m.from_sq();
        let to = m.to_sq();

        let mut swap = PIECE_VALUE[self.piece_on(to)] - threshold;
        if swap < 0 {
            return false;
        }
        swap = PIECE_VALUE[self.piece_on(from)] - swap;
        if swap <= 0 {
            return true;
        }

        let mut occupied = self.pieces() ^ square_bb(from) ^ square_bb(to);
        let mut stm = self.side_to_move;
        let mut attackers = self.attackers_to_occ(to, occupied);
        let mut res = 1;

        loop {
            stm = flip_color(stm);
            attackers &= occupied;

            let mut stm_attackers = attackers & self.pieces_c(stm);
            if stm_attackers == 0 {
                break;
            }
            if self.pinners(flip_color(stm)) & occupied != 0 {
                stm_attackers &= !self.blockers_for_king(stm);
                if stm_attackers == 0 {
                    break;
                }
            }
            res ^= 1;

            if stm_attackers & self.pieces_t(PAWN) != 0 {
                let bb = stm_attackers & self.pieces_t(PAWN);
                swap = PAWN_VALUE - swap;
                if swap < res {
                    break;
                }
                occupied ^= least_significant_square_bb(bb);
                attackers |= bishop_attacks(to, occupied) & self.pieces_tt(BISHOP, QUEEN);
            } else if stm_attackers & self.pieces_t(KNIGHT) != 0 {
                let bb = stm_attackers & self.pieces_t(KNIGHT);
                swap = KNIGHT_VALUE - swap;
                if swap < res {
                    break;
                }
                occupied ^= least_significant_square_bb(bb);
            } else if stm_attackers & self.pieces_t(BISHOP) != 0 {
                let bb = stm_attackers & self.pieces_t(BISHOP);
                swap = BISHOP_VALUE - swap;
                if swap < res {
                    break;
                }
                occupied ^= least_significant_square_bb(bb);
                attackers |= bishop_attacks(to, occupied) & self.pieces_tt(BISHOP, QUEEN);
            } else if stm_attackers & self.pieces_t(ROOK) != 0 {
                let bb = stm_attackers & self.pieces_t(ROOK);
                swap = ROOK_VALUE - swap;
                if swap < res {
                    break;
                }
                occupied ^= least_significant_square_bb(bb);
                attackers |= rook_attacks(to, occupied) & self.pieces_tt(ROOK, QUEEN);
            } else if stm_attackers & self.pieces_t(QUEEN) != 0 {
                let bb = stm_attackers & self.pieces_t(QUEEN);
                swap = QUEEN_VALUE - swap;
                occupied ^= least_significant_square_bb(bb);
                let (ba, ra) = both_attacks_bb(to, occupied);
                attackers |=
                    (ba & self.pieces_tt(BISHOP, QUEEN)) | (ra & self.pieces_tt(ROOK, QUEEN));
            } else {
                // KING: if we "capture" with the king but the opponent still has attackers, reverse the result.
                return if attackers & !self.pieces_c(stm) != 0 {
                    (res ^ 1) != 0
                } else {
                    res != 0
                };
            }
        }
        res != 0
    }

    /// Draw by 50-move rule or repetition (stalemates are not detected).
    pub fn is_draw(&self, ply: i32) -> bool {
        if self.st().rule50 > 99
            && (self.checkers() == 0 || MoveList::new(self, GenType::Legal).len() > 0)
        {
            return true;
        }
        self.is_repetition(ply)
    }

    #[inline]
    pub fn is_repetition(&self, ply: i32) -> bool {
        let r = self.st().repetition;
        r != 0 && r < ply
    }

    pub fn has_repeated(&self) -> bool {
        let mut idx = self.states.len() - 1;
        let mut end = self.st().rule50.min(self.st().plies_from_null);
        while end >= 4 {
            end -= 1;
            if self.states[idx].repetition != 0 {
                return true;
            }
            idx -= 1;
        }
        false
    }

    /// Tests if the position has a move which draws by repetition.
    pub fn upcoming_repetition(&self, ply: i32) -> bool {
        let end = self.st().rule50.min(self.st().plies_from_null);
        if end < 3 {
            return false;
        }
        let t = tables();
        let original_key = self.st().key;
        let mut stp = self.states.len() - 2;
        let mut other = original_key ^ self.states[stp].key ^ t.zobrist_side;

        let mut i = 3;
        while i <= end {
            stp -= 1;
            other ^= self.states[stp].key ^ self.states[stp - 1].key ^ t.zobrist_side;
            stp -= 1;
            if other != 0 {
                i += 2;
                continue;
            }
            let move_key = original_key ^ self.states[stp].key;
            let mut j = h1(move_key);
            let hit = if t.cuckoo[j] == move_key {
                true
            } else {
                j = h2(move_key);
                t.cuckoo[j] == move_key
            };
            if hit {
                let mv = t.cuckoo_move[j];
                let s1 = mv.from_sq();
                let s2 = mv.to_sq();
                if (between_bb(s1, s2) ^ square_bb(s2)) & self.pieces() == 0 {
                    if ply > i {
                        return true;
                    }
                    if self.states[stp].repetition != 0 {
                        return true;
                    }
                }
            }
            i += 2;
        }
        false
    }

    // ---- Piece placement -------------------------------------------------

    #[inline(always)]
    pub fn put_piece(&mut self, pc: Piece, s: Square) {
        let b = square_bb(s);
        unsafe {
            *self.board.get_unchecked_mut(s) = pc as u8;
            self.by_type_bb[ALL_PIECES] |= b;
            *self.by_type_bb.get_unchecked_mut(type_of(pc)) |= b;
            *self.by_color_bb.get_unchecked_mut(color_of(pc)) |= b;
            *self.piece_count.get_unchecked_mut(pc) += 1;
            *self
                .piece_count
                .get_unchecked_mut(make_piece(color_of(pc), ALL_PIECES)) += 1;
        }
    }

    #[inline(always)]
    fn put_piece_d(&mut self, pc: Piece, s: Square, dts: Option<&mut DirtyThreatList>) {
        self.put_piece(pc, s);
        if let Some(d) = dts {
            self.update_piece_threats::<true>(pc, true, s, d, !0);
        }
    }

    #[inline(always)]
    fn remove_piece(&mut self, s: Square, dts: Option<&mut DirtyThreatList>) {
        let pc = self.board[s] as Piece;
        if let Some(d) = dts {
            self.update_piece_threats::<true>(pc, false, s, d, !0);
        }
        let b = square_bb(s);
        unsafe {
            self.by_type_bb[ALL_PIECES] ^= b;
            *self.by_type_bb.get_unchecked_mut(type_of(pc)) ^= b;
            *self.by_color_bb.get_unchecked_mut(color_of(pc)) ^= b;
            *self.board.get_unchecked_mut(s) = NO_PIECE as u8;
            *self.piece_count.get_unchecked_mut(pc) -= 1;
            *self
                .piece_count
                .get_unchecked_mut(make_piece(color_of(pc), ALL_PIECES)) -= 1;
        }
    }

    #[inline(always)]
    fn move_piece(&mut self, from: Square, to: Square, mut dts: Option<&mut DirtyThreatList>) {
        let pc = self.board[from] as Piece;
        let from_to = square_bb(from) | square_bb(to);
        if let Some(d) = dts.as_deref_mut() {
            self.update_piece_threats::<true>(pc, false, from, d, from_to);
        }
        unsafe {
            self.by_type_bb[ALL_PIECES] ^= from_to;
            *self.by_type_bb.get_unchecked_mut(type_of(pc)) ^= from_to;
            *self.by_color_bb.get_unchecked_mut(color_of(pc)) ^= from_to;
            *self.board.get_unchecked_mut(from) = NO_PIECE as u8;
            *self.board.get_unchecked_mut(to) = pc as u8;
        }
        if let Some(d) = dts {
            self.update_piece_threats::<true>(pc, true, to, d, from_to);
        }
    }

    #[inline(always)]
    fn swap_piece(&mut self, s: Square, pc: Piece, mut dts: Option<&mut DirtyThreatList>) {
        let old = self.board[s] as Piece;
        self.remove_piece(s, None);
        if let Some(d) = dts.as_deref_mut() {
            self.update_piece_threats::<false>(old, false, s, d, !0);
        }
        self.put_piece(pc, s);
        if let Some(d) = dts {
            self.update_piece_threats::<false>(pc, true, s, d, !0);
        }
    }

    fn update_piece_threats<const COMPUTE_RAY: bool>(
        &self,
        pc: Piece,
        put_piece: bool,
        s: Square,
        dts: &mut DirtyThreatList,
        no_rays_containing: Bitboard,
    ) {
        let occupied = self.pieces();
        let (b_attacks, r_attacks) = both_attacks_bb(s, occupied);
        let slider_attacks = b_attacks | r_attacks;
        let occupied_no_k = occupied ^ self.pieces_t(KING);
        let pt = type_of(pc);
        let sliders =
            (self.pieces_tt(BISHOP, QUEEN) & b_attacks) | (self.pieces_tt(ROOK, QUEEN) & r_attacks);

        #[inline(always)]
        fn can_slider_threat(pc: Piece, slider: Piece) -> bool {
            type_of(pc) != QUEEN || type_of(slider) == QUEEN
        }

        let process_sliders = |dts: &mut DirtyThreatList, add_direct: bool| {
            let mut b = sliders;
            while b != 0 {
                let slider_sq = pop_lsb(&mut b);
                let slider = self.piece_on(slider_sq);
                let ray = ray_pass_bb(slider_sq, s);
                let discovered = ray & slider_attacks & occupied_no_k;
                if discovered != 0 && (ray & no_rays_containing) != no_rays_containing {
                    let threatened_sq = lsb(discovered);
                    let threatened_pc = self.piece_on(threatened_sq);
                    if can_slider_threat(threatened_pc, slider) {
                        dts.push(DirtyThreat::new(
                            slider,
                            threatened_pc,
                            slider_sq,
                            threatened_sq,
                            !put_piece,
                        ));
                    }
                }
                if add_direct && can_slider_threat(pc, slider) {
                    dts.push(DirtyThreat::new(slider, pc, slider_sq, s, put_piece));
                }
            }
        };

        if pt == KING {
            if COMPUTE_RAY {
                process_sliders(dts, false);
            }
            return;
        }

        let threat_targets = if pt == PAWN {
            self.pieces_tt(KNIGHT, ROOK)
        } else if pt == BISHOP || pt == ROOK {
            self.pieces_t(PAWN)
                | self.pieces_t(KNIGHT)
                | self.pieces_t(BISHOP)
                | self.pieces_t(ROOK)
        } else {
            occupied_no_k
        };
        let mut threatened = (match pt {
            BISHOP => b_attacks,
            ROOK => r_attacks,
            QUEEN => slider_attacks,
            PAWN => pa(color_of(pc), s),
            _ => pa(pt, s),
        }) & threat_targets;
        let mut incoming = pa(KNIGHT, s) & self.pieces_t(KNIGHT);
        if pt == KNIGHT || pt == ROOK {
            incoming |= (pawn_attacks_from(WHITE, s) & self.pieces_ct(BLACK, PAWN))
                | (pawn_attacks_from(BLACK, s) & self.pieces_ct(WHITE, PAWN));
        }

        while threatened != 0 {
            let tsq = pop_lsb(&mut threatened);
            let tpc = self.piece_on(tsq);
            dts.push(DirtyThreat::new(pc, tpc, s, tsq, put_piece));
        }

        if COMPUTE_RAY {
            process_sliders(dts, true);
        } else {
            incoming |= if pt == QUEEN {
                sliders & self.pieces_t(QUEEN)
            } else {
                sliders
            };
        }

        while incoming != 0 {
            let src_sq = pop_lsb(&mut incoming);
            let src_pc = self.piece_on(src_sq);
            dts.push(DirtyThreat::new(src_pc, pc, src_sq, s, put_piece));
        }
    }

    // ---- Accessors -------------------------------------------------------

    #[inline(always)]
    pub fn side_to_move(&self) -> Color {
        self.side_to_move
    }
    #[inline(always)]
    pub fn piece_on(&self, s: Square) -> Piece {
        unsafe { *self.board.get_unchecked(s) as Piece }
    }
    #[inline(always)]
    pub fn piece_array(&self) -> &[u8; 64] {
        &self.board
    }
    #[inline(always)]
    pub fn empty(&self, s: Square) -> bool {
        self.piece_on(s) == NO_PIECE
    }
    #[inline(always)]
    pub fn moved_piece(&self, m: Move) -> Piece {
        self.piece_on(m.from_sq())
    }
    #[inline(always)]
    pub fn pieces(&self) -> Bitboard {
        self.by_type_bb[ALL_PIECES]
    }
    #[inline(always)]
    pub fn pieces_t(&self, pt: PieceType) -> Bitboard {
        unsafe { *self.by_type_bb.get_unchecked(pt) }
    }
    #[inline(always)]
    pub fn pieces_tt(&self, a: PieceType, b: PieceType) -> Bitboard {
        self.pieces_t(a) | self.pieces_t(b)
    }
    #[inline(always)]
    pub fn pieces_c(&self, c: Color) -> Bitboard {
        unsafe { *self.by_color_bb.get_unchecked(c) }
    }
    #[inline(always)]
    pub fn pieces_ct(&self, c: Color, pt: PieceType) -> Bitboard {
        self.pieces_c(c) & self.pieces_t(pt)
    }
    #[inline(always)]
    pub fn pieces_ctt(&self, c: Color, a: PieceType, b: PieceType) -> Bitboard {
        self.pieces_c(c) & (self.pieces_t(a) | self.pieces_t(b))
    }
    #[inline(always)]
    pub fn count(&self, c: Color, pt: PieceType) -> i32 {
        unsafe { *self.piece_count.get_unchecked(make_piece(c, pt)) }
    }
    #[inline(always)]
    pub fn count_both(&self, pt: PieceType) -> i32 {
        self.count(WHITE, pt) + self.count(BLACK, pt)
    }
    #[inline(always)]
    pub fn king_square(&self, c: Color) -> Square {
        lsb(self.pieces_ct(c, KING))
    }
    #[inline(always)]
    pub fn ep_square(&self) -> Square {
        self.st().ep_square
    }
    #[inline(always)]
    pub fn can_castle(&self, cr: usize) -> bool {
        self.st().castling_rights & cr != 0
    }
    #[inline(always)]
    pub fn castling_impeded(&self, cr: usize) -> bool {
        self.pieces() & self.castling_path[cr] != 0
    }
    #[inline(always)]
    pub fn castling_rook_square(&self, cr: usize) -> Square {
        self.castling_rook_square[cr]
    }
    #[inline(always)]
    pub fn checkers(&self) -> Bitboard {
        self.st().checkers_bb
    }
    #[inline(always)]
    pub fn blockers_for_king(&self, c: Color) -> Bitboard {
        unsafe { *self.st().blockers_for_king.get_unchecked(c) }
    }
    #[inline(always)]
    pub fn pinners(&self, c: Color) -> Bitboard {
        unsafe { *self.st().pinners.get_unchecked(c) }
    }
    #[inline(always)]
    pub fn check_squares(&self, pt: PieceType) -> Bitboard {
        unsafe { *self.st().check_squares.get_unchecked(pt) }
    }
    #[inline(always)]
    pub fn attacks_by(&self, pt: PieceType, c: Color) -> Bitboard {
        if pt == PAWN {
            return pawn_attacks_bb(c, self.pieces_ct(c, PAWN));
        }
        let mut threats = 0;
        let mut attackers = self.pieces_ct(c, pt);
        while attackers != 0 {
            threats |= attacks_bb(pt, pop_lsb(&mut attackers), self.pieces());
        }
        threats
    }
    #[inline(always)]
    pub fn key(&self) -> Key {
        self.adjust_key50::<false>(self.st().key)
    }
    #[inline(always)]
    fn adjust_key50<const AFTER_MOVE: bool>(&self, k: Key) -> Key {
        let lim = 14 - AFTER_MOVE as i32;
        if self.st().rule50 < lim {
            k
        } else {
            k ^ make_key(((self.st().rule50 - lim) / 8) as u64)
        }
    }
    #[inline(always)]
    pub fn raw_key(&self) -> Key {
        self.st().key
    }
    #[inline(always)]
    pub fn pawn_key(&self) -> Key {
        self.st().pawn_key
    }
    #[inline(always)]
    pub fn material_key(&self) -> Key {
        self.st().material_key
    }
    #[inline(always)]
    pub fn minor_piece_key(&self) -> Key {
        self.st().minor_piece_key
    }
    #[inline(always)]
    pub fn non_pawn_key(&self, c: Color) -> Key {
        self.st().non_pawn_key[c]
    }
    #[inline(always)]
    pub fn non_pawn_material_c(&self, c: Color) -> Value {
        self.st().non_pawn_material[c]
    }
    #[inline(always)]
    pub fn non_pawn_material(&self) -> Value {
        self.non_pawn_material_c(WHITE) + self.non_pawn_material_c(BLACK)
    }
    #[inline(always)]
    pub fn game_ply(&self) -> i32 {
        self.game_ply
    }
    #[inline(always)]
    pub fn rule50_count(&self) -> i32 {
        self.st().rule50
    }
    #[inline(always)]
    pub fn plies_from_null(&self) -> i32 {
        self.st().plies_from_null
    }
    #[inline(always)]
    pub fn is_chess960(&self) -> bool {
        self.chess960
    }
    #[inline(always)]
    pub fn captured_piece(&self) -> Piece {
        self.st().captured_piece
    }
    #[inline(always)]
    pub fn capture(&self, m: Move) -> bool {
        let mt = m.type_of();
        if mt == NORMAL || mt == PROMOTION {
            return !self.empty(m.to_sq());
        }
        mt == EN_PASSANT
    }
    #[inline(always)]
    pub fn capture_stage(&self, m: Move) -> bool {
        let mt = m.type_of();
        if mt == NORMAL {
            return !self.empty(m.to_sq());
        }
        if mt == PROMOTION {
            return !self.empty(m.to_sq()) || m.promotion_type() == QUEEN;
        }
        mt == EN_PASSANT
    }
    pub fn dtz_is_dtm(&self) -> bool {
        let all = popcount(self.pieces());
        self.count_both(PAWN) == 0 && (all == 3 || (all == 4 && self.pieces_tt(QUEEN, ROOK) == 0))
    }

    /// ASCII board representation (UCI `d` command).
    pub fn pretty(&self) -> String {
        let mut s = String::from("\n +---+---+---+---+---+---+---+---+\n");
        for r in (0..8).rev() {
            for f in 0..8 {
                s.push_str(" | ");
                s.push(PIECE_TO_CHAR[self.piece_on(make_square(f, r))] as char);
            }
            s.push_str(&format!(
                " | {}\n +---+---+---+---+---+---+---+---+\n",
                r + 1
            ));
        }
        s.push_str("   a   b   c   d   e   f   g   h\n");
        s.push_str(&format!(
            "\nFen: {}\nKey: {:016X}\nCheckers: ",
            self.fen(),
            self.key()
        ));
        let mut b = self.checkers();
        while b != 0 {
            s.push_str(&square_to_string(pop_lsb(&mut b)));
            s.push(' ');
        }
        s
    }
}

pub fn square_to_string(s: Square) -> String {
    let mut r = String::with_capacity(2);
    r.push((b'a' + file_of(s) as u8) as char);
    r.push((b'1' + rank_of(s) as u8) as char);
    r
}
