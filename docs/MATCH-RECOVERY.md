# Match interruption recovery

The development match runner writes each completed game's full detail and PGN
into an append-only journal, flushes and fsyncs it, then updates the readable PGN
and replaces a complete JSON snapshot atomically. Replacement uses bounded
retries. If replacement still fails, the previous snapshot and temporary payload
remain available. Engine runtime code does not depend on this Python tooling.

To continue an interrupted fixed sample, pass `--resume-prefix OLD` together
with a **new** `--output NEW` and the original engines, openings, resource limits
and options. The runner validates the ordered outcomes and configuration before
skipping exactly those completed games. Existing files are never overwritten.
A journal preserves per-move telemetry even if the later snapshot fails.

Legacy reports without a journal may have one complete PGN game beyond the last
JSON snapshot. Its moves and outcome can be recovered after independent rules
validation; missing telemetry and wall time are explicitly marked unavailable.
Ambiguous boundaries, changed configuration, engine forfeits and truncated journal
records stop recovery for investigation. This does not guarantee recovery from
all storage failures or power loss. Aggregate elapsed time after journal recovery
can omit time unavailable from the last header; individual saved game timings
remain recorded. Never infer a benchmark duration from missing timing data.

Five storage-fault tests exercise snapshot replacement failure, full journal
recovery, legacy PGN recovery, changed configuration, ambiguous extra games and
truncated records. Run `python -m unittest discover -s tests -p test_match_recovery.py`.
Both Windows/Linux CI include them before native Rust verification. Future source
freezes include the imported recovery helper.

The first use is documented by the
[Hyperion recovery addendum](../artifacts/research/rust-hyperion-recovery-addendum-v1.json).
Its old report preserves 82 games and its PGN preserves 83. The resumed sample
starts at game 84, keeping game 83's complete outcome and moves while marking its
missing telemetry. The original binary/source archive is unchanged; the
[runner overlay](../artifacts/research/rust-hyperion-recovery-source-v1/manifest.json)
identifies the exact new development scripts. The neural candidate remains
unpromoted because it missed the predeclared tactical gate.
