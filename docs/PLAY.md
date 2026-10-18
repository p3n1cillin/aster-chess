# Play Aster Rust and inspect its search

On Windows, run `./scripts/play.ps1`, then open **http://127.0.0.1:5188**.
The launcher builds and tests Rust, copies the standalone executable to an
immutable local runtime directory, and starts it with a hidden console. Future
builds do not overwrite an active game. Use `-SkipBuild` after a build,
`-Port 5189` for another game, or `-Stop` to stop that launcher's owned host.
Source checkouts on Windows network shares use a local Cargo target directory.

Cross-platform:

```
python scripts/fetch_rust_network.py
cargo build --release --locked
cargo run --release --locked -- play 5188
```

Choose White or Black and a 1, 3, 8 or 15 second reply budget. Click a piece,
then a legal destination; promotions offer all four pieces. Take back a turn,
flip the board, replay earlier moves, analyze without moving, stop a reply,
load a standard FEN or export PGN. Games use native Rust move rules and SAN.
Draw claims are automatic under the host's fifty-move and threefold policy;
checkmate takes precedence over draw clocks. Earlier history before a loaded
FEN is unknown.

The display shows completed-depth neural scores and legal principal variations,
real sampled positions inside search, main/quiescence function calls, beta and
TT cutoffs, null probes, reductions and latest root attempt bounds. Root scores
marked ≤ or ≥ are bounds; unfinished attempts have no completed score. Samples
include hypothetical null passes and are not an exhaustive search recording.
The visit heatmap counts calls by their last destination, including repeated
visits. Geometric control maps include pins and friendly blocker squares and
are not legal-capture maps. Material is a simple piece count, separate from
neural evaluation; no classical decomposition of the neural score is invented.

The proof button searches for a complete mating strategy within five plies and
50,000 visits. A successful export covers every legal defensive reply and ends
only at checkmate. Download its JSON, then run:

```
python scripts/verify_mate_proof.py aster-mate-proof.json --output verified.json
```

The verifier uses ordinary chess rules, without evaluation or any chess engine.
The CLI supports bounds 0..7 and up to 100,000 visits:

```
./target/release/aster.exe certify-mate proof.json 7 white "FEN"
```

Proof limits or unsupported reversible history produce an incomplete result,
not a claim of a draw or loss. Load a FEN to establish an explicit history origin
when needed. The source-derived playing search is heuristic; a prediction in
its principal variation is not a certified strategy.

The HTTP host and its search workers run the same Rust executable. It embeds
all web assets and verified neural weights. It binds only to loopback, restricts
POST origins, caps request bodies and SSE viewers, and uses a self-only content
security policy. No external engine, Python or .NET runtime serves the game.
See [source and measurement provenance](RUST-MIGRATION.md).
