// Aster core. Original attribution and source mapping: accumulator.rs.license.
// SPDX-License-Identifier: GPL-3.0-or-later
// Modified 2026-10-19: source naming and notice layout; queen-split caches, no PSQT.

use super::features::*;
use super::kernels::*;
use super::network::{FeatureTransformer, L1};
use crate::bitboard::*;
use crate::position::Position;
use crate::types::*;

#[repr(C, align(64))]
#[derive(Clone)]
pub struct AccumulatorState {
    pub accumulation: [[i16; L1]; COLOR_NB],
    pub computed: [bool; COLOR_NB],
    pub dirties: Dirties,
}

impl Default for AccumulatorState {
    fn default() -> Self {
        AccumulatorState {
            accumulation: [[0; L1]; COLOR_NB],
            computed: [false; 2],
            dirties: Dirties::default(),
        }
    }
}

#[repr(C, align(64))]
#[derive(Clone)]
pub struct CacheEntry {
    pub accumulation: [i16; L1],
    pub pieces: [u8; 64],
    pub piece_bb: Bitboard,
}

/// Finny tables: per opponent-queen state, king square and perspective, the
/// piece-square accumulation of the last position seen with that king square.
pub struct AccumulatorCaches {
    // index: opponent_has_queen * 64 + king square
    entries: Vec<[CacheEntry; COLOR_NB]>,
}

impl AccumulatorCaches {
    pub fn new(ft: &FeatureTransformer) -> Self {
        let e = CacheEntry {
            accumulation: *ft.biases,
            pieces: [0; 64],
            piece_bb: 0,
        };
        AccumulatorCaches {
            entries: vec![[e.clone(), e]; 2 * 64],
        }
    }
    pub fn clear(&mut self, ft: &FeatureTransformer) {
        for pair in self.entries.iter_mut() {
            for e in pair.iter_mut() {
                e.accumulation = *ft.biases;
                e.pieces = [0; 64];
                e.piece_bb = 0;
            }
        }
    }
    #[inline(always)]
    fn slot(opponent_has_queen: bool, ksq: Square) -> usize {
        opponent_has_queen as usize * 64 + ksq
    }
}

#[inline(always)]
fn opponent_has_queen(pos: &Position, persp: Color) -> bool {
    pos.pieces_ct(flip_color(persp), QUEEN) != 0
}

pub const MAX_SIZE: usize = MAX_PLY as usize + 1;

pub struct AccumulatorStack {
    accs: Vec<AccumulatorState>,
    size: usize,
}

impl Default for AccumulatorStack {
    fn default() -> Self {
        AccumulatorStack {
            accs: vec![AccumulatorState::default(); MAX_SIZE],
            size: 1,
        }
    }
}

#[inline(always)]
fn get_changed_pieces(old: &[u8; 64], new: &[u8; 64]) -> Bitboard {
    changed_squares(old, new)
}

// Weight rows of one update: up to 32 piece-square plus 256 threat rows.
type WeightRows<'a> = ValueList<&'a [i8], 288>;

#[inline(always)]
fn psq_rows<'a>(ft: &'a FeatureTransformer, idx: &PsqIndexList, out: &mut WeightRows<'a>) {
    for &i in idx.as_slice() {
        out.push(psq_row(ft, i));
    }
}
#[inline(always)]
fn thr_rows<'a>(ft: &'a FeatureTransformer, idx: &ThreatIndexList, out: &mut WeightRows<'a>) {
    for &i in idx.as_slice() {
        out.push(thr_row(ft, i));
    }
}

#[inline(always)]
fn psq_row(ft: &FeatureTransformer, idx: u16) -> &[i8] {
    let i = idx as usize * L1;
    &ft.weights[i..i + L1]
}
#[inline(always)]
fn thr_row(ft: &FeatureTransformer, idx: u16) -> &[i8] {
    let i = idx as usize * L1;
    &ft.threat_pp_weights[i..i + L1]
}

#[allow(clippy::too_many_arguments)]
fn apply_combined(
    persp: Color,
    ft: &FeatureTransformer,
    from: &AccumulatorState,
    to: &mut AccumulatorState,
    psq_added: &PsqIndexList,
    psq_removed: &PsqIndexList,
    thr_added: &ThreatIndexList,
    thr_removed: &ThreatIndexList,
) {
    update_acc_idx(
        to.accumulation[persp].as_mut_ptr(),
        from.accumulation[persp].as_ptr(),
        &IdxRows {
            base_psq: ft.weights.as_ptr(),
            sub_psq: psq_removed.as_slice(),
            add_psq: psq_added.as_slice(),
            base8: ft.threat_pp_weights.as_ptr(),
            sub8: thr_removed.as_slice(),
            add8: thr_added.as_slice(),
        },
    );
}

