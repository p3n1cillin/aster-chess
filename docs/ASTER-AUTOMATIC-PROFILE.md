# Unchanged automatic-path diagnostic

The fixed diagnostic is complete. The automatic AVX-512 indexed accumulator
update is the largest observed source function: 25.33% of all sampled PCs in
the canonical workload and 29.43% in foundation16. This nominates accumulator
update data movement and instruction scheduling for a separate investigation.
It establishes neither a faster implementation nor a playing-strength gain.
No playing source, release default or neural weights changed.

## Plan and audit

Plans v1 and v2 were committed before builds or collection. V2 clarified the
existing sampler's outside-module export and the bench-time overhead metric;
it changed no workload, schedule, resources or threshold. The 32 runs completed
on 2026-10-19; their analysis and preservation completed on 2026-10-20. No runs
were repeated. Each of four roles occupied each schedule position once per
workload, exactly matching the explicit committed rotation.

The workloads were the 51-position canonical depth-13 bench and the first 16
existing foundation roots at depth 14. Both used one search thread, automatic
SIMD and matched hash settings within each workload. These are diagnostic
positions, not fresh strength-validation roots. Every normalized search trace
and best move agrees with production. Canonical runs retain 1,559,611 nodes.
All 59 pinned playing inputs and production SHA-256 `6b4d46db…` are unchanged.

The three diagnostic builds use the same Rust 1.99.1, x86-64-v3 release settings,
full debugging information and matching PDBs/maps. The control is a standalone
core; production is the existing full Aster binary invoking its native core.
The `prof` and `sampler` features are development diagnostics only. The exact
compiler commands, environment and binary identities are in the collection.

## Observations

Shares below use the full sample population, including outside-module samples.
Attribution selects the first valid engine source frame from LLVM's inline
frames. It is an exclusive source attribution, not an inferred call stack.

| Observation | Canonical | Foundation16 |
| --- | ---: | ---: |
| Full sample population, four repetitions | 88,695 | 59,305 |
| Executable code samples | 87,414 | 58,594 |
| Outside-module samples | 1,281 | 711 |
| Resolved executable samples | 100% | 100% |
| `avx512::update_acc_idx` sample share | 25.33% | 29.43% |
| `avx512::sparse_affine_fc0_list` sample share | 8.63% | 7.46% |
| `Worker::search<0>` exclusive sample share | 6.42% | 5.41% |
| Median counters/control bench ratio | 1.0461 | 1.0313 |
| Median sampler/control bench ratio | 1.4060 | 1.4583 |

All eight sampled runs exceed the predeclared 100 executable samples and 80%
resolution requirements. No captured executable-region PC falls outside the
PE code section. All 8,293 distinct RVAs have preserved symbolizer output.
Per-run counts, unknown/non-engine bins, function/line ranks and repetition
ranges remain in the analysis. The profile's largest source-line bins are the
indexed signed-byte loads/widening and additions around `kernels.rs:477–478`.
Debug line mapping is approximate instruction attribution; it cannot identify
cache misses or prove a hardware cause.

Inclusive counters corroborate substantial accumulator work: `acc_update`
accounts for a median 66.47% and 70.83% of `total_eval` ticks respectively.
These are overlapping, unserialized TSC observations, not disjoint runtime
percentages. In particular, the existing `acc_kernel` counter excludes indexed
updates; its small value cannot establish a small total accumulator cost.
The analysis preserves every counter's ticks and calls without summing them
as disjoint costs.

The sampler perturbs elapsed bench time by about 41–46% versus the diagnostic
control. This passes the declared 2x upper bound but still limits transfer to
ordinary execution. The counter overhead is about 3–5%. All per-repetition
bench and wall ratios are published, including ratios to production. Wall
time includes startup/export. None of these ratios is an optimization result.
Samples are temporally dependent; no sample-level confidence intervals are
reported. Outside PCs are available only as emitted module totals. Heuristic
caller RVAs are archived but excluded from primary attribution.

## Decision and next research

No candidate is adopted. The next step is bounded offline inspection of the
preserved indexed-update machine code and source, to formulate one distinct
policy affecting accumulator update scheduling or data movement. This is
separate from the rejected transform/nonzero-input fusion experiment. No
cache-miss, spill or bottleneck cause is yet established, and no tile size or
instruction variant has been selected or queried.

A candidate needs its own committed policy, fresh roots, explicit balanced
timing order, matched resources, correctness/exactness requirements, timing
and paired-game gates, and bounded stopping rules before implementation or
candidate queries. Failed disagreement, evaluation-risk, PGO and fusion trials
stay closed. Public/absolute Elo and superiority remain unestablished.

## Evidence

- Plans: `artifacts/research/aster-automatic-profile-plan-v{1,2}.json`.
- Collection: `artifacts/verification/aster-automatic-profile-collection-v1.json`.
- Analysis: `artifacts/verification/aster-automatic-profile-analysis-v1.json`.
- Raw traces/counters/PCs: `artifacts/research/aster-automatic-profile-runs-v1/`.
- Raw symbols and attribution: `artifacts/research/aster-automatic-profile-symbolization-v1/`.
- Unchanged source snapshot: `artifacts/research/aster-automatic-profile-source-v1/`.
- EXE/PDB/map preservation receipt: `artifacts/verification/aster-automatic-profile-preservation-v1.json`.
- Completion: `artifacts/verification/aster-automatic-profile-completion-v1.json`.

Exact executables, matching PDBs, maps and build logs are preserved in the local
SHA-addressed research binary store, with paths, sizes and hashes in the receipt.
The repository preserves all raw emitted profiles and source snapshots. LLVM
tools and diagnostic features are not standalone Aster runtime dependencies.

## Follow-up: bounded machine-code inspection

A separate plan was committed before one offline disassembly on 2026-10-20.
The unchanged debug-control indexed-update function contains 258 static
instructions, including 64 signed-byte widening loads across four row loops.
Sixteen accumulator vectors stay in registers; no direct stack-relative vector
spill/load appears. The local stack traffic holds scalar list/loop metadata.
Weight-row loads addressed through `rbp` are not stack spills. Outer control
visits two 512-lane tiles for the 1,024-lane accumulator.

This rules out a vector-spill explanation for this exact compiled function; it
does not measure cache stalls or prove an instruction-throughput limit. No
candidate variant has been selected, compiled or queried. Next commit one
separate update-policy hypothesis and fresh roots before its implementation.
The disassembly, empty stderr, pinned tool/input identities and bounded result
are preserved in `artifacts/research/aster-indexed-update-inspection-v1/` and
`artifacts/verification/aster-indexed-update-inspection-v1.json`. The original
profile completion and its completion-time documentation stay frozen.
