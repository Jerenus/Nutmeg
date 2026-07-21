# Ontology Kernel v2 Package 4B Implementation Plan — Factor Learning, Regime & Integrity/Action

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Complete the calibrate verb — attribute forecast skill to factors (single-factor paired + multi-factor Shapley with a `confounded_not_attributable` guard), build shrinkage factor estimates and versioned lifecycle *proposals* (applied only by the existing judge_operator Action), add the Integrity & Action scorecards, and project a pre-match RegimeVector — all re-computable DuckDB projections that never mutate operational truth.

**Architecture:** Extends Package 4A's substrate. New pure attribution + regime primitives feed new projectors (`factor_score_contributions`, `factor_estimates`, `factor_lifecycle_proposals`, `integrity_action_scorecards`, `regime_vectors`, `regime_postmatch_labels`) registered into `kernel.calibrate`. calibrate emits proposals; it never changes factor status — `FactorActions.apply_factor_status` (judge_operator) does. Regime is a thermometer: it never changes a direction or stake.

**Tech Stack:** Python 3.13, DuckDB 1.2, SQLAlchemy 2 Core, frozen dataclasses, pytest, ruff; Packages 1/2/3/4A.

**Design Spec:** `docs/superpowers/specs/2026-07-21-ontology-kernel-v2-package-4-design.md` (§2.4 attribution, §2.5 lifecycle, §2.6 regime, §3 tables 4–8, §5 acceptance 4B).

**Depends on (merged):** 4A `AnalyticsProjectionBuilder`/`ProjectionContext`/`compute_forecast_score_rows`/`scoring`; `DecisionRepository` (factor applications/definitions), `FactorActions.propose_factor_status`/`apply_factor_status`, `FinanceRepository` (tickets/settlements/ledger), `MarketRepository.latest_fair`/`closing_fair`, `CalibrateService`, `OntologyKernelStatus`.

---

## Scope Boundary

Includes: pure Shapley/paired factor attribution with the simplex guard; `factor_score_contributions`, `factor_estimates` (shrinkage), `factor_lifecycle_proposals` projections; a versioned lifecycle policy; the Integrity & Action scorecards; a pre-match `regime_vectors` projection (real `market_shape` + `portfolio_risk` axes; other axes carry coverage + `percentile_unavailable` when their sensor inputs/cohort are thin) and a separate `regime_postmatch_labels` projection; registration into `kernel.calibrate` + new status counts.

Excludes (documented follow-ons, not silently skipped): the full richness of all five regime sensor sub-axes (information_weather/fixture_pressure/data_health beyond coverage stubs) — their inputs (weather, congestion, lineup uncertainty) are not all in the store yet; bootstrap/Bayesian intervals beyond the normal approx; and Package 5 (migration, CLI rewire, old-writer shutdown, schedule restore).

Only **additive** changes to earlier modules: new `nutmeg/analytics/*` modules, two `DecisionRepository` readers, extra `CalibrateService` projectors, and new `OntologyKernelStatus` counts.

---

## File Structure

### New production modules
- `nutmeg/analytics/attribution.py`: pure `attribute_factors(prior, belief, factors, y)` → per-factor Brier contribution or `confounded`.
- `nutmeg/analytics/factor_projection.py`: `FactorContributionsProjector` (`factor_score_contributions`) + `FactorEstimatesProjector` (`factor_estimates`, shrinkage).
- `nutmeg/analytics/lifecycle.py`: `LIFECYCLE_POLICY` (versioned thresholds) + `FactorLifecycleProjector` (`factor_lifecycle_proposals`).
- `nutmeg/analytics/integrity_action.py`: `IntegrityActionScorecardProjector` (`integrity_action_scorecards`).
- `nutmeg/analytics/regime.py`: pure sensors + `RegimeVectorProjector` (`regime_vectors`) + `RegimePostmatchProjector` (`regime_postmatch_labels`).

### New tests
`tests/analytics/test_attribution.py`, `test_factor_projection.py`, `test_lifecycle.py`, `test_integrity_action.py`, `test_regime.py`, `test_package4b_e2e.py`.

### Existing files modified (additive)
- `nutmeg/ontology/repository/decision.py`: `iter_factor_applications(revision_id)`, `factor_definition(id)`.
- `nutmeg/analytics/calibrate_flow.py`: register the six new projectors; extend `CalibrateResult`.
- `nutmeg/ontology/kernel.py`: `factor_estimate_count`/`regime_vector_count`/`lifecycle_proposal_count` status counts (via `projection_counts` extension).
- `nutmeg/analytics/substrate.py`: extend `projection_counts` to return the new counts.
- `docs/ontology-kernel-operations.md`: Package 4B section.

### User-owned files that must not be reverted
`SOUL.md`, three decision plists, untracked `media/`/`memory/`/`scripts/`. Execute in the Task 0 worktree. Do not touch paused schedules or the freeze archive.

---

### Task 0: Worktree
`git worktree add .claude/worktrees/ontology-kernel-v2-package4b -b feature/ontology-kernel-v2-package4b`; `uv sync --extra dev`. Confirm HEAD is the Package 4A merge.

