# Search profiling

The optional `ASTER_PROFILE` build records evaluation, legal-move-existence,
move-ordering and static-exchange call counts and elapsed ticks. The
instrumented search also counts reduced searches and their total reduced plies.
It additionally exposes a quiet-pruning counter for research builds. The
archived late-quiet candidate uses it; the restored default leaves it at zero.
The archived history-guided candidate additionally counted its depth discounts. These
counters measure policy use, not playing strength. The normal
build resolves the evaluation and exchange aliases directly to the existing
implementations and compiles out the profiling class, counters and timers.
UCI output and the normal benchmark format remain unchanged.

The default reduction policy is unchanged after both search experiments were
rejected. The restored depth-9 reference profile records 604,209 total nodes;
the history-depth candidate searched 783,246 under the same five-position
benchmark. Its extra depth is not retained. All 64 uninstrumented depth-8
searches match frozen 0.5.1 in move, score and node count after restoration.
[Restored profile](../artifacts/benchmarks/restored-0.5.1-profile-depth9.json).

From the repository root, build to a separate output directory:

```powershell
dotnet build src/Engine/Engine.csproj -c Release -p:DefineConstants=ASTER_PROFILE -p:OutputPath=C:/Users/lukem/source/repos/WIP/chess/artifacts/profile/bin/
.\.venv\Scripts\python.exe scripts/benchmark.py --engine artifacts/profile/bin/Aster.dll --depth 9 --output artifacts/benchmarks/new-profile.json
```

Change the absolute output path for another checkout. Use the separate output
directory to avoid replacing a release or a candidate currently being matched.
The benchmark's position records gain a `profile` field. Every search resets
the counters, so these are per-position measurements. Profiling currently
assumes one search at a time, matching the engine's single-thread configuration.

Static exchange is mostly nested inside move ordering. Its time is therefore
already included in that category, and the categories must not all be summed.
Timer calls, instrumentation and JIT affect the measured cost. These diagnostics
identify targets for optimization; ordinary uninstrumented fixed-depth runs
and equal-time matches establish practical effects.

The first depth-9 profile of the history-penalty experiment attributed
60.357 milliseconds of the 247-millisecond Kiwipete search to legal-move
existence checks. That experiment's 64-game match finished 22/20/22 W/D/L
against 0.4.0, with no evidence of a strength gain. The default history behavior
was restored, and the legal predicate became the next measured optimization.
[Profile report](../artifacts/benchmarks/history-malus-profile-depth9.json).

The new predicate proves existence from an ordinary move by an unpinned
non-king piece when the side is not in check. It computes orthogonal and
diagonal absolute pins with slider x-rays. If that proof is unavailable, it
uses full pseudo-legal generation and make/undo legality checks. En passant,
king moves, castling and check evasions always retain the complete fallback.
The predicate does not implement draw adjudication; search checks draw rules
separately before speculative cutoffs.

The `haslegal` diagnostic lets the independent verifier check this predicate
directly against python-chess. `scripts/verify.py --setups 2000` additionally
samples bounded valid material configurations to include unusual pins,
checks and terminal positions. The default verification still includes
explicit mate, stalemate and pinned-piece fixtures.
