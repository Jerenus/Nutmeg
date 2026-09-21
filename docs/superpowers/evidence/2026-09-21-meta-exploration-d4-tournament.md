# Meta-Exploration D4 Tournament As-Built

Date: 2026-09-22
Spec: `docs/superpowers/specs/2026-09-21-dream-rsi-meta-exploration-v1-design.md`
Plan: `docs/superpowers/plans/2026-09-21-dream-rsi-meta-exploration-d4.md`

## Review Result

D4 implementation is complete at the isolated-code/fixture level. The approved
selection contract is content-addressed (canonical SHA-256
`1a125fc0b0912bc435a36e10a9b6f389f25af5bfa0256102f7d641c4aeea459f`).
It fixes D0 tier order, all quality fields, units, materiality, unknown-value
treatment, incumbent tie, and zero worst-stratum decline. The approval was Jun's
"可以，继续" after the full artifact and hash were presented; no live-run authority
was inferred. The D0 pilot and incumbent artifact were not changed.

The D4 implementation has strict declarative baseline variants, sealed world-pool
readiness and derivative-cluster checks, replay-derived scores, independent
selection and proof checking in the completion Action, atomic holdout exposure,
bounded archive decisions, and read-only tournament detail. The completion Action
recomputes each score from the persisted sealed tree and exactly one replay trace,
then derives the winner rather than trusting a supplied claim. Archive admission
does not change the winner; full-capacity retirement is limited to the oldest
dominated behavioral clone and exactly the space required. Weighted action
histogram Jaccard distance enforces the frozen 0.2 diversity minimum.

An explicit replay preparation entry point validates every registered artifact
and sealed world before filling missing D3 cells. Frozen tournament preparation
remains read-only. Temporary-store tests recompute the same 60-cell matrix and
selection proof twice, finish through the Action, and verify the exposed holdout
slice. Report projection includes each cell, comparison reasons, per-stratum
quality metrics, worst-stratum limit, holdout dates, archive decisions, exposure
and contract hash. No production state was modified.

## Verification

- D4/protected targeted pytest command from the plan, extended with read-service
  regression: 233 collected, exited 0 after the final runtime edit.
- Targeted Ruff across discovery, governance, read service, CLI and changed tests:
  exited 0 after the final edit.
- `uv run pytest -q`: 3,887 collected, exited 0 after the final runtime edit; only two third-party
  websockets deprecation warnings.
- `git diff --check`: exited 0 before evidence writing; rechecked at commit.
- Archive admission tests exercised a red-to-green Jaccard threshold, full-capacity
  clone retirement, invalid eviction order and excess retirement rollback.

The read-only `uv run nutmeg discovery readiness` returned `record_only` on
2026-09-22: sealed worlds 0/30, independent business dates 0/20, effective
sample size 0/24, and replay integrity unknown. This does **not** satisfy the
real baseline readiness or SC-001 gate. Fixture coverage and score comparison
must not be represented as real-world tournament evidence. No live tournament,
prospective shadow run, optimizer generation, canary or deployment was executed.

The repository contained unrelated pre-existing decision, experiment, script and
memory changes. D4 commits stage only the files identified in this plan.

## Next Gate

Jun must review this D4 evidence before D5 implementation. Real tournament,
canary and deployment each require separate authorization and prerequisites;
prior permission to develop D4-D7 does not authorize those actions.