---

### Task 1: Pure factor attribution (Shapley + simplex guard)
**Files:** Create `nutmeg/analytics/attribution.py`; Test `tests/analytics/test_attribution.py`

- [ ] **RED:** `attribute_factors(prior, belief, factors, y)` where `factors: list[(factor_id, delta_dict)]`, `y` one-hot:
  - one factor → its contribution equals the whole paired Brier gain `brier(prior,y) - brier(belief,y)`;
  - two factors → contributions **sum to** the whole gain (Shapley efficiency);
  - a factor set whose intermediate `prior + ΣS` leaves `[0,1]` on any component → returns the sentinel `CONFOUNDED` (a module constant), not numbers.
```python
def test_single_factor_is_whole_gain():
    prior = {"home": 0.5, "draw": 0.3, "away": 0.2}
    belief = {"home": 0.6, "draw": 0.25, "away": 0.15}
    y = {"home": 1.0, "draw": 0.0, "away": 0.0}
    result = attribute_factors(prior, belief, [("f1", {"home": 0.1, "draw": -0.05, "away": -0.05})], y)
    assert abs(result["f1"] - (brier(prior, y) - brier(belief, y))) < 1e-12

def test_two_factors_sum_to_gain():
    ...
    total = brier(prior, y) - brier(belief, y)
    assert abs(sum(result.values()) - total) < 1e-12

def test_off_simplex_is_confounded():
    prior = {"home": 0.5, "draw": 0.3, "away": 0.2}
    f = [("a", {"home": 0.6, "draw": -0.3, "away": -0.3}),   # prior+a -> home 1.1 (off simplex)
         ("b", {"home": -0.6, "draw": 0.3, "away": 0.3})]
    belief = {"home": 0.5, "draw": 0.3, "away": 0.2}
    assert attribute_factors(prior, belief, f, y) is CONFOUNDED
```
- [ ] **Implement** `attribute_factors`: build subset sums; for each subset `S` compute `dist_S = prior + Σ_{j∈S} delta_j`; if any component `< -1e-9` or `> 1+1e-9` for any `S` → return `CONFOUNDED`; `v(S) = brier(prior, y) - brier(dist_S, y)`; Shapley `φ_i = Σ_S w(|S|) (v(S∪{i}) - v(S))` with `w(s) = s!(n-s-1)!/n!`. Also expose `attribute_closing(prior, belief, factors, c)` reusing the same machinery with `c` in place of `y`. Run + ruff. Commit `feat(analytics): factor Shapley attribution`.

---

### Task 2: Factor contribution + estimate projections
**Files:** Create `nutmeg/analytics/factor_projection.py`; Modify `nutmeg/ontology/repository/decision.py`; Test `tests/analytics/test_factor_projection.py`

- [ ] **Implement** `DecisionRepository.iter_factor_applications(revision_id) -> list[(factor_definition_id, delta_distribution)]` and `factor_definition(factor_definition_id) -> FactorDefinitionRow | None`.
- [ ] **RED:** with two committed forecasts each carrying one factor `fd-rest` and a home-win outcome, `FactorContributionsProjector(engine)` writes `factor_score_contributions` rows (one per revision×factor) with `brier_contribution` set and `confounded=False`; a revision whose factor subset leaves the simplex writes `confounded=True` and null contribution.
- [ ] **Implement** `FactorContributionsProjector`: for each committed revision with ≥1 factor application, compute the one-hot `y` (4A `outcome_one_hot`) and closing `c`; call `attribute_factors`; write a row per factor (`confounded=True`, nulls, when the sentinel returns). `ctx.write('factor_score_contributions', rows, column_types=…)`.
- [ ] **RED:** `FactorEstimatesProjector(engine)` aggregates contributions by `(factor_definition_id, factor_family, factor_version, scope_key, market)` into `factor_estimates` with `n_eff`, `raw_mean`, `shrunk_mean`, interval; a small-n factor's `shrunk_mean` is strictly between its `raw_mean` and the global mean.
- [ ] **Implement** `FactorEstimatesProjector`: mean of non-confounded `brier_contribution` per stratum = `raw_mean`; `shrunk_mean = (n·raw + K·global)/(n+K)` with `K=10` (documented); normal-approx interval. Skip confounded rows. Run + ruff. Commit `feat(analytics): factor contributions and shrinkage estimates`.

---

### Task 3: Lifecycle proposals (versioned policy) + Action apply
**Files:** Create `nutmeg/analytics/lifecycle.py`; Test `tests/analytics/test_lifecycle.py`

- [ ] **RED:** `FactorLifecycleProjector(engine)` reads `factor_estimates` + current factor status and writes `factor_lifecycle_proposals`:
  - a probation factor whose skill-contribution interval low > 0 and `n_eff ≥ policy.min_n` → a `probation→active` proposal;
  - an active factor whose interval high < 0 → an `active→retired` proposal;
  - status is **unchanged** by the projector (assert factor status is still probation);
  - applying the proposal via `FactorActions.apply_factor_status` (judge_operator) transitions it; an ai_analyst apply is REJECTED.
