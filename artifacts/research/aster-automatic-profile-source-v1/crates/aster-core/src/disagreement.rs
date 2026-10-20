// Copyright (C) 2026 Aster contributors.
// SPDX-License-Identifier: GPL-3.0-or-later
// Experimental search policy; this evidence is heuristic, never a proof.

use crate::types::*;

pub(crate) const AUDIT_LIMIT: u16 = 256;

pub(crate) struct Evidence {
    pub depth: Depth,
    pub current: Value,
    pub previous: Value,
    pub cached: Value,
    pub cached_depth: Depth,
    pub bound: Bound,
}

impl Evidence {
    #[inline(always)]
    pub fn disagrees(&self) -> bool {
        let finite = |v: Value| v.unsigned_abs() < VALUE_TB_WIN_IN_MAX_PLY as u32;
        if !(5..=10).contains(&self.depth)
            || self.cached_depth < self.depth - 3
            || !finite(self.current)
            || !finite(self.previous)
            || !finite(self.cached)
        {
            return false;
        }
        let disagreement = self.cached - self.current;
        let supported = self.bound == BOUND_EXACT
            || (disagreement > 0 && self.bound & BOUND_LOWER != 0)
            || (disagreement < 0 && self.bound & BOUND_UPPER != 0);
        supported
            && disagreement.abs() >= PAWN_VALUE / 2
            && (self.current - self.previous).abs() >= PAWN_VALUE / 3
    }
}

#[derive(Default)]
pub(crate) struct AuditBudget {
    pub spent: u16,
}

impl AuditBudget {
    #[allow(clippy::too_many_arguments)]
    #[inline(always)]
    pub fn child_depth(
        &mut self,
        evidence: bool,
        full: Depth,
        reduced: Depth,
        move_number: i32,
        capture: bool,
        checking: bool,
    ) -> Depth {
        if evidence
            && self.spent < AUDIT_LIMIT
            && (3..=8).contains(&move_number)
            && !capture
            && !checking
            && reduced < full
        {
            self.spent += 1;
            reduced + 1
        } else {
            reduced
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn evidence() -> Evidence {
        Evidence {
            depth: 7,
            current: 0,
            previous: 200,
            cached: 200,
            cached_depth: 5,
            bound: BOUND_LOWER,
        }
    }

    #[test]
    fn bound_must_support_the_disagreement_direction() {
        let mut e = evidence();
        assert!(e.disagrees());
        e.bound = BOUND_UPPER;
        assert!(!e.disagrees());
        e.cached = -200;
        assert!(e.disagrees());
        e.bound = BOUND_LOWER;
        assert!(!e.disagrees());
        e.bound = BOUND_EXACT;
        assert!(e.disagrees());
        e.bound = BOUND_NONE;
        assert!(!e.disagrees());
    }

    #[test]
    fn two_separate_finite_signals_and_recent_depth_are_required() {
        let mut e = evidence();
        e.previous = 0;
        assert!(!e.disagrees());
        e.previous = 200;
        e.cached = 0;
        assert!(!e.disagrees());
        for missing in [VALUE_NONE, VALUE_MATE, VALUE_TB, i32::MIN, i32::MAX] {
            e.cached = missing;
            assert!(!e.disagrees());
            e = evidence();
            e.previous = missing;
            assert!(!e.disagrees());
            e = evidence();
            e.current = missing;
            assert!(!e.disagrees());
            e = evidence();
        }
        e.cached_depth = 3;
        assert!(!e.disagrees());
        e = evidence();
        e.depth = 11;
        assert!(!e.disagrees());
    }

    #[test]
    fn budget_is_hard_and_never_extends_beyond_full_depth() {
        let mut budget = AuditBudget::default();
        for _ in 0..AUDIT_LIMIT {
            assert_eq!(budget.child_depth(true, 5, 4, 3, false, false), 5);
        }
        for _ in 0..100 {
            assert_eq!(budget.child_depth(true, 5, 4, 3, false, false), 4);
        }
        assert_eq!(budget.spent, AUDIT_LIMIT);
        budget = AuditBudget::default();
        assert_eq!(budget.child_depth(true, 4, 4, 3, false, false), 4);
        assert_eq!(budget.child_depth(true, 4, 5, 3, false, false), 5);
        assert_eq!(budget.spent, 0);
    }

    #[test]
    fn ineligible_moves_spend_no_budget() {
        let mut budget = AuditBudget::default();
        for n in [-1, 0, 1, 2, 9, 100] {
            assert_eq!(budget.child_depth(true, 5, 3, n, false, false), 3);
        }
        assert_eq!(budget.child_depth(false, 5, 3, 4, false, false), 3);
        assert_eq!(budget.child_depth(true, 5, 3, 4, true, false), 3);
        assert_eq!(budget.child_depth(true, 5, 3, 4, false, true), 3);
        assert_eq!(budget.spent, 0);
    }
}
