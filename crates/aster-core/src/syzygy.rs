// Aster core. Original attribution and source mapping: syzygy.rs.license.
// SPDX-License-Identifier: GPL-3.0-or-later
// Modified 2026-10-19: source naming and notice layout only.

use crate::bitboard::*;
use crate::movegen::{GenType, MoveList};
use crate::position::Position;
use crate::search::RootMove;
use crate::types::*;
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::{Arc, Mutex, OnceLock, RwLock};

pub type WdlScore = i32;
pub const WDL_LOSS: WdlScore = -2;
pub const WDL_BLESSED_LOSS: WdlScore = -1;
pub const WDL_DRAW: WdlScore = 0;
pub const WDL_CURSED_WIN: WdlScore = 1;
pub const WDL_WIN: WdlScore = 2;

#[derive(Copy, Clone, PartialEq, Eq, Debug)]
pub enum ProbeState {
    Fail,
    Ok,
    ChangeStm,
    ZeroingBestMove,
}

/// Search-time tablebase configuration (the upstream Tablebases::Config).
#[derive(Copy, Clone, Default, Debug)]
pub struct Config {
    pub cardinality: i32,
    pub root_in_tb: bool,
    pub use_rule50: bool,
    pub probe_depth: Depth,
}

const TBPIECES: usize = 7;
const MAX_DTZ: i32 = 1 << 18;

const FLAG_STM: u8 = 1;
const FLAG_MAPPED: u8 = 2;
const FLAG_WIN_PLIES: u8 = 4;
const FLAG_LOSS_PLIES: u8 = 8;
const FLAG_WIDE: u8 = 16;
const FLAG_SINGLE_VALUE: u8 = 128;

const PIECE_TO_CHAR: &[u8] = b" PNBRQK  pnbrqk";
const SYM_COUNT: usize = 4096;

const WDL_TO_VALUE: [Value; 5] = [
    -VALUE_MATE + MAX_PLY + 1,
    VALUE_DRAW - 2,
    VALUE_DRAW,
    VALUE_DRAW + 2,
    VALUE_MATE - MAX_PLY - 1,
];

// ---------------------------------------------------------------------------
// Static encoding tables
// ---------------------------------------------------------------------------

struct Maps {
    map_pawns: [i32; 64],
    map_b1h1h7: [i32; 64],
    map_a1d1d4: [i32; 64],
    map_kk: [[i32; 64]; 10],
    binomial: [[u64; 64]; 6],
    lead_pawn_idx: [[u64; 64]; 6],
    lead_pawns_size: [[u64; 4]; 6],
}

fn off_a1h8(sq: Square) -> i32 {
    rank_of(sq) as i32 - file_of(sq) as i32
}

static MAPS: OnceLock<Maps> = OnceLock::new();

fn maps() -> &'static Maps {
    MAPS.get_or_init(|| {
        let mut m = Maps {
            map_pawns: [0; 64],
            map_b1h1h7: [0; 64],
            map_a1d1d4: [0; 64],
            map_kk: [[0; 64]; 10],
            binomial: [[0; 64]; 6],
            lead_pawn_idx: [[0; 64]; 6],
            lead_pawns_size: [[0; 4]; 6],
        };
        let mut code = 0;
        for s in 0..64 {
            if off_a1h8(s) < 0 {
                m.map_b1h1h7[s] = code;
                code += 1;
            }
        }
        let mut diagonal = Vec::new();
        code = 0;
        for s in 0..=27usize {
            // SQ_A1..=SQ_D4
            if off_a1h8(s) < 0 && file_of(s) <= 3 {
                m.map_a1d1d4[s] = code;
                code += 1;
            } else if off_a1h8(s) == 0 && file_of(s) <= 3 {
                diagonal.push(s);
            }
        }
        for s in diagonal {
            m.map_a1d1d4[s] = code;
            code += 1;
        }
        let mut both_on_diagonal = Vec::new();
        code = 0;
        for idx in 0..10 {
            for s1 in 0..=27usize {
                if m.map_a1d1d4[s1] == idx && (idx != 0 || s1 == SQ_B1) {
                    for s2 in 0..64 {
                        if (PSEUDO_ATTACKS[KING][s1] | square_bb(s1)) & square_bb(s2) != 0 {
                            continue;
                        } else if off_a1h8(s1) == 0 && off_a1h8(s2) > 0 {
                            continue;
                        } else if off_a1h8(s1) == 0 && off_a1h8(s2) == 0 {
                            both_on_diagonal.push((idx as usize, s2));
                        } else {
                            m.map_kk[idx as usize][s2] = code;
                            code += 1;
                        }
                    }
                }
            }
        }
        for (i, s2) in both_on_diagonal {
            m.map_kk[i][s2] = code;
            code += 1;
        }
        m.binomial[0][0] = 1;
        for n in 1..64 {
            for k in 0..6 {
                if k > n {
                    break;
                }
                m.binomial[k][n] = (if k > 0 { m.binomial[k - 1][n - 1] } else { 0 })
                    + (if k < n { m.binomial[k][n - 1] } else { 0 });
            }
        }
        let mut available = 47;
        for lead in 1..=5usize {
            for f in 0..4usize {
                let mut idx = 0u64;
                for r in RANK_2..=6usize {
                    let sq = make_square(f, r);
                    if lead == 1 {
                        m.map_pawns[sq] = available;
                        available -= 1;
                        m.map_pawns[sq ^ 7] = available;
                        available -= 1;
                    }
                    m.lead_pawn_idx[lead][sq] = idx;
                    idx += m.binomial[lead - 1][m.map_pawns[sq] as usize];
                }
                m.lead_pawns_size[lead][f] = idx;
            }
        }
        m
    })
}

// ---------------------------------------------------------------------------
// Table data
// ---------------------------------------------------------------------------

