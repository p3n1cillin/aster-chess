# Aster development process (dual track)

Approved by the user on 2026-10-19. Goal: a reproducible path to an engine
that is measurably stronger than current Stockfish, with every step backed by
statistics rather than impressions.

## Two engines from one source

| Build | Command | Bench | Role |
| --- | --- | ---: | --- |
| Upstream reference | `cargo build --release -p aster-core --features upstream-reference` | 1,559,611 | Exact port of upstream commit `effdc3fd3f`; the fixed baseline of every test |
| Aster (default) | `cargo build --release -p aster-core` | `crates/aster-core/BENCH.json` | The playing engine; may diverge through accepted changes |
| Tuning build | `--features tune` | (Aster values) | Every parameter in `src/tune.rs` is a UCI spin option |

Search constants live in `src/tune.rs` with two columns: the upstream value
and Aster's value. `tp!(Name)` folds to a literal in ordinary builds, so the
parameter layer costs nothing. Any other divergent code must be compiled out
with `#[cfg(not(feature = "upstream-reference"))]`. CI checks both signatures
(`scripts/check_bench.py`).

## Testing network

* `scripts/testnet_worker.py --spec testnet/specs/<test>.json --seed N` builds
  the base and candidate engines from Git refs and features, checks their
  bench signatures, and plays color-swapped pairs in batches, printing
  `TESTNET_RESULT` pentanomial lines. Any Linux machine can run it.
* `scripts/spsa_worker.py` runs one SPSA chain (fishtest schedule) on the
  `tune` build; `scripts/spsa_combine.py` averages independent chains.
* `scripts/testnet_job.sh` runs a job inside a Claude cloud worker session and
  commits its log to the session's `testnet/<label>-<worker>` branch;
  `scripts/testnet_collect.sh <label>` gathers those logs.
* `scripts/testnet_sprt.py` aggregates pentanomial results across workers and
  computes the GSPRT log-likelihood ratio (logistic Elo bounds).

The user approved up to 8 cloud worker sessions (4 cores each; roughly
400 games/hour per worker at 10+0.1, 2,400 at 25,000 nodes/move).

## Gates

A change enters the default engine only when, against the current default
engine as base:

1. Exactness/rules: perft, rule and verifier checks pass; speed-only changes
   keep the bench and need timing evidence instead of games.
2. **STC**: 10+0.1, 1 thread, 16 MiB, `UHO_Lichess_4852_v1`, SPRT
   `[elo0, elo1] = [0, 2]` logistic Elo, alpha = beta = 0.05, accepted.
3. **LTC**: 60+0.6, 1 thread, 64 MiB, SPRT `[0.5, 2.5]`, accepted.
   (Simplifications use non-regression bounds `[-1.75, 0.25]`.)

After acceptance, update `BENCH.json`, record the test logs under
`artifacts/testnet/`, and periodically re-measure the default engine against
both the upstream reference and the upstream engine built from source at
equal time (pinned binaries, predeclared size). A superiority claim requires
a predeclared match with a 95% lower bound above zero at more than one time
control, as `ROADMAP.md` defines.
