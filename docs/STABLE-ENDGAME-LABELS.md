# Stable endgame labels

The next playing-strength experiment tests teacher-label quality on fresh
endgames. It does not change Aster's runtime dependencies or classical default.
The frozen declaration is `artifacts/research/stable-endgame-plan-v1.json`
(SHA256 `d36914bbd359be33b49eac898cc7e6a67b15390969e39f8ad51af6799283f478`).

The target is 4096 new positions, equally divided among absolute verified scores
of 0–150, 151–400, 401–800 and 801–1500 centipawns. Independent Stockfish 19
development processes play source games and label positions. A position needs
finite labels, the same first PV move and scores within 50 centipawns at 16384
and 65536 nodes. Generation has a fixed 8192-game budget. Every query, rejected
sample, native mate score, source history, source result and unresolved game is
retained. Incomplete generation prevents training; quotas are not relaxed.

Both models use the unchanged old 60000 rows and the exact same fresh rows.
The control learns fresh static scores; the candidate learns verified search
scores. Their phase-aware architecture, complete initial weights, random state,
game partitions, batch order, paired objective and 50-epoch budget are identical.
All 269 original held-out games remain held out. Fresh held-out source games
are selected once with seed 20261117 before training. Each model selects an
epoch only by its ordinary held-out loss. Common-target diagnostics report
both models against both label sets; they do not select or retune models.

The required build, 55 native tests, independent rules/protocol checks and
depth-7 benchmark passed before training. A rebuilt assembly has a different
binary fingerprint but its 24 frozen source files match the declared baseline,
and all 32 checked depth-8 positions have identical moves, scores and nodes.
Labels and planned matches use the original declared `ac907eac…` assembly.

Before matches, both models must pass exact Python/C# inference and independent
rules checks. Tactical diagnostics retain the existing thresholds. The match
plan reserves 160 fresh opening pairs: 64 against the frozen classical engine
and 64 against the matched static control at 30ms/move, then 32 against classical
at 100ms/move only if all declared gates pass. Both short screens finish even
if tactics fail. There is no adaptive extension or tuning on their results.

Collection completed within its fixed budget: 4096 positions, 7070 source
games, 50639 queries and six unresolved source games. The independent audit
replayed all 847572 source plies and 840449 PV plies, checked every accepted
classical score and exactly reproduced all 64 randomly selected teacher
labels at both search budgets and their static scores. Rejections comprised
16957 native mate labels, 13318 changed first moves, 6782 unstable values,
1254 scores outside the range and 8232 already-full bucket samples.

The audit exposed a sampling limitation: **every fresh position is White to
move**, because sampling at multiples of four from the initial board always
reaches that side. The dataset is balanced by absolute score range, not side
to move. No positions or parameters were replaced after observing this. The
old 60000 rows retain both sides and their existing turn-pair supervision.
The deeper diagnostic preserved the first move in 22 of 32 positions at
262144 nodes. Three finite labels became native mate scores; the remaining
29 changed by 87 centipawns on average in absolute value. Local label
stability is not proof of an oracle value.

Both prepared datasets contain exactly 64096 positions, with the first 60000
rows byte-identical to the old data. Only 4047 fresh target values actually
differ. The fixed split retains 269 old held-out games and selects 130 of
1304 fresh source groups with the declared seed. There are 6087 held-out
positions, including 397 fresh endgames.

Both 50-epoch trainings completed. Complete initial state, random state,
whole-game splits and every epoch's ordinary/pair batch order matched.
Ordinary held-out loss selected epoch 10 for the control and epoch 9 for
the candidate. Their model SHA256s are respectively
`9900079c170813aeda3026834ce58654595705a7998457426252071499c0778f`
and `723870f955d642c14b36998f9ed6e7187bbbb0296cf5de40e5898396475be2de`.

On the same 397 held-out fresh positions, quantized errors were:

| Model | Static target MAE, cp | Deeper target MAE, cp |
|---|---:|---:|
| Matched static control | 149.635 | 182.275 |
| Stable-label candidate | 151.277 | 182.315 |

There is no held-out deeper-label fit improvement here. Each model's own
mixed-target metric uses a different fresh target set and must not be
compared as if the targets were identical.

Both models passed 525 exact Python/C# inference checks and 2614 independent
rules/protocol cases. Both solved 32/32 original tactics at depth 8 and 5000
nodes, and 13/13 endgames. Quiet tactics: the control solved 31/32 at depth 8
and 24/32 at 5000 nodes; the candidate solved 32/32 and 24/32 respectively.
The candidate misses the required 25 at the node budget, so promotion and
conditional longer confirmation are blocked. Both declared short match
screens completed, totaling 256 audited games. The classical screen has 32 wins, 43 draws
and 53 losses in 128 games: 41.797%, 95% opening-family interval
35.246%..48.413%, across 55 families. Its PGNs are independently audited,
with zero forfeits or unresolved outcomes. The classical confidence gate
also fails. Against the matched fresh-static model, the candidate has
44 wins, 54 draws and 30 losses: 55.469%, 95% family interval
48.864%..61.885%, across 56 families. That interval includes 50%; this
positive point score does not establish a gain. All 256 games have zero
forfeits/unresolved outcomes. The last 32 reserved pairs remain unused by
Aster; no conditional long games, retuning or extension occur. The classical
default is retained. No strength gain or new rating is claimed.

A separate post-training diagnostic computes an optimistic per-position
fit bound from the fixed ±250 cp residual cap. On the 397 fresh held-out
positions, the deeper-target floor is 43.118 cp, versus the candidate's
182.315 cp error. Only 0.504% of its corrections are clipped. This suggests
checking supervision/feature capacity before attributing the error solely
to the cap. The bound uses perfect access to teacher labels; it is not a
realizable evaluator or a strength estimate. This diagnostic does not alter
data, models, epochs, gates or matches.

The experiment's immutable manifest retains its plan, source snapshots,
generation queries/PGNs, native teacher scores, datasets/split, model weights
and checkpoints, runtime packages, diagnostics and all match reports/PGNs.
All four Windows/Linux default/IIR CI jobs passed for the data/model commit.
The next research step is two-sided endgame and paired-turn search supervision,
with feature/capacity changes isolated in separate ablations. The observed
White-only sampling and unstable deeper labels are explicit design limits.

The last exact calibrated binary remains Aster
0.7.6-q-evasion-dev: **2319**, local 95% interval **2277–2360**, on the
Stockfish 19 UCI_Elo-setting scale at 30ms/move, one thread and 64MiB hash.
Public-pool ratings and superiority to full-strength Stockfish remain
unestablished.
