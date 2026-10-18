# Aster Rust engine

Native Rust source foundation derived from **Viridithas 20.0.0**, commit
`0631113e2215714c54d397cce9a8caebc5e6f8ee`. See `UPSTREAM.json` for original
file hashes and `LICENSE.upstream-MIT` for the pinned release's MIT notice.
Original upstream documentation is preserved in `README.upstream.md`.
Aster modifications are GPL-3.0-or-later; the upstream MIT notice remains intact.

From the repository root:

```
python scripts/fetch_rust_network.py
cargo build --release --locked
cargo test --release --locked
cargo run --release --locked -- play 5188
```

The executable includes native move generation, search and NNUE evaluation,
Aster's bounded strategy proof solver, and the Rust HTTP host with embedded
presentation assets. No external chess engine, C/C++ compiler or .NET runtime
is needed. Optional C-based Syzygy probing and C zstd features are disabled.

The trained network comes from the original author; see `NETWORK.json` and
`LICENSE.network-CC0.txt`. It is fetched at build setup, SHA-256 checked by the
Rust build, and embedded in the standalone executable. Runtime decompression
uses the Rust implementation `ruzstd`.

Current playing strength must be measured for this exact fork. Neither its name
nor adoption of upstream code establishes an Elo or superiority over Stockfish.
