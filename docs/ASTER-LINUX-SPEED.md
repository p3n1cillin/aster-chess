# Linux speed: huge pages and paired widening

Speed work only. Every change keeps the canonical bench signature
(**1,559,611** nodes) on the AVX-512, AVX2 and scalar paths; no search or
evaluation decision changes. Speed is not a strength claim.

## Finding

On a Linux cloud VM (Intel Xeon, AVX-512 VNNI, 4 vCPU) Aster ran at about
**82%** of the same development commit built from source with clang, against
93% previously measured on Windows/Zen 4. Two upstream mechanisms were missing
from the port:

1. **Transparent huge pages.** On Linux the upstream reference allocates its
   network, histories, worker state and transposition table in 2 MiB aligned
   memory advised with `MADV_HUGEPAGE` (no privilege needed). Aster used plain
   heap memory, so random weight-row reads paid for TLB misses.
   `crates/aster-core/src/large_pages.rs` ports this (`LargeMem`, `LargeSlice`,
   `LargeBox`); other systems fall back to aligned heap memory.
2. **Paired widening add.** The reference widens two int8 weight rows at once
   with one byte unpack and one `maddubs` against ones, halving the shuffle-port
   work of sign-extending each row. On Intel the 512-bit shuffle port is the
   bottleneck of the accumulator update. The AVX-512 kernels now store int8
   rows in the paired layout (`kernels::PAIR_ORDER`, decided once at network
   load) and consume rows in pairs. Sums are exact (`|w0 + w1| <= 256`), and a
   unit test checks both AVX-512 kernels against an independent wide oracle,
   including wrapping and in-place updates. AVX2 and scalar layouts are unchanged.
   (An earlier Zen 4 trial of maddubs widening was 2% slower there; Zen 4
   double-pumps 512-bit shuffles, so the trade-off is CPU-dependent. Re-measure
   on Zen 4 before claiming a gain there.)

## Measurement

Concurrent interleaved benches, 12 rounds, ratio to the clang reference within
each round (`artifacts/research/aster-linux-speed-v1/`):

| Binary | Median nps | Ratio (median, IQR) |
| --- | ---: | --- |
| Reference, clang 18 | 821,294 | 1.000 |
| Reference, gcc 13 PGO | 803,944 | 1.011 (0.950–1.038) |
| Aster before (`234121d`) | 663,954 | 0.817 (0.783–0.872) |
| Aster with both changes | 755,810 | 0.913 (0.887–0.964) |

The VM is noisy; individual runs vary by ±10%. Intermediate measurements had
huge pages alone at about 0.87–0.89 and both changes at 0.90.

## Equal-time status match

Predeclared plan, fastchess log/config, PGN and report:
`artifacts/matches/aster-779bba2-vs-sfdev-uho/`. Aster `779bba2` against the
gcc PGO build of the pinned upstream commit, 10+0.1, one thread, 16 MiB hash,
400 color-swapped pairs from `UHO_Lichess_4852_v1.epd` (seed 20261019):
**191 wins, 199 losses, 410 draws (49.5%)**, −3.5 ± 11.8 Elo, pentanomial
[0, 100, 208, 92, 0]. The interval contains zero: level within noise, as
expected for an exact port at ~91% speed. This is not a superiority result.

## Tried, not adopted

The upstream AVX-512 ICL `write_multiple_dirties` (VBMI byte compress and
permute of dirty threats) was ported and kept the bench signature on every
path, but 16 concurrent rounds against the adopted build showed no difference
beyond the VM's noise (median ratios 0.99–1.03 for identical binaries).
