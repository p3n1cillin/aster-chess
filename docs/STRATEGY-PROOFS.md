# Native explanations and independently checkable strategies

Aster can explain queen/rook-versus-king choices and export a complete winning
strategy certificate. This is the first implemented distinctive capability:
the pinned Stockfish 19 binary responds to `explain` with an unknown-command
message, while Aster explains the move and alternative mate bounds. This is
a comparison of native interfaces, not a claim that Stockfish cannot find
these wins or that external tools cannot add explanations. Stockfish's
[official FAQ](https://official-stockfish.github.io/docs/stockfish-wiki/Stockfish-FAQ.html#move-annotations)
also distinguishes engine evaluations from annotations added by interfaces.

## A proof, not just a principal variation

The certificate is a directed acyclic graph. Each attacker position chooses
one legal move. Each defender position includes every legal reply. Every
edge strictly decreases the mate bound, and every leaf is actual checkmate.
An independent Python verifier uses only chess rules: no Aster executable,
Aster table data, Stockfish or Syzygy. It validates every edge, coverage of
defensive replies, reachability and checkmate leaves. Its proof establishes
an upper bound on forced mate, not optimality; the separately exhaustive
table recurrence validation establishes the optimal theoretical distances.

Example:

```powershell
artifacts/publish/proof-dev/Aster.exe certify artifacts/proofs/my-rook-proof.json '7k/8/8/8/8/8/R7/K7 w - - 0 1'
.venv/Scripts/python.exe scripts/verify_strategy_proof.py artifacts/proofs/my-rook-proof.json --output artifacts/validation/my-rook-proof.json
```

The preserved example proves mate within 19 plies through 51 positions,
57 edges, 30 defensive replies and five checkmate leaves. A corresponding
queen example proves mate within 13 plies through 31 positions, 34 edges,
18 defensive replies and four checkmate leaves.

The UCI command `explain` emits protocol-clean `info string explanation`
JSON with a plain-language summary and legal alternatives. For the rook
example it explains that `a2a7` reduces the mate bound from 19 to 18 plies,
while `a2b2` leaves 28 plies. It runs on a cloned board in a bounded worker;
`isready` and `stop` remain responsive during concurrent infinite search.
The full graph is exported with the separate `certify` command. Existing
certificates are never overwritten.

## Scope and evidence

Proofs currently cover winning KQK/KRK positions. Unsupported material,
theoretical draws, uncertain rule-50 boundaries, arbitrary retained prior
history and certificate capacity limits produce explicit incomplete results.
No truncated graph is presented or exported as a complete certificate.
FEN origins assume no earlier repetition history; a just-reset halfmove
clock makes earlier reversible history irrelevant. Clock plus mate bound
must remain below 100. Every speculative move is restored in `finally`.

In addition to four preserved examples, 32 seeded certificates cover both
piece types, both colors and both turn roles. All independently verify:
18,621 positions and 26,102 edges, with the largest graph containing 3,428
positions. Corruption tests reject omitted defensive replies, nondecreasing
bounds and false mate leaves.

The proof build passes 51 engine tests and 17,491 independent rule/protocol
checks. Its core search, evaluation and table files are identical to the
frozen conversion candidate; 66 fixed-node move/score/node outputs agree.
Its interface adds explanations, not an additional strength claim. The
ordinary source build exposes these diagnostics but leaves the experimental
evaluation/root constraints disabled. It passes 49 engine tests, 1,614
required differential checks and the unchanged 146,772-node benchmark.

General winning plans, tactical sacrifices and ordinary middlegame
explanations remain future work. Extend proof coverage with concrete,
independently checkable claims; do not turn a search score or single PV into
a claimed guarantee.
