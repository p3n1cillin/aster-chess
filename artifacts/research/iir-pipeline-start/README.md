# Aster

Aster is an independent chess engine written in C# for .NET 8. The project aims
to surpass Stockfish in measured playing strength. The current engine is an
early, working foundation and is far below that target: version 0.6.0 lost all
eight games in its full-strength Stockfish 19 smoke match. Detailed progress,
regressions and preserved reports are in [measured progress](artifacts/PROGRESS.md).

Source and research history are maintained in the private
[GitHub repository](https://github.com/p3n1cillin/aster-chess).
See [version control](docs/VERSION-CONTROL.md) for tracked evidence and exact-byte preservation.

## Build and run

Install the .NET 8 SDK, then run from this directory:

```powershell
dotnet build Aster.sln -c Release
dotnet src/Engine/bin/Release/net8.0/Aster.dll
```

The engine starts in UCI mode. For a manual test, enter:

```text
uci
isready
position startpos moves e2e4 e7e5
go depth 6
quit
```

Wait for `bestmove` before entering `quit`. Search is asynchronous; `quit` or
`stop` interrupts the current search. `go movetime 1000` searches for up to one
second, subject to the configured move overhead.

On Windows, a chess GUI can load
`src/Engine/bin/Release/net8.0/Aster.exe`. Keep its sibling DLL, runtimeconfig
and deps files with the executable. The .NET 8 runtime must be installed.
For a single executable that uses the installed runtime:

```powershell
dotnet publish src/Engine/Engine.csproj -c Release -r win-x64 --self-contained false -p:PublishSingleFile=true -o artifacts/publish/win-x64
```

## Engine capabilities

- Bitboards, legal move generation, FEN, all standard castling rules, en passant,
  and all four promotion choices.
- Incremental Zobrist hashing and tapered classical evaluation, pawn structure,
  passed pawns, bishop pairs, mobility, rook files and basic king safety.
  Shared attack maps avoid repeated attack queries while preserving scoring.
  See [evaluation research](docs/EVALUATION.md) for checks and rejected experiments.
- Iterative deepening, aspiration windows, principal variation search,
  check extensions, transposition table, killers and history move ordering,
  null-move pruning and late-move reductions.
- Guarded shallow reverse-futility pruning, with stalemate and pawn-endgame
  safeguards. Retained after paired regression matches and tactical checks.
- Quiescence search with full check evasions and stalemate detection; guarded
  horizon transposition caching, with rule-50 keys and repetition safeguards; legal
  static exchange evaluation to order trades and prune losing non-checking
  captures at the horizon.
- Repetition and rule-50 draw handling, conservative insufficient-material
  detection and mate-distance scores. Checkmate takes precedence over a
  rule-50 draw. Search cycles are scored as draws; game-history threefold
  requires three occurrences.
- Fast legal-move existence using absolute-pin detection, with complete
  fallback checks for king moves, castling, en passant and check evasions.
- UCI depth, node, move-time and clock limits, `searchmoves`, `go infinite`,
  and interruptible search. Options: `Hash`, `Threads` (currently 1 only),
  `Move Overhead`, `Clear Hash`, `EvalFile`.

An optional, independent neural evaluator and training pipeline are available.
Current source also supports experimental turn-aware formats 5/6 and squared
activation formats 7/8;
the preserved 0.6.0 package supports formats 1..4. See
[turn-aware research](docs/TURN-AWARE.md) for validation and rejected models.
Squared activation research is documented in
[squared evaluation experiments](docs/SQUARED-ACTIVATION.md).
Static-label and initialization checks are recorded in
[label experiments](docs/LABEL-INITIALIZATION.md); direct supervision of
opposite-turn score differences is documented in [paired training](docs/PAIR-LOSS.md).
An optional compile-time classical threat experiment and a fresh opening suite
are documented in [geometric threats](docs/GEOMETRIC-THREATS.md); the correction
is disabled in ordinary builds after quiet-tactic regressions.
Fresh endgame label coverage and a separately frozen move suite are recorded
in [endgame diagnostics](docs/ENDGAME-DIAGNOSTIC.md).
An original, opt-in king-and-pawn solver is documented in
[KPK endgame research](docs/KPK.md), with exhaustive oracle validation and
independent move-choice checks. It is disabled in ordinary builds.
Complete-game conversion failures and the original opt-in queen/rook mating
solver are documented in [endgame conversion](docs/ENDGAME-CONVERSION.md).
Native explanations and complete, independently checkable queen/rook mating
strategies are available through [proof mode](docs/STRATEGY-PROOFS.md).
An opt-in deferred-capture optimization preserves deterministic search traces
but fails its warm timing and longer-control regression gates; it remains
disabled in ordinary builds. See [deferred scoring](docs/DEFERRED-CAPTURES.md).
The matched 0.7.6-q-evasion development build has a [provisional local rating](docs/RATING.md)
of **2319 (95% interval 2277..2360)** on the SF19 UCI_Elo-setting-equivalent
scale at 30 ms per move, one thread and 64 MiB hash. Public Elo and the preserved
production package's rating remain unestablished; session reports identify
the rated version, scale and conditions explicitly.
The [quiescence evasion optimization](docs/QUIESCENCE-EVASIONS.md) is enabled
in ordinary 0.7.6-feature-dev source after passing the frozen gates and auditing
all 576 regression/confirmation games. It preserves 416 complete search traces
and shows a 5.29% warm speed gain. The ordinary build repeats those traces;
the rating remains attached to the exact matched candidate. A rating gain
over the previous 2300 estimate is unproven.
The next opt-in [unseeded secondary search experiment](docs/INTERNAL-REDUCTIONS.md)
passes correctness and tactical checks; its frozen 640-game regression has
pending results. It remains disabled in ordinary builds.
Version 0.6.0 adds king-region-conditioned features, lazy accumulator rebuilds
and vectorized integer output, retaining compatibility with earlier Aster models.
The tested trained models regressed in matches, so the classical evaluator
remains the default. See [neural experiments](docs/NEURAL.md) for the format,
inference checks, reproduction commands and results, and
[king-context research](docs/KING-CONTEXT.md) for the newer architecture.
Use `EvalFile` to select
a model explicitly or `<classical>` to switch back.

It does not yet support Chess960, pondering, MultiPV, general tablebases or parallel
search.

## Verify correctness

The dependency-free C# test runner covers reference perft positions, incremental
state, special moves, terminal rules, tactics, time limits and cancellation:

```powershell
dotnet run --project tests/Engine.Tests -c Release
```

The independent Python verifier compares legal moves and FENs against
python-chess, compares reference perft counts, validates principal variations,
and exercises UCI through both a raw client and python-chess's UCI client:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe scripts/verify.py
```

Python and python-chess are only needed for development tests and match tools.
The engine itself has no third-party runtime dependency beyond .NET.

## Measure progress

```powershell
dotnet src/Engine/bin/Release/net8.0/Aster.dll perft 5
dotnet src/Engine/bin/Release/net8.0/Aster.dll bench 7
.\.venv\Scripts\python.exe scripts/benchmark.py --depth 7 --output artifacts/benchmarks/current.json
.\.venv\Scripts\python.exe scripts/fetch_stockfish.py --tag sf_19
.\.venv\Scripts\python.exe scripts/match.py --pairs 8 --movetime 0.1 --output artifacts/matches/stockfish19
```

The fetch script uses the official release, verifies GitHub's published SHA-256,
and retains its license/source archive locally. The match tool swaps colors for
each opening, gives both engines one thread, equal Hash and equal time per move,
and writes PGN plus a report with engine identities and binary fingerprints.
Full-strength Stockfish is the default. An alternative engine or a previous
Aster build can be passed with `--opponent path/to/engine`.

For a broader regression sample, use `--openings tests/fixtures/openings-v1.json`.
This frozen suite has 64 distinct positions after 16 legal plies, sampled from
near-best teacher continuations and checked within 80 centipawns of equality
at a stronger budget. Training positions were excluded. The match tool validates
each complete move history, rejects transposed duplicates, pins the suite hash
and uses each entry once; request at most 64 pairs. Omitting `--openings` retains
the original eight-line smoke suite, repeating it for larger requests.
The generator is `scripts/generate_openings.py`; its seed, budgets, teacher and
exclusions are recorded in the fixture. Bounded teacher checks do not prove
that openings are equal or statistically independent.

Games stopped at the move cap stay unresolved and are excluded from W/D/L.
Crashes, illegal moves and timeouts are recorded as forfeits and fail the run.
Small samples are smoke checks; they cannot establish a reliable rating or
superiority. `--nodes` is available for deterministic experiments, but equal
nodes are not an equal-time strength comparison.

Diagnostic UCI extensions are `legal`, `d` (FEN), `eval` and `perft <depth>`.
From 0.5.0, `haslegal` reports whether any legal move exists. The verifier checks
it independently; `--setups 2000` adds random valid material configurations.
An optional compile-time profiler is documented in [search profiling](docs/PROFILING.md).
The CLI `bench` emits JSON lines for five fixed positions and an aggregate.
`scripts/audit_match.py <output-prefix>` independently checks saved PGN outcomes
and the report's win/draw/loss counts.
`scripts/analyze_match.py <report.json>` adds exploratory confidence intervals
by resampling whole opening clusters. These are regression aids, not the final
predeclared test of the project goal.
New match reports retain per-move search depth, nodes, scores and measured time;
analysis summarizes those diagnostics by engine. For a fixed-depth comparison
with legal-PV checks across the 64-position suite:

```powershell
.\.venv\Scripts\python.exe scripts/compare_search.py --opponent artifacts/publish/baseline-0.3.1/Aster.dll --depth 6 --output artifacts/benchmarks/comparison.json
```

See [the research roadmap](ROADMAP.md) and [measured progress](artifacts/PROGRESS.md).

## References and external tools

- [UCI protocol, Shredder Chess](https://www.shredderchess.com/chess-info/features/uci-universal-chess-interface.html)
- [Official Stockfish download documentation](https://official-stockfish.github.io/docs/stockfish-wiki/Download-and-usage.html)
- [Pinned Stockfish 19 release](https://github.com/official-stockfish/Stockfish/releases/tag/sf_19)
- [python-chess](https://github.com/niklasf/python-chess), a separately licensed
  development dependency (GPL-3.0-or-later).

Stockfish is a separately licensed GPL-3.0 tool downloaded into ignored
`tools/stockfish/`. Aster's production code calls neither Stockfish nor
python-chess. No Stockfish source, neural weights, or opening data are embedded
in the engine.