#[derive(Clone)]
struct PairsData {
    flags: u8,
    max_sym_len: u8,
    min_sym_len: u8,
    blocks_num: u32,
    sizeof_block: u64,
    span: u64,
    lowest_sym: usize,
    btree: Vec<[u8; 3]>,
    block_length: usize,
    block_length_size: u32,
    sparse_index: usize,
    sparse_index_size: u64,
    data: usize,
    data_end: usize,
    base64: Vec<u64>,
    symlen: Vec<u8>,
    pieces: [u8; TBPIECES],
    group_idx: [u64; TBPIECES + 1],
    group_len: [i32; TBPIECES + 1],
    map_idx: [u16; 4],
}

impl Default for PairsData {
    fn default() -> Self {
        PairsData {
            flags: 0,
            max_sym_len: 0,
            min_sym_len: 0,
            blocks_num: 0,
            sizeof_block: 0,
            span: 0,
            lowest_sym: 0,
            btree: Vec::new(),
            block_length: 0,
            block_length_size: 0,
            sparse_index: 0,
            sparse_index_size: 0,
            data: 0,
            data_end: 0,
            base64: Vec::new(),
            symlen: Vec::new(),
            pieces: [0; TBPIECES],
            group_idx: [0; TBPIECES + 1],
            group_len: [0; TBPIECES + 1],
            map_idx: [0; 4],
        }
    }
}

#[inline(always)]
fn lr_left(lr: &[u8; 3]) -> u16 {
    (((lr[1] & 0xF) as u16) << 8) | lr[0] as u16
}
#[inline(always)]
fn lr_right(lr: &[u8; 3]) -> u16 {
    ((lr[2] as u16) << 4) | (lr[1] >> 4) as u16
}

#[derive(Copy, Clone, PartialEq, Eq)]
enum TbType {
    Wdl,
    Dtz,
}

struct Mapped {
    mmap: memmap2::Mmap,
    items: [[PairsData; 4]; 2],
    map: usize,
}

struct TbTable {
    kind: TbType,
    file_name_w: String, // e.g. "KRvK" (white-stronger orientation)
    key: Key,
    key2: Key,
    piece_count: i32,
    has_pawns: bool,
    has_unique_pieces: bool,
    pawn_count: [u8; 2],
    mapped: OnceLock<Option<Mapped>>,
}

impl TbTable {
    fn sides(&self) -> usize {
        if self.kind == TbType::Wdl { 2 } else { 1 }
    }
}

impl Mapped {
    #[inline(always)]
    fn get(&self, t: &TbTable, stm: usize, f: usize) -> &PairsData {
        &self.items[stm % t.sides()][if t.has_pawns { f } else { 0 }]
    }
}

// --- little helpers over the mapped bytes ---
#[inline(always)]
fn le_u16(b: &[u8], off: usize) -> u16 {
    u16::from_le_bytes([b[off], b[off + 1]])
}
#[inline(always)]
fn le_u32(b: &[u8], off: usize) -> u32 {
    u32::from_le_bytes(b[off..off + 4].try_into().unwrap())
}
#[inline(always)]
fn be_u32(b: &[u8], off: usize) -> u32 {
    u32::from_be_bytes(b[off..off + 4].try_into().unwrap())
}
#[inline(always)]
fn be_u64(b: &[u8], off: usize) -> u64 {
    u64::from_be_bytes(b[off..off + 8].try_into().unwrap())
}

fn fits(p: usize, count: u64, stride: u64, end: usize) -> bool {
    if p > end {
        return false;
    }
    let room = (end - p) as u64;
    count == 0 || stride <= room / count
}

fn decompress_pairs(b: &[u8], d: &PairsData, idx: u64) -> i32 {
    if d.flags & FLAG_SINGLE_VALUE != 0 {
        return d.min_sym_len as i32;
    }
    let k = (idx / d.span) as u32;
    let mut block = le_u32(b, d.sparse_index + k as usize * 6);
    let mut offset = le_u16(b, d.sparse_index + k as usize * 6 + 4) as i32;
    let diff = (idx % d.span) as i64 - (d.span / 2) as i64;
    offset += diff as i32;

    if block >= d.block_length_size {
        block = d.block_length_size - 1;
    }
    let bl = |i: u32| le_u16(b, d.block_length + 2 * i as usize) as i32;
    while offset < 0 && block > 0 {
        block -= 1;
        offset += bl(block) + 1;
    }
    while offset > bl(block) && block + 1 < d.block_length_size {
        offset -= bl(block) + 1;
        block += 1;
    }

    let mut ptr = d.data + block as usize * d.sizeof_block as usize;
    let mut buf64: u64 = if ptr + 8 <= d.data_end {
        be_u64(b, ptr)
    } else {
        0
    };
    ptr += 8;
    let mut buf64_size: i32 = 64;
    let mut sym: u16;

    loop {
        let mut len = 0usize;
        while buf64 < d.base64[len] {
            len += 1;
        }
        sym = ((buf64 - d.base64[len]) >> (64 - len - d.min_sym_len as usize)) as u16;
        sym = sym.wrapping_add(le_u16(b, d.lowest_sym + 2 * len));
        sym &= (SYM_COUNT - 1) as u16;

        if offset < d.symlen[sym as usize] as i32 + 1 {
            break;
        }
        offset -= d.symlen[sym as usize] as i32 + 1;
        let real_len = len + d.min_sym_len as usize;
        buf64 <<= real_len;
        buf64_size -= real_len as i32;
        if buf64_size <= 32 {
            buf64_size += 32;
            if ptr + 4 <= d.data_end {
                buf64 |= (be_u32(b, ptr) as u64) << (64 - buf64_size);
            }
            ptr += 4;
        }
    }

    while d.symlen[sym as usize] != 0 {
        let left = lr_left(&d.btree[sym as usize]);
        if offset < d.symlen[left as usize] as i32 + 1 {
            sym = left;
        } else {
            offset -= d.symlen[left as usize] as i32 + 1;
            sym = lr_right(&d.btree[sym as usize]);
        }
    }
    lr_left(&d.btree[sym as usize]) as i32
}