- [ ] **Implement** `LIFECYCLE_POLICY = {'policy_version': 'lifecycle-v1', 'min_n': 5, ...}` and `FactorLifecycleProjector`: read estimates (via a small DuckDB read or recompute), read `factor_status`, emit proposal rows with `rationale_json`. It only writes the projection; the transition is the existing Action. Run + ruff. Commit `feat(analytics): factor lifecycle proposals`.

---

### Task 4: Integrity & Action scorecards
**Files:** Create `nutmeg/analytics/integrity_action.py`; Test `tests/analytics/test_integrity_action.py`

- [ ] **RED:** with a settled winning ticket and an approved ticket, `IntegrityActionScorecardProjector(engine)` writes `integrity_action_scorecards` rows: an `action_finance` card with `ledger_balance`, `stake_total`, `payout_total`, `ticket_count`, `settlement_count` computed from real Transactions; an `evidence_integrity` card with `outcome_completeness` (fraction of scored matches with an outcome) and `closing_coverage`. "No entry = not bet" holds — ledger equals the signed sum of cash transactions.
- [ ] **Implement** `IntegrityActionScorecardProjector`: read finance aggregates (ledger balance across accounts, stake/payout sums, counts) and evidence/outcome coverage from the committed-revision + outcome + closing joins. Run + ruff. Commit `feat(analytics): integrity and action scorecards`.

---

### Task 5: RegimeVector (pre-match) + post-match labels
**Files:** Create `nutmeg/analytics/regime.py`; Test `tests/analytics/test_regime.py`

- [ ] **RED (sensors):** pure `market_shape(fair)` → `{normalized_entropy, favorite_concentration, draw_mass}` (entropy normalized by `log(K)`); a flat distribution has normalized_entropy ≈ 1, a spiked one ≈ 0.
- [ ] **RED (projector):** `RegimeVectorProjector(engine)` writes one `regime_vectors` row per match with a committed forecast, `scope_type='match'`, five axes in `axes_json` (real `market_shape` from latest fair + `portfolio_risk` from that match's tickets; the other three axes carry `{coverage, percentile: 'percentile_unavailable'}` when their sensor cohort is thin), and a `labels` list. A thin cohort marks `percentile_unavailable` rather than borrowing a baseline.
- [ ] **RED (post-match):** `RegimePostmatchProjector(engine)` writes `regime_postmatch_labels` for matches with an outcome (e.g. `upset` when the pre-match favorite lost) in a **separate** table from `regime_vectors` (no pre-match leakage).
- [ ] **Implement** the sensors + projectors. Run + ruff. Commit `feat(analytics): regime vectors and post-match labels`.

---

### Task 6: Register in calibrate + status counts + e2e + docs + verification
**Files:** Modify `nutmeg/analytics/calibrate_flow.py`, `nutmeg/analytics/substrate.py`, `nutmeg/ontology/kernel.py`; Create `tests/analytics/test_package4b_e2e.py`; Modify `docs/ontology-kernel-operations.md`

- [ ] **Implement** register the six new projectors in `CalibrateService.build` (after the 4A pair); extend `CalibrateResult` with `factor_estimate_count`/`lifecycle_proposal_count`/`regime_vector_count`; extend `substrate.projection_counts` and `OntologyKernelStatus` with `factor_estimate_count`/`regime_vector_count`/`lifecycle_proposal_count` (+`to_dict`, +uninitialized zeros).
- [ ] **RED e2e:** a committed forecast with a factor + outcome + closing + a settled ticket; `kernel.calibrate.build(...)` populates all Package 4B projections deterministically at a fixed high-watermark; a confounded revision feeds no estimate; a lifecycle proposal is emitted while factor status is unchanged; the Action then applies it; `status()` reflects the new counts.
- [ ] Drive to GREEN. Document Package 4B (attribution conserves + refuses to fake it; estimates shrink; calibrate proposes but the Action applies; regime is a thermometer; five scorecards now complete).
- [ ] Full suite `uv run pytest -q`; `uv run ruff check .`; `uv run python -m compileall -q nutmeg scripts`; `bash scripts/verify.sh`.
- [ ] Project verify: 4B adds no code to the old decision path and never mutates operational truth except through the existing judge_operator factor Action; state so.
- [ ] Commit `test(analytics): verify package 4b learning and regime`; inspect branch; hand back for review.

---

## Package 4B Spec Coverage
| Design (§) | Task |
|---|---|
| Shapley attribution + confounded guard (§2.4) | 1, 2 |
| Shrinkage factor estimates (§2.4) | 2 |
| Lifecycle proposes, Action applies (§2.5) | 3 |
| Integrity & Action scorecards (§9.6) | 4 |
| RegimeVector thermometer + percentile_unavailable (§2.6, §11) | 5 |
| Post-match labels separate (no leakage) (§11.4) | 5 |
| Registered in calibrate; counts (§5) | 6 |

Package 4B completes umbrella Package 4 (Learning & Regime). Package 5 (Evidence Migration & Cutover) then imports history, rewires the CLI, shuts the old write paths, and — as the single irreversible go-live step — restores the paused schedules for user confirmation.
