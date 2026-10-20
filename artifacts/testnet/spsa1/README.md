# spsa1: first distributed SPSA run (2026-10-19/20)

Eight independent SPSA chains (one Claude cloud worker each, 4 cores) tuned all
48 parameters of `crates/aster-core/src/tune.rs` from upstream values, at
10+0.1, 1 thread, 16 MiB, `UHO_Lichess_4852_v1`, engine commit `24593c4`,
fishtest schedule (planned N = 500, 6 pairs per step, seeds 101-108).

Outcome: the chains stopped early, between 01:15 and 03:17 UTC, at 70-130
steps (9,720 games in total), because the worker containers restarted and the
detached jobs did not survive. `combined.json` is the games-weighted average.
No parameter moved more than 0.6% from its upstream value, which is within
SPSA noise at this sample size. Nothing was adopted and no SPRT was run; the
default engine still equals the upstream reference (bench 1,559,611).

Lessons for the next run: detached jobs in worker containers do not survive a
container restart, so a worker must check for a dead job on every poll and
resume it from its last `SPSA_STATE` (not yet implemented); and fishtest-scale
tunes use roughly 60,000-150,000 games, about 6-15 times this run.
