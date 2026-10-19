# Aster Core

Aster's native Rust UCI search and neural evaluation core. It runs directly
inside the Aster executable and also builds as the standalone `aster-core`
engine. No external engine process or C++ runtime is used. The public engine
identity is **Aster 1.0.0**. See [the branding/refactor record](../../docs/ASTER-CORE.md)
for compatibility and unchanged-search validation.

Stockfish is copyright the Stockfish developers (see [AUTHORS](AUTHORS)) and is
licensed under the GNU GPL v3 or later ([Copying.txt](Copying.txt)). This port is
distributed under the same license. [UPSTREAM.json](UPSTREAM.json) pins the release,
the reference binary, the network and a SHA-256 for every ported C++ source file.

## Implementation

Bitboards and attacks (magic bitboards, plus AVX2 dual hyperbola
quintessence on AVX2 builds), position and make/unmake including NNUE threat
tracking, move generation, move ordering, all histories and correction
histories, the transposition table, search and quiescence search, Lazy SMP
threads, time management, UCI options and output, `bench`, `speedtest`, `perft`, Syzygy
tablebase probing (WDL/DTZ, root ranking, in-search probes, PV extension), and the
complete NNUE: K32Q2 (king bucket x opponent-queen), FullThreats and PP_3Wide
feature sets with int8 weights, the accumulator stack with queen-split
Finny-table caches (incremental forward/backward, hybrid king-move and refresh
paths) and 32 1024→32→32→1 layer stacks selected by piece count and queens.

Since 2026-10-19 the core follows the Stockfish development source at commit
`effdc3fd3f` (2026-10-17): the SFNNv18 network `nn-c9e480e92425`, legal-only move
generation, lazily computed threat maps and the search and time-management
changes made after `sf_19`. [UPSTREAM.json](UPSTREAM.json) pins the commit and a
SHA-256 for each ported source file.

Large pages: on Linux the network, histories, accumulator caches and
transposition table use 2 MiB aligned memory advised as transparent huge pages,
as upstream does (`src/large_pages.rs`); Windows large pages (which need the
lock-pages privilege) and NUMA binding are not ported.

## Exactness

The port reproduces Stockfish's search exactly, not approximately:

* `bench` reports **1,559,611 nodes**, the signature of the pinned
  development commit, and all 690 `info`/`bestmove` lines of the 51 bench
  searches are identical to that commit built from source (excluding time,
  nps and hashfull). Before the update the core matched the official `sf_19`
  binary in the same way (2,497,913 nodes).
* Raw and final NNUE evaluations equal the reference's on all 45 evaluable
  bench positions.
* The bench signature is identical on all three kernel paths: AVX-512 VNNI,
  AVX2 and scalar (`ASTER_SIMD=avx2|scalar` forces a lower path).
* Tests: published perft counts (standard and Chess960, Chess960 counts
  confirmed with the official binary), FEN round-trips, slider attacks against a
  reference generator, and incremental accumulators against full refreshes
  along random games. Aster's independent python-chess verifiers pass against
  this core as well.
* Syzygy: WDL and DTZ probes equal python-chess's independent reader on 14,000
  random positions across all 35 3- and 4-piece tables (both colors;
  `scripts/fetch_syzygy_dev_tables.py`, `scripts/verify_syzygy_probe.py`). With
  `SyzygyPath` set, fixed-depth searches of 17 tablebase positions print the
  same 260 lines as the official binary, including DTZ-extended PVs to mate.

Integer-exactness is what makes this possible: NNUE accumulators use wrapping
16-bit arithmetic and the layers use exact 32-bit dot products, so incremental,
refreshed, scalar and SIMD evaluations are bit-identical.

## Speed

Same-session medians of seven interleaved `bench` runs on a Ryzen 5 7600X
(Zen 4, AVX-512 VNNI), one thread, 16 MB hash, Windows. Both binaries search the
same 1,559,611-node bench:

| Binary | Nodes/second | Relative |
| --- | ---: | ---: |
| Pinned development commit, clang 21 `-O3 -flto -march=znver4` | 1,876,788 | 100% |
| Aster Core, generic x86-64 build with runtime SIMD dispatch | 1,746,484 | 93.1% |

Aster-side speed work since the update (each kept change preserved the
signature): history prefetches issued as soon as `do_move` knows the new keys
(+3.2%), L1 prefetch hints for search tables and plain-pointer access to
init-time tables (+1.1%), folded threat-index tables with packed dirty-threat
decoding, a two-perspective threat pass, unchecked fixed-capacity list pushes,
VBMI2 16-bit compresses for the first layer's non-zero list and range-masked
history indices (each within noise). Tried and rejected: paired `maddubs`
widening of int8 rows (2% slower on Zen 4) and a T2 hint for weight rows.

On a Linux Intel AVX-512 VM (2026-10-19), after porting huge pages and the
paired int8 widening add (AVX-512 and AVX2), Aster measured about 0.91–0.94 of
the upstream commit built with clang 18 (automatic AVX-512 path) and 0.84 of the
upstream `x86-64-bmi2` build on the forced AVX2 path; see
[the Linux speed record](../../docs/ASTER-LINUX-SPEED.md).

Speed is not strength evidence. At equal time, a slower identical search reaches
fewer nodes, so this port should be expected to score slightly below 50% against
the official binary until it is at least as fast.

## Build and run

```
python scripts/fetch_aster_network.py
cargo build --release --locked -p aster-core
./target/release/aster-core bench
```

The binary looks for `nn-c9e480e92425.nnue` in the working directory, next to the
executable and in this crate. The `embed-net` feature (used by Aster) embeds the
network after `build.rs` verifies its SHA-256.

Development-only features: `prof` (cycle counters around hot sections) and
`sampler` (Windows instruction-pointer sampling profiler).

Use `ASTER_SIMD=scalar|avx2` for development-only kernel selection. The former
SIMD variable and crate/helper names have been replaced by the Aster names.