fn check_dtz_stm(t: &TbTable, m: &Mapped, stm: usize, f: usize) -> bool {
    if t.kind == TbType::Wdl {
        return true;
    }
    let flags = m.get(t, stm, f).flags;
    (flags & FLAG_STM) as usize == stm || (t.key == t.key2 && !t.has_pawns)
}

fn map_score(t: &TbTable, m: &Mapped, f: usize, mut value: i32, wdl: WdlScore) -> i32 {
    if t.kind == TbType::Wdl {
        return value - 2;
    }
    const WDL_MAP: [usize; 5] = [1, 3, 0, 2, 0];
    let d = m.get(t, 0, f);
    let flags = d.flags;
    let b = &m.mmap[..];
    let idx = d.map_idx[WDL_MAP[(wdl + 2) as usize]] as usize;
    if flags & FLAG_MAPPED != 0 {
        if flags & FLAG_WIDE != 0 {
            value = le_u16(b, m.map + 2 * (idx + value as usize)) as i32;
        } else {
            value = b[m.map + idx + value as usize] as i32;
        }
    }
    if (wdl == WDL_WIN && flags & FLAG_WIN_PLIES == 0)
        || (wdl == WDL_LOSS && flags & FLAG_LOSS_PLIES == 0)
        || wdl == WDL_CURSED_WIN
        || wdl == WDL_BLESSED_LOSS
    {
        value *= 2;
    }
    value + 1
}

fn do_probe_table(
    pos: &Position,
    t: &TbTable,
    m: &Mapped,
    wdl: WdlScore,
    result: &mut ProbeState,
) -> i32 {
    let mp = maps();
    let mut squares = [0usize; TBPIECES];
    let mut pieces = [0u8; TBPIECES];
    let mut size = 0usize;
    let mut lead_pawns_cnt = 0usize;
    let mut lead_pawns: Bitboard = 0;
    let mut tb_file = 0usize;
    let b = &m.mmap[..];

    let symmetric_black_to_move = t.key == t.key2 && pos.side_to_move() == BLACK;
    let black_stronger = pos.material_key() != t.key;
    let flip = symmetric_black_to_move || black_stronger;
    let flip_color = if flip { 8 } else { 0 };
    let flip_squares = if flip { 56 } else { 0 };
    let stm = (flip as usize) ^ pos.side_to_move();

    if t.has_pawns {
        let pc = (m.get(t, 0, 0).pieces[0] ^ flip_color as u8) as Piece;
        let mut bb = pos.pieces_ct(color_of(pc), PAWN);
        lead_pawns = bb;
        loop {
            squares[size] = pop_lsb(&mut bb) ^ flip_squares;
            size += 1;
            if bb == 0 {
                break;
            }
        }
        lead_pawns_cnt = size;
        // std::max_element returns the first maximum
        let mut best = 0;
        for i in 1..lead_pawns_cnt {
            if mp.map_pawns[squares[best]] < mp.map_pawns[squares[i]] {
                best = i;
            }
        }
        squares.swap(0, best);
        tb_file = file_of(squares[0]).min(7 - file_of(squares[0]));
    }

    if !check_dtz_stm(t, m, stm, tb_file) {
        *result = ProbeState::ChangeStm;
        return 0;
    }

    let mut bb = pos.pieces() ^ lead_pawns;
    loop {
        let s = pop_lsb(&mut bb);
        squares[size] = s ^ flip_squares;
        pieces[size] = (pos.piece_on(s) ^ flip_color) as u8;
        size += 1;
        if bb == 0 {
            break;
        }
    }

    let d = m.get(t, stm, tb_file);

    for i in lead_pawns_cnt..size - 1 {
        for j in i + 1..size {
            if d.pieces[i] == pieces[j] {
                pieces.swap(i, j);
                squares.swap(i, j);
                break;
            }
        }
    }

    if file_of(squares[0]) > 3 {
        for sq in squares.iter_mut().take(size) {
            *sq ^= 7;
        }
    }

    let mut idx: u64;
    if t.has_pawns {
        idx = mp.lead_pawn_idx[lead_pawns_cnt][squares[0]];
        squares[1..lead_pawns_cnt].sort_by_key(|&s| mp.map_pawns[s]);
        for i in 1..lead_pawns_cnt {
            idx += mp.binomial[i][mp.map_pawns[squares[i]] as usize];
        }
    } else {
        if rank_of(squares[0]) > 3 {
            for sq in squares.iter_mut().take(size) {
                *sq ^= 56;
            }
        }
        for i in 0..d.group_len[0] as usize {
            if off_a1h8(squares[i]) == 0 {
                continue;
            }
            if off_a1h8(squares[i]) > 0 {
                for sq in squares.iter_mut().take(size).skip(i) {
                    *sq = ((*sq >> 3) | (*sq << 3)) & 63;
                }
            }
            break;
        }

        if t.has_unique_pieces {
            let adjust1 = (squares[1] > squares[0]) as u64;
            let adjust2 = (squares[2] > squares[0]) as u64 + (squares[2] > squares[1]) as u64;
            let (s0, s1, s2) = (squares[0], squares[1], squares[2]);
            idx = if off_a1h8(s0) != 0 {
                (mp.map_a1d1d4[s0] as u64 * 63 + (s1 as u64 - adjust1)) * 62 + s2 as u64 - adjust2
            } else if off_a1h8(s1) != 0 {
                (6 * 63 + rank_of(s0) as u64 * 28 + mp.map_b1h1h7[s1] as u64) * 62 + s2 as u64
                    - adjust2
            } else if off_a1h8(s2) != 0 {
                6 * 63 * 62
                    + 4 * 28 * 62
                    + rank_of(s0) as u64 * 7 * 28
                    + (rank_of(s1) as u64 - adjust1) * 28
                    + mp.map_b1h1h7[s2] as u64
            } else {
                6 * 63 * 62
                    + 4 * 28 * 62
                    + 4 * 7 * 28
                    + rank_of(s0) as u64 * 7 * 6
                    + (rank_of(s1) as u64 - adjust1) * 6
                    + (rank_of(s2) as u64 - adjust2)
            };
        } else {
            idx = mp.map_kk[mp.map_a1d1d4[squares[0]] as usize][squares[1]] as u64;
        }
    }

    // encode_remaining
    idx *= d.group_idx[0];
    let mut group_start = d.group_len[0] as usize;
    let mut remaining_pawns = t.has_pawns && t.pawn_count[1] != 0;
    let mut next = 0usize;
    loop {
        next += 1;
        let glen = d.group_len[next] as usize;
        if glen == 0 {
            break;
        }
        squares[group_start..group_start + glen].sort();
        let mut n: u64 = 0;
        for i in 0..glen {
            let sqi = squares[group_start + i];
            let adjust = squares[..group_start].iter().filter(|&&s| sqi > s).count();
            n += mp.binomial[i + 1][sqi - adjust - 8 * remaining_pawns as usize];
        }
        remaining_pawns = false;
        idx += n * d.group_idx[next];
        group_start += glen;
    }

    map_score(t, m, tb_file, decompress_pairs(b, d, idx), wdl)
}

