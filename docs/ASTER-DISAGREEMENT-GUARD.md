# Aster disagreement-guard experiment

This experiment asks whether a small, evidence-triggered verification budget can
improve selective search. It starts from the unmodified development core at commit
`6cffbf26`, with the pinned `effdc3fd3f` foundation and `nn-c9e480e92425` network.
The neural weights, evaluation formula, move generation and existing heuristics
are fixed. No superiority or world-first claim follows from implementing it.

Selective search extensions have substantial prior art, including
[Search Control Methods in Deep Blue](https://aaai.org/papers/0004-ss99-07-004-search-control-methods-in-deep-blue/)
and [singular extensions](https://doi.org/10.1016/0004-3702(90)90073-9).
The Aster hypothesis here is a specific conjunction of cached-bound disagreement,
same-side evaluation volatility and a capped quiet-move verification budget.
This limited literature check does not establish global novelty.

## Frozen policy

At a non-root, non-check PV/cached-PV node at depth 5 through 10, require a cached
score from at least depth minus three, with all compared scores finite. Its gap
from corrected neural evaluation must be at least half the internal pawn value.
The bound must support that direction of disagreement. The current evaluation
must also differ from the same side's evaluation two plies earlier by at least
one third of the internal pawn value. Excluded-move and mate-seeking searches are
not eligible.

For surviving quiet, nonchecking moves numbered 3 through 8, restore one ply of
an existing late-move reduction, capped at full child depth. Each worker can do
this at most 256 times per search, across all iterative-deepening iterations.
It does not bypass the existing move-pruning rules. The evidence and the added
search are heuristic; they are not proofs that a move is safe or correct.

The experiment is compiled only with Cargo feature `aster-engine/disagreement-guard`.
Normal builds exclude the policy, option, budget fields and telemetry. Research
builds expose `Aster Disagreement Guard`, initially true; setting it false restores
the baseline search. Its per-search `info string` reports activity and the cap.

```
cargo build --workspace --release --locked --features aster-engine/disagreement-guard
```

## Test design

The [plan](../artifacts/research/aster-disagreement-plan-v1.json) fixes the policy,
budgets, controls and gates before candidate queries. A pinned development teacher
generated 96 new balanced roots, excluding previously frozen opening roots.
Their historical presence in an external neural network's training data is unknown.
The first 64 pairs use 30 ms per move; the remaining 32 use 100 ms. All 192 games
must finish and be independently audited even if screening gates fail. Each engine
has one thread and 64 MiB hash. The two control-specific runs execute concurrently
without local compilation; the execution record states that shared-machine scope.

Qualification checks include native/default/feature tests, independent rules/perft,
terminal edges, HTTP/SSE play, mate proofs, legal PV replay, enabled/disabled SMP
readiness/stop/undo, activity caps and equal-node cost. Tactical scores must not
fall below control at the same 20,000-node budget. Candidate eligibility also
requires both control-specific 95% opening-family bootstrap lower score bounds
strictly above 50%. Families retain the starting FEN and first four opening plies.
No tuning or additional games based on these results is allowed.

Passing would qualify the idea for separately declared reference confirmation;
it would not establish superiority over the reference engine. Failing keeps the
normal build unchanged and retains the experimental code, outcomes and PGNs.

## Checks recorded before matches

The guard activates 331 times across the 96 roots, with valid moves/PVs and no
budget violation. Equal-node median throughput is 0.9920 of control in the local
screen. Tactical scores match control at 32/32, 31/32 and 16/16. Both workspace
test profiles pass in default and feature modes. Enabled/disabled lifecycle and
independent rules, edge, HTTP/SSE and certificate checks pass. The initial lifecycle
verifier expected an obsolete FEN-output prefix; its failure and verifier-only
correction are retained.

With the option disabled, all 51 bench searches exactly match control and report
1,559,611 nodes. Normal builds also preserve all 96 fixed-depth comparisons. An
eight-pair local default-build timing check has median elapsed ratio 0.99899;
that small difference is not treated as a speed gain.

CI's default tactical reference had still pointed to the older release-core report.
It now uses a separately frozen report from the unmodified development core:
31/32 at depth eight. The older 30/32 release-core report is preserved. This
rebinds the equivalence check to the current foundation; it does not relax a
candidate promotion gate. The separate legacy 32/32 gate remains.

## Completed result: retain as experimental

All 96 color-swapped pairs completed, with no forfeits or unresolved games.
Independent PGN replay and journal/report comparison pass for both controls,
including complete search telemetry. Results are against the frozen Aster control,
not a direct Stockfish match.

| Control | Games | Candidate W/D/L | Score | 95% family interval |
| --- | ---: | --- | ---: | --- |
| 30 ms/move | 128 | 14/96/18 | 48.44% | 44.92..51.98% |
| 100 ms/move | 64 | 2/57/5 | 47.66% | 44.17..50.78% |

Both strength gates fail. The intervals include 50%, so neither improvement nor
a definite regression is established by this sample. No parameters were retuned,
no extra games were added, and no reference confirmation was triggered. The
[decision](../artifacts/verification/aster-disagreement-decision-v1.json) keeps
`eligible_for_confirmation` and `production_enabled` false. The feature remains
available for research and is compiled out of normal builds.

Both profiles pass 151 native tests plus two compile-fail lifetime checks in
default and feature configurations. Windows and Linux
[CI pass at the tested code commit](https://github.com/p3n1cillin/aster-chess/actions/runs/39256241550).
The independent enabled checks cover 2,630 positions, 14 perft cases, 94 edge
cases, real HTTP/SSE play and eight mate certificates over 42 positions. The
legacy depth-seven bench also passes. All four source snapshots pass their hash
audit; the final feature/default snapshots match current build and tool sources.
Exact tested binaries are preserved outside the disposable worktree by SHA-256.

The practical result is a reproducible negative experiment and improved research
infrastructure. No new Elo, significant advantage over Stockfish or global
novelty is established. These roots are now consumed evidence: any distinct
future hypothesis needs a new frozen policy and fresh test roots. Raising the
budget or changing thresholds to fit this result is not a valid confirmation.

The reports and PGNs are
[`30ms`](../artifacts/matches/aster-disagreement-30ms-v1.json),
[`30ms PGN`](../artifacts/matches/aster-disagreement-30ms-v1.pgn),
[`100ms`](../artifacts/matches/aster-disagreement-100ms-v1.json) and
[`100ms PGN`](../artifacts/matches/aster-disagreement-100ms-v1.pgn).
The [completion record](../artifacts/verification/aster-disagreement-completion-v1.json)
indexes the checks and their fingerprints. Absolute/public Elo remains uncalibrated.
