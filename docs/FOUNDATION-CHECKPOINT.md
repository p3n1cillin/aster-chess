# Stronger foundation checkpoint — 2026-10-05

The user asked to combine a stronger engine's source and trained knowledge with
Aster's original engine, proof capabilities and visualization. Work was stopped
at the user's request for the night. The goal is paused, not completed.

## Saved work

- `main` remains at `d1a5d53`; its playable C# engine is unchanged.
- `research/continuation-history-v1` contains an opt-in ordering prototype,
  predeclared plan and 256 independently audited fresh opening positions.
  The default solution built and 60 candidate engine tests passed. No tactical
  qualification or strength matches were run; it remains disabled and unrated.
- `research/berserk-foundation` contains draft checksum-pinned download/build
  scripts and a match-runner alias for Berserk's `MoveOverhead` option. These
  changes are a checkpoint, not a tested or integrated native engine.

## Selected candidate for investigation

[Berserk 14](https://github.com/jhonnold/berserk/releases/tag/14), released
2026-05-24, upstream commit `8ae895a6151695be4a50d4fb65b0c131659c513a`.
It supplies native C search and a trained neural evaluation. Its source headers
specify GPL-3.0-or-later; preserve upstream authorship, licensing and dependency
notices when importing it. The release embeds its network; no separate network
license was found in the inspected repository. Review and record that provenance
before distributing a derivative.

Verified local official release assets:

- `berserk-14-avx2-pext.exe`: SHA-256
  `0a4f120db51b8416bc200d510fb355448406a9bd073f064adf7d2671cbbc36f2`.
- `berserk-9b84c340af7e.nn`: SHA-256
  `9b84c340af7e45f6e07f0046235ccb327f4ae0840c8ee2c4b97b99121e5c5084`.
- Portable LLVM/MinGW 20260922 UCRT x86-64 archive: SHA-256
  `e3ad77d117a4bea19a7a3b333341824d79a5a371004a10e25b8504e7b3047666`.

The CPU is an AMD Ryzen 5 7600X. Official binaries and weights are in the
research checkout's ignored `tools/berserk/14`. The pinned upstream checkout is
in the main checkout's `.aster-local/berserk-upstream`; the compiler is in
`.aster-local/toolchains/llvm-mingw-20260922-ucrt-x86_64`. The upstream repository
and compiler remain local downloads, not newly authored Aster code.

## Resume point

Import an attributed, pinned source tree into `native/aster-berserk`, preserving
all upstream notices. Review the draft build script, build the source with the
pinned weights and freeze binary/source manifests. Verify rules, cancellation,
protocol responsiveness, legal principal variations and tactics. Predeclare and
run equal-resource color-swapped matches on fresh openings against frozen Aster,
retaining reports and PGNs. No local Berserk-versus-Aster matches have run, and
no superiority or rating for the proposed derivative has been established.

Then integrate Aster's proofs and visualization with genuine native search
instrumentation. The current browser visualization observes the original C#
engine and must not be represented as a trace of Berserk's search.

## Rating at checkpoint

Last calibrated build: `0.7.6-q-evasion-dev`, approximately **2319**, with a
95% opening-family interval **2277–2360**, on the local Stockfish 19 UCI_Elo
setting scale at 30 ms/move, one thread and 64 MiB hash. This is not public Elo.
The current visual build, continuation prototype and proposed native foundation
are unrated. Surpassing full-strength Stockfish remains an unachieved goal.
