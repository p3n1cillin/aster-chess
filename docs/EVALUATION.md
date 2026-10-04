# Classical evaluation research

Aster's evaluator is original C# code. Its material, piece-square, pawn,
mobility and king-safety terms are provisional. Evaluation experiments must
pass rule checks, tactics and paired matches before becoming defaults.

## Shared attack maps

Compute each color's pawn attacks once with masked bit shifts. Accumulate king,
knight and sliding-piece attacks while computing mobility, then count attacked
king-neighbor squares from the accumulated map. The old evaluator queried each
king-neighbor square independently and rebuilt enemy pawn attacks per color.

This refactor preserves scores: all 20,000 dataset evaluations match frozen
0.5.0 exactly. All 64 depth-8 opening searches also retain their move, score and
node count (5,155,458 nodes). Total elapsed time in that run was 2.857 rather
than 3.177 seconds. Short timings include JIT and machine effects and do not
establish playing strength.

The frozen build is `artifacts/publish/shared-attacks-dev/Aster.dll`, SHA-256
`8ff9fadbd625e635224937aeaecb5f39751d1922501fd2e5dd316395c727a753`.
Reports: `artifacts/validation/shared-attacks-evaluation.json` and
`artifacts/benchmarks/shared-attacks-vs-0.5-depth8.json`.

The released 0.5.1 package repeats both comparisons with identical scores and
fixed-depth work. Its separate timing was 2.503 vs 3.141 seconds; run-to-run
variation prevents a precise general speed estimate. Its paired 0.5.0 matches
scored 31/24/9 at 30 ms/move (64 games) and 12/14/6 at 100 ms/move (32 games).
The longer sample's exploratory interval includes 50%; these are regression
results under the recorded conditions, not a general rating claim.

## Rejected coordinated king pressure experiment

Count each knight, bishop, rook or queen whose attacks touch the opposing king
or a neighboring square. Each contacted square contributes 2, 2, 3 or 5 units
respectively. Require at least two distinct attacking pieces. The extra danger
is `min(400, units² * min(4, attackers) / divisor)`, where the divisor is 16
with an attacking queen present, otherwise 32. Add the white-minus-black danger
to the middlegame score before phase interpolation; endgame weights are unchanged.
The existing attacked-neighbor term remains in place.

The 64-game, 30-ms/move paired match against the frozen shared-map evaluator
finished 18/24/22 W/D/L, a 46.9% score with an exploratory opening-cluster
interval of 36.7%..57.0%. It passed all tactics and rule checks, but did not
provide evidence for retaining this term. The term was removed from the default.
The binary and source remain in `artifacts/publish/king-coordination-dev` and
`artifacts/research/king-coordination-source`. Report and PGN are preserved at
`artifacts/matches/king-coordination-vs-shared-attacks-30ms`.

These weights were hand-selected and untuned. Contacts are geometric attacks,
not a proof of legal or successful attacking moves. The cap, two-piece threshold
and phase scaling limit the term, but actual matches determine whether it is
useful. Testing against the frozen shared-map build isolates scoring from the
refactor's speedup. Results and acceptance decisions belong in
`artifacts/PROGRESS.md`; passing tactics alone is insufficient.

An independent color/rank symmetry test checks static evaluations in reference
positions and seeded legal playouts. Swapping piece colors, mirroring ranks and
swapping the side to move must preserve the side-to-move score, including tempo.

## Reproduce comparisons

```powershell
.venv/Scripts/python.exe scripts/compare_evaluation.py --help
.venv/Scripts/python.exe scripts/compare_search.py --help
.venv/Scripts/python.exe scripts/match.py --engine artifacts/publish/king-coordination-dev/Aster.dll --opponent artifacts/publish/shared-attacks-dev/Aster.dll --openings tests/fixtures/openings-v2.json --pairs 32 --movetime 0.03 --output artifacts/matches/new-king-pressure-run
.venv/Scripts/python.exe scripts/audit_match.py artifacts/matches/new-king-pressure-run
.venv/Scripts/python.exe scripts/analyze_match.py artifacts/matches/new-king-pressure-run.json
```

Preserve each binary and its matching source snapshot before further edits.
Version-2 neural models add corrections to the currently selected classical
evaluator; they are not bound to the older evaluator used to train them. Any
classical scoring change therefore requires new strength checks for those
models. The existing learned prototypes remain experimental.
