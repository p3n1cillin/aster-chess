# Aster Rust

Aster is now developed and built in **Rust only**. Its active engine is an
attributed source fork of **Viridithas 20.0.0**, with its original trained neural
network, Aster's independently checkable mating certificates, and a native Rust
browser host. It does not invoke Stockfish, python-chess or the legacy C# engine
at runtime. The upstream MIT notice and exact source fingerprints are preserved
in `crates/engine/LICENSE.upstream-MIT` and `crates/engine/UPSTREAM.json`.

The goal remains to surpass full-strength Stockfish in reproducible, controlled
playing-strength tests. **That goal has not been achieved.** Adopting a strong
engine's source or finding a faster build is not evidence of surpassing it.

## Build and play

Install Rust using [rustup](https://rustup.rs/). The repository pins Rust 1.99.1.
The x86-64 builds require AVX2/BMI2 (x86-64-v3). No .NET or C/C++ compiler is used
by Aster's build. Optional upstream C tablebases and C zstd are disabled; weights
are decompressed in Rust and embedded in the executable.

```powershell
python scripts/fetch_rust_network.py
cargo build --release --locked
cargo test --release --locked
cargo run --release --locked -- play 5188
```

Open **http://127.0.0.1:5188**. Select White or Black, set the thinking budget,
play legal moves, take back moves, analyze a FEN, inspect search samples and
principal variations, and export PGN. Windows convenience launchers:

```powershell
./scripts/build.ps1
./scripts/play.ps1
```

On a Windows network share, use these scripts: they put executables in a local
Cargo target directory, allowing the source checkout to remain on the share.
If Windows blocks unsigned scripts on the share, use a process-scoped invocation:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File ./scripts/build.ps1
pwsh -NoProfile -ExecutionPolicy Bypass -File ./scripts/play.ps1 -SkipBuild
```

The web server and its search workers run the same Rust executable. Its board,
move rules, SAN and proof solver are also Rust. HTML/CSS/JavaScript presentation
assets are embedded; no frontend build or remote runtime service is required.

## UCI and verification

```powershell
cargo run --release --locked
# uci
# isready
# position startpos moves e2e4 e7e5
# go movetime 1000
cargo run --release --locked -- bench 7
python -m pip install -r requirements-dev.txt
python scripts/verify.py
python scripts/smoke_rust_play.py
python scripts/smoke_mate_proof.py
```

`stop` and `isready` remain responsive during search. Extra diagnostics include
`legal`, `legal-exists`, `d`, and `aster-trace on|off`. Live visualization shows actual sampled
branches (including hypothetical null moves), search-function counts, visit
heatmaps, real root attempt bounds and completed-depth evaluations. Samples are
not a recording of every searched position. Neural values are not presented as
a fictitious classical evaluation breakdown.

To export a bounded mating strategy from a FEN origin:

```powershell
./target/release/aster.exe certify-mate proof.json 5 white "7k/8/5KQ1/8/8/8/8/8 w - - 0 1"
python scripts/verify_mate_proof.py proof.json --output verified-proof.json
```

A complete certificate covers every legal defensive reply and ends only in real
checkmate. Work limits, draw rules or an insufficient bound produce an incomplete
result, never a winning certificate. This adds independently inspectable evidence
alongside the heuristic playing search.

## Research, rating and provenance

See [Rust migration](docs/RUST-MIGRATION.md), [roadmap](ROADMAP.md),
[results](artifacts/PROGRESS.md) and [rating policy](docs/RATING.md).
The Rust build has **no calibrated Elo yet**. The last measured original Aster
build was about **2319 (95% interval 2277–2360)** on a local Stockfish 19
UCI_Elo-setting scale at 30 ms/move, one thread and 64 MiB hash. That rating is
not transferred to Rust and is not a public rating.

Original C# code, failed experiments and archived binaries remain as historical
research evidence. They are not built by current scripts or CI. Their former
instructions are preserved in [the legacy README](docs/LEGACY-CSHARP-README.md).
The former Berserk/C++ exploration is retained only in its research branches.

Original Aster additions are GPL-3.0-or-later; upstream files retain their own
notices. See [licenses and attribution](THIRD_PARTY_NOTICES.md) and
[contribution guidance](CONTRIBUTING.md).
