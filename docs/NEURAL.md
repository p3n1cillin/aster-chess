# Learned evaluation experiments

The production default remains the classical evaluator. Three initial learned
models passed inference checks but regressed in matches against Aster 0.2.0.
They are preserved as experiments, not recommended engine defaults.

## Runtime

Aster implements its own compact, shared `768 -> H -> 1` network, with a separate
linear material/PSQT term. There are two perspectives. Black swaps piece colors
and mirrors ranks; the output subtracts the black perspective from white, making
the value antisymmetric under that transformation. A side-to-move tempo term
is applied separately. Formats 5 and 6 instead use separate moving-side and
opponent output weights, so evaluation can depend on whose turn it is.

The new experimental king-context format adds 16 own-king regions, each
conditioning another copy of the 768 piece-square features. There are 13,056
possible features and at most 64 active features per perspective. Ordinary moves
update both feature groups; crossing a king-region boundary rebuilds that
perspective from the current piece set. Lazy make/undo cancellation is preserved.
See [king-context experiments](KING-CONTEXT.md) for the data and validation.

Integer feature weights, biases and output weights are quantized. Hidden
activations are clipped to `[0, 256]`. Piece changes accumulate as sparse deltas;
the runtime applies them when evaluation is actually requested. Make/undo pairs
that cancel without an evaluation incur no dense accumulator update. Vectorized
updates use `System.Numerics.Vector<int>` with a scalar fallback. All inference
is local C#; training frameworks are not runtime dependencies.

Model loading is explicit:

```text
setoption name EvalFile value C:/path/to/model.ann
setoption name EvalFile value <classical>
```

Loading a model preserves the position and history and clears the transposition
table. `ucinewgame` and subsequent `position` commands retain the selected model.
A failed model load preserves the prior evaluator. `nncheck` compares incremental
and rebuilt raw neural values for diagnostics.

## File format

All integers are little-endian. The payload is exactly:

| Field | Representation |
| --- | --- |
| Magic | 8 bytes, `ASTNN001` |
| Version | int32, 1..12 |
| Features | int32, 768 for v1/v2; 13,056 for v3..v10; 13,136 for v11/v12 |
| Hidden width | int32, multiple of 8 in 8..256 |
| Activation scale | int32, 256 |
| Output scale | int32, 256 |
| Linear weights | Features int16, centipawns |
| Hidden bias | H int16, scale 256 |
| Feature weights | Features × H int16, feature-major, scale 256 |
| Output weights | H int16 for v1..v4; 2H for v5..v8; 4H for v9..v12, centipawns × 256 |

For version 1, white score is `(linearWhite - linearBlack) / 2` plus
`sum((clip(accWhite) - clip(accBlack)) * output) / 65536`. Signed divisions
truncate toward zero. A side-to-move tempo of 12 cp is added after orientation.

Version 2 uses this network as a correction to Aster's classical evaluation,
clipped to ±250 cp. The existing classical tempo is retained. Changing the
classical evaluator changes a version-2 model's effective behavior, so its
training metadata pins the baseline engine fingerprint.

Version 3 is a bounded classical correction with king-context features. Version
4 uses the same context features as a standalone evaluation, retaining the 12-cp
tempo. A king is oriented to its perspective by mirroring ranks for black.
Its region is `(rank / 2) * 4 + file / 2`, using zero-based coordinates and
integer division. Every piece activates its ordinary feature and
`768 * (region + 1) + ordinaryFeature`. All formats retain exact signed
integer inference and the same activation/output scales.

Version 5 is a king-context classical correction; version 6 is standalone.
They concatenate H moving-side output weights and H opponent output weights.
The residual is `dot(clip(accMoving), movingWeights) +
dot(clip(accOpponent), opponentWeights)`, divided by 65536 and oriented to
white before adding the fixed white linear term. Separate cached scores for
each turn ensure null moves cannot reuse the wrong output. The final sum uses
64-bit integers, including in the vectorized path. The standalone 12-cp tempo
and hybrid ±250-cp correction limits remain unchanged.

