# Rust foundation and migration — 18 October 2026

The user requested Rust-only development and permitted using any strong engine
source. Active engine and web-host builds now use Cargo. The original C# source
and all earlier research evidence remain historical; no current launcher or CI
job builds them. The earlier Berserk/C++ exploration was superseded before any
C/C++ foundation build was performed in this continuation.

## Source and trained knowledge

The native source foundation is **Viridithas 20.0.0**, commit
`0631113e2215714c54d397cce9a8caebc5e6f8ee`. This exact release is MIT licensed;
later master has different licensing and was not imported. Upstream notices,
README, attack/cuckoo embeds and original file fingerprints are retained in
`crates/engine`. Original Aster modifications are GPL-3.0-or-later. The trained
`sandhi-s2-b200` v109 network is CC0-1.0; its full SHA-256, immutable URL and
pinned license source are in `crates/engine/NETWORK.json`.

This adopts a strong source search and trained evaluation, rather than merely
renaming the former C# engine or invoking a third-party engine binary. The Rust
executable contains its own imported-and-modified board, move generation,
search, inference, proof solver and web host. No Stockfish, python-chess or C#
engine is called by the product. Optional C tablebases and C zstd build paths
are disabled; Rust `ruzstd` performs runtime decompression. Stockfish and
python-chess remain development references and independent test tools.

Aster's bounded AND/OR mating certificates were ported to Rust. Child board
copies isolate speculative proof moves during limits or cancellation. Complete
certificates cover every defense and only real checkmate leaves. Native Rust
board/SAN/PGN logic supports the visual game. The presentation assets are
embedded HTML/CSS/JavaScript, with no frontend build or external runtime service.

The source foundation additionally fixes terminal precedence before pruning and
quiescence stand-pat/TT cutoffs, including stalemate and checkmate at draw clocks;
retains terminal FEN clocks instead of silently resetting them; validates
certificate/game roots; and answers UCI readiness during active search. These
are recorded correctness changes, not an assertion that the fork preserves
every upstream search result or playing rating.

## Frozen playing screen

The [predeclared plan](../artifacts/research/rust-foundation-plan-v1.json) precedes
candidate queries. Sixty-four fresh, color-swapped opening parents were generated
with pinned Stockfish 19, checked independently and excluded from 46 prior suites.
Separate 32-position partitions screen original Aster and full-strength Stockfish.
The source/weight/compiler manifest is
[the v1 snapshot](../artifacts/research/rust-source-v1/manifest.json).
Its standalone binary SHA-256 is
`2bdacdad9ad9c4df7e33e0ef033c17011308636b6b93c3704483e2d4164c2cc9`.

All games request 30 ms/move, one thread and 64 MiB hash. Move overhead is zero
where supported; the Rust engine exposes no overhead option. There are no books,
tablebases, evaluation adjudications or resignations. Full histories, actual
elapsed/search telemetry, options/defaults, binary and source fingerprints, PGNs
and unresolved results are retained. The cap is 400 additional plies. Runs use
the same Ryzen 5 7600X desktop without CPU affinity; these are local short-control
screens, not isolated-laboratory or public-rating measurements.

| Frozen Rust foundation v1 opponent | Wins | Draws | Losses | Score |
| --- | ---: | ---: | ---: | ---: |
| Original Aster visual-play-dev | 63 | 0 | 1 | 98.44% |
| Full-strength Stockfish 19 | 1 | 39 | 24 | 32.03% |

All 128 games pass independent PGN/rules audits, with no forfeits or unresolved
games. The predeclared first-four-ply family bootstrap has 29 families per screen,
20,000 samples and seed 20261019. The intervals are 95.0%..100% against original
Aster and 25.81%..37.90% against Stockfish. This is evidence of a much stronger
foundation than original Aster under these conditions, and a remaining gap to
Stockfish. It is not an absolute/public Elo or a universal superiority result.

## Safety and visualization follow-up

Current **0.9.1** corrects a maximum-depth PV scratch access that could panic,
keeps aspiration fail-high/fail-low bounds off the completed-evaluation graph,
converts mate-in-moves correctly for the display, and reports terminal scores
consistently. The [separate safety plan](../artifacts/research/rust-safety-plan-v2.json)
and its addendum precede its paired regression. The completed v1 screens are
preserved and are not extended to rescue a strength claim.

All 32 fresh depth-nine results match v1 in completed depth, nodes, score and
full PV. Release and debug native suites each pass **130 tests**, including
terminal precedence, cancellation/limits, root validation and the explicit
maximum-depth regression. Independent checks cover **2630 positions**, **14 perft
cases**, live branch/null replay, observer-on/off equivalence and readiness during
infinite search. HTTP/SSE tests independently replay legal moves, SAN, PVs,
branches and PGN, including undo, stop, Black play, geometry and terminal scores.
All **27** legacy general-material/castling fixtures re-export in Rust and pass
independent verification across **122** certified positions. Failed intermediate
logs and diagnostic snapshots are preserved alongside the final records.

The separately planned safety-v2 regression finished **3 wins, 25 draws and
4 losses** against foundation-v1 over 16 color-swapped opening pairs. Its
family-bootstrap score interval is **40.0%..56.67%**: an inconclusive engineering
check, with no strength increase claimed. Together the three audited matches
contain **160 games**, with no forfeits or unresolved games.

The final **play-v3** build additionally queues an immediate "Move now" request
while its worker starts, so the engine turn cannot be stranded. This changes
the host only. All 32 completed depth-nine outputs, including nodes and full PV,
match safety-v2 exactly. Its standalone binary SHA-256 is
`246b2c6c1dbb6b98a0d90013fedb47b54b95317992593d98cc486ef66ef91fdb`;
[the v3 manifest](../artifacts/research/rust-source-v3/manifest.json) freezes its
source, compiler and weights. Final tactical gates solve **32/32** original,
**28/32** quiet and **16/16** endgame positions at their recorded limits.
Additional perft checks pass start depth 5 (4,865,609), Kiwipete depth 4
(4,085,603) and rook endgame depth 5 (674,624).

The Windows browser checks cover both colors, actual moves, mobile layout,
live telemetry, a correctly displayed mate-in-two and a downloaded proof, with
no JavaScript errors. The source
archives, paired reports and screenshots keep these checks auditable. Current
CI builds and tests Rust on Windows and Linux; its final run status is recorded
with the session evidence when complete.

## Remaining work

The Rust version is uncalibrated: no historical rating is transferred from C#,
from the upstream project's rating lists or from a small regression match.
The prior calibrated C# reference remains 2319 (95% interval 2277..2360) on the
local SF19 UCI_Elo-setting scale at 30 ms, one thread and 64 MiB hash.

The general proof CLI and browser proof flow are native Rust. The former C#
background UCI `explain` protocol, specialized queen/rook strategy-table generators
and experimental C# neural formats remain historical research and are not active
Rust features. Extend native explanations and certificate browsing, calibrate
the exact new binary at multiple controls, and investigate compatible newer
neural knowledge and individually tested search improvements. Surpassing
full-strength Stockfish remains an unachieved project goal.