fn set_groups(t: &TbTable, d: &mut PairsData, order: [i32; 2], f: usize) {
    let mp = maps();
    let mut n = 0usize;
    let mut first_len: i32 = if t.has_pawns {
        0
    } else if t.has_unique_pieces {
        3
    } else {
        2
    };
    d.group_len[n] = 1;
    for i in 1..t.piece_count as usize {
        first_len -= 1;
        if first_len > 0 || d.pieces[i] == d.pieces[i - 1] {
            d.group_len[n] += 1;
        } else {
            n += 1;
            d.group_len[n] = 1;
        }
    }
    n += 1;
    d.group_len[n] = 0;

    let pp = t.has_pawns && t.pawn_count[1] != 0;
    let mut next = if pp { 2 } else { 1 };
    let mut free_squares = 64 - d.group_len[0] - if pp { d.group_len[1] } else { 0 };
    let mut idx: u64 = 1;
    let mut k = 0i32;
    while (next as usize) < n || k == order[0] || k == order[1] {
        if k == order[0] {
            d.group_idx[0] = idx;
            idx *= if t.has_pawns {
                mp.lead_pawns_size[d.group_len[0] as usize][f]
            } else if t.has_unique_pieces {
                31332
            } else {
                462
            };
        } else if k == order[1] {
            d.group_idx[1] = idx;
            idx *= mp.binomial[d.group_len[1] as usize][(48 - d.group_len[0]) as usize];
        } else {
            d.group_idx[next] = idx;
            idx *= mp.binomial[d.group_len[next] as usize][free_squares as usize];
            free_squares -= d.group_len[next];
            next += 1;
        }
        k += 1;
    }
    d.group_idx[n] = idx;
}

const WHITE_C: u8 = 0;
const GREY_C: u8 = 1;
const BLACK_C: u8 = 2;

fn set_symlen(d: &mut PairsData, s: usize, colour: &mut [u8], cyclic: &mut bool) -> u8 {
    colour[s] = GREY_C;
    let sr = lr_right(&d.btree[s]) as usize;
    if sr == 0xFFF {
        colour[s] = BLACK_C;
        return 0;
    }
    let sl = lr_left(&d.btree[s]) as usize;
    if colour[sl] == GREY_C || colour[sr] == GREY_C {
        *cyclic = true;
        colour[s] = BLACK_C;
        return 0;
    }
    if colour[sl] == WHITE_C {
        d.symlen[sl] = set_symlen(d, sl, colour, cyclic);
    }
    if colour[sr] == WHITE_C {
        d.symlen[sr] = set_symlen(d, sr, colour, cyclic);
    }
    colour[s] = BLACK_C;
    d.symlen[sl].wrapping_add(d.symlen[sr]).wrapping_add(1)
}

fn set_sizes(d: &mut PairsData, b: &[u8], mut data: usize, end: usize) -> Option<usize> {
    if !fits(data, 1, 1, end) {
        return None;
    }
    d.flags = b[data];
    data += 1;
    if d.flags & FLAG_SINGLE_VALUE != 0 {
        d.blocks_num = 0;
        d.block_length_size = 0;
        d.span = 0;
        d.sparse_index_size = 0;
        if !fits(data, 1, 1, end) {
            return None;
        }
        d.min_sym_len = b[data];
        return Some(data + 1);
    }
    let zero_at = d
        .group_len
        .iter()
        .take(7)
        .position(|&g| g == 0)
        .unwrap_or(7);
    let tb_size = d.group_idx[zero_at];
    if !fits(data, 9, 1, end) {
        return None;
    }
    if b[data] >= 64 || b[data + 1] >= 64 {
        return None;
    }
    d.sizeof_block = 1u64 << b[data];
    data += 1;
    d.span = 1u64 << b[data];
    data += 1;
    d.sparse_index_size = tb_size.div_ceil(d.span);
    let padding = b[data] as u32;
    data += 1;
    d.blocks_num = le_u32(b, data);
    data += 4;
    d.block_length_size = d.blocks_num + padding;
    d.max_sym_len = b[data];
    data += 1;
    d.min_sym_len = b[data];
    data += 1;
    if d.min_sym_len == 0 || d.min_sym_len > d.max_sym_len || d.max_sym_len >= 64 {
        return None;
    }
    d.lowest_sym = data;
    let n = (d.max_sym_len - d.min_sym_len + 1) as usize;
    d.base64 = vec![0u64; n];
    if !fits(data, n as u64, 2, end) {
        return None;
    }
    for i in (0..n.saturating_sub(1)).rev() {
        d.base64[i] = (d.base64[i + 1]
            .wrapping_add(le_u16(b, d.lowest_sym + 2 * i) as u64)
            .wrapping_sub(le_u16(b, d.lowest_sym + 2 * (i + 1)) as u64))
            / 2;
        if d.base64[i].wrapping_mul(2) < d.base64[i + 1] {
            return None;
        }
    }
    for i in 0..n {
        d.base64[i] <<= 64 - i - d.min_sym_len as usize;
    }
    data += n * 2;
    if !fits(data, 2, 1, end) {
        return None;
    }
    let symlen_size = le_u16(b, data) as usize;
    data += 2;
    if !fits(data, symlen_size as u64, 3, end) {
        return None;
    }
    d.btree = vec![[0x00, 0xF0, 0xFF]; SYM_COUNT];
    for i in 0..symlen_size.min(SYM_COUNT) {
        d.btree[i] = [b[data + 3 * i], b[data + 3 * i + 1], b[data + 3 * i + 2]];
    }
    d.symlen = vec![0u8; SYM_COUNT];
    let mut colour = vec![WHITE_C; SYM_COUNT];
    let mut cyclic = false;
    for sym in 0..symlen_size {
        if colour[sym] == WHITE_C {
            let v = set_symlen(d, sym, &mut colour, &mut cyclic);
            d.symlen[sym] = v;
        }
    }
    if cyclic {
        return None;
    }
    Some(data + symlen_size * 3 + (symlen_size & 1))
}

