# Late quiet move pruning experiment

The 0.6.0 reference reduces late quiet continuations but still searches them at
least to quiescence. This candidate omits some late quiet moves at shallow
non-PV nodes. It is a separate search experiment with the classical evaluator;
neural models and move ordering are unchanged.

## Policy and invariants

Pruning is eligible only below the root, outside check and a PV window, with
non-pawn material, no prior occurrence of the position, and depth at most three.
The move must be quiet and must not give check. It must appear after legal move
number `4 + depth * depth`, giving thresholds of 5, 8 and 13. The current alpha
must be outside the mate-score region, an earlier searched move must have a
non-losing-mate score, and the resulting halfmove clock must be below 90.

Legality is established before pruning. The first legal move is always searched,
so a node with no legal moves still receives mate/stalemate handling and a node
with moves never returns an uninitialized score. A pruned move uses the common
`finally` undo path. Captures, promotions, checks, evasions, pawn-only endings,
repetition and draw-boundary nodes retain the existing search. Quiescence and
its terminal-rule handling are unchanged.

The candidate passes 39 C# tests, 2,614 independent rule/protocol checks, all
32 tactical fixtures at depth 8, and the same 32 at a 5,000-node budget. These
are correctness/regression gates, not proof that quiet tactics are preserved
in every position.

## Fixed-depth diagnostics

Across the 64-position v1 suite at depth 8, the candidate searches 2,414,432
nodes versus 5,155,458 for frozen 0.6.0, about 53.2% fewer. Elapsed time is
1.813 versus 2.619 seconds in that run. Only 44 moves and 11 scores agree:
this pruning changes the searched tree, so reduced work cannot be presented
as an equivalent-search optimization or a strength gain.
[Search comparison](../artifacts/benchmarks/late-quiet-pruning-vs-0.6.0-depth8.json).

The instrumented five-position depth-9 run searches 279,225 nodes and counts
236,877 pruned quiet moves. Timers and counters compile out of normal builds.
The counter measures policy use, not successful pruning decisions.
[Profile](../artifacts/benchmarks/late-quiet-pruning-profile-depth9.json).

## Playing-strength gate

Run color-swapped matches against frozen classical 0.6.0 with one thread,
equal Hash and equal move time. Preserve reports, PGNs, unresolved outcomes,
the candidate and matching source/build manifests. The match runner now accepts
explicit frozen source manifests, verifies their binary and source-file hashes,
and records the resulting provenance directly in native-engine match reports.

```powershell
.venv/Scripts/python.exe scripts/match.py --engine artifacts/publish/late-quiet-pruning-dev/Aster.exe --opponent artifacts/publish/baseline-0.6.0/Aster.exe --source-manifest artifacts/research/late-quiet-pruning-source/manifest.json --opponent-source-manifest artifacts/research/king-context-release-source/manifest.json --openings tests/fixtures/openings-v3.json --pairs 32 --movetime 0.03 --output artifacts/matches/late-quiet-pruning-vs-0.6.0-30ms
```

The thresholds above were chosen before the match. Regression openings are
development material; reserve separate suites and a predeclared statistical
test for an eventual Stockfish-superiority claim.

The 64-game, 30-ms/move match finished **18/26/20 W/D/L**, scoring **48.4%**
with an exploratory opening-cluster interval of **39.1%..57.8%**. All games
completed without forfeits or unresolved results and passed independent PGN
auditing. Both engines' median completed depth was 9. Reduced fixed-depth work
has not demonstrated a playing-strength benefit at this control.
[Match](../artifacts/matches/late-quiet-pruning-vs-0.6.0-30ms.json),
[PGN](../artifacts/matches/late-quiet-pruning-vs-0.6.0-30ms.pgn),
[analysis](../artifacts/matches/late-quiet-pruning-vs-0.6.0-30ms.analysis.json).

