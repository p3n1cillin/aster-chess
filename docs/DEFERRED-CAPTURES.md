# Deferred capture scoring experiment

The opt-in `ASTER_LAZY_ORDER` build identifies itself as
**Aster 0.7.5-lazy-order-dev**. It defers exchange scoring of other captures
when the transposition move is present in the generated move list. The cached
move remains first; other captures are scored only if the loop reaches its
second iteration. Main search and quiescence use the same policy.

Quiet history and killer scores are still captured before the first move is
searched. Descendant searches can update the shared history table, so scoring
quiet moves afterward would silently change ordering. Capture scores depend
only on the restored board. Generated order, equal-score ties, extensions,
reductions, pruning, cache/history rules and every move-restoration path stay
as before. This is an engineering optimization hypothesis, not new chess
knowledge or a claim of greater intelligence.

## Frozen inputs and gates

Candidate DLL SHA-256:
`5da4badd1232e51edf1622fa347a979a3df61fe6f24473874d3f474e0bddf07d`.
Source: `artifacts/research/lazy-order-source/manifest.json`.
The control is the exact locally rated ordinary 0.7.4 DLL, SHA-256
`52439f58cf10a4a5dad8d4d48bf9db59db0a3f14b3c1c6216f79182b4a646d9a`.

The [original plan](../artifacts/research/lazy-order-plan-v1.json) declares
behavior/tactical gates, a 5% warm timing threshold and two paired regressions.
A separate [pre-match amendment](../artifacts/research/lazy-order-plan-amendment-v1.json)
records one mistaken baseline assumption: both candidate and control solve
**25/32** quiet positions at 5,000 nodes, with identical moves, depths, nodes
and solved status. The original failed **32/32** absolute gate and its report
remain preserved. The correction precedes timing and all matches; it changes
no engine parameter, timing threshold, match budget or match score gate.

The fresh parent suite contains 208 teacher-balanced legal 20-ply positions,
seed 20261102, excluding three development datasets, five prior opening suites
and the prior 144-opening rating parent. Before Aster queries it is split into
64 pairs at 30 ms/move, 16 distinct pairs at 100 ms/move and 128 reserved
conditional rating pairs. Independent audits verify histories, deduplication,
nine exclusion sources and pinned teacher provenance. This is a regression
suite, not the final Stockfish-superiority test pool.

## Behavior and actual cost

The candidate passes **49 engine tests** and **1,614 independent rule/protocol
checks**. All **80 fresh openings** have identical complete depth-eight UCI
traces, including every reported node count, score, selective depth and PV.
They total **6,101,786 nodes** in both engines. Another **256 seeded cases**
retain game history, warm TT entries, FEN origins, rule-50 clocks, short node
limits and restricted root moves, again with identical warm/search traces.
PV legality is checked independently. Timing/nps fields are excluded from
these equality checks; they depend on wall-clock behavior. This is extensive
bounded coverage, not a universal proof of program equivalence.

Original tactics remain **32/32** at depth eight and 5,000 nodes. Quiet tactics
remain **32/32** at depth eight and **25/32** at 5,000 nodes. Endgame diagnostics
remain **13/16** at 5,000 nodes.

Instrumented depth-nine search retains all five best moves, scores, depths
and **604,209 nodes**. Exchange calls fall from **558,458** to **521,244**:
**37,214** avoided, or **6.66%**. These are work counters. Instrumented timing
includes measurement overhead and overlapping categories.

The actual warm timing test uses two persistent ordinary engine processes,
two warmup passes and six measured passes through the first 16 fresh openings
at depth ten, alternating process order. Every move, score, depth, node count
and PV agrees. Measured round speed ratios are approximately 1.0110, 1.0080,
1.0049, 1.0010, 1.0101 and 1.0053. The median ratio is **1.00664**, only
**0.66%** faster in this local microbenchmark. Extra scans and bookkeeping
consume most of the saved exchange cost; the declared **1.05** gate fails.
The optimization remains opt-in. No Elo gain follows from this timing result.

## Paired regression and preservation

The original fixed budget of 128 games at 30 ms/move and 32 games at
100 ms/move was completed by `scripts/run_lazy_order.py`. Both engines use
one thread, 64 MiB hash and Move Overhead 0, preserve full histories and
leave games unfinished at the cap unresolved. The same runner refuses to
overwrite an existing experiment. Final W/D/L and family-bootstrap intervals
are recorded in `artifacts/research/lazy-order-assessment-v1.json`; all **160
PGNs** are audited independently, with no forfeits or unresolved games.

| Control | Games | W | D | L | Score | 95% family interval |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 30 ms/move | 128 | 47 | 53 | 28 | 57.42% | 51.17%..64.02% |
| 100 ms/move | 32 | 7 | 16 | 9 | 46.88% | 34.38%..59.38% |

The primary resampling retains both colors within first-four-ply families:
58 families at 30 ms and 16 at 100 ms, with 20,000 samples and seed 20261103.
The short-control result favors the candidate in this suite; the longer
sample does not confirm it and also fails the declared point-score gate.
Do not pool controls to hide that difference or infer Elo from the results.
The failed timing gate
prevents ordinary-engine promotion and conditional rating, regardless of a
favorable small-sample match result.

The ordinary flag-inactive build passes the required build, **49 tests**,
**1,614 rule/protocol checks** and the **146,772-node** benchmark. Across all
80 fresh openings it retains the frozen reference's moves, scores and
**6,101,786 nodes**. Its exact source and runtime files are preserved in
`artifacts/research/lazy-order-default-source` and
`artifacts/publish/lazy-order-default-dotnet`. Production 0.6.0 stays intact.
The [experiment manifest](../artifacts/research/lazy-order-experiment-v1-manifest.json)
retains both plans, all sources/binaries, exact pipelines, fixtures, audits,
traces, timings, tactical failures, match reports/PGNs and rating status.

The reserved rating openings have not been queried by Aster. The last
established measurement remains the frozen ordinary 0.7.4 local estimate
**2300 (95% interval 2265..2335)** at 30 ms/move on the SF19 strength-setting
scale; public Elo remains unestablished. This experiment does not supersede
that binary's rating. See [rating policy](RATING.md).

Next investigate the larger profiled costs separately: check-evasion nodes
currently test for a legal move before generating/searching evasions, and
that duplication deserves a controlled experiment with terminal-mate and
maximum-ply safeguards. Keep the independent playing-strength and native
proof capability goals intact; a faster small benchmark alone cannot meet them.
