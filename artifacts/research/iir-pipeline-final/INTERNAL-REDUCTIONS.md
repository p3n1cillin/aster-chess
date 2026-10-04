# Unseeded secondary search experiment

The opt-in **0.7.7-iir-dev** build searches one ply less at a secondary,
zero-window node with depth at least five and no TT move. It leaves root/PV,
check, repeated-position, pawn-only and halfmove-clock 90+ nodes unchanged,
and declines mate-bound windows. The reduced depth governs subsequent
pruning, descendant search and table storage. It never stores the unreduced
requested depth for this node. This is an original, small selective-search
hypothesis, not a demonstrated strength gain.

Candidate DLL: `artifacts/publish/iir-dev/Aster.dll`, SHA-256
`e6c1ea589dfb28441a610e23c93d7287c5a5ea52d5741112e542ddb18acfe85e`.
Source: `artifacts/research/iir-source/manifest.json` (23 files).
The frozen ordinary 0.7.6 baseline is
`artifacts/publish/q-evasion-default-dotnet/Aster.dll`, SHA-256
`3801b8cbc1cbbb98e2435ab5b00b161d08c2be16d4a18af7cc56e3eb2f43e343`.
Neither engine is a Stockfish wrapper.

The candidate passes **52 engine tests**, including a real search check that
unseeded secondary nodes store depth four for a depth-five request, while
seeded/root/PV/late-clock/pawn-only nodes keep depth five. Those searches also
check board/hash/evaluation restoration. **2,614 independent rules/protocol
checks**, 14 perft fixtures and 1,000 independently generated legal setups pass,
including six checkmates and one stalemate. Original tactics remain 32/32 at
depth eight and 5,000 nodes; quiet tactics remain 32/32 at depth eight and
25/32 at 5,000 nodes; endgame diagnostics remain 13/16 at 5,000 nodes.

All **256** seeded retained-history/FEN/clock/warm-cache/restricted-move/node
cases pass independent PV/bestmove legality, limits and root restoration.
**176** full traces agree with baseline; changed traces are expected here.
On **64 fresh depth-eight openings**, candidate and baseline agree on 58
moves and 49 scores. Work is **4,994,060 versus 5,043,413 nodes**.
The instrumented depth-nine benchmark records **202** reduction triggers and
**591,552** nodes. Neither profile time nor reduced node count assigns Elo.

The [frozen plan](../artifacts/research/iir-plan-v2.json) allocates **512 games
at 30 ms/move** and **128 at 100 ms/move**, color-swapped, one thread, 64 MiB
hash and Move Overhead 0, capped at 400 additional plies. The 448-opening parent
is generated independently with pinned SF19, seed 20261108, 20 legal plies,
2,048-node selection and 20,000-node balance checks within 80 cp. It excludes
three development datasets and eight previous opening parents/suites. All
partitions and independent exclusion/history audits are frozen before opening
queries. The separate synthetic verifier uses independently fixed seed 20261110;
its cases do not select or filter the generated pool.

The [original plan](../artifacts/research/iir-plan-v1.json) misspells the intended
512-position development dataset filename. Version two corrects only that
pathname after unit/rule checks and before fixture generation or any opening,
tactical or match queries. The original plan and correction script remain
preserved; no candidate parameter, seed, budget or threshold changes.

Promotion requires every correctness/tactical/behavior/profile gate, zero
forfeits/unresolved games, a primary 95% family lower bound **strictly above
50%** at 30 ms, and a score at least **50%** with lower bound at least **45%**
at 100 ms. Resample first-four-legal-ply families with both colors and all pairs,
20,000 samples, seed 20261109. All 640 regression games run even if an earlier
tactical gate fails. Only if all gates pass may the final 128 reserved pairs
receive a 256-game local rating confirmation against SF19's previously fixed
2300 strength setting. The maximum is **896 games**, with no adaptive extension,
retuning or selecting a new opponent setting from these results.

All **640 regression games** are complete and independently audited:

| Control | Games | W | D | L | Score | 95% family interval |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 30 ms/move | 512 | 153 | 220 | 139 | 51.37% | 48.20%..54.52% |
| 100 ms/move | 128 | 36 | 60 | 32 | 51.56% | 45.49%..57.79% |

There are no forfeits or unresolved games. The **30 ms confidence gate fails**:
its primary lower bound is not strictly above 50%. Both intervals contain 50%.
Neither a strength gain nor a regression is established. The candidate stays
opt-in under the original rules; no parameters, thresholds or budgets changed.
The conditional rating run is skipped and **128 reserved rating openings remain
unused by Aster**. The actual runner exited successfully after applying these
gates. Exact reports, PGNs, audits and logs are preserved at
`artifacts/matches/iir-vs-0.7.6-{30ms,100ms}.*`.
Windows/Linux CI also passes the ordinary and opt-in builds (51/52 tests),
independent rules, both tactical suites and endgame diagnostics.

`scripts/run_iir.py` refuses
to overwrite/restart an existing execution. Inspect the authoritative process
handle before treating a run as stopped; `iir-execution-v1.json` is a progress
record, not proof that a process is live. The pipeline and rating analyzer were
frozen before matches. The final audit/preservation script was frozen while
the first match was still incomplete, and its live-run refusal check passes.
The [decision](../artifacts/research/iir-decision-v1.json) keeps the verified
ordinary source and exact pre-match DLL: their hashes still match after the
runner exits. The required checks remain valid without rebuilding unchanged
playing code. No new rating is attached to the candidate.

The ordinary 0.7.6 build passes its required Release build, **51 tests**,
**1,614 independent checks** and unchanged **146,772-node** benchmark. Its
64 fresh moves, scores and node counts agree with the frozen baseline. Its new
source snapshot is `artifacts/research/iir-default-source/manifest.json`;
the compile-time experiment remains disabled. Current measured rating stays
with the earlier exact **0.7.6-q-evasion-dev** binary: **2319 (95% interval
2277..2360)** on the local SF19 UCI_Elo-setting equivalent scale at 30 ms/move,
one thread, 64 MiB. The IIR candidate and renamed ordinary binary are not
separately rated. Public Elo and full-strength Stockfish superiority remain
unestablished.

The [session record](../artifacts/ratings/session-20261004-iir.json) retains
the last measured exact-binary rating and records the failed gate. Every source,
binary, fixture, report, PGN, audit, correction and pipeline copy is indexed in
the [preservation manifest](../artifacts/research/iir-experiment-v1-manifest.json).
Recheck it without replacing evidence:

```powershell
.venv/Scripts/python.exe scripts/preserve_iir.py --verify
```

```powershell
dotnet publish src/Engine/Engine.csproj -c Release -p:DefineConstants=ASTER_IIR -o artifacts/publish/new-iir-run
```

Preserve the existing package and source snapshots; use a new output directory
for a reproducibility build.
