# Turn-aware evaluation research

The classical evaluator remains the default. Two initial turn-aware models
regressed in paired games against frozen Aster 0.6.0. The project has not
surpassed Stockfish.

## Motivation and implementation

Earlier models produce a white score from the board's pieces and add a fixed
12-cp side-to-move tempo. For a board legal with either turn, their white-score
difference is always 24 cp. A preserved diagnostic labels 128 counterfactual
turn pairs with pinned Stockfish 19 at 8,192 nodes per turn. The mean absolute
teacher difference is 263.0 cp. The mean unavoidable pair error for a
position-only score plus that fixed tempo is 125.4 cp, with median 29 cp.
This bound concerns that counterfactual sample, not the natural training
distribution or playing strength.

Formats 5 (classical correction) and 6 (standalone) keep the existing
13,056-feature king-context transformer and give the moving and opposing
perspectives separate output weights. There are 2H output weights. Black-to-
move outputs are converted to white scores before adding the linear term.
The accumulator caches each turn separately, handles null moves without
piece updates and uses a 64-bit residual sum. Earlier formats remain readable.
The optional runtime is entirely C# and has no teacher or Python dependency.

Two new tests exercise both formats against an independent scalar formula,
special moves, random play, cloning, make/undo, null moves, search cancellation
and serialization. Extreme H=256 weights test a residual exceeding signed
32-bit range. All 41 tests pass with hardware intrinsics enabled and disabled.
Independent Python integer inference agrees on 525 positions per initial
model. A hybrid model also passes 17,491 independent rule/protocol checks.

## Initial 50,000-position experiments

Both models use H=64 and the same held-out games as the earlier models:
45,288 training positions and 4,712 held-out positions. Training selects an
epoch by held-out teacher loss; no match results choose the weights. The
classical evaluator's MAE on these labels is 162.0 cp.

| Model | Selected epoch | Quantized held-out MAE | Original/quiet tactics at depth 8 | W/D/L vs 0.6.0 |
| --- | ---: | ---: | --- | --- |
| Turn-aware hybrid v1 | 6 | 152.21 cp | 32/32; 32/32 | 6 / 12 / 14 |
| Turn-aware standalone v1 | 2 | 151.34 cp | 32/32; 31/32 | 9 / 6 / 17 |

Each match uses the first 16 v4 openings, with colors swapped, 30 ms per move,
one thread and 64 MiB hash per engine. The exploratory opening-cluster score
intervals are 25.0%..51.6% for hybrid and 21.9%..53.1% for standalone. All
64 games completed and passed independent PGN audits. Neither candidate is
selected as the default. These small development samples do not establish Elo.

The hybrid's diagnostic mean turn difference is only 56.1 cp on the same 128
pairs. Merely permitting turn-dependent output did not make it learn the
teacher's turn effect adequately, nor did teacher-fit improvements produce
stronger play.

## Paired training data

The augmented dataset retains all 50,000 original rows and adds 10,000
opposite-turn positions. Each pair preserves every FEN field except turn,
has no en passant target, and is structurally legal, nonterminal and outside
check. New labels use the same pinned teacher at 8,192 nodes with a 600-cp
absolute bound. The dataset is deduplicated and excludes exact positions in
all four regression opening suites.

Counterfactual rows retain their parent game ID, so pairs cannot cross the
training/validation game split. Their `source_ply` records parent provenance;
they do not claim to be played game positions. The combined split is 54,310
training and 5,690 held-out positions. Compare new candidates separately on
the original 4,712 held-out positions before comparing fit with earlier models.
These new labels come from FENs without histories, unlike original labels
generated during played games; repetition context can therefore differ.

The independent parent audit checks that original rows are unchanged and
that each new row changes only turn and remains in its parent group.
Generation, data, teacher, classical-score and trainer fingerprints are
preserved with each artifact. The paired hybrid selects epoch 6, with 155.36 cp
MAE on all 5,690 combined held-out positions and 153.04 cp on the original
4,712 positions. The paired standalone selects epoch 2: 153.38 cp on the
combined sample and 151.31 cp on the original sample. Combined-sample MAEs
are not directly comparable to the earlier original-sample figures.

The retrained hybrid solves 32/32 original tactics and 31/32 quiet tactics;
the retrained standalone solves 32/32 and 30/32, respectively. The hybrid
scores 6 wins, 8 draws and 18 losses against 0.6.0 in its 32-game paired
match, with exploratory score interval 21.9%..42.2%. It is rejected as a
default. The standalone finishes with 6 wins, 4 draws and 22 losses, with
exploratory interval 9.4%..42.2%; it is also rejected. All **128 games** across
the four candidates completed and passed independent PGN audits, without
forfeits or unresolved results.

Rescoring the preserved 128 counterfactual pairs gives mean turn differences
of 74.0 cp for paired hybrid and 69.5 cp for paired standalone. Mean pair
errors are 211.2 cp and 215.2 cp. The extra data strengthens the learned
average tempo but still does not approach the teacher's varied turn effects.
Most sampled hidden activations remain inside the linear portion of clipped
ReLU. Richer feature interactions are a future hypothesis requiring separate
inference, tactical and match validation.

## Preserved artifacts

The candidate binary/source snapshot is `artifacts/publish/turn-aware-dev`
and `artifacts/research/turn-aware-source/manifest.json`. Frozen classical
0.6.0 remains in `artifacts/publish/baseline-0.6.0`; the production package
retains its original hash. Models, checkpoints and exact trainer sources live
in the four `artifacts/training/turn-aware-*-v1` directories. Each match's JSON,
PGN and cluster analysis are retained under `artifacts/matches`.

The final source build passes 41 tests and the required 146,772-node depth-7
benchmark. Legacy v2 and v4 models still agree with independent Python
inference on 525 positions each. The experiment manifest binds models, data,
source snapshots, reports and diagnostic artifacts; see
`artifacts/research/turn-aware-experiment-manifest.json`.
