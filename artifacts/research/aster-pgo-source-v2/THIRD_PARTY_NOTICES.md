# Licenses and attribution

Copyright 2026 p3n1cillin and Aster contributors. Original Aster source,
project-authored documentation and research material are offered under the
GNU General Public License, version 3 or any later version. See [LICENSE](LICENSE).
Existing third-party licenses and notices remain authoritative for their files.

Aster's active engine and web host are built in Rust. The native engine source
is derived from Viridithas 20.0.0, commit
`0631113e2215714c54d397cce9a8caebc5e6f8ee`, released under MIT by Cosmo Bobak.
The original notice is in `crates/engine/LICENSE.upstream-MIT`; per-file upstream
fingerprints are in `crates/engine/UPSTREAM.json`. Later Viridithas releases may
have different terms; this import is the exact MIT release, not current master.
The original README is preserved beside the imported source. Aster's additions
are GPL-3.0-or-later under the project license.

The embedded `sandhi-s2-b200` network is pinned to the official v109 asset and
full SHA-256 in `scripts/fetch_rust_network.py` and checked by the Rust build.
Its author identifies Viridithas networks as CC0-1.0 at
https://github.com/cosmobobak/viridithas#license. Search code and trained weights
retain their upstream provenance; adopting them is not an original Aster
training or Stockfish-superiority claim. C-based optional tablebases and zstd
are disabled; pure Rust `ruzstd` performs decompression.

Since Aster 1.0.0 the default playing core is `crates/aster-core`, a Rust port of
Stockfish 19 (tag `sf_19`) by the Stockfish developers, derived from Glaurung and
licensed GPL-3.0-or-later. Its `AUTHORS`, `Copying.txt` and `UPSTREAM.json` (release,
reference binary, network and per-file source fingerprints) are kept in that crate.
The original per-file Rust headers are preserved verbatim in adjacent `.license`
notices, referenced from each affected source file. Keep those notices with the
source. Test-count provenance and the legacy optimization citation are preserved
the same way. See `docs/SOURCE-NAMES.md` for the source-naming audit and its scope.

The embedded `nn-1a298aa575a0.nnue` network is the official Stockfish 19 network,
pinned by SHA-256 in `scripts/fetch_aster_network.py` and checked by `build.rs`.
The previous Viridithas-derived core remains available as `aster legacy`.

The engine and play host do not invoke the Stockfish executable, python-chess or the
historical C# engine at runtime: the Stockfish-derived core is compiled Rust code.
The official Stockfish binary remains a development reference and opponent.
Cargo.lock records Rust dependency versions and registry checksums.

`artifacts/research/conversion-stockfish19-source/` preserves the official
Stockfish 19 source distributed with the pinned release. It is copyrighted by
the Stockfish developers, derives from Glaurung, and retains its GPL-3.0-or-later
file headers and `Copying.txt`. Its manifest records source fingerprints and
the separately downloaded release binary; this publication makes no claim that
the preserved binary was rebuilt from that snapshot. Other immutable research
snapshots containing that source retain the same rights and notices.
See [Stockfish](https://github.com/official-stockfish/Stockfish).

The five tiny development-oracle tables in `tools/syzygy-development-v1/` come
from python-chess v1.11.2's test data. The manifest records each upstream URL and
SHA-256. They retain that project's GPL-3.0-or-later license, provided beside them
as `LICENSE.txt`; they are never loaded by Aster. python-chess and chess are
separately installed development dependencies under the same license.
See [python-chess](https://github.com/niklasf/python-chess/tree/v1.11.2).

.NET, Python, optional training libraries and CI actions are external dependencies
and retain their respective licenses. Project licensing does not relicense them.

The frozen `artifacts/publish/rust-hyperion-v1` research executable embeds the
CC0-1.0 v111 Hyperion network, SHA-256
`2a7d2ef636767d2cf56bbae12cec42e72845156fc2607bf92bdcfc9c98b03944`.
Its archived source retains the original MIT/GPL notices and pinned CC0 license.
It is an unpromoted experiment, not the production network. See
`docs/RUST-HYPERION-TRIAL.md` for the fixed plan and failed expected-move gate.
