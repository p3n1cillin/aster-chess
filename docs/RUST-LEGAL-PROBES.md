# Rust terminal-query experiment — 18 October 2026

The Rust foundation tests for a legal move before quiescence stand-pat,
transposition cutoffs and other pruning. This preserves mate/stalemate precedence,
but its existence query builds the complete move list at every visited node.
This experiment shortens that query without changing evaluation, move ordering,
pruning, neural weights or the moves searched at a fixed depth.

Outside check, candidate 0.9.2 probes ordinary single pawn pushes and knight
moves. Each candidate is passed through the existing legality predicate, including
its pin checks. A successful probe establishes that a legal move exists. All
other cases use the original complete generator, including promotion-only moves,
en passant, castling, checks and positions with no legal moves. The method takes
an immutable board reference and does not make speculative moves.

The shortcut's candidates are a subset of the complete generator's candidates:
the same pawn/empty-square masks and knight attack table are used, with own
pieces excluded and promotions left to the fallback. An unsuccessful shortcut
therefore cannot suppress a legal move, and a successful shortcut still requires
the normal legality test. The search receives the same boolean result; it does
not consume these probes as a reordered move list.

## Frozen design and checks

The [predeclared plan](../artifacts/research/rust-legal-probe-plan-v1.json) fixes
the design, opening generation, partitions, timing protocol, two match controls
and promotion thresholds before candidate modification or queries. Sixty-four
fresh parents exclude all 50 earlier opening suites: 16 are for timing, 32 for
30 ms matches and 16 for independent 100 ms matches. No candidate retuning or
outcome-driven extension of the sample is permitted.

The frozen standalone candidate SHA-256 is
`b51e97647dd086ed0a30682fba77ea627dd5d8cf9bfc291e34a4064b04916213`.
[Its source snapshot](../artifacts/research/rust-legal-probe-source-v1/manifest.json)
pins the compiler, weights, dependencies and all 117 listed source/helper files.
The opponent is frozen Rust play-v3, SHA-256
`246b2c6c1dbb6b98a0d90013fedb47b54b95317992593d98cc486ef66ef91fdb`,
with its separately preserved source-v4 manifest.

Both release and debug native suites pass **132 tests**. The independent oracle
checks **4630** positions for full legal moves, the existence predicate and FEN
preservation, plus 14 perft references, history replay, readiness during search,
stop and sampled null/search branches. A separate **94-position** edge suite
covers mirrored pins, promotion-only moves and late-clock terminals, including
stalemates where every available pawn or knight probe exposes the king. The
new `legal-exists` UCI diagnostic allows the oracle to check the predicate
directly. CI runs both independent checkers.
Both Windows/Linux CI jobs pass at `ecbcee7`; the
[complete CI record](../artifacts/ci/rust-legal-probe-39169381039.json) and logs
are preserved.

The actual HTTP/SSE host and proof exports pass. Tactical results retain
**32/32** at depth eight, **28/32** quiet positions at 5000 nodes and **16/16**
endgames at 5000 nodes. Native bench seven retains **124781 nodes**.

## Same-work timing

The [timing record](../artifacts/benchmarks/rust-legal-probe-same-work-v1.json)
contains eight counterbalanced rounds over 16 fresh positions, at requested
depth 12, one thread and 64 MiB hash. Each process has a discarded warmup;
new-game/reset/readiness work is outside each measured search. Baseline/candidate
order alternates, and position order reverses on odd rounds. All **256** timed
searches retain exactly the same completed depth, nodes, score, best move and
complete principal variation for their position.

The median baseline/candidate elapsed-time ratio is **1.07358**, equivalent to
about **6.85% less elapsed time** for the same searches. The candidate is faster
in all eight rounds and passes the predeclared 3% timing gate. Individual ratios
range from 1.04427 to 1.16233. This is a local desktop measurement without CPU
affinity or application isolation; it establishes no Elo or playing-strength gain.

## Playing results and decision

The separately partitioned 64-game 30 ms and 32-game 100 ms samples are retained
with full PGNs, source/binary hashes, options, openings, actual per-move elapsed
times and search telemetry. Rules alone adjudicate games; the cap is 400
additional plies, and unresolved games are never counted as draws. Complete
results are independently audited, with no forfeits or unresolved games:

| Requested time per move | Wins | Draws | Losses | Score | 95% family score interval |
| --- | ---: | ---: | ---: | ---: | --- |
| 30 ms, 32 opening pairs | 13 | 40 | 11 | 51.56% | 45.16%..57.81% |
| 100 ms, 16 opening pairs | 6 | 20 | 6 | 50.00% | 40.63%..57.81% |

The bootstrap uses 20,000 samples, seed 20261019, and initial FEN plus the first
four opening plies as the family definition. The short/long samples contain
31/16 families. Both intervals include 50%; no playing-strength gain is
established. The timing gate and both fixed engineering match thresholds pass,
as do all correctness, tactics, host, proof and CI gates.

The [recorded decision](../artifacts/research/rust-legal-probe-decision-v1.json)
therefore promotes **0.9.2**. The engine searches the same fixed-depth work more
quickly; this does not establish an Elo increase or superiority over Stockfish.
Rust Aster remains uncalibrated. No extra games or candidate variants were chosen
from the outcomes. Both source snapshots, all reports and PGNs remain preserved.

## Intermediate tooling corrections

The first endgame command named a nonexistent fixture; it was corrected to
`tests/fixtures/endgames-v1.json` before the final gate run. The edge checker
initially expected trailing whitespace on an empty legal-move response; the
process client deliberately strips it, so the checker prefix was corrected.
Neither correction changed engine behavior. Original upstream CRLF endings
were restored before the final build to keep its source diff reviewable; the
earlier LF-formatted engineering binary had SHA-256 `2e298573…`, while all final
checks, timing and matches identify the complete frozen `b51e9764…` hash above.