fn set_dtz_map(
    t: &TbTable,
    items: &mut [[PairsData; 4]; 2],
    map: &mut usize,
    mut data: usize,
    max_file: usize,
    end: usize,
    b: &[u8],
) -> Option<usize> {
    if t.kind == TbType::Wdl {
        return Some(data);
    }
    *map = data;
    for f in 0..=max_file {
        let flags = items[0][if t.has_pawns { f } else { 0 }].flags;
        if flags & FLAG_MAPPED != 0 {
            if flags & FLAG_WIDE != 0 {
                data += data & 1;
                for i in 0..4 {
                    if !fits(data, 2, 1, end) {
                        return None;
                    }
                    items[0][if t.has_pawns { f } else { 0 }].map_idx[i] =
                        ((data - *map) / 2 + 1) as u16;
                    let step = 2 * le_u16(b, data) as u64 + 2;
                    if !fits(data, step, 1, end) {
                        return None;
                    }
                    data += step as usize;
                }
            } else {
                for i in 0..4 {
                    if !fits(data, 1, 1, end) {
                        return None;
                    }
                    items[0][if t.has_pawns { f } else { 0 }].map_idx[i] = (data - *map + 1) as u16;
                    let step = b[data] as u64 + 1;
                    if !fits(data, step, 1, end) {
                        return None;
                    }
                    data += step as usize;
                }
            }
        }
    }
    Some(data + (data & 1))
}

/// Parses a freshly mapped file into PairsData records (the upstream `set`).
fn parse(t: &TbTable, b: &[u8]) -> Option<([[PairsData; 4]; 2], usize)> {
    let end = b.len();
    let mut data = 4usize; // skip magic
    let mut items: [[PairsData; 4]; 2] = Default::default();
    let mut map = 0usize;
    const SPLIT: u8 = 1;
    const HAS_PAWNS: u8 = 2;
    if !fits(data, 1, 1, end) {
        return None;
    }
    if t.has_pawns != (b[data] & HAS_PAWNS != 0) || (t.key != t.key2) != (b[data] & SPLIT != 0) {
        return None;
    }
    data += 1;
    let sides = if t.sides() == 2 && t.key != t.key2 {
        2
    } else {
        1
    };
    let max_file = if t.has_pawns { 3 } else { 0 };
    let pp = t.has_pawns && t.pawn_count[1] != 0;
    let fi = |f: usize| if t.has_pawns { f } else { 0 };

    for f in 0..=max_file {
        for i in 0..sides {
            items[i % t.sides()][fi(f)] = PairsData::default();
        }
        if !fits(data, 1 + pp as u64 + t.piece_count as u64, 1, end) {
            return None;
        }
        let order = [
            [
                (b[data] & 0xF) as i32,
                if pp { (b[data + 1] & 0xF) as i32 } else { 0xF },
            ],
            [
                (b[data] >> 4) as i32,
                if pp { (b[data + 1] >> 4) as i32 } else { 0xF },
            ],
        ];
        data += 1 + pp as usize;
        for k in 0..t.piece_count as usize {
            for i in 0..sides {
                items[i % t.sides()][fi(f)].pieces[k] =
                    if i != 0 { b[data] >> 4 } else { b[data] & 0xF };
            }
            data += 1;
        }
        for i in 0..sides {
            let mut d = std::mem::take(&mut items[i % t.sides()][fi(f)]);
            set_groups(t, &mut d, order[i], f);
            items[i % t.sides()][fi(f)] = d;
        }
    }
    data += data & 1;

    for f in 0..=max_file {
        for i in 0..sides {
            let mut d = std::mem::take(&mut items[i % t.sides()][fi(f)]);
            data = set_sizes(&mut d, b, data, end)?;
            items[i % t.sides()][fi(f)] = d;
        }
    }
    data = set_dtz_map(t, &mut items, &mut map, data, max_file, end, b)?;

    for f in 0..=max_file {
        for i in 0..sides {
            let d = &mut items[i % t.sides()][fi(f)];
            d.sparse_index = data;
            if !fits(data, d.sparse_index_size, 6, end) {
                return None;
            }
            data += d.sparse_index_size as usize * 6;
        }
    }
    for f in 0..=max_file {
        for i in 0..sides {
            let d = &mut items[i % t.sides()][fi(f)];
            d.block_length = data;
            if !fits(data, d.block_length_size as u64, 2, end) {
                return None;
            }
            data += d.block_length_size as usize * 2;
        }
    }
    for f in 0..=max_file {
        for i in 0..sides {
            data = (data + 0x3F) & !0x3F;
            let d = &mut items[i % t.sides()][fi(f)];
            d.data = data;
            if !fits(data, d.blocks_num as u64, d.sizeof_block, end) {
                return None;
            }
            data += d.blocks_num as usize * d.sizeof_block as usize;
            d.data_end = data;
        }
    }
    if sides == 1 && t.sides() == 2 {
        // Symmetric WDL tables store one side; keep both slots usable.
        for f in 0..4 {
            items[1][f] = items[0][f].clone();
        }
    }
    Some((items, map))
}