impl AccumulatorStack {
    #[inline(always)]
    pub fn latest(&self) -> &AccumulatorState {
        &self.accs[self.size - 1]
    }

    pub fn reset(&mut self) {
        let a = &mut self.accs[0];
        a.dirties.dirty_piece = DirtyPiece::default();
        a.dirties.dirty_threats.clear();
        a.dirties.dirty_pawn_pairs = DirtyPawnPairs::default();
        a.computed = [false, false];
        self.size = 1;
    }

    #[inline(always)]
    pub fn push(&mut self) -> &mut Dirties {
        debug_assert!(self.size < MAX_SIZE);
        let st = &mut self.accs[self.size];
        st.computed = [false, false];
        st.dirties.dirty_threats.clear();
        st.dirties.dirty_pawn_pairs = DirtyPawnPairs::default();
        self.size += 1;
        &mut st.dirties
    }

    #[inline(always)]
    pub fn pop(&mut self) {
        debug_assert!(self.size > 1);
        self.size -= 1;
    }

    /// Mutable target and shared source accumulators (distinct indices).
    #[inline(always)]
    fn pair(&mut self, target: usize, source: usize) -> (&mut AccumulatorState, &AccumulatorState) {
        debug_assert!(target != source);
        let p = self.accs.as_mut_ptr();
        unsafe { (&mut *p.add(target), &*p.add(source)) }
    }

    pub fn evaluate(
        &mut self,
        pos: &Position,
        ft: &FeatureTransformer,
        cache: &mut AccumulatorCaches,
    ) {
        let last_white = self.find_last_usable_accumulator(WHITE);
        let last_black = self.find_last_usable_accumulator(BLACK);
        if self.accs[last_white].computed[WHITE] && self.accs[last_black].computed[BLACK] {
            self.forward_update_incremental_both(pos, ft, last_white, last_black);
        } else {
            self.evaluate_side(WHITE, pos, ft, cache, last_white);
            self.evaluate_side(BLACK, pos, ft, cache, last_black);
        }
    }

    fn evaluate_side(
        &mut self,
        persp: Color,
        pos: &Position,
        ft: &FeatureTransformer,
        cache: &mut AccumulatorCaches,
        last_usable: usize,
    ) {
        const MIN_PC_COUNT_HYBRID: i32 = 15;

        if self.accs[last_usable].computed[persp] {
            self.forward_update_incremental(persp, pos, ft, last_usable);
        } else {
            let dp = self.latest().dirties.dirty_piece;
            if dp.pc == make_piece(persp, KING)
                && dp.remove_pc != make_piece(flip_color(persp), QUEEN)
                && self.size >= 2
                && self.accs[self.size - 2].computed[persp]
                && popcount(pos.pieces()) >= MIN_PC_COUNT_HYBRID
                && (dp.from & 0b100) == (dp.to & 0b100)
                && dp.add_sq == SQ_NONE
            {
                let n = self.size;
                let (target, computed) = self.pair(n - 1, n - 2);
                update_accumulator_hybrid(persp, pos, ft, target, computed, cache);
                return;
            }
            let n = self.size;
            let t = crate::prof::prof_start!();
            update_accumulator_refresh_cache(persp, ft, pos, &mut self.accs[n - 1], cache);
            crate::prof::prof_end!(7, t);
            self.backward_update_incremental(persp, pos, ft, last_usable);
        }
    }

    fn find_last_usable_accumulator(&self, persp: Color) -> usize {
        let mut idx = self.size - 1;
        while idx > 0 {
            if self.accs[idx].computed[persp] {
                return idx;
            }
            if psq_requires_refresh(&self.accs[idx].dirties.dirty_piece, persp) {
                return idx;
            }
            idx -= 1;
        }
        0
    }

    fn forward_update_incremental(
        &mut self,
        persp: Color,
        pos: &Position,
        ft: &FeatureTransformer,
        begin: usize,
    ) {
        let ksq = pos.king_square(persp);
        let q = opponent_has_queen(pos, persp);
        for next in begin + 1..self.size {
            let (target, computed) = self.pair(next, next - 1);
            update_accumulator_incremental::<true>(persp, ft, ksq, q, target, computed);
        }
    }

