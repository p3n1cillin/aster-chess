# Midpoint row-prefetch trial: rejected

One default-off Rust policy adds a T1 hint at byte 512 of each existing changed
threat/pawn-pair row hint, only on the automatic AVX-512 path. It changes no
weights, indices, arithmetic or search. The earlier profile motivated looking
at update data movement; it did not establish a cache-stall cause.

The experiment is rejected. Automatic elapsed fails the predeclared speed gate.
An independent audit also catches an error in the committed ordering plan:
per-batch balance holds, but the claimed per-root first-slot balance does not.
All observations and the first failed audit are preserved. There is no corrected
rerun, distance/hint variant, adoption or strength claim.

## Prospective controls and correctness

Plan `a01a3aa5` precedes generation and implementation. Commit `a34e1dc7`
freezes 80 fresh legal-history roots and the unchanged control source before
implementation: 16 timing roots, 32 disjoint 30 ms match roots and 32 disjoint
100 ms match roots. There is zero final-root overlap with 74 prior suites.
The exact candidate and source are frozen at `aca2aca1`; its SHA-256 is
`044f80be39d8f7fdc6e048414d790e5351277dce881fa03e8252959a83ddb4ae`.
Production remains `6b4d46db…`. Both use Rust 1.99.1, the pinned network and
x86-64-v3 release settings, without PGO or profiling instrumentation.

All pre-timing correctness gates pass:

- Feature/default debug and release each pass 157 native tests plus two
  compile-fail checks; formatting and source-name audits pass.
- All 51 normalized canonical searches agree in all three SIMD modes, retaining
  1,559,611 nodes. Every one of 80 fresh depth-nine roots agrees per mode.
- Three fixed 20,000-node tactical suites retain identical moves and work in
  every mode. Independent rules verify 2,630 positions and 14 perft cases;
  special-rule edges, actual HTTP/SSE play and eight proof certificates pass.
- One-, two- and four-thread ready/stop/root-undo checks pass. The standalone
  runtime remains Rust, with no external playing engine behind it.
- Windows and Linux CI pass on the candidate revision, including feature builds,
  tests and automatic/AVX2/scalar signatures.

## Timing and ordering failure

All 28 fixed batches finish once: 12 automatic, eight AVX2, eight scalar. Each
batch has 16 matched roots, one search thread and 64 MiB hash per engine.
There are 448 root pairs (896 timed searches), plus six declared warmups.
Behavior stays identical. The ratios below are descriptive, because the
ordering protocol is ineligible for adoption.

| Mode | Median candidate/control elapsed | 95% batch bootstrap interval | Numeric gate |
| --- | ---: | ---: | --- |
| Automatic | 1.00779 | 1.00093–1.02533 | Fail |
| AVX2 | 1.00549 | 0.99317–1.02956 | Within tolerance |
| Scalar | 0.99227 | 0.97704–1.01232 | Within tolerance |

Automatic needed a median at most 0.99 and upper bound at most 1.00. Other modes
needed median at most 1.01 and upper bound at most 1.03. No threshold changes.

The explicit schedule reverses root traversal on odd batches and selects roles
using `(batch + traversal_ordinal) % 2`. These two parity changes cancel for
each root: it always receives the same role first. Each batch still has eight
AB and eight BA pairs. The runner followed the exact committed array, but the
plan incorrectly claimed each root received equal first/second slots. This is
a plan construction error, distinct from the earlier fusion implementation's
ordering deviation. Neither record is overwritten or corrected after results.

The first independent audit fails its per-root balance assertion. Its source
and failure output remain unchanged. A separate supplemental reporter verifies
the raw order, monotonic query intervals, hash chains, elapsed totals and
bootstrap calculations, explicitly retaining `protocol_conformant=false`.
It does not turn the failed audit into a passing experiment. Future timing
plans must pass combinatorial balance checks on their explicit schedule before
any engine query, including interactions with reversed root traversal.

## Decision and preserved evidence

The prospectively conditional 64 pairs (128 games) are unused because timing
fails. No journals or PGNs were started. Original engine, Cargo and workflow
files are restored byte for byte to `082180f2`; the playable binary is unchanged.
The exact candidate executable is preserved in the SHA-addressed local research
binary store. Full source snapshots, candidate workflow, build log, all traces,
test logs, timing observations, initial audit failure and supplemental decision
are retained in the repository and Git history.

Key records:

- `artifacts/research/aster-midpoint-prefetch-plan-v1.json`
- `artifacts/research/aster-midpoint-prefetch-build-v1.json`
- `artifacts/research/aster-midpoint-prefetch-{control-source,source}-v1/`
- `artifacts/verification/aster-midpoint-prefetch-correctness-v1.json`
- `artifacts/verification/aster-midpoint-prefetch-timing-v1.json`
- `artifacts/verification/aster-midpoint-prefetch-first-audit-failure-v1.log`
- `artifacts/verification/aster-midpoint-prefetch-decision-v1.json`
- `artifacts/verification/aster-midpoint-prefetch-restoration-v1.json`
- `artifacts/verification/aster-midpoint-prefetch-ci-v1.json`
- `artifacts/verification/aster-midpoint-prefetch-completion-v1.json`

Do not retune this prefetch policy from these results. Next investigate whether
accumulator row lists contain removable redundant work, using a separately
predeclared bounded counting diagnostic before proposing any candidate. This
has no measured benefit yet. Fresh roots and separate gates remain required for
any later candidate. Public/absolute Elo, novelty and superiority remain
unestablished; the overarching research goal continues.
