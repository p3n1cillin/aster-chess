# Contributing to Aster

Use GitHub issues for reproducible bugs and research proposals, and pull requests
for focused changes. State the observed behavior, the exact source version,
reproduction steps, validation results and remaining limitations. Do not infer
playing strength from a few games or from search speed.

Install Rust with rustup; `rust-toolchain.toml` pins the compiler. Active builds
are Rust only. Do not build the historical C# implementation.

```sh
python scripts/fetch_rust_network.py
cargo build --release --locked
cargo test --release --locked
cargo run --release --locked -- bench 7
```

For independent rule and protocol checks, create a Python environment, install
`requirements-dev.txt`, and run `python scripts/verify.py` and
`python scripts/smoke_rust_play.py`. CI also runs tactics and proof checks on Windows
and Linux. See [AGENTS.md](AGENTS.md) for verification required by each change.

Keep UCI stdout protocol-clean. Move-generation changes require perft and
independent differential checks. Search/evaluation changes require the documented
frozen tactics and paired playing gates before promotion. Preserve failed and
inconclusive experiments alongside successful results. Do not overwrite frozen
reports, datasets, source snapshots or SHA-256 manifests.

Useful starting points include reproducible rule/protocol bugs, browser usability,
independent proof verification, cross-platform build fixes and measured experiments
from [ROADMAP.md](ROADMAP.md). Read the corresponding research document before
repeating an experiment already rejected.

Contributions to original project files are offered under GPL-3.0-or-later.
Preserve third-party notices and licenses. Only submit material you can
redistribute; never include credentials or private machine configuration.
