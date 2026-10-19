# Neural evaluation validation — 19 October 2026

Three test-only Rust guards now exercise the embedded network with independent
arithmetic and state reconstruction. They do not change the playing algorithm,
weights, inference, version or runtime dependencies. The production engine
remains Rust 0.9.2 with the pinned v109 Sandhi model.

- A dense scalar first-layer oracle compares against AVX2 SIMD over 80 seeded
  positions. It explicitly handles packing, clipped pairwise activation, dense
  integer products, bias and Hard-Swish. Integer overflow and non-finite values
  fail; floating outputs use a small relative arithmetic tolerance.
- Incremental accumulators and raw evaluation must equal a complete refresh at
  every visited branch and after undo. Positions include ordinary play,
  castling, en passant and promotions.
- Eight seeded legal walks leave up to seven lazy update steps pending, compare
  against fresh reconstruction, then undo all moves and check the original board.

The scalar packing oracle targets the normal x86-64-v3/AVX2 product configuration
used by Windows/Linux CI. It does not claim to validate other SIMD layouts.
These guards first passed locally with the existing v109 model before any model
trial. Cargo automatically includes them in release and debug test suites.

The later CC0 Hyperion trial uses the same guards but is a separate experiment.
Its newer trained data passes compatibility and arithmetic checks, yet misses a
predeclared expected-move gate. It is not adopted into the production engine.
The fixed playing sample and complete research evidence are preserved separately;
no upstream rating or historical C# rating is transferred to Rust.
