// Aster core. Original attribution and source mapping: main.rs.license.
// SPDX-License-Identifier: GPL-3.0-or-later
// Modified 2026-10-19: source naming and notice layout only.

fn main() {
    let code = aster_core::run_uci(
        aster_core::Identity::default(),
        std::env::args().skip(1).collect(),
    );
    std::process::exit(code);
}
