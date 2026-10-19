# SF-Port: Stockfish 19 in Rust

A faithful Rust port of the [Stockfish](https://github.com/official-stockfish/Stockfish)
19 chess engine (tag `sf_19`). It is a port, not a wrapper: no C++ code, Stockfish
binary or external process runs behind it. It is Aster's default playing core
(`crates/engine`), and it also builds as a standalone UCI engine (`sf-port`).

Stockfish is copyright the Stockfish developers (see [AUTHORS](AUTHORS)) and is
licensed under the GNU GPL v3 or later ([Copying.txt](Copying.txt)). This port is
distributed under the same license. [UPSTREAM.json](UPSTREAM.json) pins the release,
the reference binary, the network and a SHA-256 for every ported C++ source file.

## What is ported

Bitboards and attacks (magic bitboards, plus Stockfish's AVX2 dual hyperbola
quintessence on AVX2 builds), position and make/unmake including NNUE threat
tracking, move generation, move ordering, all histories and correction
histories, the transposition table, search and quiescence search, Lazy SMP
threads, time management, UCI options and output, `bench`, `perft`, Syzygy
tablebase probing (WDL/DTZ, root ranking, in-search probes, PV extension), and the
complete SF 19 NNUE: HalfKAv2_hm, FullThreats and PP_3Wide feature sets, the
accumulator stack with Finny-table caches (incremental forward/backward,
hybrid king-move and refresh paths) and the 1024→32→32→1 layer stacks.

Not yet ported: NUMA binding, large pages and the `speedtest` command. Syzygy
WDL probing is verified (below); DTZ probing is ported but not yet verified,
because no DTZ tables are available locally.

## Exactness

The port reproduces Stockfish's search exactly, not approximately:

* `bench` reports **2,497,913 nodes**, the same signature as the official
  `sf_19` binary, and every one of the 51 bench searches prints identical
  `info` lines (depth, seldepth, score, nodes, hashfull, PV) and best moves.
* NNUE static evaluations equal the official binary's on all 45 evaluable
  bench positions, including the two threat-heavy stress positions.
* The bench signature is identical on all three kernel paths: AVX-512 VNNI,
  AVX2 and scalar (`SF_PORT_SIMD=avx2|scalar` forces a lower path).
* Tests: published perft counts (standard and Chess960, Chess960 counts
  confirmed with the official binary), FEN round-trips, slider attacks against a
  reference generator, and incremental accumulators against full refreshes
  along random games. Aster's independent python-chess verifiers pass against
  this core as well.
* Syzygy: WDL probes equal python-chess's independent reader on 5,000 random
  positions (both colors, all 3-man development tables), and with
  `SyzygyPath` set, fixed-depth searches of 12 tablebase positions print the
  same 180 lines as the official binary (TB scores, tbhits, PVs).

Integer-exactness is what makes this possible: NNUE accumulators use wrapping
16-bit arithmetic and the layers use exact 32-bit dot products, so incremental,
refreshed, scalar and SIMD evaluations are bit-identical.

## Speed

Same-session medians of five interleaved `bench` runs on a Ryzen 5 7600X
(Zen 4, AVX-512 VNNI), one thread, 16 MB hash, Windows:

| Binary | Nodes/second | Relative |
| --- | ---: | ---: |
| Official Stockfish 19 (GCC, AVX-512 ICL universal build) | 2,059,285 | 100% |
| SF-Port, generic x86-64 build with runtime SIMD dispatch | 1,791,903 | 87.0% |

Speed is not strength evidence. At equal time, a slower identical search reaches
fewer nodes, so this port should be expected to score slightly below 50% against
the official binary until it is at least as fast.

## Build and run

```
python scripts/fetch_sf_port_network.py
cargo build --release --locked -p sf-port
./target/release/sf-port bench
```

The binary looks for `nn-1a298aa575a0.nnue` in the working directory, next to the
executable and in this crate. The `embed-net` feature (used by Aster) embeds the
network after `build.rs` verifies its SHA-256.

Development-only features: `prof` (cycle counters around hot sections) and
`sampler` (Windows instruction-pointer sampling profiler).
