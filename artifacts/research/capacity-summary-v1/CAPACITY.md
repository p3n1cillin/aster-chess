# Nested hidden-capacity experiment

This experiment compares H64 and H128 on identical data and training objectives.
The declaration precedes initialization, new training and candidate match
queries: `artifacts/research/capacity-plan-v1.json`, SHA256
`7db54c8e65f7a0578ac16011416a6bd18f92755e95aa8e3df906d6dbe95481d0`.
The prior fresh-pair loss candidate regressed in play. Both capacity models
therefore use the prior stronger control's old static-pair weight 1 and fresh
pair weight 0. No data, split, targets, loss weights or epoch budgets differ.

The common 63826-row dataset retains the old 60000 byte-identical rows and
1913 fresh deep-labelled White/Black pairs. The inherited split has 6050
ordinary held-out rows and 180 fresh held-out pairs. Counterfactual Black
positions have no fabricated observed outcomes. All prior teacher/source
provenance, finite-label selection and endgame-source limits still apply.

Initialization preserves every H64 transformer column, linear weight, bias
and four output blocks in H128. Extra ordinary-feature columns use an independent
fixed seed; extra king-context/padding columns start zero and extra outputs
start zero. This keeps the initial function while allowing extra outputs to
learn. Both checkpoints restore the same post-H64 initialization RNG before
all batch shuffles. Complete tensor shapes differ; there is no claim that the
complete parameter states or optimization geometry are identical. The initial
functions agree exactly on all 63826 rows. Eight malformed/valid checkpoint
cases and an independent extra-output numerical gradient check pass.

Both 50-epoch trainings are complete. H64 reproduces the prior control model
byte for byte, including selected epoch 9, full initial state/RNG and every
epoch's batch fingerprint. Candidate selects epoch 8; all ordinary, old-pair
and fresh-pair batch orders match. The selected model fingerprints are:

- H64: `460736dd293709d72817ba1bee67e3186edabd097c456fc61ad0425d2a6b7725`
- H128: `668b96e42471d4ca20605ced76134caec8c99aba90db1aa95fdd1afbc44e181e`

Overall quantized held-out MAE is 131.5398cp versus 131.5549cp. On 360 fresh
positions it is 201.5889 versus 201.6444cp; fresh pair-difference MAE is
179.6222 versus 180.0667cp. These fit metrics show no material improvement.
The same epoch count is not equal training compute: local elapsed time is
126.13 versus 174.57 seconds. Fit metrics do not select a playing model.

Both models pass 525 exact Python/C# inference comparisons and 2614 independent
rules/protocol cases. The required build, 55 native tests, default independent
verification and depth-seven benchmark pass. All 24 runtime source files match
the frozen baseline; a metadata-only rebuild agrees on all 32 checked depth-eight
moves, scores and node counts. Matches use the original frozen `ac907eac...` DLL.
No runtime code or dependencies change to support H128.
Setup commit `8c234a3` also passes all four GitHub CI jobs on Windows/Linux
with default/IIR builds; the completed report and its fingerprint are retained.

Original tactics are 32/32 at depth 8 and 5000 nodes for both models. H64 quiet
depth/node scores are 30/32 and 24/32, with 13/16 endgames. H128 scores 32/32,
24/32 and 12/16. Candidate misses the quiet-node minimum 25 and endgame minimum
13. Correctness permits the two short screens; these tactical failures block
longer confirmation.

An original BCL-only cost harness links the exact frozen engine assembly and
runs a frozen trace over 32 old and 32 fresh held-out roots. Two sorted legal
moves per root cause make/evaluate/undo/evaluate work, with root/FEN/hash/score
restoration and repeatable checksums. Three warmup rounds precede nine measured
rounds; each role occupies each execution-order slot equally. No training or
match job contends with this measurement. Median round times are 8.8607ms
classical, 27.5918ms H64 and 43.8127ms H128: H128 costs 1.5879 times H64 on
this workload. All raw samples, source, trace and exact harness/runtime binaries
are retained. These are local evaluation-cost measurements, not broad search
speed, strength or a promotion gate. No tuning responds to the timing.
A later read-only audit independently replays all 64 roots and 128 legal child
positions with python-chess, verifies full raw-FEN restoration and matches every
measured checksum using cold classical scores plus Python quantized inference.
This adds no timing queries, filters, gates or model selection.

The frozen playing plan reserves 160 fresh opening pairs: 64 against classical
and 64 against H64 at 30ms/move, then 32 against classical at 100ms/move only
if all gates qualify. Both short screens finish despite tactical failures.
Family-bootstrap confidence gates and zero forfeits/unresolved requirements
remain unchanged; there is no adaptive extension or retuning.

The classical short screen is complete: 18 wins, 37 draws and 73 losses,
28.515625% score, with 95% family interval 22.265625%–35.0000% over 57
families. All 128 PGNs pass independent audit with no forfeits or unresolved
games. The classical confidence gate fails; the matched-control screen is
also complete: 35 wins, 51 draws and 42 losses, 47.265625% score, with 95%
family interval 40.5738%–53.5714% over 55 families. That interval includes
50%, so a relative strength change is unestablished; both its point and lower
bound miss the declared control gate. All 256 PGNs pass audit with zero
forfeits or unresolved games. Tactics, classical confidence and control gates
fail. Longer confirmation is skipped; 32 reserved pairs remain unused by
Aster. No weights, epochs, samples or gates are retuned; classical remains
the default and neither learned model is promoted.

The additional match-metadata audit confirms exact evaluator/source hashes,
applied resources, controls, ply caps and frozen opening partitions. Saved first
searches at identical full opening histories have median candidate/classical
depths 6/7 and median paired node ratio 0.453. Candidate/control depths are
6/6 and the ratio is 0.905; 51 of 64 initial moves agree. Changed evaluations
also change search trees, so this descriptive execution evidence is not an
isolated speed measurement or proof that cost alone causes the playing result.

The experiment establishes no benefit from doubling this model's width at
the declared budget. It motivates isolating richer feature interactions and
static/deep supervision compatibility while measuring inference cost, rather
than assuming width alone is the missing capability. The complete source,
initial/final checkpoints, data references, cost trace, raw timings, diagnostics,
reports and PGNs are preserved by `scripts/preserve_capacity.py`. The
[session record](../artifacts/ratings/session-20261004-capacity.json) retains
the exact prior calibrated reference.

Neither model is currently promoted or calibrated. Last exact measured rating
remains 2319, local 95% interval 2277–2360, on the SF19 UCI_Elo-setting scale
at 30ms/move, one thread and 64MiB hash. Public Elo and superiority to
full-strength Stockfish remain unestablished.
