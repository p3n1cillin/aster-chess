// Correctness checks for the Stockfish 19 Rust port.
//
// Perft results are the standard published counts. The NNUE tests compare the
// incrementally updated accumulators with a from-scratch refresh along random
// games, for every SIMD level available on the machine.

use aster_core::movegen::{GenType, MoveList};
use aster_core::nnue::accumulator::{AccumulatorCaches, AccumulatorStack, refresh_from_scratch};
use aster_core::nnue::network::{DEFAULT_NET_NAME, Network};
use aster_core::perft::perft;
use aster_core::position::{Position, START_FEN};
use aster_core::types::*;

fn pos(fen: &str, chess960: bool) -> Position {
    aster_core::init();
    let mut p = Position::default();
    p.set(fen, chess960).expect("valid FEN");
    p
}

#[test]
fn perft_standard_positions() {
    let cases: &[(&str, i32, u64)] = &[
        (START_FEN, 5, 4_865_609),
        (
            "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
            4,
            4_085_603,
        ),
        ("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", 6, 11_030_083),
        (
            "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
            5,
            15_833_292,
        ),
        (
            "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8",
            4,
            2_103_487,
        ),
        (
            "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10",
            4,
            3_894_594,
        ),
    ];
    for &(fen, depth, nodes) in cases {
        let mut p = pos(fen, false);
        assert_eq!(perft(&mut p, depth, false), nodes, "{fen}");
    }
}

#[test]
fn perft_chess960() {
    // Chess960 positions; counts confirmed with the official Stockfish 19 binary.
    let cases: &[(&str, i32, u64)] = &[
        (
            "bqnb1rkr/pp3ppp/3ppn2/2p5/5P2/P2P4/NPP1P1PP/BQ1BNRKR w HFhf - 2 9",
            4,
            326_672,
        ),
        (
            "2nnrbkr/p1qppppp/8/1ppb4/6PP/3PP3/PPP2P2/BQNNRBKR w HEhe - 1 9",
            4,
            667_366,
        ),
        (
            "b1q1rrkb/pppppppp/3nn3/8/P7/1PPP4/4PPPP/BQNNRKRB w GE - 1 9",
            4,
            273_318,
        ),
    ];
    for &(fen, depth, nodes) in cases {
        let mut p = pos(fen, true);
        assert_eq!(perft(&mut p, depth, false), nodes, "{fen}");
    }
}

#[test]
fn fen_round_trip() {
    for fen in [
        START_FEN,
        "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
        "8/8/8/8/5kp1/P7/8/1K1N4 w - - 0 1",
        "rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3",
    ] {
        assert_eq!(pos(fen, false).fen(), fen);
    }
}

fn network() -> Option<Network> {
    let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join(DEFAULT_NET_NAME);
    if !path.exists() {
        eprintln!("skipping NNUE test: run python scripts/fetch_aster_network.py");
        return None;
    }
    Some(Network::load_file(&path).expect("network loads"))
}

/// Plays pseudo-random games, evaluating after every move with the incremental
/// stack and checking both perspectives against a full refresh.
#[test]
fn nnue_incremental_matches_refresh() {
    let Some(net) = network() else { return };
    aster_core::init();
    let mut rng = Prng::new(0x5EED_1234_ABCD_0001);
    let mut caches = AccumulatorCaches::new(&net.ft);
    for game in 0..60 {
        let mut p = pos(START_FEN, false);
        let mut stack = AccumulatorStack::default();
        stack.reset();
        let mut played = Vec::new();
        for _ in 0..120 {
            let moves = MoveList::new(&p, GenType::Legal);
            if moves.is_empty() || p.rule50_count() > 99 {
                break;
            }
            let m = moves.as_slice()[(rng.rand64() % moves.len() as u64) as usize];
            let gc = p.gives_check(m);
            let d = stack.push();
            p.do_move(m, gc, Some(d));
            played.push(m);
            if p.checkers() == 0 {
                net.evaluate(&p, &mut stack, &mut caches);
                for c in [WHITE, BLACK] {
                    let (acc, psqt) = refresh_from_scratch(c, &net.ft, &p);
                    assert!(
                        acc == stack.latest().accumulation[c],
                        "game {game} ply {} perspective {c}",
                        played.len()
                    );
                    assert_eq!(psqt, stack.latest().psqt[c]);
                }
            }
            // Occasionally retract moves to exercise backward updates and caches.
            if rng.rand64() % 7 == 0 && played.len() > 2 {
                for _ in 0..2 {
                    let m = played.pop().unwrap();
                    p.undo_move(m);
                    stack.pop();
                }
            }
        }
    }
}
