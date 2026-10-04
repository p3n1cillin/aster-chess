# Aster development

The project goal is an independent chess engine that eventually surpasses
Stockfish in controlled playing-strength tests. Do not claim that goal has been
achieved without evidence. Do not implement the engine as a Stockfish wrapper.
Stockfish and python-chess are development tools only, never runtime dependencies.

## Build and verification

- `dotnet build Aster.sln -c Release`
- `dotnet run --project tests/Engine.Tests -c Release --no-build`
- `.venv/Scripts/python.exe scripts/verify.py` on Windows, or the corresponding
  environment Python on other platforms.
- `dotnet src/Engine/bin/Release/net8.0/Aster.dll bench 7`

Keep UCI stdout protocol-clean and responsive to `isready`/`stop` during search.
Every speculative move must be undone, including exceptions and cancellation.
Changes to move generation require perft and independent differential checks.
Search/evaluation changes require tactical checks and paired regression matches.
Keep all terminal game rules correct at the quiescence horizon as well as the root.

Preserve match reports and PGNs. Pin external engine versions and record binaries,
source fingerprints, options, openings, time controls and unresolved games.
Never infer Elo or Stockfish superiority from a few games or from search speed.
See `ROADMAP.md` for the research direction and `artifacts/PROGRESS.md` for results.
