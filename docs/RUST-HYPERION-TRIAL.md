# Hyperion neural-knowledge trial — 19 October 2026

**Not promoted.** All 384 fixed games are complete and independently audited.
The candidate scores 31/32 on the original expected-move suite, below its
predeclared 32/32 gate. Neither playing-control interval establishes a gain.
The retained playable engine is Rust 0.9.2 with its v109 Sandhi network.
The [recorded decision](../artifacts/research/rust-hyperion-decision-v1.json)
applies every original gate without retuning or extending the sample.

## Scope and provenance

The [plan](../artifacts/research/rust-hyperion-plan-v1.json) was saved before
candidate changes or queries. It proposes only the CC0 v111 Hyperion trained
weights, from the [official release](https://github.com/cosmobobak/viridithas-networks/releases/tag/v111),
while retaining MIT-v20 runtime inference, feature indexes, neuron permutations,
search and parameters. No later AGPL engine implementation is imported.
Published upstream ratings are not Aster measurements.

A [read-only structural comparison](../artifacts/research/rust-hyperion-compatibility-v1.json)
against upstream reference `f1352d6fd2e4c53dc591588d20050ec6840ba8cc` confirms
identical feature mapping apart from the later license header, quantized tensor
order/dimensions after aliases, king buckets and inference constants. The changed
floating import-factorizer flag does not affect already quantized data. Existing
FT/L1 permutations are retained together; later permutation constants are not copied.

The trained asset SHA-256 is
`2a7d2ef636767d2cf56bbae12cec42e72845156fc2607bf92bdcfc9c98b03944`.
The standalone experimental binary SHA-256 is
`510ae5e88f0dc6d162602902df1d5778b49fcc8103a7296644b84915489801d7`.
[Its 118-file source snapshot](../artifacts/research/rust-hyperion-source-v1/manifest.json)
pins the network, compiler, options, dependencies, license source and helpers.
The frozen opponent is Rust 0.9.2, SHA-256
`b51e97647dd086ed0a30682fba77ea627dd5d8cf9bfc291e34a4064b04916213`.

## Verification and puzzle tradeoffs

All **135** native release tests and **135** debug tests pass, including three
new scalar/incremental/undo guards first checked with the old network. The
independent checks pass **4630** positions, **14** perft cases and **94** special
pin/promotion/terminal cases. Actual HTTP/SSE, live branch/PV replay, observer
on/off behavior, ready/stop and all **27** certificates (**122** independently
verified positions) pass. The product remains a standalone Rust executable.

The [latest experimental CI](../artifacts/ci/rust-hyperion-freeze-39182133145.json)
passes all 135 release and 135 debug native tests on both Windows and Linux.
Both platforms reproduce the 31/32 expected-move miss, failing that gate;
matrix fail-fast marks the Windows job cancelled. Earlier failed runs are also
retained. This is a tactical-gate rejection, not an unsafe correctness failure.
The [retained-engine CI](../artifacts/ci/rust-trial-auditor-39181461967.json)
at `91c42f5` passes both full Windows/Linux jobs, including 135 tests in each
profile, all five recovery tests and 32/32 original tactics with v109 weights.
These results apply to the named commits and frozen binaries.

Expected-move results at the fixed limits are **31/32** original (baseline 32),
**29/32** quiet (baseline 28), and **16/16** endgames (baseline 16). This is a
mixed tradeoff, not evidence that every choice or all playing strength regressed.
The [independent diagnostic](../artifacts/validation/rust-hyperion-tactical-regressions-v1.json)
records bounded Stockfish 19 analyses at 200,000 nodes per forced root move:

- Original tactic 023: the candidate chooses Nd5 instead of Nc2. The reference
  reports mate against White after Nd5; Nc2 is also evaluated as losing, but
  avoids that reported short mate in the recorded search.
- Quiet tactic 024: the candidate chooses b4 instead of Qd7. The reference
  reports a winning score after b4 and mate after Qd7. This misses the suite's
  expected mating route; the bounded result is not an independent certificate.

All newly missed expected moves are retained without tuning the model or labels.
The single initial test compilation failure swapped two test-helper arguments;
it was corrected before model evaluation, and both failed/passing logs remain.
The fetch helper verifies the current pin and preserves the recognized v109
weights in a local cache before a verified model replacement. Unknown existing
weights are refused, and production keeps its original pin.

## Fixed paired matches

The 192 fresh opening parents exclude all 54 earlier suites. The first 128
parents produce 256 color-swapped games at 30 ms/move; the remaining 64 produce
128 games at 100 ms/move. Both sides use one thread and 64 MiB hash. Reports
retain source/binary fingerprints, full histories, actual times, options and PGNs.
Rules alone adjudicate games, with a 400-additional-ply cap and no books,
tablebases, resignations or evaluation adjudications. The local desktop is not
isolated and uses no CPU affinity. First-four-ply family bootstrap settings are
20,000 samples and seed 20261019. No absolute/public Elo or Stockfish-superiority
claim is inferred. Results below close the original fixed sample.

| Control | Games | Wins | Draws | Losses | Score | 95% family score interval | Families |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| 30ms | 256 | 42 | 179 | 35 | 51.37% | 48.16%..54.60% | 90 |
| 100ms | 128 | 18 | 92 | 18 | 50.00% | 45.56%..54.30% | 57 |

Both controls pass their predeclared numerical engineering screens, with zero
forfeits and zero unresolved games. Both intervals include 50%; no strength
increase is established. The hard tactical gate and full candidate CI gate fail,
so the model is rejected regardless of the match scores. This does not establish
that Hyperion is globally weaker; its expected-move results show a mixed tradeoff.
No blending, scaling, search retuning, relabelling or alternate-model shopping
was performed. All 192 opening parents are now used research data and must be
excluded from fresh confirmation samples.

The complete [short report](../artifacts/matches/rust-hyperion-v1-30ms-complete.json)
and [long report](../artifacts/matches/rust-hyperion-v1-100ms.json) have adjacent
PGNs and full JSONL game journals. Independent rule audits pass all 256 and 128
games. Journal audits verify exact game order, pair/color assignments, openings,
configurations, full PGN headers/moves, JSON details and result counters:
[short audit](../artifacts/validation/rust-hyperion-journal-30ms-v1.json),
[long audit](../artifacts/validation/rust-hyperion-journal-100ms-v1.json).
The adjacent family analyses retain their seed, resampling settings and hashes.

## Storage interruption and exact recovery

The legacy writer raised `OSError` errno 22 while opening its JSON report after
flushing game 83's PGN. The cause is unknown; the engines exited cleanly. The
original JSON retains 82 complete telemetry records and its PGN retains 83
complete games. Both files remain byte-for-byte unchanged and are recovery
evidence, not an additional playing sample.

The [addendum](../artifacts/research/rust-hyperion-recovery-addendum-v1.json) was
saved before resumed engine queries. Recovery keeps every original outcome and
starts at game 84, pair 42 with the candidate Black, using the same binaries,
options, opening suite and limits. Exactly one game, ordinal 83, lacks per-move
telemetry and game wall time; its full moves and outcome are retained. Missing
values are explicitly unavailable. Known aggregate elapsed excludes unavailable
time and downtime; it is not a complete match-duration benchmark. Restarting
both processes and using an unisolated desktop are additional practical limits.

The new development writer journals full completed-game details and PGN with
flush/fsync before replacing complete snapshots atomically with bounded retries.
The [seven-file runner overlay](../artifacts/research/rust-hyperion-recovery-source-v1/manifest.json)
identifies this tooling change; the original 118-file engine capsule stays
immutable. Five storage-fault tests cover the recovery boundaries and are in
Windows/Linux CI. [Recovery documentation](MATCH-RECOVERY.md) records the limits;
truncated journal records stop for investigation rather than silently dropping a game.

The [reproducible recorder](../artifacts/research/rust-hyperion-record-v1.py)
checks the exact first 82 telemetry records and all 83 original PGN records,
then applies the saved plan to both complete audited samples. The
[provenance audit](../artifacts/validation/rust-hyperion-provenance-v1.json)
verifies all 117 baseline source files, 118 candidate files, seven overlay files,
both binaries, the original interrupted files and the plan fingerprint.

## Retained engine and rating

The test-only scalar/incremental/undo guards and durable match tooling are
retained with the existing engine. Playing search, inference and the v109 model
remain at Rust 0.9.2. The existing play server and saved user game are preserved.
The neural trial is complete; its candidate is not deployed or merged into the
active engine. The research branch and all evidence remain available.

**Rust is still unrated.** The historical C# local SF19-setting equivalent is
2319 (95% interval 2277..2360), attached only to its exact old binary and scale.
It is not transferred to Rust or to the upstream network's reported strength.
See [this session's rating record](../artifacts/ratings/session-20261019-hyperion.json).
Full-strength Stockfish superiority remains unachieved.
