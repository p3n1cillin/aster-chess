// Copyright (C) 2026 Aster contributors.
// SPDX-License-Identifier: GPL-3.0-or-later
// Online heuristic error proxy, not a calibrated probability or safety proof.

use crate::types::*;

pub(crate) const DEFER_LIMIT: u8 = 64;

#[derive(Clone, Copy, Default)]
struct Estimate {
    samples: u8,
    mean_square: u32,
}

pub(crate) struct RiskHistory {
    estimates: [Estimate; 48],
    pub observations: u32,
    pub deferred: u8,
}

impl Default for RiskHistory {
    fn default() -> Self {
        Self {
            estimates: [Estimate::default(); 48],
            observations: 0,
            deferred: 0,
        }
    }
}

pub(crate) fn bucket(pieces: u32, queens: bool, side: Color, depth: Depth) -> usize {
    let material = (pieces.saturating_sub(2) / 8).min(3) as usize;
    let band = ((depth.max(1) - 1) / 4).min(2) as usize;
    (((side * 2 + queens as usize) * 4 + material) * 3) + band
}

impl RiskHistory {
    pub fn new_search(&mut self) {
        self.observations = 0;
        self.deferred = 0;
    }

    pub fn observe(&mut self, key: usize, static_eval: Value, searched: Value) {
        let finite = |v: Value| v.unsigned_abs() < VALUE_TB_WIN_IN_MAX_PLY as u32;
        if !finite(static_eval) || !finite(searched) {
            return;
        }
        let error = (static_eval - searched).clamp(0, 2 * PAWN_VALUE) as u32;
        let estimate = &mut self.estimates[key];
        estimate.samples = estimate.samples.saturating_add(1).min(32);
        let difference = (error * error) as i64 - estimate.mean_square as i64;
        estimate.mean_square =
            (estimate.mean_square as i64 + difference / estimate.samples as i64) as u32;
        self.observations = self.observations.saturating_add(1);
    }

    fn margin(&self, key: usize) -> Value {
        let estimate = &self.estimates[key];
        if estimate.samples < 16 {
            0
        } else {
            (estimate.mean_square.isqrt() as i32 / 2).min(PAWN_VALUE / 4)
        }
    }

    pub fn defer(&mut self, key: usize, excess: Value) -> bool {
        if self.deferred < DEFER_LIMIT && excess >= 0 && excess < self.margin(key) {
            self.deferred += 1;
            true
        } else {
            false
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_material_depth_side_context_is_separate_and_bounded() {
        let mut keys = std::collections::BTreeSet::new();
        for side in [WHITE, BLACK] {
            for queens in [false, true] {
                for pieces in [2, 10, 18, 26] {
                    for depth in [1, 5, 9] {
                        keys.insert(bucket(pieces, queens, side, depth));
                    }
                }
            }
        }
        assert_eq!(
            keys.into_iter().collect::<Vec<_>>(),
            (0..48).collect::<Vec<_>>()
        );
        assert_eq!(bucket(32, true, BLACK, MAX_PLY), 47);
        assert_eq!(bucket(0, false, WHITE, -1), 0);
    }

    #[test]
    fn warmup_bounds_and_one_sided_error_are_required() {
        let mut history = RiskHistory::default();
        for _ in 0..15 {
            history.observe(0, PAWN_VALUE, 0);
            assert!(!history.defer(0, 0));
        }
        history.observe(0, PAWN_VALUE, 0);
        assert_eq!(history.margin(0), PAWN_VALUE / 4);
        assert!(history.defer(0, PAWN_VALUE / 4 - 1));
        assert!(!history.defer(0, PAWN_VALUE / 4));
        assert!(!history.defer(0, -1));
        assert!(!history.defer(1, 0));
        let mut under = RiskHistory::default();
        for _ in 0..64 {
            under.observe(0, -PAWN_VALUE, 0);
        }
        assert_eq!(under.margin(0), 0);
    }

    #[test]
    fn invalid_labels_cannot_train_and_clipping_prevents_overflow() {
        let mut history = RiskHistory::default();
        for invalid in [VALUE_NONE, VALUE_MATE, VALUE_TB, i32::MIN, i32::MAX] {
            history.observe(0, invalid, 0);
            history.observe(0, 0, invalid);
        }
        assert_eq!(history.observations, 0);
        for _ in 0..10000 {
            history.observe(0, 30000, -30000);
        }
        assert_eq!(history.margin(0), PAWN_VALUE / 4);
        assert_eq!(history.estimates[0].samples, 32);
    }

    #[test]
    fn search_budget_resets_but_game_history_only_clears_explicitly() {
        let mut history = RiskHistory::default();
        for _ in 0..16 {
            history.observe(0, PAWN_VALUE, 0);
        }
        for _ in 0..DEFER_LIMIT {
            assert!(history.defer(0, 0));
        }
        assert!(!history.defer(0, 0));
        history.new_search();
        assert_eq!(history.observations, 0);
        assert!(history.defer(0, 0));
        history = RiskHistory::default();
        assert!(!history.defer(0, 0));
    }
}