    fn backward_update_incremental(
        &mut self,
        persp: Color,
        pos: &Position,
        ft: &FeatureTransformer,
        end: usize,
    ) {
        let ksq = pos.king_square(persp);
        let q = opponent_has_queen(pos, persp);
        let mut next = self.size as isize - 2;
        while next >= end as isize {
            let (target, computed) = self.pair(next as usize, next as usize + 1);
            update_accumulator_incremental::<false>(persp, ft, ksq, q, target, computed);
            next -= 1;
        }
    }

    fn forward_update_incremental_both(
        &mut self,
        pos: &Position,
        ft: &FeatureTransformer,
        white_begin: usize,
        black_begin: usize,
    ) {
        let wk = pos.king_square(WHITE);
        let bk = pos.king_square(BLACK);
        let wq = opponent_has_queen(pos, WHITE);
        let bq = opponent_has_queen(pos, BLACK);
        let shared_begin = white_begin.max(black_begin);
        for next in white_begin + 1..=shared_begin {
            let (t, c) = self.pair(next, next - 1);
            update_accumulator_incremental::<true>(WHITE, ft, wk, wq, t, c);
        }
        for next in black_begin + 1..=shared_begin {
            let (t, c) = self.pair(next, next - 1);
            update_accumulator_incremental::<true>(BLACK, ft, bk, bq, t, c);
        }
        for next in shared_begin + 1..self.size {
            let (t, c) = self.pair(next, next - 1);
            update_accumulator_incremental_both(ft, [(wk, wq), (bk, bq)], t, c);
        }
    }
}

fn update_accumulator_incremental<const FORWARD: bool>(
    persp: Color,
    ft: &FeatureTransformer,
    ksq: Square,
    opp_queen: bool,
    target: &mut AccumulatorState,
    computed: &AccumulatorState,
) {
    let mut psq_removed = PsqIndexList::new();
    let mut psq_added = PsqIndexList::new();
    let mut thr_removed = ThreatIndexList::new();
    let mut thr_added = ThreatIndexList::new();

    let d = if FORWARD {
        &target.dirties
    } else {
        &computed.dirties
    };
    if FORWARD {
        threat_append_changed_indices(
            persp,
            ksq,
            &d.dirty_threats,
            &mut thr_removed,
            &mut thr_added,
        );
        pp_append_changed_indices(
            persp,
            ksq,
            &d.dirty_pawn_pairs,
            &mut thr_removed,
            &mut thr_added,
        );
        psq_append_changed_indices(
            persp,
            ksq,
            &d.dirty_piece,
            opp_queen,
            &mut psq_removed,
            &mut psq_added,
        );
    } else {
        threat_append_changed_indices(
            persp,
            ksq,
            &d.dirty_threats,
            &mut thr_added,
            &mut thr_removed,
        );
        pp_append_changed_indices(
            persp,
            ksq,
            &d.dirty_pawn_pairs,
            &mut thr_added,
            &mut thr_removed,
        );
        psq_append_changed_indices(
            persp,
            ksq,
            &d.dirty_piece,
            opp_queen,
            &mut psq_added,
            &mut psq_removed,
        );
    }
    apply_combined(
        persp,
        ft,
        computed,
        target,
        &psq_added,
        &psq_removed,
        &thr_added,
        &thr_removed,
    );
    target.computed[persp] = true;
}

fn update_accumulator_incremental_both(
    ft: &FeatureTransformer,
    kings: [(Square, bool); COLOR_NB],
    target: &mut AccumulatorState,
    computed: &AccumulatorState,
) {
    // Gather (and start prefetching) every changed row of both perspectives
    // before touching either accumulator.
    let mut thr_removed = [ThreatIndexList::new(), ThreatIndexList::new()];
    let mut thr_added = [ThreatIndexList::new(), ThreatIndexList::new()];
    let mut psq_removed = [PsqIndexList::new(), PsqIndexList::new()];
    let mut psq_added = [PsqIndexList::new(), PsqIndexList::new()];
    let d = &target.dirties;
    threat_append_changed_indices_both(
        [kings[WHITE].0, kings[BLACK].0],
        &d.dirty_threats,
        &mut thr_removed,
        &mut thr_added,
    );
    for (persp, (ksq, opp_queen)) in [WHITE, BLACK].into_iter().zip(kings) {
        pp_append_changed_indices(
            persp,
            ksq,
            &d.dirty_pawn_pairs,
            &mut thr_removed[persp],
            &mut thr_added[persp],
        );
        psq_append_changed_indices(
            persp,
            ksq,
            &d.dirty_piece,
            opp_queen,
            &mut psq_removed[persp],
            &mut psq_added[persp],
        );
    }
    for persp in [WHITE, BLACK] {
        apply_combined(
            persp,
            ft,
            computed,
            target,
            &psq_added[persp],
            &psq_removed[persp],
            &thr_added[persp],
            &thr_removed[persp],
        );
    }
    target.computed = [true, true];
}

