# From correct KPK choices to completed wins

Complete legal games revealed a concrete limitation of the preceding KPK
experiment. At 5,000 nodes per move against its ordinary control, the KPK
build safely promotes in all 32 initially won pawn-side games, but checkmates
in only one. The other 31 games draw after promotion. Against pinned,
full-strength Stockfish 19 at the same node limit, it safely promotes in
16/16 but checkmates in only 2/16. Single-move WDL preservation therefore
missed the inability to finish queen-versus-king endings.

A new opt-in `ASTER_CONVERSION` build retains KPK evaluation and adds an
original exact mating-distance solver for king and queen/rook versus king.
Its guarded root policy selects moves that reduce mate distance. It completes
32/32 initially won pawn-side games against the control and 16/16 against
Stockfish, and retains all tested defender draws. These are selected endgame
diagnostics on an inspected fixture at equal nodes. They are not equal-resource
general-strength tests, Elo estimates or evidence of surpassing Stockfish.

## Original finite-state mating solver

Each piece type has 524,288 entries for the major-piece square, both king
squares and side to move. The stronger side is normalized to White by role;
piece movement is color-independent. Reject overlaps, adjacent kings and
strong-side-to-move positions where the defender is already in check.

Build a breadth-first mate attractor from legal defender checkmates at
distance zero. A strong-side predecessor becomes won on the first winning
child, with distance one plus the minimum child distance. A defender
predecessor becomes lost only after every legal reply is won, with distance
one plus the maximum. Generate reverse king and queen/rook edges directly
from Aster's attack maps. Legal capture of the major piece is a drawing
boundary and prevents the defender's pending-reply count from reaching zero.
Stalemates and states outside the attractor are draws. No imported code or
table files enter the engine runtime.

Both tables are built before UCI search in the experimental build. Evaluation
uses zero for theoretical draws or signed `2000 - distance` for guarded wins.
The score stays below mate-score encoding; search handles actual terminal
mates, repetition and the fifty-move rule. Winning overrides decline when
`HalfmoveClock + distance >= 100`, deliberately conservative even when the
last move could mate at clock 100.

Only at a winning strong-side root, after search's draw checks, constrain
legal root moves to successors with a smaller certified mate distance. Reject
successors already present in retained history, restore every speculative
move in `finally`, and intersect the caller's `searchmoves`. If that
intersection is empty, preserve the caller's requested moves and ordinary
search. The filter does not alter interior move generation, return an
adjudicated outcome or bypass cancellation/terminal logic.

With fresh history and a safe clock, the exact recurrence ensures a decreasing
mate distance against every defender reply. Prior arbitrary histories and
late clocks are separate concerns; the root guard can conservatively fall
back. Evaluation's theoretical result alone is not a history-aware game oracle.

## Independent verification

- All 1,048,576 queen/rook entries agree with the pinned development Syzygy
  WDL oracle, including invalid-state checks.
- Queen table: 345,404 wins, 23,048 draws, 155,836 invalid states and 364
  defender checkmates; maximum mate distance 20 plies.
- Rook table: 376,868 wins, 22,244 draws, 125,176 invalid states and 216
  defender checkmates; maximum mate distance 32 plies.
- Independently generated legal successors verify the exact minimum/maximum
  distance recurrence on every win: 4,836,600 queen and 4,387,408 rook edges.
- 8,192 runtime probes cover both colors, all eight board symmetries, fresh
  and late clocks, and unchanged FENs. Ninety-five actual search choices
  reduce mate distance; 95 explicit non-progress `searchmoves` remain honored.
  Infinite search stays responsive to `isready` and `stop`.
- The experimental build passes 49 C# tests and 17,491 independent rule/
  protocol checks. Original and quiet tactics remain 32/32 at depth 8; the
  fresh endgame diagnostic remains 13/16. The initial 48-pass/one-failure
  log is retained: raw neural outputs were correct, but the integrated
  evaluation test needed to include major-piece override precedence.

## Complete games and provenance

The new match runner accepts explicit `start_fen` entries with legal UCI moves,
validates nonterminal setups, rejects transposed duplicates and refuses to
overwrite match reports. PGNs preserve `SetUp` and `FEN`, including side,
halfmove clock and fullmove number. Moves after the setup retain complete
history; earlier repetition history is unknown and explicitly recorded.
The independent audit derives move roles from the actual starting side,
checks every search move and reconstructs terminal outcomes. Four regression
tests cover legacy opening lines, malformed/duplicate/terminal setups,
Black-to-move clocks/PGNs and rejection of corrupted search roles.

The 64 synthetic KPK setups were frozen before complete-game queries. Eight
strata cover win/draw, pawn/defender turn and rook/other pawn files. Winning
samples require conversion bounds of at least 18 plies. Previous KPK choices
and three tactical/endgame fixtures are excluded by normalized state. Legal
FENs, fresh clocks and independent WDL labels are validated and hashed.
The fix uses this inspected diagnostic; do not call its repeated results
held-out confirmation.

The initial control diagnostic totals 128 games: 1 win, 127 draws and no losses.
With mating knowledge it totals 34 wins, 94 draws and no losses, including
two wins where the control fails to defend an initially drawn position.
Both candidate and control each have separate 64-game Stockfish diagnostics
on the first 32 setups. Preserve actual checkmates separately from safe
promotions, and retain every repetition/fifty-move draw and theoretical WDL
degradation. No game is adjudicated as won merely for promoting or probing
theoretical WDL.

The longer equal-time development regression totals 14 wins, 29 draws and
21 losses in 64 v5 games at 100 ms per move: 44.53%, with exploratory paired
interval 35.94%..53.13%. All games complete and pass independent auditing,
with no forfeits or unresolved results. This negative point estimate is
inconclusive, and does not justify promoting the change. It remains opt-in;
production 0.6.0 remains preserved. All six complete-game experiments total
512 audited games, with their distinct conditions and inspected fixtures
retained rather than pooled into a rating.

The follow-on [native strategy proof mode](STRATEGY-PROOFS.md) explains choices
and exports verifiable strategy graphs. Its core engine files and fixed-node
outputs agree with the frozen conversion engine; its new interface is a
separate capability. See [measured progress](../artifacts/PROGRESS.md).

## Reproduce

```powershell
dotnet build Aster.sln -c Release -p:DefineConstants=ASTER_CONVERSION
dotnet run --project tests/Engine.Tests -c Release --no-build
dotnet publish src/Engine/Engine.csproj -c Release -r win-x64 --self-contained false -p:PublishSingleFile=true -p:DefineConstants=ASTER_CONVERSION -o artifacts/publish/conversion-local
artifacts/publish/conversion-local/Aster.exe majordump queen artifacts/validation/major-queen-local.bin
artifacts/publish/conversion-local/Aster.exe majordump rook artifacts/validation/major-rook-local.bin
.venv/Scripts/python.exe scripts/verify_major_mates.py artifacts/validation/major-queen-local.bin --output artifacts/validation/major-queen-local.json
.venv/Scripts/python.exe scripts/verify_major_mates.py artifacts/validation/major-rook-local.bin --output artifacts/validation/major-rook-local.json
```

Use new output paths for every match. The diagnostic UCI command `major`
reports `info string major win|draw <strong-side:0-white,1-black> <plies>` or
`unsupported`; it does not enable evaluation in an ordinary build. Table
exports refuse overwriting. Python, python-chess, Syzygy and Stockfish are
development tools only. The runtime requires only .NET.
