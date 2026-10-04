# Initialization ablation and static-label experiment

The earlier squared model with larger initial feature weights reached parity
in 32 games, but missed one original tactical position. This experiment
isolates activation at that initialization and tests static teacher targets
on the same legal positions. The classical evaluator remains default, and
the Stockfish superiority goal remains unachieved.

## Controlled training comparisons

All candidates use H=64, initial feature standard deviation 0.10, initial
bias 0.5, learning rate 0.0002, seed 20261014 and 50 training epochs. They
retain the same game-level split: 54,310 training and 5,690 held-out rows,
including 4,712 original held-out positions. Epoch selection uses held-out
teacher loss, not match outcomes. Exact trainers and model hashes are retained.

| Candidate | Target | Activation | Selected epoch | Combined target MAE | Original target MAE | Original/quiet tactics |
| --- | --- | --- | ---: | ---: | ---: | --- |
| Larger-init turn-aware hybrid | Search score | Clipped ReLU | 8 | 154.61 cp | 152.34 cp | 32/32; 31/32 |
| Static-label hybrid | Static trace | Clipped ReLU | 7 | 126.71 cp | 127.86 cp | 32/32; 30/32 |
| Static-label squared hybrid | Static trace | Squared clipped | 6 | 126.57 cp | 127.79 cp | 32/32; 31/32 |

The classical baseline's original-position MAE is 162.01 cp on search labels
and 140.70 cp on static labels. MAEs across different target types cannot be
compared directly. Both static models are also scored against the preserved
original search labels: 150.86 cp for clipped activation and 150.70 cp for
squared activation, keeping a separate comparison on that target.
All models agree with independent Python integer inference on 525 positions.
No runtime code changes are required: formats 5/7 are already supported by
the frozen `squared-dev` build and its source manifest.

## Static-label provenance

The new 60,000-position dataset preserves every source row and game group.
Only the target changes; the original search score is retained as
`search_score_white_cp`, with `label_kind` identifying the static trace.
The pinned Stockfish 19 development binary runs with one thread and 64 MiB
hash. Its `eval` trace provides the final white-side value without searching.
Actual static label magnitudes reach 885 cp; the original ±600-cp search-label
bound is not asserted for these new labels.

Generation checks the teacher fingerprint, source digest, legal nonterminal
positions outside check, and completion. An independent audit preserves all
60,000 rows/groups and re-queries 128 static labels exactly. The legality,
canonical deduplication and all four exact-opening exclusions still pass.
The audit distinguishes retained source search budgets from current static
labels. Classical-score augmentation pins frozen 0.6.0 and both data hashes.
Stockfish remains a development tool only, never an Aster runtime dependency.

## Playing checks

Each new model receives 32 games against frozen 0.6.0: first 16 v4 openings,
color swaps, 30 ms/move, one thread and 64 MiB hash. A direct 32-game comparison
between the larger-init turn-aware and earlier larger-init squared models
isolates the trained activation variants under the same engine runtime.
These reused development openings are not a final held-out superiority test.
Reports, source/binary/model fingerprints, PGNs and independent audits are
preserved. All four 32-game screens completed and passed independent audits,
without forfeits or unresolved results.

The larger-init activation ablation scores 7 wins, 12 draws and 13 losses
against classical 0.6.0 (40.6%, exploratory interval 28.1%..53.1%). Static-label
clipped activation scores 16 wins, 8 draws and 8 losses (62.5%, interval
48.4%..75.0%). The second model warrants follow-up, but its small selected
sample does not establish a gain. It also misses two quiet-suite positions,
which must be considered before any default change.

The static-label squared model scores 12 wins, 6 draws and 14 losses
(46.9%, interval 28.1%..65.6%). In the direct activation match, the larger-init
clipped model scores 12 wins, 13 draws and 7 losses against the larger-init
squared model (57.8%, interval 45.3%..70.3%). These small samples do not
establish an activation advantage. The 64-game confirmation of the
highest-scoring static-label clipped model on v2 at 100 ms/move finishes
with 21 wins, 20 draws and 23 losses: **48.4%**, exploratory interval
**39.1%..57.8%**. All games passed independent audits without forfeits or
unresolved outcomes. The longer control and different openings do not
confirm the short-screen gain. Across these five matches, **192 games**
are preserved. The classical evaluator remains default; no Elo or
Stockfish superiority is claimed.

The follow-up rule selected the highest-scoring candidate above 50% in the
baseline screen for 32 v2 opening pairs at 100 ms/move. Selection
from several noisy screens is exploratory and may overestimate strength.
The broader, longer-control follow-up will not by itself establish Elo or
Stockfish superiority; a new default requires stronger evidence and a review
of tactical coverage.

The held-out marked-pair diagnostic uses 978 pairs from the preserved split.
Their static teacher turn difference averages 63.48 cp, with 61.49-cp standard
deviation. The two static models predict means of 31.19/33.51 cp and standard
deviations of only 4.46/4.23 cp. They still learn too little turn variation;
better average fit alone does not solve that representational/training problem.

No engine runtime changes were made in this iteration. Verification retains
42 passing tests, independent rule/protocol checks and the 146,772-node
depth-7 benchmark. The static-label source digest, generator, complete manifest,
all row/group and label-requery audits, classical-score provenance, trainer
sources, checkpoints, model fingerprints, reports, PGNs and analyses are
preserved in `artifacts/research/wide-init-turn-experiment-manifest.json`
and `artifacts/research/turn-static-experiment-manifest.json`.

Next, test supervision that directly teaches paired turn differences, richer
tactical features and stronger data coverage. Do not select a new default
from a favorable reused-opening screen or a lower teacher-error number.
