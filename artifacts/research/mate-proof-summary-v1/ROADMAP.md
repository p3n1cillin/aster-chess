# Research roadmap

## Success criterion

"Smarter than Stockfish" is operationalized as stronger standard-chess play
under equal resources, rather than a larger depth number or a favorable puzzle.
The eventual target is a reproducible match against a pinned, then-current
full-strength stable Stockfish, with a score above 50% and a statistical lower
bound above 50% under a predeclared test. Repeat at multiple time controls and
on another machine, use a broad held-out opening set, swap colors, and account
for dependence between games sharing an opening.

This target is not achieved. There is no guarantee that the available methods,
hardware, training data or time will achieve it. Stockfish is a moving reference;
keep an older pinned opponent for historical comparisons and add newer releases
as separate reference points.

The user also requests a distinctive ability beyond Stockfish's native
interface and a current rating at each session end. Aster now exports complete
queen/rook mating strategies and bounded general-material mating strategies
with native explanations and independent rule-only verification; extend this
toward useful non-mating general explanations and
proof-backed plans. This does not replace the original playing-strength goal.
The matched 0.7.6-q-evasion build now has a provisional local reference-setting
estimate of 2319 (95% family interval 2277..2360) at 30 ms per move, one thread
and 64 MiB hash. All 576 predeclared regression/confirmation games are audited.
The ordinary 0.7.6 build repeats all 416 saved candidate traces, but the rating
stays attached to the exact matched candidate. The earlier 2300 estimate has
an overlapping interval; no rating increase is established.
Public Elo remains unestablished; report the named scale, rated binary and
uncertainty at each session end. Extend measurement across controls and
reference engines using fresh confirmation for changed playing code.
See `docs/STRATEGY-PROOFS.md` and `docs/RATING.md`.

General-material mate certificates now pass independent replay on25 examples,
all36 legacy strategies and64 seeded three-ply oracle comparisons. Native
explanations remain responsive during concurrent infinite search and can be
cancelled. Playing files remain identical to frozen0.7.8, all32 fresh depth-eight
outputs agree, and32 complete paired regression games are independently audited.
All four Windows/Linux default/IIR CI jobs also verify current-build certificates.
This expands the distinctive native ability without establishing a playing
gain. See `docs/GENERAL-MATE-PROOFS.md`; next prioritize stable endgame
supervision and feature interactions for measurable playing-strength progress.

## 1. Correct, measurable foundation

Implemented: legal standard chess, bitboards, UCI, classical evaluation,
selective alpha-beta search, reference perft, differential verification,
search/protocol tests and a paired match harness.

Added a frozen 64-position opening regression suite, with legal history,
transposition deduplication, bounded teacher balance checks, training-data
exclusions and suite hashes. Match reports can retain per-move depth, nodes,
scores and elapsed time. Opening-cluster analysis remains exploratory.

Next: broaden tactical and endgame suites; independently verify static exchange
edge cases and draw-history effects on transposition-table cutoffs; add sustained
protocol fuzzing. Expand regression sampling across fresh opening seeds and
longer controls. Reserve separate held-out suites for final claims. Every search optimization
must retain cancellation safety and legal principal variations.

## 2. Stronger search and evaluation

- Profile the engine before optimizing its hot paths. Measure search effort,
  speed and playing strength separately.
- Test static exchange pruning, improved history and continuation ordering,
  verified pruning, singular extensions and time management one change at a time.
- Add a pawn/evaluation cache, stronger king safety and endgame scaling, with
  parameters tuned on training data and confirmed on held-out matches.
- Add optional Syzygy probing and parallel search with equal-resource comparisons.
  Keep a single-thread reference mode for reproducible experiments.

Reject changes that only improve a tiny puzzle suite or an isolated speed metric.
Preserve baseline binaries locally and save PGN plus JSON for every accepted run.

