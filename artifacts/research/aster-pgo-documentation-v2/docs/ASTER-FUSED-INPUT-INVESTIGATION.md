# Fused neural input investigation

Status: source-level hypothesis only. No implementation, timing result or
playing-strength gain is established. Complete the current PGO evidence first.

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