// ---------------------------------------------------------------------------
// Table registry
// ---------------------------------------------------------------------------

pub struct Tablebases {
    paths: Vec<PathBuf>,
    tables: Vec<(TbTable, TbTable)>, // (wdl, dtz)
    index: HashMap<Key, usize>,
    pub max_cardinality: i32,
    pub found_wdl: usize,
    pub found_dtz: usize,
}

static CURRENT: RwLock<Option<Arc<Tablebases>>> = RwLock::new(None);
static MAP_LOCK: Mutex<()> = Mutex::new(());

/// The tablebases selected by the last `SyzygyPath` (None if empty).
pub fn current() -> Option<Arc<Tablebases>> {
    CURRENT.read().unwrap().clone()
}

pub fn max_cardinality() -> i32 {
    current().map_or(0, |t| t.max_cardinality)
}

fn material_key_of(counts: &[[i32; 7]; 2]) -> Key {
    let t = tables();
    let mut k = 0;
    for c in [WHITE, BLACK] {
        for pt in PAWN..=KING {
            let pc = make_piece(c, pt);
            for cnt in 0..counts[c][pt] {
                k ^= t.zobrist_psq[pc][8 + cnt as usize];
            }
        }
    }
    k
}

/// (Re)initializes tablebases from a `;` (Windows) or `:` separated path list.
/// Returns the info line the engine prints, if any path was given.
pub fn init(paths: &str) -> Option<String> {
    let sep = if cfg!(windows) { ';' } else { ':' };
    let paths: Vec<PathBuf> = paths
        .split(sep)
        .filter(|p| !p.is_empty() && *p != "<empty>")
        .map(PathBuf::from)
        .collect();
    if paths.is_empty() {
        *CURRENT.write().unwrap() = None;
        return None;
    }
    maps();
    let mut tb = Tablebases {
        paths,
        tables: Vec::new(),
        index: HashMap::new(),
        max_cardinality: 0,
        found_wdl: 0,
        found_dtz: 0,
    };
    let mut add = |pieces: &[PieceType]| tb.add(pieces);
    for p1 in PAWN..KING {
        add(&[KING, p1, KING]);
        for p2 in PAWN..=p1 {
            add(&[KING, p1, p2, KING]);
            add(&[KING, p1, KING, p2]);
            for p3 in PAWN..KING {
                add(&[KING, p1, p2, KING, p3]);
            }
            for p3 in PAWN..=p2 {
                add(&[KING, p1, p2, p3, KING]);
                for p4 in PAWN..=p3 {
                    add(&[KING, p1, p2, p3, p4, KING]);
                    for p5 in PAWN..=p4 {
                        add(&[KING, p1, p2, p3, p4, p5, KING]);
                    }
                    for p5 in PAWN..KING {
                        add(&[KING, p1, p2, p3, p4, KING, p5]);
                    }
                }
                for p4 in PAWN..KING {
                    add(&[KING, p1, p2, p3, KING, p4]);
                    for p5 in PAWN..=p4 {
                        add(&[KING, p1, p2, p3, KING, p4, p5]);
                    }
                }
            }
            for p3 in PAWN..=p1 {
                let lim = if p1 == p3 { p2 } else { p3 };
                for p4 in PAWN..=lim {
                    add(&[KING, p1, p2, KING, p3, p4]);
                }
            }
        }
    }
    let msg = format!(
        "Found {} WDL and {} DTZ tablebase files (up to {}-man).",
        tb.found_wdl, tb.found_dtz, tb.max_cardinality
    );
    *CURRENT.write().unwrap() = Some(Arc::new(tb));
    Some(msg)
}

impl Tablebases {
    fn find(&self, name: &str) -> Option<PathBuf> {
        self.paths
            .iter()
            .map(|p| p.join(name))
            .find(|p| p.is_file())
    }

    fn add(&mut self, pieces: &[PieceType]) {
        let mut code: String = pieces.iter().map(|&p| PIECE_TO_CHAR[p] as char).collect();
        let k2 = code[1..].find('K').unwrap() + 1;
        code.insert(k2, 'v');
        if self.find(&format!("{code}.rtbz")).is_some() {
            self.found_dtz += 1;
        }
        if self.find(&format!("{code}.rtbw")).is_none() {
            return;
        }
        self.found_wdl += 1;
        self.max_cardinality = self.max_cardinality.max(pieces.len() as i32);

        // Piece counts: strong side (before 'v') is white for `key`.
        let (strong, weak) = code.split_at(code.find('v').unwrap());
        let weak = &weak[1..];
        let count = |s: &str| {
            let mut c = [0i32; 7];
            for ch in s.bytes() {
                let pt = PIECE_TO_CHAR.iter().position(|&x| x == ch).unwrap();
                c[pt] += 1;
            }
            c
        };
        let (cs, cw) = (count(strong), count(weak));
        let key = material_key_of(&[cs, cw]);
        let key2 = material_key_of(&[cw, cs]);
        let piece_count = pieces.len() as i32;
        let has_pawns = cs[PAWN] + cw[PAWN] > 0;
        let mut has_unique_pieces = false;
        for c in [&cs, &cw] {
            for pt in PAWN..KING {
                if c[pt] == 1 {
                    has_unique_pieces = true;
                }
            }
        }
        // Leading color: the side with fewer pawns when both have pawns.
        let (wp, bp) = (cs[PAWN], cw[PAWN]);
        let lead_white = bp == 0 || (wp != 0 && bp >= wp);
        let pawn_count = if lead_white {
            [wp as u8, bp as u8]
        } else {
            [bp as u8, wp as u8]
        };

        let make = |kind| TbTable {
            kind,
            file_name_w: code.clone(),
            key,
            key2,
            piece_count,
            has_pawns,
            has_unique_pieces,
            pawn_count,
            mapped: OnceLock::new(),
        };
        let i = self.tables.len();
        self.tables.push((make(TbType::Wdl), make(TbType::Dtz)));
        self.index.insert(key, i);
        self.index.insert(key2, i);
    }

