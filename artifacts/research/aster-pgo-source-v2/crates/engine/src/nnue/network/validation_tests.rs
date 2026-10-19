//! Test-only independent arithmetic and incremental-state checks for embedded weights.

use super::{L1_SIZE, L2_SIZE, NNUEParams, NNUEState, QA, QB, layers, output_bucket};
use crate::{chess::board::Board, util::Align};

fn compare_fresh(board: &Board, incremental: &mut NNUEState, weights: &NNUEParams) {
    incremental.force(board, weights);
    let fresh = NNUEState::new(board, weights);
    let index = incremental.current_acc;
    for colour in crate::chess::piece::Colour::all() {
        assert_eq!(
            incremental.psqt_accumulators[index].halves[colour].0,
            fresh.psqt_accumulators[0].halves[colour].0,
            "PSQT accumulator: {board}"
        );
        assert_eq!(
            incremental.threat_accumulators[index].halves[colour].0,
            fresh.threat_accumulators[0].halves[colour].0,
            "Auxiliary accumulator: {board}"
        );
    }
    assert_eq!(
        incremental.evaluate(weights, board),
        fresh.evaluate(weights, board)
    );
}

#[test]
fn incremental_and_undo_match_fresh_weights() {
    fn visit(board: &mut Board, state: &mut NNUEState, weights: &NNUEParams, depth: usize) {
        compare_fresh(board, state, weights);
        if depth == 0 {
            return;
        }
        let before = board.clone();
        for mov in board.legal_moves() {
            board.make_move(mov, state);
            visit(board, state, weights, depth - 1);
            board.unmake_move(state);
            assert_eq!(*board, before);
            compare_fresh(board, state, weights);
        }
    }
    let weights = NNUEParams::decompress_and_alloc().unwrap();
    for (fen, depth) in [
        (Board::STARTING_FEN, 2),
        (
            "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
            2,
        ),
        ("5B2/7B/6P1/R4pPk/8/7K/8/8 w - f6 0 1", 1),
        ("8/8/8/8/R1pP2k1/8/8/7K b - d3 0 1", 1),
        ("1r5k/P7/6K1/8/8/8/8/8 w - - 0 1", 2),
    ] {
        let mut board = Board::from_fen(fen).unwrap();
        let mut state = NNUEState::new(&board, weights);
        visit(&mut board, &mut state, weights, depth);
    }
}

#[test]
fn lazy_batches_and_history_match_fresh_weights() {
    let weights = NNUEParams::decompress_and_alloc().unwrap();
    let mut seed = 20_261_019_u64;
    for _ in 0..8 {
        let mut board = Board::startpos();
        let root = board.clone();
        let mut state = NNUEState::new(&board, weights);
        let mut count = 0;
        for ply in 0..80 {
            let legal = board.legal_moves();
            if legal.is_empty() {
                break;
            }
            seed = seed.wrapping_mul(6_364_136_223_846_793_005).wrapping_add(1);
            let index = usize::try_from(seed >> 32).unwrap() % legal.len();
            board.make_move(legal[index], &mut state);
            count += 1;
            // Leave several lazy deltas pending between refresh comparisons.
            if ply % 7 == 6 {
                compare_fresh(&board, &mut state, weights);
            }
        }
        compare_fresh(&board, &mut state, weights);
        for _ in 0..count {
            board.unmake_move(&mut state);
            compare_fresh(&board, &mut state, weights);
        }
        assert_eq!(board, root);
    }
}

// The product configuration is AVX2 x86-64-v3. This scalar oracle explicitly
// models packus lane order, then performs dense integer dot products, without
// using the SIMD activation, sparse indexes or vector multiply-add routines.
#[cfg(all(
    target_arch = "x86_64",
    target_feature = "avx2",
    not(target_feature = "avx512f")
))]
#[test]
fn scalar_l1_matches_simd_for_embedded_weights() {
    let weights = NNUEParams::decompress_and_alloc().unwrap();
    let mut board = Board::startpos();
    let mut seed = 20_261_020_u64;
    for _ in 0..80 {
        let state = NNUEState::new(&board, weights);
        let mut inputs = [0_i32; L1_SIZE];
        let colours = [board.turn(), !board.turn()];
        for (half, colour) in colours.into_iter().enumerate() {
            let psqt = &state.psqt_accumulators[0].halves[colour].0;
            let auxiliary = &state.threat_accumulators[0].halves[colour].0;
            for block in (0..L1_SIZE / 2).step_by(32) {
                for lane in 0..32 {
                    let source = block + [0, 16, 8, 24][lane / 8] + lane % 8;
                    let left = (i32::from(psqt[source]) + i32::from(auxiliary[source]))
                        .clamp(0, i32::from(QA));
                    let source_right = source + L1_SIZE / 2;
                    let right = (i32::from(psqt[source_right])
                        + i32::from(auxiliary[source_right]))
                    .clamp(0, i32::from(QA));
                    inputs[half * L1_SIZE / 2 + block + lane] = (left * right) >> 9;
                }
            }
        }
        let bucket = output_bucket(&board);
        let mut simd_output = Align([0.0; L2_SIZE]);
        layers::activate_ft_and_propagate_l1(
            &state.psqt_accumulators[0].halves[colours[0]],
            &state.psqt_accumulators[0].halves[colours[1]],
            &state.threat_accumulators[0].halves[colours[0]],
            &state.threat_accumulators[0].halves[colours[1]],
            &weights.l1_weights[bucket],
            &weights.l1_bias[bucket],
            &mut simd_output,
        );
        for output in 0..L2_SIZE {
            let mut sum = 0_i64;
            for (input, value) in inputs.iter().enumerate() {
                let offset = input / 4 * L2_SIZE * 4 + output * 4 + input % 4;
                sum += i64::from(*value) * i64::from(weights.l1_weights[bucket][offset]);
            }
            let sum = i32::try_from(sum).expect("Dense integer dot product must not overflow");
            #[allow(clippy::cast_precision_loss)]
            let multiplier = 512.0 / (f32::from(QA) * f32::from(QA) * f32::from(QB));
            #[allow(clippy::cast_precision_loss)]
            let preactivation = (sum as f32).mul_add(multiplier, weights.l1_bias[bucket][output]);
            let scalar = preactivation * (preactivation + 3.0).clamp(0.0, 6.0) * (1.0 / 6.0);
            let actual = simd_output[output];
            assert!(actual.is_finite() && scalar.is_finite());
            assert!(
                (actual - scalar).abs() <= 0.00001 * (1.0 + scalar.abs()),
                "L1 arithmetic mismatch: {actual} versus {scalar}, output {output}, {board}"
            );
        }
        let legal = board.legal_moves();
        if legal.is_empty() {
            board = Board::startpos();
        } else {
            seed = seed.wrapping_mul(6_364_136_223_846_793_005).wrapping_add(1);
            board.make_move_simple(legal[usize::try_from(seed >> 32).unwrap() % legal.len()]);
        }
    }
}