Implemented compile-time search profiling and a verified faster legal-move
predicate in 0.5.0. A quiet-history penalty alone was inconclusive and rejected.
The legal predicate preserves fixed-depth work and has paired match evidence;
its longer-control regression sample is positive but does not establish a general
rating. Shared attack maps preserve static scores and fixed-depth search work.
A coordinated king-pressure term passed tactics but was rejected after a
46.9% score in its 64-game ablation match. See `docs/EVALUATION.md`.
History-guided extra depth and countermove ordering were tested independently
against 0.5.1 and rejected after paired matches. A fresh 64-position third
opening suite and reduction-use profiling are preserved with the evidence.
See `docs/HISTORY-REDUCTIONS.md` and `docs/COUNTERMOVES.md`.
Guarded late quiet move pruning cut fixed-depth work substantially but did not
establish a strength gain across 160 paired games, including fresh longer-control
openings. It was removed from the default. A new quiet-move tactical suite,
fourth opening suite and verified native-source match provenance remain.
See `docs/LATE-QUIET-PRUNING.md`.
Next, target stronger king-safety/endgame features and learned evaluation;
simple ordering/depth heuristics alone have not produced the required gains.

Seven fitted geometric threat features reduce held-out static teacher error.
Their separate build has a positive but inconclusive 55.47% point estimate in
64 audited games on a new v5 opening suite, but loses two quiet endgame tactics
solved by the baseline. The correction remains disabled in the ordinary build.
All default static scores and fixed-depth work are preserved. Investigate fresh
endgame positions and outcome/search-label coverage next; do not tune to the
two known fixture answers. See `docs/GEOMETRIC-THREATS.md`.

An original opt-in KPK win attractor now has exhaustive WDL agreement and
independently certified conversion bounds. It improves a frozen move-choice
sample from 246/256 to 256/256 at equal nodes while retaining both tactical
suites. Broaden sparse endgame tests and controls before promoting it; general
tablebase probing and parallel search remain future work. See `docs/KPK.md`.

Complete KPK games expose post-promotion repetitions despite correct theoretical
choices. A separate original KQK/KRK mate attractor now passes exhaustive WDL
and exact distance recurrences, and guarded root progress converts every tested
initial pawn-side win against control and Stockfish at a diagnostic node limit.
Confirm broader equal-time play and histories before promoting it. These selected
endgame results do not establish general strength. See `docs/ENDGAME-CONVERSION.md`.

Deferred capture scoring preserves 336 complete deterministic traces and
reduces profiled SEE calls by 6.66%, but warm same-work speed improves only
0.66%. It scores 57.42% in 128 fresh games at 30 ms and 46.88% in 32 distinct
games at 100 ms. Both declared promotion gates fail; the alternative stays opt-in.
See `docs/DEFERRED-CAPTURES.md`.

The duplicate check-evasion legality query is now removed in ordinary 0.7.6
after all frozen engineering gates pass. It retains 416 complete search traces,
avoids 27,464 profiled existence queries and improves warm same-work speed by
5.29%. Fresh paired regressions score 52.93% in 256 games at 30 ms and 50% in
64 games at 100 ms, with intervals containing 50%. A separate 256-game local
rating confirmation is preserved. See `docs/QUIESCENCE-EVASIONS.md`.
Next pursue more capable search/evaluation rather than interpreting this
same-work speed gain as a demonstrated strength increase. Broaden endgame
coverage and proof-backed plans alongside the playing-strength work.

An opt-in one-ply reduction of deep unseeded secondary nodes preserves
root/PV/check/history/late-clock/pawn-only boundaries and stores only searched
depth. Correctness, tactics and limit/undo checks pass. All 640 independently
audited games finish: 51.37% at 30 ms and 51.56% at 100 ms, with 95% family intervals
48.20%..54.52% and 45.49%..57.79%. The declared short-control confidence gate
fails, so the alternative stays disabled and 128 reserved rating openings are
unused. See `docs/INTERNAL-REDUCTIONS.md`. Next prioritize broader, stable
supervision and phase-aware learned evaluation, confirmed in actual search
and paired matches. Continue extending native proof-backed plans alongside
the playing-strength work.

## 3. Learn an evaluation

Implemented: a versioned original network format, lazy incremental integer
accumulators, scalar/vectorized inference agreement checks, bounded data
generation, game-separated training/validation and quantized export. Three
initial models regressed in matches and remain experimental; the classical
evaluator is the default. See `docs/NEURAL.md` for the evidence.

Added optional king-region-conditioned piece features, independently checked
incremental inference and vectorized integer output. A second audited dataset
contains 50,000 bounded teacher-labelled positions, excludes exact regression
positions and supplies a whole-game validation split. Four compact models
improve validation teacher fit modestly but all regressed in 32-game paired
matches against frozen classical 0.5.1. Version 0.6.0 releases the optional
inference capability while retaining the classical default.
See `docs/KING-CONTEXT.md` for the architecture, data provenance and results.