    fn mapped<'a>(&self, t: &'a TbTable) -> Option<&'a Mapped> {
        t.mapped
            .get_or_init(|| {
                let _g = MAP_LOCK.lock().unwrap();
                let ext = if t.kind == TbType::Wdl {
                    "rtbw"
                } else {
                    "rtbz"
                };
                let path = self.find(&format!("{}.{ext}", t.file_name_w))?;
                let file = std::fs::File::open(&path).ok()?;
                let mmap = unsafe { memmap2::Mmap::map(&file).ok()? };
                if mmap.len() % 64 != 16 {
                    eprintln!("Corrupt tablebase file {}", path.display());
                    std::process::exit(1);
                }
                let magic: [u8; 4] = if t.kind == TbType::Wdl {
                    [0x71, 0xE8, 0x23, 0x5D]
                } else {
                    [0xD7, 0x66, 0x0C, 0xA5]
                };
                if mmap[..4] != magic {
                    eprintln!("Corrupted table in file {}", path.display());
                    std::process::exit(1);
                }
                match parse(t, &mmap) {
                    Some((items, map)) => Some(Mapped { mmap, items, map }),
                    None => {
                        eprintln!("Corrupted table in file {}", path.display());
                        std::process::exit(1);
                    }
                }
            })
            .as_ref()
    }

    fn probe_table(
        &self,
        pos: &Position,
        kind: TbType,
        result: &mut ProbeState,
        wdl: WdlScore,
    ) -> i32 {
        if popcount(pos.pieces()) == 2 {
            return WDL_DRAW;
        }
        let Some(&i) = self.index.get(&pos.material_key()) else {
            *result = ProbeState::Fail;
            return 0;
        };
        let t = if kind == TbType::Wdl {
            &self.tables[i].0
        } else {
            &self.tables[i].1
        };
        let Some(m) = self.mapped(t) else {
            *result = ProbeState::Fail;
            return 0;
        };
        do_probe_table(pos, t, m, wdl, result)
    }

    fn search<const CHECK_ZEROING: bool>(
        &self,
        pos: &mut Position,
        result: &mut ProbeState,
    ) -> WdlScore {
        let mut best_value = WDL_LOSS;
        let moves = MoveList::new(pos, GenType::Legal);
        let total = moves.len();
        let mut move_count = 0;
        let mut value;
        for &mv in moves.as_slice() {
            if !pos.capture(mv) && (!CHECK_ZEROING || type_of(pos.moved_piece(mv)) != PAWN) {
                continue;
            }
            move_count += 1;
            pos.do_move_simple(mv);
            value = -self.search::<false>(pos, result);
            pos.undo_move(mv);
            if *result == ProbeState::Fail {
                return WDL_DRAW;
            }
            if value > best_value {
                best_value = value;
                if value >= WDL_WIN {
                    *result = ProbeState::ZeroingBestMove;
                    return value;
                }
            }
        }
        let no_more_moves = move_count != 0 && move_count == total;
        if no_more_moves {
            value = best_value;
        } else {
            value = self.probe_table(pos, TbType::Wdl, result, WDL_DRAW);
            if *result == ProbeState::Fail {
                return WDL_DRAW;
            }
        }
        if best_value >= value {
            *result = if best_value > WDL_DRAW || no_more_moves {
                ProbeState::ZeroingBestMove
            } else {
                ProbeState::Ok
            };
            return best_value;
        }
        *result = ProbeState::Ok;
        value
    }

    /// WDL from the side to move's point of view (-2..2).
    pub fn probe_wdl(&self, pos: &mut Position, result: &mut ProbeState) -> WdlScore {
        *result = ProbeState::Ok;
        self.search::<false>(pos, result)
    }

    /// DTZ in plies from the side to move's point of view (see the upstream probe_dtz).
    pub fn probe_dtz(&self, pos: &mut Position, result: &mut ProbeState) -> i32 {
        *result = ProbeState::Ok;
        let wdl = self.search::<true>(pos, result);
        if *result == ProbeState::Fail || wdl == WDL_DRAW {
            return 0;
        }
        if *result == ProbeState::ZeroingBestMove {
            return dtz_before_zeroing(wdl);
        }
        let mut dtz = self.probe_table(pos, TbType::Dtz, result, wdl);
        if *result == ProbeState::Fail {
            return 0;
        }
        if *result != ProbeState::ChangeStm {
            return (dtz + 100 * (wdl == WDL_BLESSED_LOSS || wdl == WDL_CURSED_WIN) as i32)
                * wdl.signum();
        }
        let mut min_dtz = 0xFFFF;
        for &mv in MoveList::new(pos, GenType::Legal).as_slice() {
            let zeroing = pos.capture(mv) || type_of(pos.moved_piece(mv)) == PAWN;
            pos.do_move_simple(mv);
            dtz = if zeroing {
                -dtz_before_zeroing(self.search::<false>(pos, result))
            } else {
                -self.probe_dtz(pos, result)
            };
            if dtz == 1 && pos.checkers() != 0 && MoveList::new(pos, GenType::Legal).is_empty() {
                min_dtz = 1;
            }
            if !zeroing {
                dtz += dtz.signum();
            }
            if dtz < min_dtz && dtz.signum() == wdl.signum() {
                min_dtz = dtz;
            }
            pos.undo_move(mv);
            if *result == ProbeState::Fail {
                return 0;
            }
        }
        if min_dtz == 0xFFFF { -1 } else { min_dtz }
    }

    /// Ranks root moves with DTZ tables. False if a probe failed.
    pub fn root_probe(
        &self,
        pos: &mut Position,
        root_moves: &mut [RootMove],
        rule50: bool,
        rank_dtz: bool,
        time_abort: &dyn Fn() -> bool,
    ) -> bool {
        let mut result = ProbeState::Ok;
        let cnt50 = pos.rule50_count();
        let rep = pos.has_repeated();
        let bound = if rule50 { MAX_DTZ / 2 - 100 } else { 1 };
        for m in root_moves.iter_mut() {
            let mv = m.pv[0];
            pos.do_move_simple(mv);
            let mut dtz;
            if pos.rule50_count() == 0 {
                let wdl = -self.probe_wdl(pos, &mut result);
                dtz = dtz_before_zeroing(wdl);
            } else if (rule50 && pos.is_draw(1)) || pos.is_repetition(1) {
                dtz = 0;
            } else {
                dtz = -self.probe_dtz(pos, &mut result);
                dtz = if dtz > 0 {
                    dtz + 1
                } else if dtz < 0 {
                    dtz - 1
                } else {
                    dtz
                };
            }
            if pos.checkers() != 0 && dtz == 2 && MoveList::new(pos, GenType::Legal).is_empty() {
                dtz = 1;
            }
            pos.undo_move(mv);
            if time_abort() || result == ProbeState::Fail {
                return false;
            }
            let r = if dtz > 0 {
                if dtz + cnt50 <= 99 && !rep {
                    MAX_DTZ - if rank_dtz { dtz } else { 0 }
                } else {
                    MAX_DTZ / 2 - (dtz + cnt50)
                }
            } else if dtz < 0 {
                if -dtz * 2 + cnt50 < 100 {
                    -MAX_DTZ - if rank_dtz { dtz } else { 0 }
                } else {
                    -MAX_DTZ / 2 + (-dtz + cnt50)
                }
            } else {
                0
            };
            m.tb_rank = r;
            m.tb_score = if r >= bound {
                VALUE_MATE - MAX_PLY - 1
            } else if r > 0 {
                ((r - (MAX_DTZ / 2 - 200)).max(3) * PAWN_VALUE) / 200
            } else if r == 0 {
                VALUE_DRAW
            } else if r > -bound {
                ((r + (MAX_DTZ / 2 - 200)).min(-3) * PAWN_VALUE) / 200
            } else {
                -VALUE_MATE + MAX_PLY + 1
            };
        }
        true
    }

    /// Ranks root moves with WDL tables (fallback when DTZ is missing).
    pub fn root_probe_wdl(
        &self,
        pos: &mut Position,
        root_moves: &mut [RootMove],
        rule50: bool,
    ) -> bool {
        const WDL_TO_RANK: [i32; 5] = [-MAX_DTZ, -MAX_DTZ + 101, 0, MAX_DTZ - 101, MAX_DTZ];
        let mut result = ProbeState::Ok;
        for m in root_moves.iter_mut() {
            let mv = m.pv[0];
            pos.do_move_simple(mv);
            let mut wdl = if pos.is_draw(1) {
                WDL_DRAW
            } else {
                -self.probe_wdl(pos, &mut result)
            };
            pos.undo_move(mv);
            if result == ProbeState::Fail {
                return false;
            }
            m.tb_rank = WDL_TO_RANK[(wdl + 2) as usize];
            if !rule50 {
                wdl = wdl.signum() * 2;
            }
            m.tb_score = WDL_TO_VALUE[(wdl + 2) as usize];
        }
        true
    }
}

