# Fresh paired-turn supervision

This experiment tests whether paired-turn loss on deep endgame labels improves
Aster's playing strength. Both models receive identical ordinary targets; only
the extra fresh-pair objective differs. The declaration was frozen before new
teacher queries: `artifacts/research/deep-turn-plan-v1.json`, SHA256
`70e19c063e26fe4c5bd289f0807ec3ef01ff0c44f3e6309de9cc4abbcb183c8b`.

Every one of the previous 4096 White-to-move endgame parents was visited once.
Only the turn field was flipped. Invalid raw en-passant states, checks, terminal
states and excluded positions were rejected without repairing the FEN. All
4034 eligible Black roots were queried using pinned Stockfish 19 at 16384 and
65536 nodes. Acceptance required finite labels, absolute verified score at most
1500cp, the same first PV move and at most 50cp score change. All queries,
native mate labels and rejections are retained. No Aster error selected data.

The result is 1913 pairs, or 3826 fresh positions with equal side counts.
Rejections comprise 60 invalid counterfactual FENs, two excluded roots, 193 mate
labels, 26 scores outside the range, 1331 changed first moves and 571 unstable
values. The first 60000 training rows remain byte-identical. Eligible fresh
groups inherit their prior split: 1733 training pairs and 180 held-out pairs.
There are 6050 held-out ordinary rows, with all 269 original validation groups
retained. Pair eligibility changes the original score-bin balance.

Counterfactual Black positions have no played outcome or fabricated history.
The actual White source histories and original PGNs remain available. The
independent audit replayed 461828 source plies and 70109 native PV plies,
rechecked all 3826 classical scores, and reproduced 256 teacher analyses across
64 seeded pairs at both budgets. A deeper diagnostic on 32 pairs retained the
first move in 53 of 64 positions; one finite label became a mate label. These
diagnostics did not filter data. Local stability does not make labels oracles.

Both phase-aware, king-context H64 hybrid models trained for 50 epochs with
identical complete initial weights, RNG, ordinary/old-pair/fresh-pair batch
orders and held-out targets. Old static-pair loss remains weight 1; fresh-pair
loss is weight 0 for control and 1 for candidate. Even the zero-weight stream
consumes identical RNG. Selection uses only ordinary held-out loss. Gradient
and partition checks pass; a full legacy training reproduced its prior model
byte for byte, demonstrating unchanged behavior without fresh markers.

Control selected epoch 9; candidate selected epoch 16. Their quantized ordinary
held-out MAE is 131.54 and 135.57cp respectively. On 180 held-out fresh pairs,
float turn-difference MAE is 179.57 versus 196.09cp. Predicted difference
standard deviation rises from 26.20 to 95.95cp against teacher 283.59cp.
The extra objective learns variation but worsens these fit metrics.

Both models pass exact Python/C# inference and 2614 independent rules/protocol
positions. The required build, 55 native tests and depth-7 benchmark pass.
All 24 runtime source files match the declared classical engine; a metadata-only
rebuild matches moves, scores and nodes on 32 depth-8 positions. Matches use
the original frozen `ac907eac...` assembly.

Candidate passes all tactical thresholds: original 32/32 at depth 8 and 5000
nodes, quiet 32/32 at depth 8 and 25/32 at 5000 nodes, endgames 14/16 at 5000
nodes. Control scores 32, 32, 30, 24 and 13. Tactical improvement alone does
not establish playing strength.

The match plan freezes 160 fresh opening pairs. Both 128-game short screens
always finish: candidate versus classical and versus matched control at
30ms/move, one thread, 64MiB hash. A conditional 64-game classical confirmation
at 100ms/move requires all correctness/tactics gates, no unresolved games or
forfeits, classical short family-bootstrap lower bound above 50%, and control
point at least 50% with lower bound at least 45%. Promotion additionally requires
long score at least 50% with lower bound at least 45% and no issues. There is
no retuning or adaptive extension. Match results are pending.

This is an endgame-biased, finite-label experiment. Counterfactual validity
does not prove full retrograde reachability or an observed outcome. It does
not establish superiority to full-strength Stockfish. No new rating calibration
is planned: the last exact calibrated reference remains 2319, local 95%
interval 2277–2360, on the SF19 UCI_Elo-setting scale at 30ms/move. These models
do not inherit that reference's rating; public Elo remains unestablished.
