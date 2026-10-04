# Quiescence cache experiment

The candidate adds depth-zero transposition entries for non-check quiescence
nodes. It checks repetition, insufficient material and the rule-50 draw before
probing. A rule-50-specific search key separates otherwise identical positions
at different reversible-move counts. Prior occurrences and check evasions are
excluded. Only depth-zero entries can cut off quiescence, and only at a null
window; deeper main-search results supply move ordering but cannot replace a
quiescence result.

Non-check continuations are captures or promotions. They reset reversible
history, which limits the history dependence of the cached continuation. Losing
captures still undergo static exchange pruning even when they are the table
move. Mate distances are normalized by ply on store/probe. A depth-zero result
cannot replace a deeper entry for the same key; shallow exact entries also
preserve deeper exact entries.

The initial version regenerated a legal move even on a cache hit. The revised
version reuses a structural fact: depth-zero entries are created only after
quiescence has established that a legal move exists. A matching full-key entry
therefore proves the same position has a legal move. Deeper entries carry no
such guarantee. Fresh positions and checks retain the explicit legal-move test;
draw history is always checked first. Future changes to depth-zero entry creation
must preserve this invariant.

At fixed depth 6 across all 64 frozen openings, this revision produced exactly
the same moves, scores and node counts as the first cache version. The revised
version completed that run in 1.138 seconds versus 1.252 seconds. These short
timings include JIT and are machine dependent. Against 0.3.1 the wider depth-8
run used 5,155,458 nodes versus 5,517,147, with 54/64 identical moves and 46/64
identical scores. Ordering and selective search can change behavior; this is not
a universally behavior-preserving optimization. Shallower timings were mixed.

The first cache version scored 23/27/14 W/D/L against 0.3.1 at 30 ms per move
and 19/27/18 at 100 ms, each over 32 distinct color-swapped opening pairs. Both
exploratory intervals included 50%. Neither establishes a general strength gain.
Per-move diagnostics for the longer run showed median completed depth 10 for
both engines. Refer to [progress](../artifacts/PROGRESS.md) for the revised
candidate's match result and final verification.

Original candidate binaries are retained locally under
`artifacts/publish/qcache-dev/` and `qcache-legal-dev/`. Their C# source snapshots
are under `artifacts/research/qcache-source/` and `qcache-legal-source/`.
Saved reports pin binary hashes and the opening suite, including teacher
provenance, budgets, seed and excluded training dataset hash.

```powershell
.\.venv\Scripts\python.exe scripts/compare_search.py --opponent artifacts/publish/baseline-0.3.1/Aster.dll --depth 8 --output artifacts/benchmarks/new-comparison.json
.\.venv\Scripts\python.exe scripts/match.py --opponent artifacts/publish/baseline-0.3.1/Aster.dll --openings tests/fixtures/openings-v1.json --pairs 32 --movetime 0.1 --output artifacts/matches/new-cache-run
.\.venv\Scripts\python.exe scripts/audit_match.py artifacts/matches/new-cache-run
.\.venv\Scripts\python.exe scripts/analyze_match.py artifacts/matches/new-cache-run.json --output artifacts/matches/new-cache-run.analysis.json
```