fn dtz_before_zeroing(wdl: WdlScore) -> i32 {
    match wdl {
        WDL_WIN => 1,
        WDL_CURSED_WIN => 101,
        WDL_BLESSED_LOSS => -101,
        WDL_LOSS => -1,
        _ => 0,
    }
}

/// Options relevant to tablebase use.
#[derive(Copy, Clone)]
pub struct TbOptions {
    pub rule50: bool,
    pub probe_depth: i32,
    pub probe_limit: i32,
}

/// the upstream Tablebases::rank_root_moves.
pub fn rank_root_moves(
    opts: TbOptions,
    pos: &mut Position,
    root_moves: &mut Vec<RootMove>,
    rank_dtz: bool,
    time_abort: &dyn Fn() -> bool,
) -> Config {
    let mut config = Config::default();
    if root_moves.is_empty() {
        return config;
    }
    config.root_in_tb = false;
    config.use_rule50 = opts.rule50;
    config.probe_depth = opts.probe_depth;
    config.cardinality = opts.probe_limit;
    let tb = current();
    let max_card = tb.as_ref().map_or(0, |t| t.max_cardinality);
    let mut dtz_available = true;
    if config.cardinality > max_card {
        config.cardinality = max_card;
        config.probe_depth = 0;
    }
    if let Some(tb) = tb.as_ref() {
        if config.cardinality >= popcount(pos.pieces()) && !pos.can_castle(ANY_CASTLING) {
            let rank_dtz = rank_dtz || pos.dtz_is_dtm();
            config.root_in_tb = tb.root_probe(pos, root_moves, opts.rule50, rank_dtz, time_abort);
            if !config.root_in_tb && !time_abort() {
                dtz_available = false;
                config.root_in_tb = tb.root_probe_wdl(pos, root_moves, opts.rule50);
            }
        }
    }
    if config.root_in_tb {
        // Stable sort, descending tbRank
        root_moves.sort_by(|a, b| b.tb_rank.cmp(&a.tb_rank));
        if dtz_available || root_moves[0].tb_score <= VALUE_DRAW {
            config.cardinality = 0;
        }
    } else {
        for m in root_moves.iter_mut() {
            m.tb_rank = 0;
        }
    }
    config
}
