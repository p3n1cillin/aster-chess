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