These formats require the experimental `turn-aware-dev` build or current
source; the preserved production 0.6.0 package supports v1..v4. See
[turn-aware experiments](TURN-AWARE.md) for checks, models and match evidence.

Formats 7 (hybrid) and 8 (standalone) retain the turn-aware payload and replace
each clipped hidden value `a` with `floor(a*a/256)` before the output dots.
The transformed value is still in `[0,256]`; all output scales, linear terms,
turn orientation and correction limits stay the same. These formats require
current source or the preserved `squared-dev` build. See
[squared activation experiments](SQUARED-ACTIVATION.md).

## Reproduce the pipeline

Install `requirements-train.txt` into the development environment. The recorded
experiments used CPU training with four threads and fixed seeds.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-train.txt
.\.venv\Scripts\python.exe scripts/generate_data.py --positions 20000 --output artifacts/data/new-teacher.jsonl
.\.venv\Scripts\python.exe scripts/add_classical_scores.py artifacts/data/new-teacher.jsonl --engine artifacts/publish/baseline-0.2.0/Aster.dll --output artifacts/data/new-with-classical.jsonl
.\.venv\Scripts\python.exe scripts/score_static.py artifacts/data/new-with-classical.jsonl --output artifacts/data/new-static.jsonl
.\.venv\Scripts\python.exe scripts/train_network.py artifacts/data/new-static.jsonl --classical-base --output artifacts/training/new-experiment
.\.venv\Scripts\python.exe scripts/verify_network.py artifacts/training/new-experiment/model.ann --data artifacts/data/new-static.jsonl
.\.venv\Scripts\python.exe scripts/verify.py --eval-file artifacts/training/new-experiment/model.ann
.\.venv\Scripts\python.exe scripts/match.py --opponent artifacts/publish/baseline-0.2.0/Aster.dll --eval-file artifacts/training/new-experiment/model.ann --pairs 16 --movetime 0.03 --output artifacts/matches/new-experiment
```

Data is deduplicated globally by the first four FEN fields, normalizing en passant
to legally available captures so ineffective targets cannot disguise duplicates.
The original 20,000-position dataset was independently rechecked under this
normalization and still contains 20,000 distinct positions. Validation holds out
whole games. Label manifests record the teacher binary, source release, search
budgets and generation policy. Static relabeling retains the original search
score and documents its use of the teacher's `eval` trace. Training records the
dataset and model SHA-256, selected epoch, validation metrics, quantization
error and package versions. Output paths are never silently overwritten.

Stockfish is a label-producing development tool. Its source, neural weights and
inference code are not embedded in Aster. The network architecture, trainer,
inference implementation and trained parameter files here are separate Aster
artifacts. Teacher distillation does not establish superiority to the teacher.

## Results and limitations

The first dataset contains 20,000 positions from 913 games; 17,912 positions
are training data and 2,088 belong to held-out games. Its 8% random-move policy
introduces many blunders and imbalanced positions, limiting representativeness.
The initial network has piece-square inputs only, without king-conditioned or explicit
threat features, and the models were trained on a small dataset.

| Experiment | Teacher target | Held-out MAE | Classical MAE on same labels | W/D/L vs 0.2 |
| --- | --- | ---: | ---: | --- |
| Standalone v1 | 2,048-node search score | 223.0 cp | 251.7 cp | 0 / 1 / 31 |
| Hybrid v1 | 2,048-node search score | 228.1 cp | 251.7 cp | 6 / 6 / 20 |
| Hybrid static v1 | Final static evaluation | 224.3 cp | 258.0 cp | 7 / 5 / 20 |

Each match used 16 color-swapped pairs at 30 ms per move against the frozen
classical build. All PGNs were audited. Repeated openings and short budgets
limit generalization, but the observed regressions reject these defaults.
Every model matched the independent Python quantized implementation exactly
over 520 positions; quantization's held-out average error was below 1 cp.
Better teacher-score fit did not translate into stronger play.

Next experiments should improve sampling, add held-out tactical/strategic suites,
measure inference cost, and investigate king/threat features before scaling
training. Compare candidate models in actual search and retain the classical
baseline until an advantage survives broader tests.
