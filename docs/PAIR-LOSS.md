# Direct supervision of turn differences

This development experiment tests whether directly fitting the white-to-move
minus black-to-move label difference recovers variation missing from earlier
models. It uses the unchanged 60,000-position static-label dataset, H=64
clipped activation, king context, turn-aware outputs, initial feature standard
deviation 0.10, seed 20261014, 50 epochs and learning rate 0.0002.

Two predeclared additional loss weights, 1 and 4, use the same sigmoid plus
robust centipawn objective as ordinary position training. A paired minibatch
of 128 accompanies each ordinary 512-position batch. Both members retain
their original game group. Only ordinary held-out position loss selects the
checkpoint; held-out pair diagnostics never contribute gradients. Weight zero
keeps the previous training algorithm and random-number stream.

Check parent existence, identical fields apart from side to move, unique
parentage, game partitioning and identical feature inputs. Independently check
the new objective's output and transformer gradients by finite differences.
Validate each exported model against independent integer inference and both
frozen tactical suites. Preserve all results, including missed tactics.

Each model will play 32 color-swapped games against frozen classical 0.6.0
using the first 16 v4 openings at 30 ms per move, one thread and 64 MiB hash.
Training will finish before time-controlled matches begin. These are
exploratory screens. A model must solve both tactical suites completely and
score above 50% before receiving a longer confirmation; the moderate model
gets priority if both qualify. A screen alone cannot select a new default.
PGNs, complete-match audits, analyses and all binary/model/source hashes will
be preserved. The Stockfish-superiority goal remains unachieved.

## Model diagnostics

Both models agree exactly with independent integer inference on 525 positions.
The game split contains 9,022 training pairs and 978 held-out pairs. Seven
partition/malformed-input and numerical-gradient checks pass. Model sources,
checkpoints and all reports are preserved separately from previous runs.

| Model | Original held-out MAE | Turn-difference MAE | Predicted turn-difference SD | Original/quiet tactics at depth 8 |
| --- | ---: | ---: | ---: | --- |
| Previous static model, no pair loss | 127.86 cp | 47.22 cp | 4.46 cp | 32/32; 30/32 |
| Pair weight 1 | 129.03 cp | 41.99 cp | 31.81 cp | 32/32; 32/32 |
| Pair weight 4 | 130.27 cp | 47.41 cp | 45.53 cp | 32/32; 30/32 |

Teacher turn-difference standard deviation is 61.49 cp on those same held-out
pairs. Increased variation is therefore learned, but the heavier loss does not
improve difference error. These diagnostics do not establish strength.
The moderate model also passed 17,491 independent rule/protocol checks.

A supplemental moderate-model quiet check at 5,000 nodes solved 23/32; its
report is retained separately. The comparable tactical gate above uses depth 8,
as in previous experiments. The stronger-loss model does not pass that gate.

The build has zero warnings/errors, all 42 C# tests pass, default independent
verification covers 1,614 positions, and the classical depth-7 benchmark stays
at 146,772 nodes. No runtime source or production binary changed.

## Paired matches and decision

| Pair loss | W | D | L | Score | Exploratory opening-cluster interval |
| --- | ---: | ---: | ---: | ---: | --- |
| Weight 1 | 10 | 9 | 13 | 45.31% | 34.38%..56.25% |
| Weight 4 | 12 | 11 | 9 | 54.69% | 40.63%..68.75% |

All 64 games completed and passed independent PGN audits without forfeits or
unresolved outcomes. Both screens use the declared first 16 v4 opening pairs,
30 ms per move, one thread and 64 MiB hash. The heavier loss's positive score
is inconclusive and it fails the quiet tactical gate. The moderate loss passes
that gate but its score falls below the declared confirmation threshold.
Neither therefore receives a longer confirmation or becomes the default.
Classical Aster 0.6.0 remains the production evaluator.

The additional objective improves the moderate model's held-out turn-difference
error and increases learned variation, but these experiments do not establish
stronger play. Retain paired supervision as an available research option;
investigate tactical feature coverage or label coverage next instead of tuning
this loss repeatedly against the same opening screens.

[Complete provenance](../artifacts/research/pair-loss-experiment-manifest.json)
binds both models, original trainer copies, checkpoints, matched binaries and
source manifests, dataset provenance, verification, PGNs and analyses.
[Held-out diagnostic](../artifacts/validation/pair-loss-heldout-pairs.json)
scores both new models and the previous static model on the same 978 pairs.