/// Updates the accumulator for a king move within the same board half, and
/// refreshes the cache entry for the new king square.
fn update_accumulator_hybrid(
    persp: Color,
    pos: &Position,
    ft: &FeatureTransformer,
    target: &mut AccumulatorState,
    computed: &AccumulatorState,
    cache: &mut AccumulatorCaches,
) {
    let dp = target.dirties.dirty_piece;
    let old_ksq = dp.from;
    let new_ksq = dp.to;

    let current = pos.piece_array();
    let mut previous = *current;
    let mut previous_bb = pos.pieces();
    if dp.remove_sq != SQ_NONE {
        previous[new_ksq] = dp.remove_pc as u8;
    } else {
        previous[new_ksq] = NO_PIECE as u8;
        previous_bb &= !square_bb(new_ksq);
    }
    previous[old_ksq] = make_piece(persp, KING) as u8;
    previous_bb |= square_bb(old_ksq);

    let q = opponent_has_queen(pos, persp);
    let (old_entry, new_entry) = {
        let p = cache.entries.as_mut_ptr();
        let (o, n) = (
            AccumulatorCaches::slot(q, old_ksq),
            AccumulatorCaches::slot(q, new_ksq),
        );
        unsafe { (&(*p.add(o))[persp], &mut (*p.add(n))[persp]) }
    };

    let mut old_remove = PsqIndexList::new();
    let mut old_add = PsqIndexList::new();
    let mut new_remove = PsqIndexList::new();
    let mut new_add = PsqIndexList::new();

    let old_changed = get_changed_pieces(&old_entry.pieces, &previous);
    let mut old_removed_bb = old_changed & old_entry.piece_bb;
    let mut old_added_bb = old_changed & previous_bb;
    let new_changed = get_changed_pieces(&new_entry.pieces, current);
    let mut new_removed_bb = new_changed & new_entry.piece_bb;
    let mut new_added_bb = new_changed & pos.pieces();

    while old_removed_bb != 0 {
        let sq = pop_lsb(&mut old_removed_bb);
        old_remove.push(psq_make_index(
            persp,
            sq,
            old_entry.pieces[sq] as Piece,
            old_ksq,
            q,
        ));
    }
    while old_added_bb != 0 {
        let sq = pop_lsb(&mut old_added_bb);
        old_add.push(psq_make_index(persp, sq, previous[sq] as Piece, old_ksq, q));
    }
    while new_removed_bb != 0 {
        let sq = pop_lsb(&mut new_removed_bb);
        new_remove.push(psq_make_index(
            persp,
            sq,
            new_entry.pieces[sq] as Piece,
            new_ksq,
            q,
        ));
    }
    while new_added_bb != 0 {
        let sq = pop_lsb(&mut new_added_bb);
        new_add.push(psq_make_index(persp, sq, current[sq] as Piece, new_ksq, q));
    }

    let mut thr_removed = ThreatIndexList::new();
    let mut thr_added = ThreatIndexList::new();
    threat_append_changed_indices(
        persp,
        new_ksq,
        &target.dirties.dirty_threats,
        &mut thr_removed,
        &mut thr_added,
    );
    pp_append_changed_indices(
        persp,
        new_ksq,
        &target.dirties.dirty_pawn_pairs,
        &mut thr_removed,
        &mut thr_added,
    );

    // Piece-square part: refresh the new cache entry in place.
    {
        let (mut s8, mut a8) = (WeightRows::new(), WeightRows::new());
        psq_rows(ft, &new_remove, &mut s8);
        psq_rows(ft, &new_add, &mut a8);
        let p = new_entry.accumulation.as_mut_ptr();
        update_acc(
            p,
            p,
            &Rows {
                sub16: &[],
                add16: &[],
                sub8: s8.as_slice(),
                add8: a8.as_slice(),
            },
        );
    }
    // Adding the old accumulator adds (most of) the threats and pp weights we need,
    // then correct for the stale cached psq accumulation of the old king square.
    {
        let (mut s8, mut a8) = (WeightRows::new(), WeightRows::new());
        psq_rows(ft, &old_remove, &mut a8);
        psq_rows(ft, &old_add, &mut s8);
        thr_rows(ft, &thr_removed, &mut s8);
        thr_rows(ft, &thr_added, &mut a8);
        update_acc(
            target.accumulation[persp].as_mut_ptr(),
            new_entry.accumulation.as_ptr(),
            &Rows {
                sub16: &[&old_entry.accumulation[..]],
                add16: &[&computed.accumulation[persp][..]],
                sub8: s8.as_slice(),
                add8: a8.as_slice(),
            },
        );
    }

    new_entry.pieces = *current;
    new_entry.piece_bb = pos.pieces();
    target.computed[persp] = true;
}

