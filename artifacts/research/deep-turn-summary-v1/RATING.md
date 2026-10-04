# Current rating and measurement policy

The latest measured **Aster 0.7.6-q-evasion-dev** has a provisional local estimate
of **2319**, with a **95% opening-family interval of 2277..2360**, on the
**SF19 UCI_Elo-setting equivalent at 30 ms/move, one thread, 64 MiB hash** scale.
Its [confirmation record](../artifacts/ratings/session-20261004-q-evasion-confirmation.json)
identifies binary SHA-256
`a3994e4f350b2cfa261db5edc1e4ae5c332d85d4b3eaf34c0730267f3603d9a0`.
After passing all [optimization gates](QUIESCENCE-EVASIONS.md), 128 reserved
fresh color-swapped opening pairs against the previously fixed 2300 setting
produce **107 wins, 56 draws and 93 losses** (52.73%). All 576 experiment
games are audited with no forfeits or unresolved games. The declared family
bootstrap uses 98 families, 20,000 samples and seed 20261106; its score interval
is 46.75%..58.60%. All numeric gates pass. This does not establish a rating
increase over the earlier estimate because their intervals overlap.

The optimization is enabled in ordinary **0.7.6-feature-dev** source. That
renamed build repeats all 416 saved complete candidate traces, but its binary
has no separate rating match; the rating remains attached to the exact tested
candidate. Public ratings and full-strength Stockfish superiority remain
unestablished. The following earlier calibration fixes the reference setting
and measurement policy; its artifacts remain intact.

The subsequent **0.7.7-iir-dev** candidate completes 640 audited regression
games but fails its predeclared short-control confidence gate. Its 256-game
conditional rating is skipped; 128 reserved openings remain unused. The
[session record](../artifacts/ratings/session-20261004-iir.json) retains the
exact 0.7.6-q-evasion estimate above. No Elo is inferred from the two slightly
positive baseline-regression point scores or reduced fixed-depth work.

The subsequent **0.7.8-phase-dev** inference build and optional phase model
complete 128 audited architecture-screen games. The model beats its matched
neural control but fails quiet tactics and scores below frozen classical play.
It remains experimental, and conditional longer confirmation is skipped.
The [phase session record](../artifacts/ratings/session-20261004-phase.json)
retains the same exact measured 0.7.6-q-evasion reference; neither the new DLL
nor its model receives an Elo estimate from these regression games.

The subsequent **0.7.9-mate-proof-dev** build expands native independently
checkable mating strategies to general material. Its playing files remain
identical to the frozen 0.7.8 build, all 32 fresh fixed-depth outputs agree,
and 32 paired regression games are audited with no forfeits or unresolved
outcomes. This is a diagnostic interface capability, not a strength change.
The [session record](../artifacts/ratings/session-20261004-mate-proof.json)
retains the exact earlier local reference above; the new DLL is not separately
calibrated and the paired score does not establish an Elo rating.

The subsequent [stable endgame label ablation](STABLE-ENDGAME-LABELS.md) trains
two optional models on identical 64096 positions with matched initial states,
game splits and batch orders. Its **256 audited games** score **41.80%**
against frozen classical 0.7.9 and **55.47%** against its matched static model.
The latter's 95% family interval **48.86%..61.89%** includes 50%, and the
candidate fails quiet-node tactics and the classical confidence gate. Neither
model is promoted or calibrated. The [session record](../artifacts/ratings/session-20261004-stable-endgame.json)
retains the same exact **2319 / 2277..2360** reference above. Regression
scores and teacher-label fit are not new Elo measurements.

The subsequent [fresh deep paired-turn objective ablation](DEEP-TURN-PAIRS.md)
trains two models on identical **63826** rows with matched initialization,
splits and all batch streams. The candidate passes every tactical threshold
but its **256 audited games** score **42.97%** against classical and **41.41%**
against matched control, missing both playing gates. Longer confirmation is
skipped, with 32 reserved pairs unused; neither model is promoted or calibrated.
The [session record](../artifacts/ratings/session-20261004-deep-turn.json)
retains the exact **2319 / 2277..2360** local reference. These models and the
metadata-only rebuilt assembly do not inherit the calibrated binary's rating.

The frozen ordinary **Aster 0.7.4-feature-dev** has a provisional local estimate
of **2300**, with a **95% opening-family interval of 2265..2335**, on the
**SF19 UCI_Elo-setting equivalent at 30 ms/move, one thread, 64 MiB hash** scale.
This is a local reference-setting benchmark. Aster's FIDE, Chess.com, Lichess
and CCRL ratings remain **unestablished**. The preserved production 0.6.0 and
experimental proof/conversion scoring builds have not been rated by this run.

