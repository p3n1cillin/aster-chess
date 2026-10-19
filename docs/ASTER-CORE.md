# Aster core identity and behavior-preserving refactor

The engine, standalone core, UCI identity, authorship display, help/license text,
network diagnostics, browser state label and build integration now use **Aster**.
The search library and binary are `aster-core` in `crates/aster-core`, imported
as `aster_core`. Fetch its pinned network with `python scripts/fetch_aster_network.py`.
The development SIMD override is `ASTER_SIMD=scalar|avx2`. Existing external
development scripts using the old names need these new names.

Build with `cargo build --workspace --release --locked`. Run the main UCI engine
with `cargo run --release --locked`, or the core bench with
`cargo run --release --locked -p aster-core -- bench`. The workspace defaults to
the Aster application, so root `cargo run` is unambiguous. Run tests with
`cargo test --workspace --release --locked` and `cargo test --workspace --locked`.
Build helpers and CI fetch both pinned networks and test both crates. Future
source freezes include the actual default core and its network/provenance pins.

This refactor preserves the search, evaluation, move generation, constants,
network bytes, tablebase code and all third-party dependency pins. Source is
formatted using rustfmt. The startup banner is a protocol-clean `info string`;
other identity changes are presentation changes. The browser now identifies the
current Aster application rather than its historical core.

GPL copyright notices, AUTHORS, Copying.txt, upstream source manifests, external
opponent/tool URLs and immutable research evidence keep their real names.
Replacing those with Aster would misidentify contributors, downloads or opponents.
This is a branded derivative with preserved attribution, not a claim that its
upstream work was originally written by Aster.

The [review record](../artifacts/research/aster-branding-review-v1.json) retains
the exact scope and checks. Both build profiles pass **140 native tests**. The
core retains **2,497,913** bench nodes across automatic, AVX2 and scalar paths.
All **51** bench searches preserve every deterministic score/node/PV/bestmove
line; **64** depth-nine positions independently preserve the full results.
Independent checks pass **4,630** positions, **14** perft cases and **94** special
edges, plus real HTTP/SSE, ready/stop, observer equivalence, **8** certificates
(**42** proof positions) and **5** match-recovery tests.

The pre-refactor core and renamed core both score **30/32** on the historical
expected-move suite, with every move and node count identical. This is a baseline
fact, not a newly accepted strength threshold. CI retains the legacy core's
**32/32** gate explicitly in `legacy` mode and separately requires exact agreement
with the frozen default-core tactical report. The failed initial application of
the legacy threshold to the default core is retained in the evidence.

Eight counterbalanced final bench pairs measure a median candidate/baseline wall
time ratio of **0.98645** (1.35% lower elapsed). The paired-median bootstrap
interval is 0.95547..0.99899 (20,000 samples, seed 20261019). This is a small local,
unisolated timing check: it shows no measured slowdown in that run and does not
prove exactly identical speed or a reproducible gain. An earlier identity-only
build's eight pairs measured 1.02559; both runs and full transcripts remain
preserved. The final binary additionally includes the corrected browser identity
and protocol-clean startup banner; it is the binary used by the broad checks.
No search tuning or model changes were made in response to timing results.

The [153-file source capsule](../artifacts/research/aster-branding-source-v2/manifest.json)
pins the actual default core, legacy source, weights, compiler and helpers. Both
exact executables remain in the local development cache, with fingerprints in
the plan and result records. Historical match reports and fingerprints are
unchanged. No playing-strength or Elo increase is claimed from this refactor.

The initial CI run [39222407138](../artifacts/ci/aster-branding-39222407138.json)
failed at the original download server (HTTP 403), before compilation. The
fetch helper now falls back to a commit-pinned official mirror and verifies the
identical full SHA-256. A fresh download passed locally; network bytes are unchanged.

Pre-existing documentation updates for the completed speedtest command and
tablebase development instructions were carried forward through the crate rename.
