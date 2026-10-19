# Upstream candidate and idea screens (2026-10-19)

Exploratory screens after the Linux speed work. None changed the production
engine; the bench remains 1,559,611.

| Idea | Evidence | Outcome |
| --- | --- | --- |
| Exact evaluation cache beyond the TT | Instrumented bench at depth 16: 0.1% of network evaluations repeat a previously evaluated position | Rejected: no headroom |
| Lazy quiescence evaluation (skip the network when parent eval minus captured value clears beta by a margin) | At a 500 cp margin only 8% of tt-miss quiescence evaluations qualify, and 10% of those are wrong cutoffs | Rejected: inaccurate |
| Newer upstream networks `nn-781ae35764f5`, `nn-087407b9caf7` | Different architecture hashes; fishtest gains are at equal nodes or 100+1 only, rejected at 10+0.1 in real time | Not ported |
| Upstream `lmr_rescale_reduction` (fishtest STC +2.5 Elo, LTC trending negative) | Port gives bench 1,320,511, identical to upstream commit `0159167`. Local check vs exact baseline, 25,000 nodes/move, 600 UHO pairs (seed 4242): 317W/327L/556D, -2.9 +/- 10.9 Elo | Not adopted; log and PGN here |
| Per-move overhead | `go` latency 0.2 ms vs 0.14 ms upstream | Negligible |
| Machine-speed-dependent time management | Upstream master has none | No opportunity |
