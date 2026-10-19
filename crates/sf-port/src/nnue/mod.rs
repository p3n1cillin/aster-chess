// Rust port of Stockfish 19 NNUE evaluation and `evaluate.cpp`.
// Copyright (C) 2004-2026 The Stockfish developers (see AUTHORS file)
// Licensed under the GNU General Public License v3 or later.

pub mod accumulator;
pub mod aligned;
pub mod features;
pub mod kernels;
pub mod network;

use crate::position::Position;
use crate::types::*;
use accumulator::{AccumulatorCaches, AccumulatorStack};
use network::Network;

pub fn init() {
    features::init();
    kernels::init();
}

/// Static evaluation from the point of view of the side to move.
pub fn evaluate(net: &Network, pos: &Position, stack: &mut AccumulatorStack, caches: &mut AccumulatorCaches, optimism: i32) -> Value {
    debug_assert!(pos.checkers() == 0);
    let (psqt, positional) = net.evaluate(pos, stack, caches);
    let mut nnue = psqt + positional;

    // Blend optimism and eval with nnue complexity
    let complexity = (psqt - positional).abs() as i64;
    let optimism = optimism + (optimism as i64 * complexity / 476) as i32;
    nnue -= (nnue as i64 * complexity / 18236) as i32;

    let material = 534 * pos.count_both(PAWN) + pos.non_pawn_material();
    let mut v = nnue + ((nnue as i64 * material as i64 + optimism as i64 * 7675) / 91000) as i32;

    // Damp down the evaluation linearly when shuffling
    v -= v * pos.rule50_count() / 199;

    v.clamp(VALUE_TB_LOSS_IN_MAX_PLY + 1, VALUE_TB_WIN_IN_MAX_PLY - 1)
}
