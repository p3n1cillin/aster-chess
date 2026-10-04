# King-context neural evaluation

The earlier piece-square-only models regressed despite improved teacher-fit
metrics. This experiment adds king context and improves data quality. It remains
an independent Aster architecture, trainer, format and C# inference implementation.
Stockfish produces development labels only.

## Inputs and incremental inference

Each perspective activates the existing 768 piece-square features and a second
piece-square feature set selected by its own king's 2-by-2-square region. Sixteen
regions cover the board, giving 13,056 possible features in total. Black swaps
piece colors and mirrors ranks. The antisymmetric output and integer scales
remain unchanged. Hybrid format v3 bounds the learned correction to ±250 cp;
standalone v4 keeps the existing 12-cp tempo convention.

The accumulator retains the current piece set alongside queued sparse changes.
If a king changes region, only that perspective rebuilds, using the final piece
set. The other perspective applies ordinary deltas. A make/undo pair that cancels
before evaluation still avoids dense updates. Castling, captures, promotions,
en passant, FEN reloads, clones and null moves are covered by independent scalar
tests. The trainer initializes new context weights to zero so unseen regions
do not introduce random initial corrections.

The new C# property test passes for both formats. A separate output test covers
signed extreme weights and sums that exceed 32-bit range, bringing the total
to 39 tests. All 39 pass with hardware intrinsics enabled and disabled.
Deterministic synthetic v3 and v4 models each agree with the independent Python
quantized reference on 525 positions. The legacy hybrid also retains exact
agreement. Synthetic models are test fixtures, not trained playing engines.
The hybrid fixture passes 2,614 independent rule/protocol checks and 14 perft
positions. Default classical searches preserve all 64 checked moves, scores
and node counts against frozen 0.5.1.

## Bounded data experiment

Generate 256 distinct 16-ply training openings with a separate seed, excluding
all three regression suites and the original 20,000-position data. Use these
for 50,000 new positions with 8,192-node teacher labels, 512-node unsampled
play, 2% random legal moves and an absolute label cap of 600 cp. Deduplicate
canonically, exclude exact regression positions, skip check/terminal positions
and near-rule-50 states, and split whole games for validation. These are teacher
search labels, not game outcomes. Opening families can still span the training
and validation sets; the split does not prove generalization to new openings.

The completed dataset contains 50,000 positions from 2,695 sampled games
(3,014 games generated). Independent auditing finds no canonical duplicates,
illegal or terminal positions, or exact overlap with the three regression
suites. Endgames account for 44.3% of positions. All 16 king regions appear,
although their frequencies vary substantially.

The generation manifest pins the teacher binary, options, budgets, seed, opening
suite and exclusion hashes. Classical-score augmentation additionally pins its
engine and the input/output datasets. Training records those fingerprints,
selected epoch, game split, quantization error and held-out teacher-fit metrics.
Actual playing strength determines acceptance.

```powershell
.venv/Scripts/python.exe scripts/add_classical_scores.py artifacts/data/teacher-balanced-50k-v1.jsonl --engine artifacts/publish/baseline-0.5.1/Aster.exe --output artifacts/data/teacher-balanced-50k-v1-classical.jsonl
.venv/Scripts/python.exe scripts/train_network.py artifacts/data/teacher-balanced-50k-v1-classical.jsonl --king-context --classical-base --hidden 128 --epochs 50 --output artifacts/training/king-context-balanced-v1
.venv/Scripts/python.exe scripts/verify_network.py artifacts/training/king-context-balanced-v1/model.ann --data artifacts/data/teacher-balanced-50k-v1-classical.jsonl
```

Preserve the model, checkpoint, report, source and match PGNs. Keep the classical
default until a model demonstrates a benefit under paired equal-time testing.
The training directory names identify experiments, not released engine defaults.

## Trained candidates

All four runs use the same split: 45,288 training positions and 4,712 positions
held out by whole game, seed 20261014. Each has 50 training epochs and exports
the checkpoint with the lowest held-out objective. The frozen classical
evaluator's teacher-label MAE on this split is 162.01 cp. These models improve
that metric modestly but do not thereby demonstrate stronger play.

| Experiment directory | Mode | Hidden | Learning rate | Selected epoch | Quantized teacher MAE (cp) |
| --- | --- | ---: | ---: | ---: | ---: |
| `king-context-balanced-v1` | Hybrid v3 | 128 | 0.002 | 1 | 155.23 |
| `king-context-balanced-slow-v1` | Hybrid v3 | 64 | 0.0002 | 4 | 152.43 |
| `king-context-standalone-v1` | Standalone v4 | 64 | 0.0005 | 1 | 151.29 |
| `king-context-nonlinear-v1` | Hybrid v3, zero initial bias | 64 | 0.0002 | 4 | 152.57 |

