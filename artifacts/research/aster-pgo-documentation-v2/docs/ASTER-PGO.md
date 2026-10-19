# Compiler profile experiment

This is a Windows Rust 1.99.1 engineering experiment, not a new chess
algorithm or a strength claim. The two predeclared plans are
`artifacts/research/aster-pgo-plan-v1.json` and `aster-pgo-plan-v2.json`.
Playing algorithms, neural weights and ordinary build flags remain unchanged.
The implementation follows the [Rust compiler PGO documentation](https://doc.rust-lang.org/rustc/profile-guided-optimization.html).

The first collection attempt produced zero main-search, quiescence and
evaluation counters. This was detected before any optimized candidate search,
timing or match. Its profiles, build logs and coverage failure are preserved.
The second plan repairs collection using a development-only Rust executable,
`aster-pgo-trainer`, which links the same core and returns normally so LLVM
can flush its counters. Aster itself remains the standalone playing engine.
The `pgo-driver` feature only enables that training executable.

Training is fixed: 64 prior foundation roots at depth 12, three automatic
canonical benches, one AVX2 bench, one scalar bench, and the actual play/proof
smoke workloads. The repaired collection preserves 13 raw profile files and
the merged profile. Both builds use the same pinned Rust compiler, explicit
Windows target, x86-64-v3 flags, release settings and driver feature. Only
instrumentation/profile-use flags differ as recorded in the build manifest.
The 96 new validation roots were excluded from compiler-training roots;
interior search overlap and neural-model training independence are unknown.

The repaired collection has positive coverage in all three required areas.
Control and optimized builds have identical canonical traces in automatic,
AVX2 and scalar modes, each with 1,559,611 nodes. They also match on 96 fresh
depth-9 roots per mode and on three tactical suites at 20,000 nodes.
Native PGO release, ordinary release and debug checks each pass 157 tests and
two compile-fail examples. Independent rules (2,630 positions and 14 perft
cases), 94 rule edges, real HTTP/SSE play, proof export, multithread stop and
root restoration pass.

The held-out timing test is complete. It used eight alternating-order batches
of 16 fresh roots per mode. Ratios below one mean faster candidate elapsed
time; intervals bootstrap whole batches.

| Mode | Median candidate/control | 95% interval | Gate |
| --- | ---: | ---: | --- |
| Automatic | 1.00016 | 0.98986–1.01505 | Fail |
| AVX2 | 1.09875 | 1.08710–1.10685 | Fail |
| Scalar | 0.99957 | 0.99168–1.01459 | Pass |

The timing gate failed, so this profile does not replace the ordinary build.
No retraining, flag variants or added games were selected using these outcomes.
All 192 predeclared regression games complete and pass independent PGN and
journal audits, without forfeits, unresolved games or missing telemetry.

| Control | W/D/L | Score | Whole-family 95% interval |
| --- | --- | ---: | --- |
| 30 ms | 12/78/6 | 53.125% | 49.468..56.667% |
| 100 ms | 8/80/8 | 50.000% | 46.111..53.804% |

Both pass the engineering nonregression screen; neither establishes a strength
gain. Windows and Linux CI pass on both the driver implementation (`418a64a3`)
and final hash-chain analysis (`54d33be6`). The decision is **not adopted** in
`artifacts/verification/aster-pgo-decision-v2.json`. The normal release binary
retains SHA-256 `6b4d46db1b89ba9b3fd228121ac931f7791972ef3cc0e1865d00b37f96fb69e2`.
Neither this screen nor compilation speed establishes reference-engine
superiority or Elo. The development driver and evidence tools are retained.

The next source-level investigation is described in
`ASTER-FUSED-INPUT-INVESTIGATION.md`. It has no implemented or measured gain.
