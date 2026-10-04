# Squared hidden activation experiment

The classical evaluator remains the default. This experiment tests whether
nonlinear feature interactions can improve the compact learned evaluation.
Earlier turn-aware models mostly learned an average tempo and regressed in
paired games. Hidden activations were largely inside clipped ReLU's linear
range, limiting the interactions that this transformer/output combination
could represent on those samples.

## Runtime

Formats 7 (classical correction) and 8 (standalone) retain the king-context
features and separate moving/opponent output weights. After clipping an
integer hidden value `a` to `[0,256]`, the runtime applies `floor(a*a/256)`.
Its output range remains `[0,256]`, and output products keep the earlier
bounds. Scalar code uses integer division; vector code squares the lanes and
shifts right by eight. The residual sum remains 64-bit. Earlier formats keep
their original behavior. Inference uses only Aster's C# implementation.

Squaring a sum of feature contributions introduces cross terms even when
the unclipped inputs stay within range. A crafted two-pawn test verifies a
nonzero mixed score difference for squared activation and zero difference
for the previous activation. This proves representation capability, not
chess strength. Independent scalar tests cover both new formats, special
moves, null-move caches, undo, cloning, serialization and extreme weights.

All **42 tests** pass with and without hardware intrinsics. The initial
squared hybrid passes **17,491** independent rule/protocol checks, including
perft and terminal positions. Independent Python integer inference agrees
on **525 positions per trained model**. Classical search still matches
frozen 0.6.0 on all 64 depth-8 positions, including scores, moves and
5,155,458 nodes. The depth-7 benchmark remains 146,772 nodes.

## Training and diagnostic evidence

All three models use the audited 60,000-position paired dataset, H=64, seed
20261014, 50 epochs and whole-game validation. The same 269 held-out game
IDs preserve comparison on the original 4,712 positions. The combined split
contains 54,310 training and 5,690 held-out positions. Float training uses
squared clipped activations; the exported integer reference measures the
additional quantization/flooring error directly. Trainer sources are preserved
separately per model.

| Model | Initial feature std | Selected epoch | Combined MAE | Original-sample MAE | Original/quiet tactics, depth 8 |
| --- | ---: | ---: | ---: | ---: | --- |
| Squared hybrid | 0.02 | 5 | 155.51 cp | 153.09 cp | 32/32; 32/32 |
| Squared standalone | 0.02 | 1 | 153.92 cp | 152.21 cp | 32/32; 31/32 |
| Squared wider-init hybrid | 0.10 | 7 | 154.61 cp | 152.32 cp | 31/32; 30/32 |

The wider initialization puts 22.7% of initially sampled hidden values
outside the linear interval, versus zero for the other two. Its better
teacher fit does not pass the original 32/32 tactical gate; it is already
ineligible for default selection. Its match remains useful research evidence.

On the exact preserved 128 counterfactual turn pairs, mean pair errors are
211.36, 215.29 and 209.43 cp, respectively. Their mean signed turn differences
are 69.16, 78.89 and 71.88 cp. The teacher's mean absolute difference is
263.0 cp. These diagnostics still show limited learned turn dependence;
they are not ratings or general dataset lower bounds.

The standard deviation of the predicted turn differences is only 12.0,
16.3 and 13.9 cp, versus 394.7 cp for teacher differences on these same
pairs. The diagnostic includes 27 pairs with at least one teacher score
outside the training bound of ±600 cp. Among the remaining 101 pairs,
teacher differences still have 221.5-cp standard deviation and 147.1-cp
mean absolute magnitude. This label-range limitation should be considered
when interpreting the full diagnostic; it is not a fair strength benchmark.

## Playing-strength checks

Three sequential paired matches test against frozen classical 0.6.0,
using the first 16 v4 openings, color swaps, 30 ms per move, one thread and
64 MiB hash per engine. Reports pin the experimental binary, source manifest,
model, opening suite, options and unresolved outcomes. PGNs and independent
audits are preserved. The initial squared hybrid finishes with 5 wins,
12 draws and 15 losses (34.4%, exploratory interval 18.8%..50.0%) and is
rejected as a default. The standalone finishes with 6 wins, 7 draws and
19 losses (29.7%, interval 14.1%..48.4%). The wider-init hybrid finishes
with 14 wins, 4 draws and 14 losses (50.0%, interval 37.5%..62.5%).
All **96 games** completed and passed independent PGN audits, without
forfeits or unresolved results. Neither regression model is selected, and
parity in this small sample does not establish a gain for the wider model.
It also fails the tactical gate. The classical evaluator remains default.
No Elo or Stockfish superiority is claimed.

The native binary is `artifacts/publish/squared-dev/Aster.exe`, SHA-256
`5b64ad1d13769c3db6425c475bf74ecee391f721fa4c81cd7e9af32495d8a321`.
Its immutable source manifest is `artifacts/research/squared-source/manifest.json`.
The production 0.6.0 package is unchanged. Models and exact trainer sources,
checkpoints, data references, diagnostics, verification, JSON reports, PGNs
and analyses are bound by `artifacts/research/squared-experiment-manifest.json`.

Next, isolate the initialization effect by training a turn-aware model with
the same larger feature-weight initialization and the earlier activation.
Broader and longer-control testing is needed before any playing-strength
claim. Investigate training targets and tactical feature coverage rather
than treating a new model format as a strength improvement by itself.
