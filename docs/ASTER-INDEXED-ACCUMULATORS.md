# Allocation-free indexed accumulator updates

This engineering experiment removes temporary heap vectors from AVX2 and scalar
neural accumulator updates. The baseline constructs lists of row references from
indices on each update or refresh; the candidate consumes those indices directly.
AVX2 retains the existing register tile width. The scalar path updates contiguous
rows with wrapping addition/subtraction and permits in-place refreshes. AVX-512,
neural weights, search algorithms and feature selection are unchanged.

The baseline is `7aa677ec`, binary SHA-256
`bd7d472f573053dfeac704805da4c8568820c693367fb5424cab65b57a07b99c`.
Its build sources match the frozen disagreement-default snapshot. The candidate
binary is `9361d9c3b066514451bf09a1767c534d8197f5909f06151433f531768cc81100`.
Its [source snapshot](../artifacts/research/aster-indexed-accumulators-source-v1/manifest.json)
includes the benchmark/check tools and original license notices.

The [fixed plan](../artifacts/research/aster-indexed-accumulators-plan-v1.json)
predates candidate queries. It fixes 16 AB/BA bench pairs in automatic and AVX2
modes, eight scalar pairs, explicit speed/nonregression gates and 128 paired
regression games on 64 fresh roots. The roots exclude 60 previously frozen
opening suites. There is no adaptive tuning or extension based on the results.
Timing occurs without compilation or matches; its scope is this desktop, without
CPU affinity or isolation. Forced AVX2 here does not measure every AVX2 processor.

The baseline's instrumented AVX2 profile places substantial cost in accumulator
work. These counters overlap and add measurement overhead; their cycle totals
are diagnostic, not a speed gain. The candidate must instead preserve full bench
outputs and fresh fixed-depth searches, then pass paired uninstrumented timing.
The `acc_kernel` counter covers slice-based dispatch, so it does not count direct
indexed paths; use the enclosing `acc_update` counter when comparing these paths.

Two new native tests compare the scalar and available AVX2 implementations with
an independent wide-integer sum narrowed once per lane. Each exercises 128 cases
with separate/in-place destinations, empty/duplicate/cancelling/mixed indices,
extreme signed weights/accumulators and unaligned byte rows. Tests avoid mutating
global SIMD selection. This checks numeric behavior, not just typical positions.

Before timing, all 64 fresh depth-nine comparisons agree in automatic, AVX2 and
scalar modes. The three tactical suites also preserve complete per-position
results at 20,000 nodes (32/32, 31/32, 16/16). Independent rules/stop/undo checks
pass in all modes; real HTTP/SSE play, terminal edges and mate certificates pass
in automatic and AVX2 modes. Both native profiles and the retained experimental
feature tests pass. The canonical core signature remains 1,559,611; legacy bench
seven remains 124,781.

No novelty, Elo or superiority claim follows from eliminating allocations. A local
speed gain would give more search work within a time budget, but playing-strength
improvement requires its own controlled evidence. Final results are recorded below.

## Completed timing

All 86 timed/warm runs preserve all 51 normalized search traces and the
1,559,611-node signature. Candidate/baseline elapsed ratios are:

| Mode | Pairs | Median ratio | 95% paired median interval | Gate |
| --- | ---: | ---: | --- | --- |
| Automatic (AVX-512 here) | 16 | 1.00060 | 0.99760..1.00298 | Pass |
| Forced AVX2 | 16 | 0.87589 | 0.87355..0.87694 | Pass |
| Forced scalar kernel | 8 | 0.64471 | 0.64095..0.64576 | Pass |

AVX2 uses 12.41% less elapsed time; the scalar kernel uses 35.53% less.
Automatic mode is effectively unchanged. These are same-work desktop results.
All modes use the same `x86-64-v3` build: compiler auto-vectorization remains
allowed in the scalar implementation. This does not measure a CPU lacking AVX2,
or promise these gains on other processors. The source-level allocation removal
does not depend on timing noise.

Both profiles pass **153 native tests plus two lifetime compile-fail checks**.
Windows and Linux [CI pass](https://github.com/p3n1cillin/aster-chess/actions/runs/39258829100),
including explicit AVX2 and scalar signature checks. The tested source snapshots
and binary copies pass their fingerprint audits.

## Adoption decision

All 128 declared games complete and pass independent PGN replay and complete
journal/report checks. There are no forfeits, unresolved games or missing search
telemetry. Both modes use 30 ms/move, one thread and 64 MiB hash per engine.
The two runs execute concurrently on this 12-logical-processor desktop, with
mode selection inherited by both engines and recorded before the games.

| Mode | Games | Candidate W/D/L | Score | 95% pair interval |
| --- | ---: | --- | ---: | --- |
| Automatic | 64 | 6/50/8 | 48.44% | 43.75..53.13% |
| AVX2 | 64 | 13/46/5 | 56.25% | 50.00..61.72% |

Both pass the predeclared engineering regression screen: neither upper score
bound is below 50%. These small samples and pair intervals, which do not model
opening-family correlations, establish no general playing-strength gain. There
is no direct reference-engine match, Elo estimate or superiority claim here.

The [decision](../artifacts/verification/aster-indexed-accumulators-decision-v1.json)
adopts the change after all timing and correctness gates pass. Search policy,
evaluation arithmetic and neural weights remain identical; the prior disagreement
experiment remains excluded from normal builds. No parameters changed after the
trial began, and no adaptive games were added. The analysis script and its hash
were registered while the games were still in progress.

Reports and PGNs: [automatic report](../artifacts/matches/aster-indexed-accumulators-auto-v1.json),
[automatic PGN](../artifacts/matches/aster-indexed-accumulators-auto-v1.pgn),
[AVX2 report](../artifacts/matches/aster-indexed-accumulators-avx2-v1.json),
[AVX2 PGN](../artifacts/matches/aster-indexed-accumulators-avx2-v1.pgn).
The [completion record](../artifacts/verification/aster-indexed-accumulators-completion-v1.json)
indexes the remaining verification and preservation evidence. Absolute/public Elo
remains uncalibrated. Further work should profile automatic AVX-512 mode and use
a separate frozen experiment for any changed search policy.
