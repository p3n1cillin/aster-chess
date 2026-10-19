// Aster core. Original attribution and source mapping: lib.rs.license.
// SPDX-License-Identifier: GPL-3.0-or-later
// Modified 2026-10-19: source naming and notice layout only.

pub mod bitboard;
#[cfg(any(feature = "disagreement-guard", test))]
mod disagreement;
#[cfg(any(feature = "evaluation-risk", test))]
mod evaluation_risk;
pub mod history;
pub mod large_pages;
pub mod movegen;
pub mod movepick;
pub mod nnue;
pub mod perft;
pub mod position;
mod prof;
mod sampler;
pub mod search;
mod speedtest_positions;
pub mod syzygy;
pub mod timeman;
pub mod trace;
pub mod tt;
pub mod types;
pub mod uci;

/// Engine identity printed in response to `uci` and at startup.
#[derive(Clone)]
pub struct Identity {
    pub name: String,
    pub author: String,
    /// Aster debugging/observer commands (`legal`, `legal-exists`, `aster-trace`, ...).
    pub aster_extensions: bool,
}

impl Default for Identity {
    fn default() -> Self {
        Identity {
            name: uci::ENGINE_NAME.to_string(),
            author: uci::ENGINE_AUTHOR.to_string(),
            aster_extensions: false,
        }
    }
}

/// Initializes lookup tables and SIMD dispatch; safe to call more than once.
pub fn init() {
    bitboard::init();
    nnue::init();
    movegen::init();
    movepick::init();
}

/// Runs the UCI loop (commands from `args` are executed one-shot, as in the upstream reference).
pub fn run_uci(identity: Identity, args: Vec<String>) -> i32 {
    init();
    println!("info string {} by {}", identity.name, identity.author);
    let engine = match uci::Engine::new(identity) {
        Ok(e) => e,
        Err(e) => {
            println!("info string {e}");
            return 1;
        }
    };
    let mut u = uci::Uci { engine };
    u.loop_(args);
    0
}
