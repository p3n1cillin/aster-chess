# Stockfish 19 Rust core

On 2026-10-19 the user authorized porting Stockfish to Rust and using it to make
Aster stronger. `crates/sf-port` is that port; since Aster 1.0.0 it is Aster's
default UCI engine. The previous Viridithas-derived core runs as `aster legacy`.

## Commands

```
python scripts/fetch_sf_port_network.py
cargo build --release --locked
./target/release/aster                 # UCI, Stockfish 19 Rust core
./target/release/aster core bench      # bench of the default core
./target/release/aster legacy          # UCI, previous Viridithas-derived core
./target/release/sf-port bench         # standalone port with Stockfish identity
```

In Aster mode the core also answers `legal`, `legal-exists`, `d` (as
`info string fen …`), `go perft N` (adds an `info depth N nodes …` line) and
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
| Syzygy WDL vs python-chess (`scripts/verify_syzygy_probe.py`) | 5,000/5,000 positions equal |
| Syzygy searches vs official binary | 180/180 output lines identical (12 positions, depth 14) |

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
| SF-Port 19 (Rust, generic x86-64 with runtime SIMD dispatch) | 1,791,903 | 87.0% |
| Aster 1.0.0 core (same code, embedded network) | 1,793,189 | 87.1% |

The port started at 323K nodes/s with scalar NNUE kernels. The main gains were
AVX-512 VNNI and AVX2 kernels (sparse fc0 with compressed non-zero lists, tiled
accumulator updates, pairwise transform), prefetching weight rows and history
entries, 64-byte aligned weights and accumulators, removing hidden 4 KB copies of
`const` lookup tables, and AVX-512 VBMI2 move writers. Rust was not the limit on
these kernels. The remaining 12–13% is spread across search, move ordering and
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
[0, 2, 57, 5, 0], Elo **+8.1** with a 95% interval of **−5.9 to +22.2**. No games
were unresolved. The interval includes zero: this is equality within noise, not
superiority. Report and PGN: `artifacts/matches/aster-1.0.0-vs-sf19-8+0.08-64pairs.*`.

## Strength claims

No strength claim follows from these results. The core plays Stockfish 19's
moves at fixed depth, but at equal time it is about 13% slower than the official
binary, so it should be expected to score slightly below 50% against it. Any
claim that Aster is stronger than Stockfish requires predeclared paired matches
with a statistical lower bound above 50%, as described in `ROADMAP.md`.
