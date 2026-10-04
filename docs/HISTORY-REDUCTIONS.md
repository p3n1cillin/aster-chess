# History-guided late-move reduction experiment

Aster 0.5.1 orders quiet moves using successful quiet-cutoff history and reduces
late quiet moves according to depth, legal move count and principal-variation
status. Captures, promotions, check evasions and checking moves are excluded.
If a reduced search raises alpha, a full-depth zero-window search follows; an
intermediate result also receives a full-window principal-variation search.

The candidate grants one extra ply to an otherwise reduced quiet move when
its side/from/to history score is at least 4,096. It changes neither the history
updates nor move ordering. The threshold is provisional, not a tuned result.
The full-depth retry and all move-restoration paths remain intact. A reduced
search is still selective; correctness checks cannot prove equal playing strength.

The frozen baseline is `artifacts/publish/baseline-0.5.1/Aster.exe`, SHA-256
`6f6d781e7e8294757949a90cbc3a113c18f39ba6cfb88e6a30b89f91eb892313`.
The candidate is `artifacts/publish/history-lmr-dev/Aster.exe`, SHA-256
`39c20acc165856fb6191a90acd7ee45b414de4d16798ec10c08d53afd05a0be1`.
Its matching source is preserved in `artifacts/research/history-lmr-source`.

The candidate passes the existing 37 tests and 32 depth-8 tactical positions.
Across 64 fixed-depth opening comparisons, it searches 5,966,922 rather than
5,155,458 nodes, about 15.7% more. It retains 54 best moves and 39 scores.
Those changes show that the search policy differs, not that it improves play.
Report: `artifacts/benchmarks/history-lmr-vs-0.5.1-depth8.json`.

In the instrumented five-position depth-9 benchmark, the extra ply is triggered
2,629 times. Most triggers occur in the fourth middlegame position (2,281);
the Kiwipete position triggers it only 59 times. Timings include instrumentation
overhead. Normal builds compile out all profiling counters and timers.
Report: `artifacts/benchmarks/history-lmr-profile-depth9.json`.

The paired regression uses frozen `tests/fixtures/openings-v3.json`: 64 distinct
20-ply positions with seed 20261009, excluding the 20,000-position training set
and both earlier opening suites. Legal histories and the teacher binary hash
passed independent audits. SHA-256:
`b2c84b63c566712b33102e1a5f246d47a010a0341f8396c5e036937c74e241f3`.
This remains a regression suite, not the held-out final superiority test.

```powershell
.venv/Scripts/python.exe scripts/match.py --engine artifacts/publish/history-lmr-dev/Aster.exe --opponent artifacts/publish/baseline-0.5.1/Aster.exe --openings tests/fixtures/openings-v3.json --pairs 32 --movetime 0.03 --output artifacts/matches/new-history-lmr-run
.venv/Scripts/python.exe scripts/audit_match.py artifacts/matches/new-history-lmr-run
.venv/Scripts/python.exe scripts/analyze_match.py artifacts/matches/new-history-lmr-run.json
```

The candidate was rejected after its 64-game fresh-opening match at 30 ms/move
finished **13/28/23 W/D/L**, a **42.2%** score with an exploratory opening-cluster
interval of **32.8%..51.6%**. All games finished without forfeits or unresolved
outcomes and passed independent audits. Both baseline and candidate solved
32/32 tactics at 5,000 nodes as well as the depth-8 gate. The extra search effort
provided no match evidence for retaining this policy. Binary, source, JSON and
PGN remain preserved at `artifacts/matches/history-lmr-vs-0.5.1-fresh-30ms`.

All match results are recorded in
`artifacts/PROGRESS.md`. Rejecting a quiet-history ordering penalty in an earlier
experiment does not settle this separate use of history in search depth.
