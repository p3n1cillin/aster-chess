# Phase-conditioned neural output

Aster 0.7.8-phase-dev adds optional original network formats 9/10. Shared
king-region piece features feed separate turn-aware middlegame and endgame
output weights. Material phase interpolates the two outputs: knights/bishops
count 1, rooks 2 and queens 4 for both colors, capped at 24. Format 9 adds a
bounded correction to classical evaluation; format 10 evaluates independently.
Both use clipped hidden activation. The classical evaluator remains the default.

Integer inference blends signed 64-bit head sums before one division. Each
side's cached score also records phase, so a changed phase cannot reuse an old
score. Captures, promotions, castling, en passant, king-region changes, null
moves, cloning, cancellation and undo are checked against a scalar rebuild.
All 53 engine tests pass; 7,350 independent Python/C# inference comparisons
cover formats 1..10, scalar/vector execution for phase formats and maximum-size
signed-int16 extremes. Default search retains every move, score and node count
on 80 fresh depth-eight positions; bench seven retains 146,772 nodes. The
classical and both trained models each pass 2,614 independent legality/perft/
protocol checks. Model inference additionally agrees on 525 positions each.

## Controlled training

The [plan](../artifacts/research/phase-plan-v1.json) was frozen before
implementation, training or candidate queries. Two 64-hidden models use the
same 60,000 static-labelled positions, seed 20261014, whole-game split,
50 epochs, learning rate 0.0002, batch 512, activation bias 0.5, transformer
standard deviation 0.1 and paired-turn loss weight 1. Ordinary held-out loss
alone selects epoch 11 for both. Initial shared weights and random-generator
states agree; MG and EG outputs clone the control head, producing equivalent
initial values at all phases. The retrained control reproduces the earlier
moderate paired-loss model byte for byte.

| Measurement | Matched control | Phase output |
| --- | ---: | ---: |
| Quantized held-out MAE, all 5,690 rows | 127.623 cp | 127.426 cp |
| Phase 0..8, 2,540 rows | 138.202 cp | 137.945 cp |
| Phase 9..16, 1,257 rows | 133.754 cp | 133.664 cp |
| Phase 17..24, 1,893 rows | 109.356 cp | 109.170 cp |
| Float held-out turn-difference MAE, 978 pairs | 42.017 cp | 41.120 cp |
| Quantization MAE | 1.187 cp | 1.193 cp |
| Original tactics, depth 8 / 5,000 nodes | 32 / 32 | 32 / 32 |
| Quiet tactics, depth 8 / 5,000 nodes | 32 / 23 | 30 / 24 |
| Endgame moves, 5,000 nodes | 13 | 13 |

The teacher-fit change is small. Two lost depth-eight quiet tactics and the
25-position quiet-node threshold already block promotion. This is an
architecture ablation on existing development data, not evidence of broader
endgame generalization or stronger play.

Engine DLL SHA-256:
`ea5ba189628bf12c597620438563e323aed1306a2426bc91ec82f6a72f4f85ff`.
Control model SHA-256:
`98535307c0c30b529cf242d2a947ccacf66678b25710f80de980e13ec4c77975`.
Phase model SHA-256:
`037f06f436437a50ada9c2ced14d6c1a960fb127dd7d1122dd01defb2029416e`.
Dataset SHA-256:
`bfea2a0226b65879961c7cde551dde3d715a9e59ef9e99adf627e3744f2be162`.
Source, checkpoints, full histories and frozen scripts remain in the repository.

## Paired matches

Both predeclared 64-game screens finish: phase vs frozen classical 0.7.6 and
phase vs matched neural control, each on a distinct fresh 32-pair opening
partition at 30 ms/move, one thread and 64 MiB hash. All 128 PGNs are
independently audited with no forfeits or unresolved games.

| Opponent | W / D / L | Score | 95% opening-family interval |
| --- | --- | ---: | --- |
| Frozen classical 0.7.6 | 15 / 19 / 30 | 38.28% | 27.42%..49.19% |
| Matched neural control | 26 / 25 / 13 | 60.16% | 52.50%..67.42% |

The candidate beats its matched neural control in this limited screen, but
remains below classical play and loses two quiet depth-eight tactics. Both
frozen tactical and classical confidence gates fail. The longer confirmation
is skipped and all 16 reserved pairs remain unused by Aster. There is no
retuning, adaptive extension or inferred Elo. The original plan requires
all correctness/tactical gates and a short classical opening-family confidence
lower bound strictly above 50%, plus a control score of at least 50% with
lower bound at least 45%. The bootstrap uses 20,000 samples, seed 20261113
and 31/28 first-four-ply families respectively. This single initialization,
dataset and short control do not establish broad strength or transfer to
other engines/settings. The [decision](../artifacts/research/phase-decision-v1.json)
recomputes all declared gates.

The pipeline is frozen before matches. A small separately frozen preservation
adapter normalizes evidence paths for POSIX, retaining the original Windows
preserver and every gate byte for byte. Partial runs refuse final preservation.
Completed artifact hashes and PGN audits can be rechecked with:

```powershell
.venv/Scripts/python.exe scripts/preserve_phase_portable.py --verify
```

No learned default or strength gain has been selected. The last matched local
rating remains 2319 (95% interval 2277..2360) for the exact earlier
0.7.6-q-evasion binary; this new binary/model is unrated. The
[session record](../artifacts/ratings/session-20261004-phase.json) retains that
exact matched reference. Public Elo and
full-strength Stockfish superiority remain unestablished. Next investigate
broader stable endgame supervision and feature interactions in a separate
predeclared experiment, without tuning to these fixture answers.
