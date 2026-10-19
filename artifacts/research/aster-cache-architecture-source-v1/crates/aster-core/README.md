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
complete NNUE: HalfKAv2_hm, FullThreats and PP_3Wide feature sets, the
accumulator stack with Finny-table caches (incremental forward/backward,
hybrid king-move and refresh paths) and the 1024→32→32→1 layer stacks.

Not yet ported: NUMA binding and large pages (neither is used by the official
binary on a single-node machine without the lock-pages privilege).

## Exactness

The port reproduces Stockfish's search exactly, not approximately:

* `bench` reports **2,497,913 nodes**, the same signature as the official
  `sf_19` binary, and every one of the 51 bench searches prints identical
  `info` lines (depth, seldepth, score, nodes, hashfull, PV) and best moves.
* NNUE static evaluations equal the official binary's on all 45 evaluable
  bench positions, including the two threat-heavy stress positions.
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

Same-session medians of five interleaved `bench` runs on a Ryzen 5 7600X
(Zen 4, AVX-512 VNNI), one thread, 16 MB hash, Windows:

| Binary | Nodes/second | Relative |
| --- | ---: | ---: |
| Official Stockfish 19 (GCC, AVX-512 ICL universal build) | 2,059,285 | 100% |
| Aster Core, generic x86-64 build with runtime SIMD dispatch | 1,791,903 | 87.0% |

Speed is not strength evidence. At equal time, a slower identical search reaches
fewer nodes, so this port should be expected to score slightly below 50% against
the official binary until it is at least as fast.

## Build and run

```
python scripts/fetch_aster_network.py
cargo build --release --locked -p aster-core
./target/release/aster-core bench
```

The binary looks for `nn-1a298aa575a0.nnue` in the working directory, next to the
executable and in this crate. The `embed-net` feature (used by Aster) embeds the
network after `build.rs` verifies its SHA-256.

Development-only features: `prof` (cycle counters around hot sections) and
`sampler` (Windows instruction-pointer sampling profiler).

Use `ASTER_SIMD=scalar|avx2` for development-only kernel selection. The former
SIMD variable and crate/helper names have been replaced by the Aster names.
