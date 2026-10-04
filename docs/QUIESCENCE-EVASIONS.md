# Quiescence evasion legality experiment

The tested **0.7.6-q-evasion-dev** candidate lets the full check-evasion loop
establish whether a legal move exists. If no evasion succeeds, it returns the
normal mate-distance score. It retains the early legal-move test for non-check
stand-pat nodes and the maximum-ply static fallback. Draw-history, rule-50 and
checkmate precedence, TT policies, move order, pruning and reductions remain
unchanged. This does not combine the rejected deferred-capture experiment.

The frozen DLL is `artifacts/publish/q-evasion-dev/Aster.dll`, SHA-256
`a3994e4f350b2cfa261db5edc1e4ae5c332d85d4b3eaf34c0730267f3603d9a0`.
Its 23-file source snapshot is `artifacts/research/q-evasion-source/manifest.json`.
The baseline is the exact frozen locally rated ordinary 0.7.4 DLL, SHA-256
`52439f58cf10a4a5dad8d4d48bf9db59db0a3f14b3c1c6216f79182b4a646d9a`.

The candidate passes **51 engine tests** and **1,614 independent rule/protocol
checks**. New tests directly invoke the real horizon routine at plies 126/127:
mate, stalemate, rule-50 precedence, a legal drawing evasion and restoration
after a deterministic stop inside an evasion. Initial test-harness compilation
mistakes were corrected; failed build logs remain preserved.

All **160 fresh depth-eight openings** and **256 seeded retained-history,
FEN, clock, warm-cache and restricted-search cases** have identical complete
search traces after removing time/nps fields. Independent PV legality checks
pass. Both engines search **11,259,452 nodes** in the fresh suite. Original
tactics stay 32/32 at depth 8 and 5,000 nodes, quiet tactics 32/32 at depth 8 and
25/32 at 5,000 nodes, and endgame diagnostics 13/16 at 5,000 nodes.

Instrumented five-position depth-nine output and **604,209 nodes** agree.
Legal-move existence calls drop from **480,859** to **453,395**: **27,464**
avoided. Checkmating nodes can now score pseudo-moves before proving no legal
evasion; this adds some exchange work but does not add search visits or change
the returned mate. Instrumented times are diagnostics, not strength evidence.

Two warmup and six measured passes through the first 16 fresh positions at
depth 10 retain every move, score, depth, node count and PV. The median measured
baseline/candidate elapsed ratio is **1.05291**, or **5.29%** faster in this
local microbenchmark. This passes the declared 1.05 performance gate; it does
not by itself establish greater playing strength.

The [plan](../artifacts/research/q-evasion-plan-v1.json) freezes a disjoint
288-opening parent: 128 pairs at 30 ms, 32 at 100 ms and 128 conditional rating pairs.
The seeded teacher generation excludes three development datasets, five prior
opening suites and both earlier rating/deferred-scoring parents. Independent
audits confirm histories, deduplication, ten exclusion sources and provenance.
This is a regression pool, not the final Stockfish-superiority opening set.

All frozen engineering gates pass. The complete paired regressions are:

| Control | Games | W | D | L | Score | 95% family interval |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 30 ms/move | 256 | 76 | 119 | 61 | 52.93% | 48.89%..56.96% |
| 100 ms/move | 64 | 13 | 38 | 13 | 50.00% | 41.94%..58.09% |

Both intervals contain 50%. This qualifies a same-work engineering
optimization under the frozen rules; it does not prove a strength gain.
The reserved 256-game confirmation against SF19's 2300 setting then finishes
**107 wins, 56 draws, 93 losses**, a **52.73%** score. All **576** PGNs pass
independent replay and outcome audits, with no forfeits or unresolved games.
No budget was extended and no parameters were retuned.

The optimization is now enabled in ordinary **0.7.6-feature-dev** source.
The promoted default DLL is `artifacts/publish/q-evasion-default-dotnet/Aster.dll`,
SHA-256 `3801b8cbc1cbbb98e2435ab5b00b161d08c2be16d4a18af7cc56e3eb2f43e343`.
Its source is frozen in `artifacts/research/q-evasion-default-source/manifest.json`.
The required Release build, **51 tests**, **1,614 independent checks** and
**146,772-node** depth-seven benchmark pass. All **416** saved complete
candidate traces replay exactly on this ordinary build, excluding time/nps.
Earlier production and experiment snapshots remain preserved.

The exact matched candidate has a provisional local estimate of **2319 (95%
interval 2277..2360)** on the **SF19 UCI_Elo-setting equivalent at 30 ms/move,
one thread, 64 MiB hash** scale. See the
[rating record](../artifacts/ratings/session-20261004-q-evasion-confirmation.json).
This rating belongs to the matched candidate binary; the renamed ordinary
build has verified trace agreement but no separate rating match. The previous
2300 estimate has an overlapping interval, so a rating increase is unproven.
Public Elo and full-strength Stockfish superiority remain unestablished.

Exact binaries, source, reports, PGNs, audits, failed test-harness logs and
pipeline copies are indexed in the
[preservation manifest](../artifacts/research/q-evasion-experiment-v1-manifest.json).