/// HalfKA data comes from the Finny table entry, threats from the active features.
fn update_accumulator_refresh_cache(
    persp: Color,
    ft: &FeatureTransformer,
    pos: &Position,
    acc_state: &mut AccumulatorState,
    cache: &mut AccumulatorCaches,
) {
    let ksq = pos.king_square(persp);
    let q = opponent_has_queen(pos, persp);
    let entry = &mut cache.entries[AccumulatorCaches::slot(q, ksq)][persp];
    let mut removed = PsqIndexList::new();
    let mut added = PsqIndexList::new();

    let changed = get_changed_pieces(&entry.pieces, pos.piece_array());
    let mut removed_bb = changed & entry.piece_bb;
    let mut added_bb = changed & pos.pieces();
    while removed_bb != 0 {
        let sq = pop_lsb(&mut removed_bb);
        removed.push(psq_make_index(persp, sq, entry.pieces[sq] as Piece, ksq, q));
    }
    while added_bb != 0 {
        let sq = pop_lsb(&mut added_bb);
        added.push(psq_make_index(persp, sq, pos.piece_on(sq), ksq, q));
    }
    entry.piece_bb = pos.pieces();
    entry.pieces = *pos.piece_array();

    let mut active = ThreatIndexList::new();
    threat_append_active_indices(persp, pos, &mut active);
    pp_append_active_indices(persp, pos, &mut active);

    {
        let p = entry.accumulation.as_mut_ptr();
        update_acc_idx(
            p,
            p,
            &IdxRows {
                base_psq: ft.weights.as_ptr(),
                sub_psq: removed.as_slice(),
                add_psq: added.as_slice(),
                base8: ft.threat_pp_weights.as_ptr(),
                sub8: &[],
                add8: &[],
            },
        );
        update_acc_idx(
            acc_state.accumulation[persp].as_mut_ptr(),
            entry.accumulation.as_ptr(),
            &IdxRows {
                base_psq: ft.weights.as_ptr(),
                sub_psq: &[],
                add_psq: &[],
                base8: ft.threat_pp_weights.as_ptr(),
                sub8: &[],
                add8: active.as_slice(),
            },
        );
    }
    acc_state.computed[persp] = true;
}

/// Reference evaluation of one perspective from scratch (used by consistency checks).
pub fn refresh_from_scratch(persp: Color, ft: &FeatureTransformer, pos: &Position) -> [i16; L1] {
    let ksq = pos.king_square(persp);
    let q = opponent_has_queen(pos, persp);
    let mut acc = *ft.biases;
    let mut b = pos.pieces();
    while b != 0 {
        let sq = pop_lsb(&mut b);
        let i = psq_make_index(persp, sq, pos.piece_on(sq), ksq, q);
        for (a, w) in acc.iter_mut().zip(psq_row(ft, i)) {
            *a = a.wrapping_add(*w as i16);
        }
    }
    let mut active = ThreatIndexList::new();
    threat_append_active_indices(persp, pos, &mut active);
    pp_append_active_indices(persp, pos, &mut active);
    for &i in active.as_slice() {
        for (a, w) in acc.iter_mut().zip(thr_row(ft, i)) {
            *a = a.wrapping_add(*w as i16);
        }
    }
    acc
}
