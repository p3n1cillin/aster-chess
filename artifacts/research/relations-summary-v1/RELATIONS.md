# Geometric attack and defense feature experiment

Aster 0.8.0-relations-dev supports an optional H64 evaluator with 80 additional
geometric relationship features. The classical evaluator remains the default.
The declaration precedes feature implementation, initialization, training and
new opening queries: `artifacts/research/relations-plan-v1.json`, SHA256
`59dd0ea5f62f96754b2682692affb84789b2a425f07049104759995ceb94fee2`.

Each color and non-king piece type has two counts: pieces attacked by the
opponent and undefended, and pieces attacked by the opponent and defended.
Geometric control includes pawns, kings, pinned pieces and the first occupied
square along slider rays. These counts do not establish legal captures, safe
exchanges or zugzwang. Each count is clipped to 0..3 (3 means three or more)
and activates one of four bins. Color is relative to the evaluated perspective.
There are 20 active relation features per perspective, including zero-count
bins, bringing the maximum to 84 and the total vocabulary to 13,136.

Formats 11 (bounded classical correction) and 12 (standalone) retain clipped
activation, turn-aware four-head phase interpolation and king-context features.
Formats 1..10 retain their prior layout and scoring. `nnattacks` prints the
20 absolute White/Black count bins as a protocol-safe diagnostic. The native
runtime is independent C# with BCL-only dependencies.

The accumulator recalculates geometric maps only after changed piece geometry.
It removes prior categorical embeddings and adds changed bins. King-bucket
rebuilds restore relation embeddings; null moves preserve geometry. Speculative
make/undo pairs that cancel before evaluation retain lazy cancellation.

The required build, 57 native tests, 1614 independent rules/protocol positions
and 146772-node benchmark pass. Against frozen prior classical play, all 32
depth-eight moves, scores and node counts agree exactly. Independently computed
Python geometric maps agree at 4232 positions, including all count bins, pins,
turn flips and color/rank mirroring. Nonzero H16 hybrid and H256 standalone
synthetic models each pass 525 exact C#/Python inference checks.

Both roles use the inherited 63826-row dataset, whole-game 6050-row validation
split, H64 width, 50 epochs, old-pair loss weight 1 and fresh-pair weight 0.
Candidate initialization copies every shared row, bias and output head from
the frozen H64 control; all new feature and padding rows start at zero.
Initial predictions agree exactly on all 63826 rows. Both restore the same
post-initialization RNG. Eight explicit checkpoint validation cases and
independent finite-difference checks of new linear/transformer gradients pass.
The control reproduces its prior model byte for byte, selected epoch 9 and all
50 batch fingerprints. Candidate also selects epoch 9; every ordinary, old-pair
and fresh-pair batch order matches. Selected model SHA256 values are:

- Control: `460736dd293709d72817ba1bee67e3186edabd097c456fc61ad0425d2a6b7725`
- Relations: `41f8728853c368335badf8e29ea03415ab24c492306caecefbf33c8c9c6676a8`

Quantized held-out MAE decreases from 131.5398cp to 127.7188cp. On 360 fresh
endgame rows it decreases from 201.5889cp to 189.6333cp; on 180 fresh turn
pairs, difference MAE decreases from 179.6222cp to 173.2222cp. These are fit
diagnostics on the same held-out labels, not playing-strength estimates.

The separate frozen legal-operation cost harness has median times 7.7465ms
classical, 28.0646ms control and 40.0387ms relations for 76800 evaluations
per round. The candidate costs 1.4267 times the control on this local workload.
Nine rounds balance each role across order slots, with three warmup rounds.
An independent legal replay checks all 192 root/child scores and every recorded
checksum. This cost ratio does not measure broad search speed or establish
why a model wins or loses games.

Playing validation uses 160 fresh color-swapped opening pairs, excluding all
prior parents, training and diagnostic data and tactical fixtures. Both declared
128-game short screens must finish even if tactical thresholds fail. The final
32 reserved pairs are queried only if the frozen playing and tactical gates pass.
A separate counterbalanced make/eval/undo/eval cost trace reports inference
expense without selecting the model or changing gates. Reports, sources,
initial/final checkpoints, runtime packages and PGNs are preserved.

Both selected models pass 525 exact inference comparisons and 2614 independent
rules/protocol positions. Candidate tactics solve 31/32 original positions at
depth eight (required 32), 32/32 at 5000 nodes, 30/32 quiet positions at depth
eight (required 32), 25/32 quiet positions at 5000 nodes and 13/16 endgames.
Two tactical gates fail. The short screens still run as declared, but the
candidate is ineligible for promotion and longer confirmation.

Both short screens complete and all 256 PGNs pass independent legality/outcome
audit with no forfeits or unresolved games. The frozen family bootstrap uses
20000 samples and seed 20261128:

| Opponent | W / D / L | Score | 95% opening-family interval | Families |
| --- | --- | --- | --- | --- |
| Classical Aster | 35 / 40 / 53 | 42.97% | 36.51%..49.25% | 53 |
| Matched H64 control | 44 / 55 / 29 | 55.86% | 49.56%..61.62% | 53 |

The control tolerance gate passes, but its interval includes 50%, so this
screen does not establish a relative playing gain. The classical gate and two
tactical thresholds fail. No model is promoted or retuned. Longer confirmation
is skipped, leaving the final 32 reserved opening pairs unused by Aster.

Saved first searches at identical opening histories have median depths 6/7
against classical and 6/6 against control. Median paired node ratios are 0.4123
and 0.8140 respectively. Evaluations change search trees; these observations do
not prove that cost alone causes the match results. A separate metadata audit
checks exact runtime/source/model fingerprints, applied resources, time
controls, ply caps and opening partitions. All 211 capacity and 206 deep-turn
archived artifacts remain byte-identical. All four Windows/Linux default/IIR
setup CI jobs pass on commit `240c515ea060324412bdd13779214f5ff2e8b36b`.

The selected features improve held-out label fit at this budget, but have not
produced an evaluator ready to replace classical play. Further feature work
should isolate inference expense and the compatibility of mixed static/deep
targets, using fresh playing gates and preserving the failed tactical cases.
No model rating or superiority over full-strength Stockfish is established.
The last measured exact reference remains 2319, interval 2277..2360, on the
SF19 UCI_Elo-setting-equivalent scale at 30ms/move, one thread and 64MiB hash.
The new runtime and both models remain separately uncalibrated. See
[the session record](../artifacts/ratings/session-20261004-relations.json).
