# Aster source naming

The 2026-10-19 source cleanup removes the upstream engine name from editable
Rust, Python, PowerShell, C#, browser assets and workflow source, including source filenames.
The audit covers `crates`, `scripts`, `src`, `tests` and `.github`: **341 files**,
with no matches. Run `python scripts/verify_source_names.py` to repeat the check;
CI runs it before fetching models or building the engine.

This is a naming and metadata refactor. The Rust search, evaluation, move
generation, neural weights, time management and tablebase algorithms are unchanged.
It does not make inherited work independently authored or establish a strength gain.

## Attribution and data

Each affected core source file points to its adjacent `.license` notice. Those
notices preserve the original copyright, license and source-mapping headers
verbatim. The test-count provenance and the legacy optimization citation are
also preserved beside their source files. `AUTHORS`, `Copying.txt`, package
authorship metadata, `UPSTREAM.json` and third-party notices retain the true names.
Ship the adjacent notices with the corresponding source; source freezes include them.

`scripts/research-reference.json` holds the real development-opponent download
URLs, pinned directory names, historical report keys, archive paths and scientific
descriptions. `research_reference.py` loads those values only for development
scripts. The Rust engine does not read this metadata or invoke the opponent.
Historical JSON formats, recorded opponent identities and archived paths retain
their exact values. Frozen research reports, PGNs, datasets, old source snapshots,
documentation and Git history are outside the source-name audit and remain factual.

Fetch the development opponent with `python scripts/fetch_reference.py --tag sf_19`.
The former fetch command has been renamed; current command documentation is updated.
Model fetching remains `python scripts/fetch_aster_network.py`, with the same
SHA-256 and official mirror URLs read from metadata.

## Verification

- Both debug and release profiles pass 140 native tests, and formatting passes.
- All 51 deterministic benchmark searches match the saved baseline, with the
  canonical **2,497,913-node** signature. The single local timing pair is retained
  for transparency; it is not a statistically established speed result.
- Independent checks pass 2,630 positions, 14 perft cases and 94 special-rule
  positions, plus the real HTTP/SSE play interface and eight proof certificates
  covering 42 positions. Five match-recovery tests pass.
- Resolving metadata lookups reproduces the previous syntax trees of all 62
  changed scripts, apart from the documented help/error and source-freeze changes.
  All non-comment lines in the 22 changed Rust files are unchanged.
- The source audit was also checked with injected forbidden comments and filenames;
  both were rejected. Model verification and match/watch command help still work.

See the [source audit](../artifacts/verification/aster-source-names-v2.json),
[metadata comparison](../artifacts/verification/aster-source-metadata-equivalence-v2.json),
[Rust/notice comparison](../artifacts/verification/aster-source-metadata-equivalence-v1.json),
[benchmark transcripts](../artifacts/verification/aster-source-names-behavior-v1.json)
and [179-file source snapshot](../artifacts/research/aster-source-names-v2/manifest.json).
