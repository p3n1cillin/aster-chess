# Fresh endgame targets and regression checks

Generate fresh played games with the pinned development teacher at 512 nodes
per move and a seeded 3% random legal-move rate. Sample up to four positions
per source game after ply 40, every fourth ply, with at most twelve pieces,
phase at most eight, no check or terminal/claimable draw and a rule-50 clock
below 90. Exclude exact canonical positions from both prior development datasets,
all five opening suites and both earlier tactical suites. Do not choose samples
based on any Aster evaluator's errors or moves.

The resulting **512 positions** come from **140 of 187 source games**. Their
PGNs, exact played histories and source results are preserved. Seven games hit
the 240-ply cap and remain unresolved; they are not counted as draws. The other
source results are 94 White wins, 67 Black wins and 19 draws. These outcomes
reflect the recorded exploratory play policy, not oracle position values or
engine-strength matches. The dataset is diagnostic and is not used for fitting.

For each position retain the static evaluation trace and native MultiPV=2
scores/PVs at 8,192 and 65,536 nodes. Search labels start from the FEN with its
rule-50 clock and without earlier played repetition history. Source histories
are retained separately, so played outcomes need not agree with FEN-only labels.
Keep centipawn and mate scores separately rather than replacing mates with a
large arbitrary number. Audit all legal source histories, PGN results, native
label types/PVs, completed manifests and every exact-position exclusion.

## Coverage and value diagnostics

The deeper labels contain **409 finite centipawn scores** and **103 mate
scores**. Only **164 positions** have a finite score within the earlier training
window of +/-600 cp. Thus this fresh set also probes a range omitted by the
previous teacher-score filter. The played policy and endgame sampling bias the
distribution; it is not representative of all chess positions.

On the 409 finite positions, static teacher scores differ from 65,536-node
search scores by 144.57 cp MAE. The 8,192-node search scores differ by 78.33 cp
MAE. Comparing unchanged evaluators on the same positions gives:

| Evaluator | MAE against deeper search, all finite | MAE within prior +/-600-cp window |
| --- | ---: | ---: |
| Classical 0.6.0 | 243.28 cp | 221.00 cp |
| Experimental geometric threats | 234.25 cp | 212.23 cp |
| Earlier static-label hybrid | 211.58 cp | 173.83 cp |
| Moderate paired hybrid | 210.09 cp | 175.12 cp |

These value diagnostics do not establish playing strength. In particular, the
models' lower error still did not yield a verified match gain in earlier tests.
All binaries/source manifests and both model digests are checked and recorded.

The pinned source shows that both the final static trace and ordinary finite
search scores use the same position-dependent centipawn conversion. This check
rules out a simple static-versus-search display-unit mismatch; it does not
explain away their different values. See the official
[static trace](https://github.com/official-stockfish/Stockfish/blob/sf_19/src/evaluate.cpp)
and [search score conversion](https://github.com/official-stockfish/Stockfish/blob/sf_19/src/score.cpp).
No teacher code or weights are incorporated into Aster.

## Frozen move regression suite

Freeze **16** endgame positions before inspecting Aster moves: take the first
eligible position per source game whose first move is stable at both budgets,
whose first two scores are finite with a >=120-cp side-to-move gap at both
budgets, and whose verified score lies within +/-1500 cp. Eighteen source games
qualify in this dataset, so the suite is intentionally small. It complements
the original tactical suites; it does not replace their gates or prove optimality.

| Evaluator | Depth 8 | 25,000 nodes |
| --- | ---: | ---: |
| Classical 0.6.0 | 13/16 | 14/16 |
| Experimental geometric threats | 13/16 | 14/16 |
| Earlier static-label hybrid | 13/16 | 14/16 |
| Moderate paired hybrid | 14/16 | 15/16 |

The one-position advantage is a regression diagnostic, not superiority evidence.
Equal-node and equal-depth results are not equal-time strength comparisons.
The ordinary evaluator and production package remain unchanged.

## Larger-budget consistency check

Re-query **128 positions** at 262,144 nodes, including all sixteen frozen
fixture positions and seeded additional samples from finite scores within/outside
the training window and native mate scores. All sixteen fixture best moves
remain unchanged. Across the broader stratified sample only **87/128** best moves
agree, **8** labels switch between finite and mate form, and the **88** pairs
that remain finite change by **47.68 cp MAE**. Neither budget gives oracle values.
The frozen fixture is retained unchanged and the complete re-query is preserved.

Next prioritize fresh balanced endgames and label stability, with positions kept
outside these now-frozen diagnostics. Compare search targets and played outcomes
explicitly before new training. Wider label coverage and exact endgame knowledge
may help, but must still be checked in actual paired matches.

The ordinary build passes **43 tests**, independent rule/protocol verification
covers **1,614 positions**, and the required depth-7 benchmark remains **146,772
nodes**. [Complete provenance](../artifacts/research/endgame-diagnostic-experiment-manifest.json)
binds the dataset, full source PGNs, every label/query, fixture, evaluator/model
identities, exact scripts and verification. The Stockfish-superiority goal remains
active and unachieved.
