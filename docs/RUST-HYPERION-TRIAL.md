# Hyperion neural-knowledge trial â€” 19 October 2026

**Not promoted.** The frozen Hyperion candidate passes correctness checks but
scores 31/32 on the original expected-move suite, below its predeclared 32/32
gate. The production engine keeps Rust 0.9.2 and its v109 Sandhi network.
The separately fixed 384-game sample is completed and audited before closing
this research record; its outcome does not waive the failed gate.

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

The [candidate CI record](../artifacts/ci/rust-hyperion-39179523535.json)
reproduces 31/32 on Linux after its correctness checks pass. That expected-move
gate fails; matrix fail-fast cancels the Windows job. The complete failed run
is preserved rather than weakening the threshold. Local Windows release/debug
suites above pass all 135 correctness tests. Production validation has a
separate CI run against its unchanged v109 network.

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
claim is inferred. Complete results and the recorded decision follow the fixed run.
