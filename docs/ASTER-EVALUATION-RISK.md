# Online evaluation-risk experiment

This experiment learns a small, per-worker history of observed static-evaluation
overestimation, then uses it to defer marginal reverse-futility cutoffs. It is
separate from the earlier disagreement guard, which remains disabled. Normal
builds exclude the new model, option, counters and search changes.

The [plan](../artifacts/research/aster-evaluation-risk-plan-v1.json) was committed
and pushed as `e0233c52` before implementation and candidate queries. It fixes
the policy, 128 fresh roots, all resources and gates. The roots exclude 63 prior
opening suites; teacher sampling does not establish neural-training independence.
The control is the adopted Rust core at `2f84d460`, binary
`9361d9c3b066514451bf09a1767c534d8197f5909f06151433f531768cc81100`.

## Fixed policy

The history has 48 contexts: side to move, queen presence, material band and
depth band. Labels come only from completed, non-root, non-check, non-excluded
PV searches with a quiet normal best move and a finite score strictly inside
the original window (and below the final beta). The depth is saved after prior
reduction adjustments; labels use depths two through ten. These remain selective
search results, not ground-truth game values or unbiased samples.

The model tracks squared positive error `max(corrected_static - searched, 0)`,
clipped at twice the pawn value. The integer mean warms up over 32 observations,
then updates at 1/32. At least 16 observations are required before use. The
margin is half the integer square root, capped at one quarter of a pawn.

At depths three through eight, outside mate seeking, only an ordinary reverse-
futility cutoff using corrected static evaluation can be deferred. Its excess
over the original cutoff must be below that margin. Each worker may defer at
most 64 cutoffs per search across iterative deepening. Existing null-move and
other pruning still run afterward: a deferral is not a safety certificate.
History persists within a game and clears with game/hash resets; per-search
telemetry resets independently. No global shared model or external inference runs.

Uncertainty and evaluation-error search control have substantial prior art; see
[Search Control Methods in Deep Blue](https://aaai.org/papers/0004-ss99-07-004-search-control-methods-in-deep-blue/).
This particular conjunction is an Aster hypothesis, with no global novelty claim.
The learned statistic is a heuristic risk proxy, not a calibrated probability.

Build with `cargo build --workspace --release --locked --features aster-engine/evaluation-risk`.
Research builds expose `Aster Evaluation Risk`, initially true. Disabled mode
must preserve the canonical signature and deterministic searches exactly.

## Qualification and fixed trial

The isolated 128-position equal-20,000-node screen observes 3,341 training labels
and only **one** deferred cutoff, with median throughput ratio 1.0047. This sparse
activity limits confidence in usefulness; no thresholds are changed to fit it.
All moves and PVs replay legally. Disabled mode matches all 128 depth-nine roots
and all 51 canonical bench searches, at 1,559,611 nodes.

Tactics match control at 32/32, 31/32 and 16/16. Independent checks pass 2,630
rule positions, 14 perft cases, 94 terminal edges, real HTTP/SSE play and eight
mate certificates over 42 positions. Six lifecycle cases check enabled/disabled
readiness, stop and root restoration with one, two and four threads; three
deterministic searches confirm game and Clear Hash resets.

The trial completes all 256 games even if screening fails: 64 color-swapped
pairs at 30 ms/move and 64 at 100 ms, with one thread and 64 MiB per engine.
Promotion eligibility requires both strict 95% whole-opening-family score lower
bounds above 50%, unchanged tactical solved counts, valid cost and correctness
gates, zero forfeits and zero unresolved games. Families use full starting FEN
and the first four opening plies; bootstrap is fixed at 20,000 samples, seed
20261019. Eligibility would still require a separately declared reference trial.
There is no adaptive retuning, extra games, Elo estimate or superiority claim.

## Completed decision: keep disabled

All 256 games are complete and independently audited, with no forfeits,
unresolved games or missing telemetry. Results are against the frozen Aster
control, not a reference-engine confirmation.

| Control | W/D/L | Score | 95% whole-family interval |
| --- | --- | ---: | --- |
| 30 ms | 16/101/11 | 51.95% | 48.41..55.38% |
| 100 ms | 3/120/5 | 49.22% | 47.27..51.12% |

Both strength gates fail. Neither a gain nor a definite regression is established.
The [decision](../artifacts/verification/aster-evaluation-risk-decision-v1.json)
retains `eligible_for_confirmation=false` and `production_enabled=false`.
No thresholds changed, no extra games were added and no reference trial was
triggered. Sparse isolated-root activity remains a limitation of this hypothesis;
these consumed roots cannot be reused as fresh confirmation for a retuned policy.

All four workspace configurations pass 157 native tests plus two compile-fail
lifetime checks. Windows and Linux
[CI pass](https://github.com/p3n1cillin/aster-chess/actions/runs/39262037781), including
combined research-feature tests. Normal builds preserve all 128 fresh depth-nine
comparisons and all 51 bench traces at 1,559,611 nodes. Eight timing pairs give
normal-build elapsed ratio 1.00424; this is diagnostic, not a claimed speed gain.
The exact binaries, source snapshots, complete PGNs, journals and reports are
preserved. The [completion record](../artifacts/verification/aster-evaluation-risk-completion-v1.json)
indexes the verification. Absolute/public Elo and reference superiority remain
unestablished. The research continuation stays active for distinct hypotheses.
