// Copyright (C) 2026 Aster contributors.
// SPDX-License-Identifier: GPL-3.0-or-later
// Development-only native driver. Normal return permits profiling data to flush.

use std::process::ExitCode;

fn main() -> ExitCode {
    let mut args: Vec<String> = std::env::args().skip(1).collect();
    if args.first().is_some_and(|arg| arg == "core") {
        args.remove(0);
    }
    let status = aster_core::run_uci(
        aster_core::Identity {
            name: format!("Aster {}", env!("CARGO_PKG_VERSION")),
            author: "Aster contributors".to_string(),
            aster_extensions: true,
        },
        args,
    );
    ExitCode::from(u8::try_from(status).unwrap_or(1))
}
