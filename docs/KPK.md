# Exact king-and-pawn endgame experiment

Aster has an original finite-state solver for king and pawn versus king
(KPK). The opt-in `ASTER_KPK` build consults its generated table before either
classical or neural evaluation. The ordinary build and preserved 0.6.0
production package retain their previous evaluation. This experiment does not
establish general strength or superiority over Stockfish.

## Algorithm and boundaries

Normalize the pawn to White on files a-d and ranks 2-7. There are 196,608
entries: 24 pawn squares, two king squares and the side to move. Reject piece
overlap, adjacent kings and positions where the side that just moved left its
king attacked. Compute a win attractor: the pawn side needs one winning legal
successor; the defender needs every legal successor to lose. Safe queen or
rook promotion is a winning boundary, immediate capture and stalemate are
draws, and unresolved cycles after convergence are draws.

The solver generates its own table from Aster's attack maps; it imports no
Stockfish code or external table data. A lazy initializer runs before UCI
search in the experimental build. Both colors and all pawn files normalize
to the same table. The runtime requires only .NET, with no Python, teacher
engine or Syzygy files.

For each win the solver retains a conservative upper bound to safe promotion
or pawn checkmate, at most 38 plies. This is not optimal distance to conversion,
mate or a zeroing move. Draws evaluate to zero. Wins use a signed score of
`400 - bound`, below the ordinary value of a surviving rook or queen. When
`HalfmoveClock + bound >= 100`, a winning probe declines to override normal
evaluation. The guard deliberately ignores intermediate pawn-move clock
resets and may therefore decline usable wins. Neither probe adjudicates a
game nor bypasses search terminal, repetition or rule-50 handling. Repetition
history can still invalidate a theoretical winning plan.

This is a KPK evaluation aid, not general tablebase support or an exact root
move selector. Search still chooses moves. Raw neural accumulators remain
unchanged; KPK takes precedence only at final experimental evaluation.

## Independent evidence

- Independent Python/Syzygy classification agrees on all 196,608 normalized
  entries: 30,932 invalid, 111,282 wins and 54,394 draws. WDL assumes a fresh
  reversible clock; clock guards are checked separately.
- A separate certificate examines 772,036 legal successor edges from all
  111,282 wins, including 51,084 promotion edges. Every pawn-side win has a
  strictly decreasing strategy against every defender reply, with queen,
  rook, bishop and knight promotion outcomes independently checked.
- 4,096 runtime checks cover pawn color, file reflection, fresh/late clocks,
  unchanged board state and responsive `isready`/`stop` during search.
- On a frozen 256-position sample at 5,000 nodes per position, the candidate
  preserves oracle WDL in 256/256 choices, versus 246/256 for 0.6.0. The sample
  has 128 pawn-side wins and 128 defender-side draws. This targeted regression
  does not measure conversion speed or general playing strength.
- The experimental build passes 46 C# tests and 17,491 independent
  rule/protocol checks. Original and quiet tactics remain 32/32 at depth 8;
  the separate fresh endgame diagnostic remains 13/16.

The initial integration run had three failures because existing neural-only
tests assumed they also controlled final KPK evaluation. Corrected tests
preserve raw network assertions, exercise neural output/cap behavior with two
pawns, and add an explicit KPK precedence test. The initial failure log is
retained alongside the passing run.

The paired-game plan was frozen before observing move-choice or match
results. Against frozen 0.6.0, 64 color-swapped games at 30 ms per move on
the first 32 v5 openings finish 23 wins, 25 draws and 16 losses: 55.47%, with
exploratory paired opening-cluster interval 48.44%..62.50%. All games pass
the independent PGN audit, with zero forfeits or unresolved games. Three
mainlines reach KPK, covering 33 positions; searched variations can also
reach it, and the match score cannot be attributed to this feature.

The ordinary build passes 45 C# tests, the required 1,614 differential checks,
and an additional 17,491-check native run. Its required depth-7 benchmark
retains 146,772 nodes. The KPK candidate searches 146,766 nodes, a six-node
change; timing and node counts do not establish stronger play. Keep this
implementation opt-in pending wider endgame and longer-control evidence.
See [measured progress](../artifacts/PROGRESS.md) and
[complete provenance](../artifacts/research/kpk-experiment-manifest.json).

## Reproduce

```powershell
dotnet publish src/Engine/Engine.csproj -c Release -r win-x64 --self-contained false -p:PublishSingleFile=true -p:DefineConstants=ASTER_KPK -o artifacts/publish/kpk-local
dotnet build Aster.sln -c Release -p:DefineConstants=ASTER_KPK
dotnet run --project tests/Engine.Tests -c Release --no-build
artifacts/publish/kpk-local/Aster.exe kpkdump artifacts/validation/kpk-local.bin
.venv/Scripts/python.exe scripts/verify_kpk.py artifacts/validation/kpk-local.bin --output artifacts/validation/kpk-local-oracle.json
.venv/Scripts/python.exe scripts/certify_kpk.py artifacts/validation/kpk-local.bin --output artifacts/validation/kpk-local-certificate.json
.venv/Scripts/python.exe scripts/verify_kpk_choices.py artifacts/validation/kpk-local.bin --candidate artifacts/publish/kpk-local/Aster.exe --baseline artifacts/publish/baseline-0.6.0/Aster.exe --output artifacts/validation/kpk-local-choices.json
```

The preserved match command is:

```powershell
.venv/Scripts/python.exe scripts/match.py --engine artifacts/publish/kpk-dev/Aster.exe --opponent artifacts/publish/baseline-0.6.0/Aster.exe --source-manifest artifacts/research/kpk-source/manifest.json --opponent-source-manifest artifacts/research/king-context-release-source/manifest.json --pairs 32 --movetime 0.03 --openings tests/fixtures/openings-v5.json --output artifacts/matches/kpk-local-regression
```

Preserve existing binary, dump, report and source snapshot paths. Development
oracle files are pinned by `tools/syzygy-development-v1/manifest.json` to the
python-chess v1.11.2 test data and verified by SHA-256. Its
[WDL documentation](https://python-chess.readthedocs.io/en/latest/syzygy.html)
describes the fresh-clock assumption. Aster never reads these files.

Ordinary builds need no compile flag. The diagnostic UCI command `kpk` emits
`info string kpk win <bound>`, `draw 0` or `unsupported`; its existence does
not mean the ordinary build uses KPK evaluation. `kpkdump <path>` is a separate
command-line export and refuses to overwrite a prior table.
