// Aster Core: a faithful Rust port of Stockfish 19.
// Copyright (C) 2004-2026 The Stockfish developers (see AUTHORS file)
// Rust port copyright (C) 2026 Aster contributors.
// Licensed under the GNU General Public License v3 or later.

fn main() {
    let code = aster_core::run_uci(
        aster_core::Identity::default(),
        std::env::args().skip(1).collect(),
    );
    std::process::exit(code);
}