Each trained model passes exact integer reference agreement on 525 positions
and solves all 32 tactical regression fixtures at depth 8. The zero-bias model
starts with 48.3% of sampled preactivations outside the linear interval; the
selected checkpoint has only 2.6%. This diagnostic does not establish which
architecture would play better.

All comparisons use pinned binaries, one thread, equal Hash and 30 ms/move,
with both colors on the first 16 positions of regression suite v3. This suite
has been reused for development and is not a final held-out superiority test.
The 128-unit and zero-bias models use vector output; the other two use scalar
output. The inference ablation below measures that implementation difference.

| Candidate against classical 0.5.1 | W | D | L | Score | Exploratory opening-cluster interval |
| --- | ---: | ---: | ---: | ---: | --- |
| Hybrid, 128 units | 8 | 7 | 17 | 35.9% | 23.4%..48.4% |
| Hybrid, 64 units | 7 | 11 | 14 | 39.1% | 26.6%..51.6% |
| Standalone, 64 units | 3 | 10 | 19 | 25.0% | 12.5%..37.5% |
| Hybrid, 64 units, zero initial bias | 7 | 11 | 14 | 39.1% | 26.6%..53.1% |

Reports, PGNs, opening-cluster analyses and per-move diagnostics are preserved:
[128-unit hybrid](../artifacts/matches/king-context-balanced-vs-0.5.1-30ms.json),
[64-unit hybrid](../artifacts/matches/king-context-balanced-slow-vs-0.5.1-30ms.json),
[standalone](../artifacts/matches/king-context-standalone-vs-0.5.1-30ms.json),
[zero initial bias](../artifacts/matches/king-context-nonlinear-vs-0.5.1-30ms.json).
All 128 candidate-versus-baseline games completed, with no forfeits or unresolved
outcomes, and passed independent PGN audits. None of the models was accepted
as a default. The games report fewer searched nodes for the neural candidates;
inference cost and evaluation quality both need further work. These runs do
not separate their contributions or establish an Elo rating.
The classical evaluator remains the default. A final pipeline snapshot is
preserved with source hashes; the earlier runs preceded the activation-bias
diagnostics, so that snapshot is not a byte-exact claim about earlier trainer
revisions. The training reports bind arguments, datasets, model hashes and
saved checkpoints.
[Combined provenance](../artifacts/research/king-context-experiment-manifest.json)
binds report/PGN hashes to preserved binaries, source manifests, training data
and models. The frozen 0.6.0 binary is retained separately from the active package.

Version 0.6.0 releases the optional inference and pipeline capability while
keeping the classical search behavior: all 64 depth-8 opening positions match
frozen 0.5.1 in move, score and node count (5,155,458). The packaged executable
passes 17,491 independent rule/protocol checks with a trained hybrid selected,
all 32 classical tactics, and exact 525-position inference comparisons for all
four new models and a legacy hybrid.
[Packaged search comparison](../artifacts/benchmarks/aster-0.6.0-classical-vs-0.5.1-depth8.json),
[extended neural verification](../artifacts/validation/aster-0.6.0-king-context-extended.json).

## Inference cost

The output layer clamps and multiplies vector lanes while accumulating their
dot products in a 64-bit total. This preserves the scalar result, including
extreme signed weights. With the 64-unit hybrid model, all 64 depth-8 searches
retain identical moves, scores and node counts (5,854,047 nodes). The vector
build took 4.691 seconds versus 4.914 seconds for scalar output, about 4.5%
less in that short run. JIT and machine effects limit that timing result.

A paired 32-game, 30-ms/move ablation with the same model on both sides finished
9/17/6 W/D/L, scoring 54.7%; its exploratory opening-cluster interval is
43.8%..65.6%. Every game completed and passed independent PGN auditing. This
small match does not establish a playing-strength gain.
[Search comparison](../artifacts/benchmarks/king-context-vector-vs-scalar-depth8.json),
[match](../artifacts/matches/king-context-vector-vs-scalar-30ms.json),
[PGN](../artifacts/matches/king-context-vector-vs-scalar-30ms.pgn),
[analysis](../artifacts/matches/king-context-vector-vs-scalar-30ms.analysis.json).
