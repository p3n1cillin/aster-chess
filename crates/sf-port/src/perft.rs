// Rust port of Stockfish 19 `perft.h`.
// Copyright (C) 2004-2026 The Stockfish developers (see AUTHORS file)
// Licensed under the GNU General Public License v3 or later.

use crate::movegen::{GenType, MoveList};
use crate::position::Position;
use crate::types::Depth;
use crate::uci;

/// Counts all the leaf nodes up to the given depth (move generation check).
pub fn perft(pos: &mut Position, depth: Depth, root: bool) -> u64 {
    let mut nodes = 0;
    let leaf = depth == 2;
    for &m in MoveList::new(pos, GenType::Legal).as_slice() {
        let cnt;
        if root && depth <= 1 {
            cnt = 1;
            nodes += 1;
        } else {
            pos.do_move_simple(m);
            cnt = if leaf { MoveList::new(pos, GenType::Legal).len() as u64 } else { perft(pos, depth - 1, false) };
            nodes += cnt;
            pos.undo_move(m);
        }
        if root {
            println!("{}: {}", uci::move_to_uci(m, pos.is_chess960()), cnt);
        }
    }
    nodes
}
