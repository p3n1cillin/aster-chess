// Aster core. Original attribution and source mapping: mod.rs.license.
// SPDX-License-Identifier: GPL-3.0-or-later
// Modified 2026-10-19: source naming and notice layout only.

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
pub fn evaluate(
    net: &Network,
    pos: &Position,
    stack: &mut AccumulatorStack,
    caches: &mut AccumulatorCaches,
    optimism: i32,
) -> Value {
    debug_assert!(pos.checkers() == 0);
    let nnue = net.evaluate(pos, stack, caches);
    scale_evaluation(nnue, optimism, pos)
}

/// Material balance from the side to move's point of view.
#[inline(always)]
fn simple_eval(pos: &Position) -> i32 {
    let us = pos.side_to_move();
    let them = flip_color(us);
    PAWN_VALUE * (pos.count(us, PAWN) - pos.count(them, PAWN)) + pos.non_pawn_material_c(us)
        - pos.non_pawn_material_c(them)
}

/// Applies search-dependent scaling (optimism, material, rule50) to the raw
/// network output.
pub fn scale_evaluation(nnue: Value, optimism: i32, pos: &Position) -> Value {
    // Agreement between network and material, each squashed into [-1024, 1024]:
    // easy positions (agreement) are boosted when winning, complex ones damped.
    let se = simple_eval(pos);
    let se_norm = se * 1024 / (se.abs() + 1024);
    let nnue_norm = nnue * 1024 / (nnue.abs() + 1024);
    let correl = se_norm * nnue_norm / 512;

    let mut v = nnue + nnue * correl / 65536 + optimism * correl / 16384;

    // Scale the combined evaluation by total material
    let material = 521 * pos.count_both(PAWN) + pos.non_pawn_material();
    v += (material as i64 * v as i64 / 90649) as i32;

    // Damp down the evaluation linearly when shuffling
    v -= v * pos.rule50_count() / 189;

    v.clamp(VALUE_TB_LOSS_IN_MAX_PLY + 1, VALUE_TB_WIN_IN_MAX_PLY - 1)
}
