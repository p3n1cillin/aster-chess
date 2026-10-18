# General mating strategy certificates

This document preserves the historical C# implementation and its evidence.
For the active Rust build and proof export, see [Rust migration](RUST-MIGRATION.md)
and [current play controls](PLAY.md).

Aster 0.7.9-mate-proof-dev can export independently checkable forced-mate
strategies for positions with any standard-chess material. This extends the
existing native queen/rook-versus-king interface. A pinned Stockfish 19 test
does not return a native certificate or explanation for `explain mate 3`;
this describes its native interface, not an inability to calculate mates
or use external tools.

## Use

```powershell
dotnet artifacts/publish/mate-proof-dev-v2/Aster.dll certify-mate artifacts/proofs/my-mate.json 7 white '8/8/4K3/1k6/8/1p6/8/Q1R5 w - - 0 1'
.venv/Scripts/python.exe scripts/verify_mate_proof.py artifacts/proofs/my-mate.json --output artifacts/validation/my-mate.json
```

The first command proves that White can force mate within five plies after
the quiet move **Qa3** (`a1a3`). The complete certificate has **18 positions**,
including every legal defensive reply. Its search visits **26,990** positions
while testing bounds up to seven; visited search positions are distinct from
the completed certificate size. The independent verifier follows every branch
with ordinary chess rules and checks every final checkmate. It uses no engine,
evaluation, teacher or tablebase. A mate bound is an upper bound, not a claim
of the globally shortest possible mate.

`certify-mate` takes a new output path, a bound from 0..7 plies, `white` or
`black` as the mating side, and a FEN. The mating side may be different from
the side to move, allowing certificates rooted at a defender turn. Existing
files are never overwritten; incomplete searches do not export a certificate.

In UCI mode, `explain mate 7 50000` runs a bounded background proof for the
current side to move and emits protocol-clean `info string explanation` JSON.
The response names a verified first move when complete, the mate bound, visits
and completed strategy size. `explain` retains queen/rook endgame explanations
and uses this general search for other material. `isready` remains responsive;
`stop` cancels the proof and search. A new position, new game, changed options
or quit also cancels an old explanation. Proof work runs only when requested.

## What makes the claim checkable

The original AND/OR search uses every legal move. At an attacker node, one
proved continuation suffices; at a defender node, every legal reply must have
a proved continuation. Checks are ordered first, but quiet moves and every
promotion remain available. Iterative bounds share one total visit budget.
No playing-search pruning, evaluation score, null move or hash-only cache can
establish a certificate. Failed branches do not enter the final graph.

Every node records full FEN including clocks. Each edge makes a legal move and
strictly reduces its remaining mate bound; internal distances equal one plus
the maximum child bound. All reachable leaves must be actual checkmate of the
defender. The verifier replays exact full positions on every path, rejects
drawn intermediate states and verifies full defensive coverage. Checkmate is
tested before draw claims, including already mated roots at clock 100 or 150.

Roots assume a fresh FEN history origin, or a reset halfmove clock that makes
earlier reversible history irrelevant. Arbitrary retained reversible history
is rejected. Nonterminal roots conservatively require clock plus requested
bound below 100. The seven-ply limit is below the minimum eight plies needed
for a fresh legal position's third occurrence. These guards are conservative;
an incomplete result is not evidence of a draw or loss. Work limits are
50,000 visits by default and at most 100,000. Cancellation and budget failures
return an explicit unproved result; every speculative move is undone.

## Evidence

The [plan](../artifacts/research/mate-proof-plan-v1.json) is frozen before
implementation and candidate queries. Current candidate SHA-256:
`ac907eac90bba15acab80c15d16f195044a8ac2b59a7964f5a065bc0caaa0ae8`.
The original candidate/source/diagnostics are preserved. Before matches, a
revision additionally rejects impossible triple-check roots and expands
independent terminal-clock and legacy coverage. Valid-position search,
playing code and all declared gates remain unchanged. An initial en passant
fixture had a g6 escape; its failed test log and independently verified
correction are retained.

The current build passes **55 engine tests** and **2,614** independent
rule/perft/protocol checks. All original/quiet/endgame tactical thresholds
pass. A separate rules-only solver agrees on **64 seeded positions** at a
three-ply bound, with no budget-unknown cases. **25 native certificates**
independently verify **126 positions** and **42 defensive replies**, covering
both colors, attacker/defender roots, five-ply quiet mating plans, promotion,
en passant and terminal clock boundaries. Two independently constructed valid
castling alternatives also verify. All **36 legacy certificates** still verify.
Eleven corruptions are rejected: omitted defenses, illegal moves, cycles,
nondecreasing bounds, false leaves, altered clocks, unreachable nodes, wrong
winner, incomplete claims, unsupported horizons and false work budgets.

During concurrent infinite playing search, the five-ply explanation completes
with readiness/stop below one second. Eight stop tests cancel the proof and
restore the current position. Malformed commands, incomplete exports and
overwrite attempts are rejected. CI checks eight current-build certificates
with the independent rules verifier on Windows/Linux and both build variants.

Ordinary playing files match the frozen 0.7.8 source byte for byte. On **32
fresh depth-eight openings**, every move, score and node count agrees,
**2,371,866 nodes** each. Bench seven retains **146,772 nodes**. A fixed
32-game paired unchanged-play regression completes at 30 ms/move, one thread,
64 MiB hash and zero move overhead: **10 wins, 11 draws and 11 losses**,
score **48.44%**, no forfeits or unresolved games. Every PGN is independently
audited. Its point score is descriptive, never evidence of a strength increase.
Windows/Linux CI passes all four jobs, with 55 default/56 IIR tests and eight
independently verified current-build certificates in each job.

The complete immutable experiment can be rechecked with:

```powershell
.venv/Scripts/python.exe scripts/preserve_mate_proof.py --verify
```

The latest exact measured rating remains **2319** (95% interval **2277..2360**)
on the SF19 setting-equivalent scale at 30 ms, one thread and 64 MiB hash,
for the earlier 0.7.6-q-evasion binary. This interface build is not separately
rated. Public Elo and full-strength Stockfish superiority remain unestablished.
General strategic plans and broader stable endgame learning remain next work.