The initial 32-game, 100-ms/move match finished **14/10/8 W/D/L**, scoring
**59.4%**, with an exploratory interval of **46.9%..70.3%**. All games completed
and passed independent PGN auditing. This sample motivates a broader check;
it does not establish a strength improvement. A 3.1-second structural fixture
audit ran alongside the opening seconds of its first game; this is retained as
a measurement limitation. The broader run begins after independent work finishes.
[Longer match](../artifacts/matches/late-quiet-pruning-vs-0.6.0-100ms.json),
[PGN](../artifacts/matches/late-quiet-pruning-vs-0.6.0-100ms.pgn),
[analysis](../artifacts/matches/late-quiet-pruning-vs-0.6.0-100ms.analysis.json).

Frozen v4 provides 64 new, distinct 20-ply opening positions, seed 20261017.
Generation excludes both training datasets, the three prior regression suites
and all 256 training-opening positions, and verifies teacher balance within
80 cp at 20,000 nodes. Independent auditing verifies legal histories and no
exact overlap with exclusions. The unchanged candidate is tested at 100 ms/move
on the first 32 positions, with both colors, for 64 games. Opening families can
still overlap; this remains development regression material.
[Fresh opening audit](../artifacts/validation/openings-v4-holdout.json).

The fresh 64-game, 100-ms/move run finished **15/36/13 W/D/L**, scoring
**51.6%**, with an exploratory interval of **43.0%..59.4%**. All games completed
and passed independent PGN auditing. This broader sample does not confirm the
initial longer-control signal. The candidate is **rejected as a default**;
the working search policy and UCI identity are restored to 0.6.0. The frozen
candidate, source/build manifest, reports, analyses and PGNs remain available.
[Fresh match](../artifacts/matches/late-quiet-pruning-vs-0.6.0-fresh-100ms.json),
[PGN](../artifacts/matches/late-quiet-pruning-vs-0.6.0-fresh-100ms.pgn),
[analysis](../artifacts/matches/late-quiet-pruning-vs-0.6.0-fresh-100ms.analysis.json).

All **160 games** across three runs completed without forfeits or unresolved
outcomes. Neither fewer nodes nor the small positive longer-control scores
establish an Elo rating or Stockfish superiority. The production 0.6.0 package
retains its original binary hash. Only the optional profiling counter and
research tooling/fixtures remain from this experiment.
[Combined provenance](../artifacts/research/late-quiet-pruning-experiment-manifest.json)
binds the candidate/baseline source manifests, restored source, all match files
and both new fixtures. Restored search matches all 64 reference depth-8 moves,
scores and node counts, and passes 39 tests and 17,491 independent checks.

## Quiet-move regression coverage

The original 32-position tactical set contains 21 captures, five non-capture
checking moves and only six quiet non-checking moves. The generator now supports
an explicitly quiet subset, multiple training-data exclusions, prior-fixture
exclusions, a checked teacher binary hash and recorded budgets/options/source
fingerprints.

Frozen suite `tactics-quiet-v1.json` has **32** legal, unique, nonterminal
positions sampled from **99** generated games (128-game budget, seed 20261016).
The best move must be a non-capture, non-promotion, non-checking continuation
that remains first under 5,000- and 50,000-node MultiPV checks, with a verified
gap of at least 120 cp. Its positions are excluded from both training datasets
and the original tactical suite. An independent structural/exclusion audit
passes. Label stability at bounded teacher budgets is not proof of optimality.
[Suite](../tests/fixtures/tactics-quiet-v1.json),
[audit](../artifacts/validation/tactics-quiet-v1-audit.json).

Both the pruning candidate and frozen 0.6.0 solve **32/32 at depth 8**. At a
5,000-node limit they solve **26/32** and **25/32**, respectively. Node-limited
tactics are a search diagnostic, not an equal-time strength measurement.
[Candidate depth 8](../artifacts/tactics/late-quiet-pruning-quiet-depth8.json),
[baseline depth 8](../artifacts/tactics/baseline-0.6.0-quiet-depth8.json),
[candidate 5,000 nodes](../artifacts/tactics/late-quiet-pruning-quiet-nodes5000.json),
[baseline 5,000 nodes](../artifacts/tactics/baseline-0.6.0-quiet-nodes5000.json).

The new suite includes 15 positions already in check and two positions with
only pawns and a king for the moving side. Fifteen positions are outside check
with non-pawn material and away from the draw boundary. This mix exercises both
quiet evasions and ordinary quiet solutions; it does not isolate every internal
node where pruning is eligible.