The [session record](../artifacts/ratings/session-20261004-calibration-v1.json)
identifies the exact binary and source, reference engine, options, hardware,
openings, controls, uncertainty and all six reports. Binary SHA-256:
`52439f58cf10a4a5dad8d4d48bf9db59db0a3f14b3c1c6216f79182b4a646d9a`.
The original [plan](../artifacts/research/rating-plan-v1.json) was declared
before match queries. No playing code changed or package was promoted in
response to the result.

## The bounded calibration

Five strength settings received 16 color-swapped opening pairs each. These
160 games selected the setting closest to a 50% score, with ties choosing the
lower setting. Screening chooses the reference; it does not assign a rating.

| SF19 setting | W | D | L | Screening score |
| ---: | ---: | ---: | ---: | ---: |
| 1320 | 31 | 0 | 1 | 96.88% |
| 1800 | 21 | 7 | 4 | 76.56% |
| 2300 | 12 | 5 | 15 | 45.31% |
| 2800 | 0 | 6 | 26 | 9.38% |
| 3190 | 0 | 5 | 27 | 7.81% |

Independent confirmation used **128 fresh openings**, both colors, against
the selected 2300 setting: **100 wins, 56 draws and 100 losses**, a **50%**
score in **256 games**. All **416** screening/confirmation PGNs passed
independent legal-history and terminal-outcome audits. There were no forfeits
or unresolved games. The Ryzen 5 7600X host runs Windows 11 with the .NET 8
runtime. Both engines used one thread, 64 MiB hash and Move Overhead 0;
the cap was 400 additional plies. Full histories start from standard chess.

The 144 teacher-balanced opening positions were frozen and split before
Aster queries. Exact positions from development datasets and five previous
opening suites were excluded. This is a local regression/calibration suite,
not the broad final held-out pool for a Stockfish-superiority claim.

## Model and uncertainty

The declared local model is
`R = reference_setting + 400 * log10(score / (1 - score))`.
At exactly 50%, the estimate equals the reference setting. It does not validate
the opponent dial's advertised numbers against any public rating pool.

The primary interval resamples the **94 opening families**, defined by the
first four legal UCI plies, retaining both colors and every pair in each
sampled family. A secondary interval resamples complete opening pairs. Both
use 20,000 draws and the declared seed 20261101. The primary score interval
is **44.92%..55.07%**. Family resampling addresses this opening dependence;
it does not measure uncertainty in the dial's calibration, hardware effects
or transfer to different controls and opponents.

All numeric gates pass: complete audited budget, no unresolved confirmation
games, finite primary interval no wider than 200 local units, and point and
interval within 1320..3190. Unfinished games would remain in pessimistic and
optimistic bounds and suppress the point estimate. Zero/one scores would
remain unbounded rather than being clipped into a fabricated finite rating.

The [Stockfish FAQ](https://official-stockfish.github.io/docs/stockfish-wiki/Stockfish-FAQ.html#the-elo-rating-of-stockfish)
explains that rating depends on opponents and match conditions. Its
strength-limited mode deliberately chooses weaker moves. The 2300 setting
is a development reference, and this result does **not** establish superiority
over full-strength Stockfish 19. Weak selection has no exposed random seed;
saved PGNs preserve observed games without promising bitwise replay.

## Reproduce and report

`scripts/run_rating.py` executes the frozen plan and refuses to overwrite an
existing run. `scripts/analyze_rating.py` validates provenance and applies
the declared selection, bootstrap and numeric gates; it also refuses to
overwrite an existing rating record. `scripts/verify_rating_result.py`
recomputes the saved result without modifying it.

```powershell
.venv/Scripts/python.exe scripts/verify_rating_result.py
.venv/Scripts/python.exe scripts/test_rating_analysis.py
```

Exact scripts, source, binaries, fixtures, reports, PGNs, audits and checks
are retained in the [experiment manifest](../artifacts/research/rating-experiment-v1-manifest.json).
Earlier unestablished session records remain intact. At every session end,
identify the rated version, named scale, control and uncertainty. A future
engine version needs fresh confirmation; this result cannot be transferred
automatically. Broaden controls and reference engines before making broader
rating claims. The main project goal remains improving actual play until
full-strength Stockfish superiority is supported by controlled evidence.
