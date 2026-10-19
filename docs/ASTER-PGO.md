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

The timing gate failed, so this profile will not replace the ordinary build.
No retraining or flag variants will be selected using these outcomes. The
predeclared 192 regression games must still complete and be audited. The 30 ms
control completes 96 games at 12W/78D/6L (53.125%, whole-family 95% interval
49.468..56.667%), with no forfeits, unresolved games or missing telemetry.
Its independent PGN and journal audits pass. The 100 ms control is running;
the final combined decision remains pending. Windows and Linux CI pass on
commit `418a64a3`. Neither speed nor this engineering regression screen
establishes reference-engine superiority or Elo.

The next source-level investigation is described in
`ASTER-FUSED-INPUT-INVESTIGATION.md`. It has no implemented or measured gain.
