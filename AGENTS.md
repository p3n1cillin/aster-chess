# Aster development

The project goal is an independent chess engine that eventually surpasses
Stockfish in controlled playing-strength tests. Do not claim that goal has been
achieved without evidence. Do not implement the engine as a Stockfish wrapper.
Stockfish and python-chess are development tools only, never runtime dependencies.

On 2026-10-19 the user authorized a faithful Rust port of Stockfish 19 in
`crates/aster-core` (GPL-3.0-or-later, Stockfish attribution preserved). It is a
port, not a wrapper: no C++ code, Stockfish binary or external process runs
behind it. Its first acceptance gate is an identical `bench` node signature to
the pinned official sf_19 binary (2,497,913 nodes). The user's later goal is to
use the port to make Aster stronger than Stockfish; that remains unproven until
predeclared paired matches show it. A faster port is a speed result, not a
strength claim.

## Build and verification

Active development is Rust only, as requested by the user on 2026-10-18.
Do not build the historical C# implementation or introduce C/C++ build paths.
The active source foundation is an attributed Viridithas 20 Rust fork; preserve
its MIT notice and original source fingerprints. Stockfish is a development
opponent/research reference, never an external runtime engine behind Aster.

- `python scripts/verify_source_names.py`
- `python scripts/fetch_rust_network.py`
- `python scripts/fetch_aster_network.py`
- `cargo run --release --locked -p aster-core -- bench` must print 2,497,913 nodes
- `cargo build --workspace --release --locked`
- `cargo test --workspace --release --locked`
- `cargo test --workspace --locked`
- `.venv/Scripts/python.exe scripts/verify.py` on Windows, or the corresponding
  environment Python on other platforms.
- `.venv/Scripts/python.exe scripts/smoke_rust_play.py`
- `.venv/Scripts/python.exe scripts/verify_rust_legal_edges.py`
- `.venv/Scripts/python.exe scripts/smoke_mate_proof.py`
- `cargo run --release --locked -- bench 7`

Keep UCI stdout protocol-clean and responsive to `isready`/`stop` during search.
Every speculative move must be undone, including exceptions and cancellation.
Changes to move generation require perft and independent differential checks.
Search/evaluation changes require tactical checks and paired regression matches.
Keep all terminal game rules correct at the quiescence horizon as well as the root.

Preserve match reports and PGNs. Pin external engine versions and record binaries,
source fingerprints, options, openings, time controls and unresolved games.
Never infer Elo or Stockfish superiority from a few games or from search speed.
See `ROADMAP.md` for the research direction and `artifacts/PROGRESS.md` for results.

Editable source uses Aster naming. Preserve original per-file attribution in
adjacent `.license` notices and ship them with the source. Development-reference
URLs, historical keys and archive paths live in `scripts/research-reference.json`;
do not relabel opponents or modify frozen evidence to pass the source-name audit.
See `docs/SOURCE-NAMES.md` for the exact audit scope.
