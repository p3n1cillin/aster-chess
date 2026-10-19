# Aster cache architecture experiment

This is a substantive Rust storage/API rewrite, starting from commit `53e6fc0`.
It replaces the transposition table's raw-pointer write handles and fabricated
entry slices with typed buckets, borrowed write leases and checked indexing.
The cache's thread-sharing traits now follow from its atomic fields rather than
a manually asserted unsafe implementation. Prefetch still uses the architecture's
intrinsic; the rest of the cache implementation needs no unsafe block.

The new API prevents retaining a writer after its table is dropped or resizing a
table while a writer remains in use. Two compile-fail documentation checks exercise
those restrictions. Cache tests cover colliding keys and stable replacement ties,
generation wrapping, zero tags, extreme hashes, shallow writes, mate-score aging,
depth penalties, clear/resize and concurrent access. Invalid zero-sized allocation
requests are rejected before lookup. The surrounding search engine still uses its
existing engine-owned shared-state pointer; this change does not claim to prove
the whole engine's memory safety.

To preserve behavior, buckets still occupy 32 bytes and contain three ten-byte
slots. Tag selection, packed metadata, replacement/aging policy, atomic ordering,
search parameters and neural weights remain fixed. Search copies its shared-state
handle locally before borrowing a cache lease, allowing recursive worker mutation
without discarding the lease's table-lifetime constraint.

The [predeclared plan](../artifacts/research/aster-cache-architecture-plan-v1.json)
requires exact benchmark/depth/tactical equivalence, native and independent checks,
16 counterbalanced timing pairs and 96 audited regression games. Timing and game
results determine whether this candidate is accepted; a source rewrite alone is
not a speed or strength result. No parameter tuning or extra match games are
authorized by the outcome of this experiment.

This is one stage of a larger modernization. Aster still inherits its search and
evaluation algorithms and uses the same trained weights. The unchanged benchmark
is deliberately recognizable. Original notices remain in their adjacent files,
and provenance and historical results retain their true identities. A full
independent implementation would also need independent evaluation/training and
new playing-strength evidence; it cannot be guaranteed to preserve performance.
