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

Collection is currently running. No training, match result, strength gain or
new rating is claimed. The last exact calibrated binary remains Aster
0.7.6-q-evasion-dev: **2319**, local 95% interval **2277–2360**, on the
Stockfish 19 UCI_Elo-setting scale at 30ms/move, one thread and 64MiB hash.
Public-pool ratings and superiority to full-strength Stockfish remain
unestablished.
