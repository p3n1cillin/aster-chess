# Version control

The project is maintained in the private GitHub repository
`p3n1cillin/aster-chess`. Source, tests, experiment plans, immutable source
snapshots, engine packages, datasets, trained checkpoints, reports, PGNs and
rating evidence belong in version control. Every frozen file retains its exact
bytes: `.gitattributes` disables line-ending conversion so SHA-256 manifests
survive checkout on another platform.

Local Python environments, build output, Python caches, IDE user settings and
credentials are ignored. Stockfish is a development tool only. Its release
manifest is tracked; downloaded third-party executable/archive files stay local
and can be fetched again with `scripts/fetch_stockfish.py --tag sf_19` on Windows.
The original pinned Stockfish source snapshot and license are retained among
the research evidence. No Git LFS or paid storage is required for this initial
repository: the largest tracked file is below GitHub's ordinary file limit.

Commit meaningful research milestones and push them after local checks.
Experimental candidates remain opt-in until their frozen gates pass. Store
immutable reports before summarizing them; do not replace a failed experiment
with a successful rerun. The existing CI workflow builds and checks the engine
on Windows and Linux for each push and pull request.
Its matrix covers both the ordinary build and the opt-in IIR candidate, with
unit/rule/protocol checks, both tactical suites at depth/node limits, endgame
diagnostics and the depth-seven benchmark.
Changes confined to research artifacts or Markdown documentation skip these
build jobs; source, scripts, test fixtures and workflow changes trigger them.

```powershell
git status --short
git add <changed-paths>
git commit -m "Describe the verified change"
git push origin main
```

Review staged paths before committing, especially generated files. A new clone
can build and run the independent engine without Stockfish or Python. Research
reproduction also needs the documented development dependencies and pinned
external engine downloads.
