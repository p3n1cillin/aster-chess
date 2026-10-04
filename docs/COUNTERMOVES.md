# Rejected countermove ordering experiment

Record a quiet move that causes a main-search beta cutoff as a possible reply
to the previous move. The table is indexed by the previous moving piece's
color/type and destination square (12 × 64 entries). Promotions use the piece
that moved, before promotion. This small table is reset at the start of each
search, alongside the killers.

At a later node with the same previous-move context, the recorded reply receives
priority below both killers and winning captures, above ordinary history moves
and losing captures. The transposition move remains first. The table changes
ordering only: captures, reductions, extensions, pruning and depth retries
retain their existing policies.

The search records previous-move context at each ply in both main search and
quiescence. Null moves mark their context absent; a child cannot learn or use a
reply to a fictitious null move. Root context is absent. Context arrays are
private search metadata, never position state, and do not change repetition or
rule-50 history. Every successful speculative board move is still undone.

The frozen candidate is `artifacts/publish/countermove-dev/Aster.exe`, SHA-256
`1dc6ddfc2052d0aa58e8c2fff5a123392a08990c9a15cff94929d23eb61f142d`.
Source: `artifacts/research/countermove-source`. Baseline: frozen 0.5.1,
SHA-256 `6f6d781e7e8294757949a90cbc3a113c18f39ba6cfb88e6a30b89f91eb892313`.

The candidate passes all 37 existing tests and 32/32 depth-8 tactics. The native
package passes 2,614 independent legal/FEN/predicate checks, 14 perft fixtures,
and UCI/PV checks. Across 64 depth-8 opening comparisons it searches 4,880,064
rather than 5,155,458 nodes (5.3% fewer), retaining 60 best moves and 45 scores.
Neither fixed-depth work nor the tactical gate proves improved playing strength.
Reports: `artifacts/validation/countermove.json`,
`artifacts/tactics/countermove-depth8.json`, and
`artifacts/benchmarks/countermove-vs-0.5.1-depth8.json`.

Paired matches use frozen `tests/fixtures/openings-v3.json`, with its audited
training/prior-suite exclusions, distinct legal histories and pinned teacher.
This suite is shared with the history-reduction experiment. Multiple comparisons
on the same regression suite limit generalization; final superiority claims
require separate held-out tests. Results and the default-selection decision
are recorded in `artifacts/PROGRESS.md`.

The first 64-game match at 30 ms/move scored **19/30/15 W/D/L**, or **53.1%**,
with an exploratory opening-cluster interval of **43.8%..62.5%**. It is
inconclusive for a strength gain. Every game finished without forfeits or
unresolved outcomes and passed the independent audit. Both the candidate and
baseline also solved all 32 tactical positions at 5,000 nodes.
Report: `artifacts/matches/countermove-vs-0.5.1-fresh-30ms.json`.

The 100-ms/move comparison finished **8/13/11 W/D/L** over 32 games, a **45.3%**
score with an exploratory interval of **29.7%..60.9%**. All games completed and
passed audits. Neither control demonstrates a benefit, so countermove ordering
was removed from the default; Aster 0.5.1 retains its prior ordering. The lower
fixed-depth node count is insufficient to retain this heuristic by itself.
The frozen experiment and all 96 games remain available for further research.
Report: `artifacts/matches/countermove-vs-0.5.1-fresh-100ms.json`.
