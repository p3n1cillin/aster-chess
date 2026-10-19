# Aster native Rust core

On 2026-10-19 the user authorized porting Stockfish to Rust and using it to make
Aster stronger. `crates/aster-core` is that port; since Aster 1.0.0 it is Aster's
default UCI engine. The previous Viridithas-derived core runs as `aster legacy`.

## Commands

```
python scripts/fetch_aster_network.py
cargo build --release --locked
./target/release/aster                 # UCI, Aster native Rust core
./target/release/aster core bench      # bench of the default core
./target/release/aster legacy          # UCI, previous Viridithas-derived core
./target/release/aster-core bench         # standalone Aster UCI engine
./target/release/aster-core speedtest     # multi-threaded benchmark
```

Tablebases: set `SyzygyPath` as in Stockfish (`;`-separated on Windows). For
development, `python scripts/fetch_syzygy_dev_tables.py` fetches all 3- and
4-piece WDL/DTZ tables (4.3 MB, SHA-256 pinned) and
`python scripts/verify_syzygy_probe.py --engine <exe> --tables tools/syzygy-development-v2`
compares the engine's probes with python-chess.

In Aster mode the core also answers `legal`, `legal-exists`, `d` (as
`info string fen â€¦`), `go perft N` (adds an `info depth N nodes â€¦` line) and
`aster-trace on|off`, so the browser play host and Aster's python-chess
verifiers work unchanged. Tracing only observes the search: best move, score and
node count are identical with tracing on and off (checked by `verify_rust.py`).

## Evidence

| Check | Result |
| --- | --- |
| `bench` signature | 2,497,913 nodes, equal to the official `sf_19` binary |
| Bench `info`/`bestmove` lines (51 searches) | identical to the official binary, excluding time and nps |
| NNUE static eval vs official `eval` | 45/45 evaluable bench positions identical |
| Kernel paths | AVX-512 VNNI, AVX2 and scalar all give 2,497,913 |
| Perft | published counts, standard and Chess960 |
| Incremental vs refreshed accumulators | equal along 60 random games, every SIMD level |
| `scripts/verify.py` on Aster 1.0.0 | passed: 1,630 positions, 14 perft checks, trace replay |
| `scripts/verify_rust_legal_edges.py` | passed: 94 positions |
| `scripts/smoke_rust_play.py` | passed against the new core |
| UCI | `isready`/`stop` answered in under 1 ms during a 4-thread infinite search |
| Syzygy WDL+DTZ vs python-chess (`scripts/verify_syzygy_probe.py`) | 14,000/14,000 positions equal (35 tables, 3â€“4 man) |
| Syzygy searches vs official binary | 260/260 output lines identical (17 positions, depth 14, DTZ tables) |

One verifier expectation changed deliberately. With the fifty-move clock at 100
in `7k/8/6K1/8/8/8/8/R7 w - - 100 1`, Stockfish semantics give Ra8# (mate 1):
a fifty-move draw must be claimed by the side to move (FIDE 9.3), so it does not
end the game by itself. The legacy core still treats the claimable draw as
final, and `verify_rust.py` keeps that expectation for `aster legacy`.

## Speed

Five interleaved `bench` runs per engine, one thread, 16 MB hash, same session,
Ryzen 5 7600X (Zen 4, AVX-512 VNNI), Windows:

| Engine | Median nodes/s | Relative |
| --- | ---: | ---: |
| Official Stockfish 19 (GCC 15.2, AVX-512 ICL build) | 2,059,285 | 100% |
| Aster Core 19 (Rust, generic x86-64 with runtime SIMD dispatch) | 1,791,903 | 87.0% |
| Aster 1.0.0 core (same code, embedded network) | 1,793,189 | 87.1% |

The port started at 323K nodes/s with scalar NNUE kernels. The main gains were
AVX-512 VNNI and AVX2 kernels (sparse fc0 with compressed non-zero lists, tiled
accumulator updates, pairwise transform), prefetching weight rows and history
entries, 64-byte aligned weights and accumulators, removing hidden 4 KB copies of
`const` lookup tables, and AVX-512 VBMI2 move writers. Rust was not the limit on
these kernels. The remaining 12â€“13% is spread across search, move ordering and
memory latency (line-level sampling with `--features sampler`, a linker map or
PDB line tables and `llvm-symbolizer`).

