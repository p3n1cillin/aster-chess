# Fused neural input investigation

Status: completed, **not adopted**. The implementation passes arithmetic and
runtime checks but fails its prospectively fixed timing gate. The original
active source is restored; exact candidate sources remain archived in
`artifacts/research/aster-fused-input-source-v1` and Git history.

The plan (`artifacts/research/aster-fused-input-plan-v1.json`, committed
`d03935b2`) precedes implementation and candidate queries. It fixes 64 fresh
roots, excluding 70 prior suites, one fusion policy and conditional matches.
The candidate is SHA-256 `fbb3fa6c328c4702b484d93545f2c2495200686553782fff5f6805f3db0c3ce6`;
the ordinary control is `6b4d46db1b89ba9b3fd228121ac931f7791972ef3cc0e1865d00b37f96fb69e2`.

Arithmetic checks cover 1,161 extreme, seeded-random and single-active-byte
fixtures against scalar transform/affine oracles and exact old index ordering,
plus the aligned runtime handle. This host supports all required ISA features.
Feature release/debug each pass 160 native tests plus two compile-fail examples;
default configurations pass 157 plus two. All 51 canonical traces (1,559,611
nodes) and 64 fresh depth-nine roots agree in all three SIMD modes. Tactical,
independent rules/perft/edge, actual HTTP/SSE, proof, readiness/stop and root
restoration checks pass. Correct arithmetic does not establish useful speed.
Windows and Linux CI pass on candidate revision `525e4ecd`; the Windows final
feature branding/signature pass is also preserved from its completed job log.
The API's stale step snapshot is retained separately rather than relabelled.

| Mode | Batches | Median candidate/control elapsed | Batch 95% interval | Gate |
| --- | ---: | ---: | --- | --- |
| Automatic | 12 | 1.02665 | 1.02124..1.03248 | Fail |
| AVX2 | 8 | 1.00694 | 1.00106..1.01890 | Pass |
| Scalar | 8 | 1.01573 | 1.00283..1.02102 | Fail |

Lower ratios are faster. AVX2's small regression fits the declared engineering
tolerance; automatic and scalar fail. All 28 batches are retained. No parameters,
flags, extra timing runs or variants are selected using these results. The
conditional 64 paired openings (128 games) remain unused, as specified before
the trial. No playing-strength result or Elo follows from this experiment.
The cause of the regression is not measured; do not attribute it to a particular
copy, register spill or cache effect without a separate diagnostic.

Ordering deviation: the plan's wording can be read as alternating AB/BA for
each root within a batch. The checker alternated order between whole batches,
using that order for every root in each batch. Every root still has equal runs
in each direction, but a literal per-root reading was not followed. Treat this
trial as ineligible for adoption independently of the failed speed gate. No
rerun replaces these outcomes; future plans must state this ordering explicitly.

The original hypothesis and requirements are retained below. Further work should
profile the unchanged automatic path and select a distinct measured bottleneck,
rather than tune this failed variant to these roots.

A fresh build after source restoration initially failed a full-file hash
identity assertion. The rebuilt executable is preserved. Independent section
comparison and a byte-level check locate all 23 differing bytes in PE timestamps
and the CodeView debug GUID; every other byte matches. This is linker metadata,
not a change in generated instructions. The original pinned playable binary is
restored and its branding/canonical checks pass. See
`artifacts/verification/aster-fused-input-restored-metadata-v1.json`.

## Original source-level hypothesis

`Network::evaluate` currently transforms two perspectives into 1,024 bytes.
The AVX-512 sparse affine kernel rereads those bytes in `nnz_vbmi2` to collect
nonzero groups of four bytes. The proposed engineering experiment would retain
each pair of transformed 64-byte vectors in registers and collect the same
indices before storing the input. This removes the separate input scan, but
may increase register pressure enough to lose time. Kernel fusion is an
established optimization; no global novelty is claimed.

Use the same pairwise transform, lane permutation, saturating pack, index
permutation and 16-bit compression as the existing path. Process pairs of
vectors within each perspective, retaining the original nonzero index order.
Keep fallback paths for AVX-512 without VBMI2, AVX2 and scalar. Do not change
neural weights, search decisions, move ordering or ordinary compiler flags.

Arithmetic constraints from the existing implementation: each transformed byte
is at most `floor(255 * 255 / 512) = 127`. Thus each packed four-byte signed
32-bit group is nonnegative, and saturation to signed 16-bit preserves whether
the group is zero. The current compression index vector compensates for the
128-bit lane interleaving introduced by the pack; preserve that compensation
exactly. Use side-to-move perspective first, as the current network does.
Generate indices in pairs of transformed vectors to retain the old compression
width. This is a source-level equivalence argument to test, not proof that
fusion will be faster on this CPU.

Required checks before candidate timing:

- Compare all transformed bytes and ordered nonzero indices against the old
  implementation. Include zero/dense inputs, saturation boundaries, negative
  accumulator extremes, single active four-byte groups and seeded random data.
- Compare affine sums against both the old kernel and scalar arithmetic;
  exercise output slack limits and both perspective boundaries.
- Preserve all 51 canonical traces and the 1,559,611-node signature in every
  SIMD mode, plus fresh deterministic roots, tactics and independent rules.
- Establish normal-return buffer initialization and lifetime safety; do not
  expose uninitialized list slack as initialized Rust references.

Before implementation or candidate queries, separately commit a fixed plan
with exact source/binary hashes, fresh roots, one concrete fusion policy,
counterbalanced timing, thresholds and a bounded paired-match gate. No tuning
to the current PGO roots or results. Use matched ordinary builds rather than
the rejected PGO artifact. If timing fails, preserve the candidate without
promoting it; do not infer playing strength from a kernel microbenchmark.