Experimental formats 5/6 add side-to-move-dependent output and preserve
integer inference and null-move cache correctness. A 128-pair counterfactual
diagnostic exposes the fixed-tempo limitation of earlier models. An audited
60,000-position dataset adds 10,000 opposite-turn labels while retaining
parent game groups and all original rows. Initial turn-aware models and both
paired-data retrained models regress against 0.6.0; the classical default remains.
See `docs/TURN-AWARE.md`. Next, test richer nonlinear feature interactions;
adding turn-dependent output alone has mostly learned an average tempo.

Squared clipped hidden activation (experimental formats 7/8) adds interactions
inside the unclipped range and retains verified integer bounds. Two models
regress, while a larger-initialization hybrid reaches 50% in a small paired
sample but fails one original tactical position. All 96 games are audited;
no learned default or strength gain is selected. Isolate initialization with
an activation ablation, then broaden controls and examine target/feature
coverage. See `docs/SQUARED-ACTIVATION.md`.

The larger-initialization activation ablation and two static-label models
have 192 audited paired games. Static clipped activation's positive short
screen did not confirm on different openings at a longer control. The new
60,000-position static dataset preserves source labels/groups, passes
independent re-query and provenance checks, and separates source search
budgets from current labels. Test direct paired-turn supervision and tactical
feature coverage next; no learned default is selected.
See `docs/LABEL-INITIALIZATION.md`.

Direct paired-turn supervision now improves moderate-weight held-out difference
error and learned variation while retaining the whole-game split. Its two
models have 64 audited paired games: the moderate model scores below 50%,
while the heavier model's inconclusive positive screen fails quiet tactics.
Neither qualifies for the predeclared longer confirmation. Retain this optional
training objective; investigate tactical feature and label coverage next.
See `docs/PAIR-LOSS.md`. The classical default is unchanged.

Phase-conditioned turn-aware output (formats 9/10) passes 53 engine tests and
7,350 independent inference comparisons. A matched training control reproduces
the earlier model exactly; shared initial weights/RNG, data and budgets match.
The phase model's 128 audited paired games score 60.16% against that control
(95% family interval 52.50%..67.42%), but only 38.28% against classical 0.7.6
(27.42%..49.19%) and lose two quiet depth-eight tactics. Both promotion gates
fail; longer confirmation is skipped, with 16 reserved pairs unused. This
limited neural ablation improvement does not establish broad strength.
See `docs/PHASE-OUTPUT.md`. Broaden stable endgame supervision and feature
interactions separately; preserve the classical default and fresh confirmation.

Next, extend feature interactions and the reproducible data pipeline using
diverse legal self-play positions and scored outcomes or explicitly documented
teacher labels. Partition by game to avoid train/test leakage; remove duplicate
and terminal positions and retain provenance, search budget and model hashes.

Expand the compact prototype and keep verifying inference against the training runtime.
Measure strength in the actual search, not just validation loss. Quantize only
after establishing numerical agreement and acceptable match results. Teacher
distillation is a starting point, not evidence of exceeding the teacher.

## 4. Research beyond the reference

A fresh 512-position endgame diagnostic preserves full source histories,
native mate/centipawn labels at multiple budgets and source outcomes, including
seven unresolved games. It adds a frozen 16-position move suite confirmed at
262,144 nodes. Broader label instability and limited coverage within the prior
score window motivate fresh balanced endgames and target-stability checks
before fitting again. Source outcomes are descriptive, not oracle labels.
See `docs/ENDGAME-DIAGNOSTIC.md`.

Run self-play and outcome-based learning against a pool of historical engines;
investigate targeted weaknesses using held-out matches. Compare hybrid search
and evaluation approaches using matched resource budgets. Preserve ablations
so gains can be attributed to search, evaluation, data or hardware.

Large training or tournament runs will need explicit resource planning. Do not
start paid services or unbounded background jobs implicitly. Local bounded
experiments can proceed while the architecture is being validated.

## 5. Demonstrate superiority

Freeze the candidate, opponent, options, hardware, time controls, adjudication,
opening suite and statistical stopping rule before the final test. Use enough
paired games to distinguish the hypothesized improvement, save every game,
report unresolved outcomes and failures, and independently reproduce the result.
Publish the evidence and practical limits alongside any strength claim.
