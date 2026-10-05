# Play Aster and watch the search

On Windows, run from the repository:

```powershell
./scripts/play.ps1
```

Open **http://127.0.0.1:5188**. The launcher builds Release, starts a hidden local
server, and keeps its logs and process record in the ignored `.aster-local`
directory. Running it again reuses the same server. Stop it with
`./scripts/play.ps1 -Stop`; use `-Port 5189` if you need another port.

The cross-platform equivalent is:

```text
dotnet build Aster.sln -c Release
dotnet src/Play/bin/Release/net8.0/Aster.Play.dll
```

The .NET 8 SDK includes the ASP.NET runtime needed by the host. The engine and
interface have no Python, Stockfish, external JavaScript, model download or
online service dependency.

## Playing

Click or tap a piece, then one of its legal destinations. Choose your promotion
piece when prompted. **New game** selects White or Black and a reply budget of
1, 3, 8 or 15 seconds. Aster automatically replies using its independent native
search and the default classical evaluator, one thread and a 64 MiB hash table.

- **Move now** interrupts Aster and plays its best available legal move.
- **Take back** removes your previous move and its reply, including a pending
  reply. If you play Black, Aster's opening stays on the board.
- **Analyze** searches the current position without playing a move. **Stop
  analysis** leaves the game position unchanged.
- **Flip board** changes perspective. Move-history buttons replay game positions;
  **Live** returns to the playable position. Lenses pause during replay.
- **Load position** starts from a valid six-field FEN with your current color and
  reply budget. FEN has no earlier repetition history.
- **Download PGN** preserves native SAN moves and the starting FEN where needed;
  **Copy FEN** copies the position currently displayed on the main board.

The host maintains one game shared by its open tabs. Games live in memory;
download your PGN before restarting the host or starting another game. The play
host automatically claims a draw at threefold repetition or 100 reversible
half-moves; checkmate takes precedence. Stalemate and recognized insufficient
material also end the game.

## Reading the visualization

**Inside Aster** shows evaluation from White's perspective, completed search
depth, deepest visited ply, nodes, speed and elapsed time. The chart records the
score at every completed depth. Centipawns are an evaluation, not a probability.
Terminal results override the headline score. The **position fingerprint**
retains static evaluation of the current game position separately from the last
search's score, which may belong to the position before Aster's reply.

**Expected continuation** is the latest completed principal variation. Click a
move to inspect its predicted board on the miniature board. **Follow live**
returns to the search stream. A predicted line is not a forced strategy or a mate
certificate.

**Live searched position** follows actual positions inside the search, sampled
about 12 times per second. These frames contain the actual current FEN and path
from the search root. A `null` path entry is a hypothetical pass used by null-move
pruning: it changes turn and clears en passant without advancing either game
clock. Counters count all node visits, including repeated positions; they show
main search, quiescence, beta and transposition-table cutoffs, null probes and
reductions. The last 48 branch samples are retained in the browser and the most
recent 12 are available to inspect. Sampling does not expose the entire search
tree. It avoids streaming millions of frames per second.

**Root moves** shows each visited root move's latest attempt at the current
depth, nodes spent on that attempt and score from the searched side's perspective.
`≤` is an upper bound, `≥` a lower bound; these are not ranked MultiPV evaluations.
"Window exact" means an exact alpha-beta result for that completed attempt.
"Latest PV" refers to the last fully completed depth, which can differ from the
depth currently underway. A cancelled attempt is labelled "unfinished".

**Search visits** colors squares by the destination of the last move leading to
each visited node. White/Black control counts geometric attacks: pinned pieces
and friendly slider blockers are included. Control is not a legal-capture map.
Static piece values plus squares, other evaluation terms and tempo sum to the
static score; material balance is a separate descriptive measure.

## Verification and limits

Native observer tests compare trace-enabled and trace-disabled searches at fixed
node limits, replay every sampled path, check cancellation/root restoration and
exercise a failing observer. Game tests cover both colors, replies, takebacks,
stop, analysis, special-move SAN and terminal results. Run them with:

```text
dotnet run --project tests/Play.Tests -c Release --no-build
```

`scripts/smoke_play.py` tests the real HTTP/SSE host and independently replays
game moves, native SAN, PVs, sampled branches and PGN using development-only
python-chess. It also checks event ordering, assets, rejected requests, stop and
playing Black. Both checks run in the Windows/Linux CI matrix.

The optional observer records events without changing search decisions or
evaluation. Recording and rendering still cost time; equivalence at a fixed node
budget does not imply identical timed replies. The visual build and its 1..15
second reply budgets have no established rating. The last calibrated local
rating remains attached to its exact historical binary; see [rating](RATING.md).
This interface does not establish superiority over Stockfish.