Tried without a measurable gain, recorded so they are not repeated blindly:
Rust profile-guided optimization with the `llvm-tools` component (1.75M vs 1.79M
nodes/s, slower), `-C target-cpu=native` for the whole crate, Stockfish's AVX2
dual hyperbola slider attacks (kept for AVX2 builds; identical attacks on 1.28M
random occupancies), Stockfish's AVX-512 16-move sorter (kept; same order),
vectorized PSQT updates and fc2 (kept), and prefetching both halves of every
weight row (reverted: slower). Every kept change preserved the bench signature.

## Equal-time match

`scripts/paired_match.py` played 64 color-swapped pairs from
`tests/fixtures/openings-v4.json` at 8+0.08 s, one thread, 16 MB hash, five games
concurrently, against the pinned official Stockfish 19 binary. Aster 1.0.0 scored
**5 wins, 2 losses, 121 draws** (51.2%), pentanomial [LL, LD, DD, WD, WW] =
[0, 2, 57, 5, 0], Elo **+8.1** with a 95% interval of **âˆ’5.9 to +22.2**. No games
were unresolved. The interval includes zero: this is equality within noise, not
superiority. Report and PGN: `artifacts/matches/aster-1.0.0-vs-sf19-8+0.08-64pairs.*`.

The same setup at 30+0.3 s (2026-10-19, Aster binary SHA-256 `38ae0bf9…`,
Stockfish `45bc8e49…`, openings `5d2b8f4a…`) gave **1 win, 0 losses, 127 draws**
(50.4%), pentanomial [0, 0, 63, 1, 0], Elo **+2.7** with a 95% interval of
**−2.6 to +8.0**, no unresolved games. The draw rate rises with time, and the
interval again includes zero. Report and PGN:
`artifacts/matches/aster-1.0.0-vs-sf19-30+0.3-64pairs.*`.

## Development-source update (2026-10-19)

With the user's approval the core was brought up to the Stockfish development
source at commit `effdc3fd3f6de6e75fe1374a51a7a7eed66f880b` (2026-10-17, 55
commits after `sf_19`): the SFNNv18 network `nn-c9e480e92425` (K32Q2 features,
int8 weights, no PSQT, 32 layer stacks, new evaluation scaling), legal-only move
generation, lazily computed threat maps, about fifteen search changes and two
time-management changes. The port is exact: `bench` gives **1,559,611 nodes**,
and all 690 bench `info`/`bestmove` lines and all 45 static evaluations equal
the same commit built from source with clang 21. AVX-512, AVX2 and scalar kernel
paths give the same signature. All python-chess verifiers, perft and the
mate-proof and play smoke tests pass, as do 149 workspace tests in release and
the core's tests in debug.

Speed against that clang build of the same commit is 93.1% (7 interleaved
bench runs; see the crate README for the individual Aster changes).

Before porting, a scouting match of the clang-built development commit against
the official Stockfish 19 binary at 8+0.08 (128 pairs) gave +2.7 Elo,
95% interval −8.0 to +13.4: the development source's gain over 19 at short time
controls is small. The ported Aster core then played the official Stockfish 19
binary at 8+0.08, 128 color-swapped pairs, one thread, 16 MB hash: **4 wins, 4
losses, 248 draws**, pentanomial [0, 4, 120, 4, 0], Elo **0.0**, 95% interval
**−7.6 to +7.6**, no unresolved games. That run used the core at about 90.6% of
the reference speed, before the Aster speed work. Report and PGN:
`artifacts/matches/aster-sfdev-port-vs-sf19-8+0.08-128pairs.*` (the report's
final fields were added after a file-lock error at the end; see its `note`).

## Strength claims

No strength claim follows from these results. The core plays the pinned
development commit's moves at fixed depth and is level with Stockfish 19 within
noise at equal time. Any
claim that Aster is stronger than Stockfish requires predeclared paired matches
with a statistical lower bound above 50%, as described in `ROADMAP.md`.

Engine/crate branding now uses Aster. See [current commands and validation](ASTER-CORE.md).
