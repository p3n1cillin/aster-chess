# Fitted geometric threat correction

This experiment tests a small original classical correction for attacked
material. Seven features count loose pawns/minors/rooks/queens and defended
minors/rooks/queens attacked by lower-valued pieces. A piece is loose when
attacked by the opponent and undefended by its own side. The lower-value class
excludes loose pieces to avoid counting them twice. Minor pieces have equal
value for classification; kings contribute control but are never scored targets.
Attacks are geometric, including pinned pieces and occupied target squares.
These are evaluation features, not proof of profitable legal captures.

White-minus-black weaknesses are phase-interpolated using separate middlegame
and endgame weights. The correction is added after the ordinary classical
score's interpolation, with integer truncation toward zero, before tempo and
the final score clamp. The search, move generation and terminal rules are
unchanged. The experimental build uses `ASTER_THREATS`; the ordinary build
collects no extra attack maps in its evaluation path and retains its scores.

## Training and held-out evidence

Use only the 50,000 original played positions in the preserved 60,000-position
static-label dataset. Keep the existing whole-game split: 45,288 training
positions and 4,712 held-out positions. Optimize the earlier sigmoid/robust
centipawn objective for 500 fixed Adam updates with a small weight penalty.
Clamp weights to 0..150 cp. Neither held-out errors nor matches choose weights
or iteration count. Export integer weights and retain all extracted features,
fitter sources, dataset digest and fit report.

| Feature | Middlegame cp | Endgame cp |
| --- | ---: | ---: |
| Loose pawn | 12 | 68 |
| Loose minor | 63 | 35 |
| Loose rook | 34 | 27 |
| Loose queen | 40 | 23 |
| Defended minor attacked by pawn | 38 | 13 |
| Defended rook attacked by pawn/minor | 23 | 21 |
| Defended queen attacked by pawn/minor/rook | 28 | 12 |

Overall held-out MAE improves from 140.70 to 137.42 cp. On the 1,877 positions
with a nonzero net threat feature it improves from 158.65 to 150.42 cp;
the other 2,835 positions have unchanged scores. Geometric threats are therefore
present in the existing training data, rather than absent. The new features
partly explain residual teacher error, but better fit does not establish strength.

## Verification and match protocol

Both builds pass all 43 tests, including move/undo/search rules, color/rank
symmetry and direct loose-versus-defended threat cases. Python attack masks and
integer correction agree with the experimental C# bitboards on 1,842 positions.
The candidate passes 17,491 independent rule/protocol checks. The ordinary
control preserves all 60,000 static scores and all moves, scores and 5,155,458
nodes in 64 depth-8 searches against frozen 0.6.0. Its depth-7 benchmark remains
146,772 nodes; the threat candidate uses 159,912. Search speed is not strength.

The candidate solves 32/32 original tactics and 30/32 quiet tactics at depth 8;
the baseline solves 32/32 quiet tactics. Preserve those misses. The correction
is ineligible for promotion under that tactical gate.

Still run the required paired regression: 64 games using the first 32 entries
of a new frozen v5 opening suite, 30 ms per move, one thread and 64 MiB hash.
The suite uses a new seed, excludes exact positions in all previous opening
suites and both development datasets, and records the pinned teacher and
generation/balance-check budgets. Opening-family overlap can remain. Finish
training and verification before timed games. Save all PGNs and reports with
binary/source/options/opening/time-control fingerprints and audit every game.
This is a development test, not the final Stockfish-superiority experiment.

## Match outcome and decision

The 64-game v5 match finished **24 wins, 23 draws and 17 losses**, a 55.47%
score, with exploratory opening-cluster interval **45.31%..64.84%**. All games
completed and passed independent PGN audits, with no forfeits or unresolved
results. The positive point estimate is inconclusive; no Elo is inferred.
The quiet-tactic regressions independently rule out promoting this correction.
Production 0.6.0 retains its original binary and ordinary source scoring stays
unchanged. The correction remains an explicitly enabled research build only.

The two misses are `tactic-012` (Kf6-e7 instead of Kf6-g7) and `tactic-026`
(Kg6-g7 instead of Rg5-h5), both sparse endgames. These are also misses of the
earlier static-label neural model. This common result motivates fresh endgame
coverage and outcome/search-target diagnostics; it does not justify tuning
weights to those two known fixture answers. Investigate pawn races, opposition,
zugzwang and defended-piece legality before retaining coarse threat penalties.

The fresh fixture contains 64 legal positions, independently audited against
the two training datasets and four older opening suites. Its SHA-256 is
`e63c68d4024428bef2f84a4289db06c4aee70e60aa9f081cf437d2a6d237c46e`.
Candidate and control have separate immutable 20-file source snapshots and
recorded compile flags. No Stockfish code or weights enter the engine runtime.

[Complete provenance](../artifacts/research/geometric-threats-experiment-manifest.json)
binds the exact fitter, extracted training features, data, candidate/control
builds, checks, fresh fixture, all PGNs, audit and match analysis.
