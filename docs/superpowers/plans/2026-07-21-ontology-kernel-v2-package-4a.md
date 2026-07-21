# Ontology Kernel v2 Package 4A Implementation Plan — Analytical Substrate & Forecast Scoring

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Build a re-computable DuckDB projection substrate and score committed forecasts against outcomes and closing fair — Brier/skill/log/RPS/closing/CLV primitives, a `forecast_scores` projection, and three scorecards (Forecast Truth, Market Information, Calibration & Selectivity) — all pure functions of the SQLite high-watermark that never touch operational truth.

**Architecture:** DuckDB `analytics.duckdb` (opened via the existing `connect_analytics_db` POSIX-locked helper) holds only re-computable projections; each row carries six provenance columns. An `AnalyticsProjectionBuilder` freezes the SQLite high-watermark (`max(rowid)` of `actions`), runs registered projectors in one DuckDB transaction that replaces the prior rows for that `projection_version`, records a `projection_runs` row, and keeps the last good projection when a build fails. `kernel.calibrate.build(...)` is the read-only facade.

**Tech Stack:** Python 3.13, DuckDB 1.2, SQLAlchemy 2 Core (SQLite reads), frozen dataclasses, pytest, ruff; Packages 1/2/3 kernel.

**Design Spec:** `docs/superpowers/specs/2026-07-21-ontology-kernel-v2-package-4-design.md` (§2.1 substrate, §2.2 scoring, §2.3 scorecards, §3 tables 1–3, §5 acceptance 4A).

**Depends on (merged):** `OntologyPaths`, `OntologyUnitOfWork`, `schema` (`actions`), `schema_decision` (`forecast_series`/`forecast_revisions`), `schema_market` (`market_snapshots`), `FinanceRepository.current_outcome`, `OntologyKernel`/`OntologyKernelStatus`, `build_ontology_kernel`, `nutmeg.storage.duckdb_utils.connect_analytics_db`.

---

## Scope Boundary

Package 4A includes: `OntologyPaths.analytics`; a high-watermark reader; pure scoring primitives; the DuckDB substrate (`projection_runs` + builder, keep-last-good, deterministic); the `forecast_scores` and `forecast_scorecards` projections (scorecards 1–3); the `kernel.calibrate.build` facade + `projection_run_count`/`scorecard_count` status counts.

Package 4A excludes (Package 4B): factor Shapley attribution, `factor_estimates`, lifecycle proposals, Integrity/Action scorecards, RegimeVector. had 3-way is the outcome mapping shipped here; non-had outcome mappings (ttg RPS one-hot, etc.) are a documented 4B follow-on — non-had revisions score where inputs exist and set `has_outcome=False` otherwise, never a fabricated 0.

Only **additive** changes to earlier modules: a new `analytics` package, one `OntologyPaths` field (with `ensure_directories` unchanged — DuckDB self-creates), new `OntologyKernelStatus` counts, and `build_ontology_kernel` exposing `calibrate`.

---

## File Structure

### New production modules
- `nutmeg/analytics/__init__.py`
- `nutmeg/analytics/scoring.py`: pure metrics (§2.2).
- `nutmeg/analytics/high_watermark.py`: `high_watermark(engine) -> int`.
- `nutmeg/analytics/substrate.py`: `PROVENANCE_COLUMNS`, `ProjectionContext`, `AnalyticsProjectionBuilder`, `projection_runs` DDL.
- `nutmeg/analytics/outcomes.py`: `outcome_one_hot(market_kind, belief_keys, score_90) -> dict | None`.
- `nutmeg/analytics/forecast_projection.py`: `ForecastScoresProjector` → `forecast_scores`.
- `nutmeg/analytics/scorecards.py`: `ForecastScorecardProjector` → `forecast_scorecards`.
- `nutmeg/analytics/calibrate_flow.py`: `CalibrateService` + `CalibrateRequest`/`CalibrateResult`.

### New tests
`tests/analytics/__init__.py`, `test_scoring.py`, `test_high_watermark.py`, `test_substrate.py`, `test_outcomes.py`, `test_forecast_projection.py`, `test_scorecards.py`, `test_calibrate_flow.py`, `test_package4a_e2e.py`.

### Existing files modified (additive)
- `nutmeg/ontology/paths.py`: `analytics` path.
- `nutmeg/ontology/repository/decision.py`: `iter_committed_revisions()`.
- `nutmeg/ontology/repository/market.py`: `closing_fair(match, market)`.
- `nutmeg/ontology/kernel.py`: `projection_run_count`/`scorecard_count`; `calibrate` attribute.
- `nutmeg/ontology/wiring.py`: build `CalibrateService`.
- `docs/ontology-kernel-operations.md`: Package 4A section.

### User-owned files that must not be reverted
`SOUL.md`, three decision plists, untracked `media/`/`memory/`/`scripts/`. Execute in the Task 0 worktree. Do not touch paused schedules or the freeze archive.

---

### Task 0: Worktree
`git worktree add .claude/worktrees/ontology-kernel-v2-package4a -b feature/ontology-kernel-v2-package4a`; `uv sync --extra dev`. Confirm HEAD is the Package 3B merge; dirty entries only user-owned.

---

### Task 1: Analytics path + high-watermark reader
**Files:** Modify `nutmeg/ontology/paths.py`; Create `nutmeg/analytics/__init__.py`, `nutmeg/analytics/high_watermark.py`; Test `tests/analytics/__init__.py`, `tests/analytics/test_high_watermark.py`

- [ ] **RED** (`test_high_watermark.py`): build engine, run migrations; `high_watermark(engine)` is an int ≥ 0; after committing one Action (e.g. `insert_match_minimal` is not an Action — instead run a `change_budget_policy` via BudgetActions) the watermark strictly increases. Also assert `OntologyPaths.from_data_dir(d).analytics == d/'ontology'/'analytics.duckdb'`.
```python
from nutmeg.analytics.high_watermark import high_watermark
from nutmeg.ontology.paths import OntologyPaths
# ...
def test_watermark_monotonic(tmp_path):
    engine = build_ontology_engine(tmp_path / "ontology.db"); run_migrations(engine)
    before = high_watermark(engine)
    # any committed Action bumps rowid
    from nutmeg.ontology.actions.budget_actions import BudgetActions, ChangeBudgetPolicyRequest
    from nutmeg.ontology.actions.service import ActionService
    from nutmeg.ontology.actions.models import ActorRole
    from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
    from datetime import UTC, datetime
    BudgetActions(ActionService(lambda: OntologyUnitOfWork(engine))).change_budget_policy(
        ChangeBudgetPolicyRequest(channel="jczq", total_cap=400.0, bucket_caps={}, policy_version="budget-v1",
            actor_id="op", actor_role=ActorRole.JUDGE_OPERATOR, idempotency_key="bp:1",
            requested_at=datetime(2026,7,19,tzinfo=UTC)))
    assert high_watermark(engine) > before

def test_analytics_path(tmp_path):
    p = OntologyPaths.from_data_dir(tmp_path)
    assert p.analytics == tmp_path / "ontology" / "analytics.duckdb"
```
- [ ] **Implement:** add `analytics: Path` to `OntologyPaths` and set it in `from_data_dir` to `root / 'analytics.duckdb'` (do **not** create it in `ensure_directories`; DuckDB self-creates). Implement `high_watermark`:
```python
from sqlalchemy import Engine, literal_column, select
def high_watermark(engine: Engine) -> int:
    with engine.connect() as connection:
        value = connection.execute(select(literal_column('max(rowid)')).select_from(
            literal_column('actions'))).scalar_one_or_none()
    return int(value) if value is not None else 0
```
- [ ] Run tests + `uv run ruff check`. Commit `feat(analytics): analytics path and high-watermark`.

---

### Task 2: Pure scoring primitives
**Files:** Create `nutmeg/analytics/scoring.py`; Test `tests/analytics/test_scoring.py`

- [ ] **RED** (`test_scoring.py`):
```python
import math
from nutmeg.analytics.scoring import (
    brier, brier_skill, closing_skill_delta, directional_alignment, log_score, rps, ticket_clv_log,
)

def test_brier_perfect_and_worst():
    assert brier({"home": 1.0, "draw": 0.0, "away": 0.0}, {"home": 1.0, "draw": 0.0, "away": 0.0}) == 0.0
    assert brier({"home": 0.0, "draw": 0.0, "away": 1.0}, {"home": 1.0, "draw": 0.0, "away": 0.0}) == 2.0

def test_brier_skill_and_zero_denominator():
    # belief better than prior -> positive skill
    s = brier_skill([0.2], [0.5]); assert s == 1 - 0.2 / 0.5
    assert brier_skill([0.0], [0.0]) is None   # prior denom 0 -> unavailable

def test_closing_and_directional():
    q = {"home": 0.6, "draw": 0.25, "away": 0.15}; p = {"home": 0.5, "draw": 0.3, "away": 0.2}
    c = {"home": 0.62, "draw": 0.24, "away": 0.14}
    assert closing_skill_delta(q, p, c) < 0            # belief closer to closing
    assert directional_alignment(q, p, c) > 0          # moved with closing

def test_log_score_and_rps_and_clv():
    assert log_score({"home": 0.5}, {"home": 1.0}, clip=1e-9) == -math.log(0.5)
    # ordered RPS: cumulative squared error
    assert rps({"a": 0.0, "b": 1.0, "c": 0.0}, {"a": 0.0, "b": 1.0, "c": 0.0}) == 0.0
    assert ticket_clv_log(2.10, 2.00) == math.log(2.10 / 2.00)
```
- [ ] **Implement** each per §2.2. `brier(q, y)` sums over the union of keys (`(q.get(k,0)-y.get(k,0))**2`). `brier_skill(scores, prior_scores)`: `denom=sum(prior_scores)`; `return None if denom==0 else 1 - sum(scores)/denom`. `log_score(q, y, clip)`: for the outcome key with `y==1`, `-log(max(min(q_k,1-clip),clip))`. `rps(q, y)`: order keys, cumulative-sum squared error `Σ_j (Σ_{k<=j}(q-y))^2`. `closing_skill_delta(q,p,c)=brier(q,c)-brier(p,c)`. `directional_alignment(q,p,c)=Σ_k (q_k-p_k)*(c_k-p_k)`. `ticket_clv_log(entry,closing)=log(entry/closing)`. `metric_version='scoring-v1'` module constant.
- [ ] Run + ruff. Commit `feat(analytics): pure scoring primitives`.

---

### Task 3: Projection substrate + projection_runs (keep-last-good, deterministic)
**Files:** Create `nutmeg/analytics/substrate.py`; Test `tests/analytics/test_substrate.py`

- [ ] **RED** (`test_substrate.py`): a builder over a trivial projector that writes rows to a table `demo(x INTEGER)` plus provenance:
  (a) two builds at the same high-watermark leave one `succeeded` run per version and identical `demo` rows (deterministic replace, not append);
  (b) a projector that raises marks its run `failed` and leaves the previous `succeeded` `demo` rows intact;
  (c) each `demo` row carries the six provenance columns.
```python
def test_build_is_deterministic_and_replaces(tmp_path):
    engine = _engine(tmp_path)
    builder = AnalyticsProjectionBuilder(engine, OntologyPaths.from_data_dir(tmp_path).analytics)
    def demo(ctx):
        ctx.write("demo", [{"x": 1}, {"x": 2}])
    r1 = builder.build([("demo", "demo-v1", demo)], built_at="2026-07-19T00:00:00+00:00")
    r2 = builder.build([("demo", "demo-v1", demo)], built_at="2026-07-19T00:00:00+00:00")
    assert r1.status == "succeeded" and r2.status == "succeeded"
    with connect_analytics_db(OntologyPaths.from_data_dir(tmp_path).analytics) as con:
        rows = con.execute("SELECT x FROM demo ORDER BY x").fetchall()
        assert rows == [(1,), (2,)]                 # replaced, not doubled
        runs = con.execute("SELECT count(*) FROM projection_runs WHERE status='succeeded'").fetchone()
        assert runs[0] == 2

def test_failed_build_keeps_last_good(tmp_path):
    engine = _engine(tmp_path); path = OntologyPaths.from_data_dir(tmp_path).analytics
    builder = AnalyticsProjectionBuilder(engine, path)
    builder.build([("demo", "demo-v1", lambda ctx: ctx.write("demo", [{"x": 7}]))],
                  built_at="2026-07-19T00:00:00+00:00")
    def boom(ctx): raise RuntimeError("projector failed")
    result = builder.build([("demo", "demo-v1", boom)], built_at="2026-07-19T01:00:00+00:00")
    assert result.status == "failed"
    with connect_analytics_db(path) as con:
        assert con.execute("SELECT x FROM demo").fetchall() == [(7,)]   # last good intact
```
- [ ] **Implement:** `PROVENANCE_COLUMNS = ('projection_name','projection_version','source_high_watermark','built_at','cohort_definition_version','metric_version')`. `ProjectionContext` exposes `write(table, rows: list[dict])` accumulating `(table, version, rows)` in memory (does not touch DuckDB yet) and the frozen provenance values. `AnalyticsProjectionBuilder(engine, analytics_path, cohort_definition_version='cohort-v1', metric_version='scoring-v1')`:
  - `build(projectors, built_at, high_watermark=None) -> ProjectionRunResult` where `projectors: list[(name, version, callable(ctx))]`.
  - freeze `hw = high_watermark or high_watermark(engine)`; run each projector callable to fill the context (in memory); on any exception record a `failed` `projection_runs` row (in its own DuckDB tx) and return — **no** projection rows touched.
  - on success, in **one** DuckDB transaction: ensure `projection_runs` DDL; for each written table, `CREATE TABLE IF NOT EXISTS` inferring columns from the first row + the six provenance TEXT/INTEGER columns, `DELETE FROM <table> WHERE projection_version = ?`, then insert rows with provenance stamped; finally insert a `succeeded` `projection_runs` row. Use a deterministic `run_id = f"{built_at}:{hw}:{name}"` (no clock/random).
- [ ] Run + ruff. Commit `feat(analytics): projection substrate with keep-last-good`.

---

### Task 4: Outcome one-hot + forecast_scores projection
**Files:** Create `nutmeg/analytics/outcomes.py`, `nutmeg/analytics/forecast_projection.py`; Modify `nutmeg/ontology/repository/decision.py`, `nutmeg/ontology/repository/market.py`; Test `tests/analytics/test_outcomes.py`, `tests/analytics/test_forecast_projection.py`

- [ ] **RED** (`test_outcomes.py`):
```python
from nutmeg.analytics.outcomes import outcome_one_hot
def test_had_one_hot():
    keys = ["home", "draw", "away"]
    assert outcome_one_hot("had", keys, "2-1") == {"home": 1.0, "draw": 0.0, "away": 0.0}
    assert outcome_one_hot("had", keys, "1-1") == {"home": 0.0, "draw": 1.0, "away": 0.0}
    assert outcome_one_hot("ttg", keys, "2-1") is None   # non-had mapping is a 4B follow-on
```
- [ ] **Implement** `outcome_one_hot(market_kind, belief_keys, score_90)`: for `market_kind == 'had'` map the 90' result to `home/draw/away` one-hot over `belief_keys`; otherwise return `None`.
- [ ] **Implement** repository reads:
  - `DecisionRepository.iter_committed_revisions() -> list[CommittedRevisionRow]` joining `forecast_revisions` (status='committed') to `forecast_series` for `match_id`/`market_definition_id`; each row carries `forecast_revision_id, match_id, market_definition_id, made_at, prior_distribution, belief_distribution, commitment_tier, actor_id, model_name, model_version`.
  - `MarketRepository.closing_fair(match_id, market_definition_id) -> dict[str,float] | None` selecting the `market_snapshots` row with `snapshot_kind='closing'` (latest `as_of`) and returning `json.loads(fair_distribution_json)`, else `None`.
- [ ] **RED** (`test_forecast_projection.py`): seed one committed had forecast (prior/belief), a final outcome (home win), and a closing snapshot; run `ForecastScoresProjector(engine).project(ctx)`; assert one `forecast_scores` row with `brier == brier(belief, y)`, `prior_brier == brier(prior, y)`, `has_outcome`, `has_closing`, and `closing_skill_delta` set. A revision with **no** outcome yields a row with `has_outcome=False` and null `brier` (never 0). A revision with no closing yields null `closing_skill_delta`/`directional_alignment` but is not dropped.
- [ ] **Implement** `ForecastScoresProjector(engine)`: read committed revisions; for each, look up market_kind (via `market_definitions.market_kind`), outcome (`FinanceRepository.current_outcome`), closing fair; compute the metrics with the Task 2 primitives and Task 4 one-hot (guarding None inputs); `ctx.write('forecast_scores', rows)`. Determinism: no clock inside.
- [ ] Run + ruff. Commit `feat(analytics): forecast scores projection`.

---

### Task 5: Forecast scorecards (three cohorted scorecards)
**Files:** Create `nutmeg/analytics/scorecards.py`; Test `tests/analytics/test_scorecards.py`

- [ ] **RED** (`test_scorecards.py`): given `forecast_scores` rows across two markets, `ForecastScorecardProjector` writes `forecast_scorecards` rows for scorecards `forecast_truth`, `market_information`, `calibration` cohorted by `market_definition_id`; each row has `n`, `coverage`, `raw_brier`, `prior_brier`, `brier_skill` (or null when prior denom 0), and a `[skill_low, skill_high]` interval; a cohort where belief beats prior reports `brier_skill > 0`.
- [ ] **Implement** `ForecastScorecardProjector(engine, analytics_path)`: read `forecast_scores` from DuckDB (the substrate wrote them earlier in the same build — read from `ctx`'s DuckDB path *after* forecast_scores committed) **or** re-derive by re-reading SQLite; to avoid intra-build ordering coupling, this projector **re-reads SQLite committed revisions** and recomputes the same rows in memory, then aggregates cohorts. For each scorecard and cohort compute: `n`, `coverage` (fraction with the metric's inputs), `raw_brier` (mean belief Brier over scored), `prior_brier` (mean prior Brier), `brier_skill` via `brier_skill(scores, prior_scores)`, and a bootstrap-free normal-approx interval `skill ± 1.96·se` (documented simple method; `se` from per-item skill contributions; when n<2 or denom 0 → interval null). `market_information` uses closing coverage/`closing_skill_delta`; `calibration` reports follow-market vs divergent counts in `extra_json`. `ctx.write('forecast_scorecards', rows)`.
- [ ] Run + ruff. Commit `feat(analytics): forecast scorecards`.

---

### Task 6: calibrate facade + wiring + status counts
**Files:** Create `nutmeg/analytics/calibrate_flow.py`; Modify `nutmeg/ontology/kernel.py`, `nutmeg/ontology/wiring.py`; Test `tests/analytics/test_calibrate_flow.py`

- [ ] **RED** (`test_calibrate_flow.py`): build a kernel, seed a committed had forecast + outcome + closing, `kernel.calibrate.build(CalibrateRequest(as_of=..., built_at=...))` returns a `CalibrateResult` whose `scorecards` includes the three names and whose `run_id` is set; `kernel.status().scorecard_count >= 3` and `projection_run_count >= 1`. A second `build` at the same high-watermark is deterministic (same row counts).
- [ ] **Implement** `CalibrateService(engine, analytics_path)` with `build(request) -> CalibrateResult`: construct an `AnalyticsProjectionBuilder`, register `[('forecast_scores','fs-v1',ForecastScoresProjector(engine).project), ('forecast_scorecards','sc-v1',ForecastScorecardProjector(engine, path).project)]`, call `builder.build(...)`, then read back scorecard names/counts from DuckDB for the result. Add `projection_run_count`/`scorecard_count` to `OntologyKernelStatus` (+`to_dict`, +uninitialized branch = 0) computed by reading `analytics.duckdb` when it exists (guard: if the file is absent, both are 0 — never create it in `status`). Add `calibrate` to `OntologyKernel.__init__` and `build_ontology_kernel`.
- [ ] Run + ruff. Commit `feat(analytics): calibrate facade and status counts`.

---

### Task 7: e2e gate, docs, verification
**Files:** Create `tests/analytics/test_package4a_e2e.py`; Modify `docs/ontology-kernel-operations.md`

- [ ] **RED e2e:** seed **two** committed had forecasts on two matches (one where belief beats the market prior on a home win, one follow-market), record outcomes and closing snapshots; `kernel.calibrate.build(...)` twice at the same high-watermark → identical `forecast_scores`/`forecast_scorecards` row counts (determinism); the `forecast_truth` cohort with the sharper belief reports `brier_skill > 0`; a match with **no** outcome contributes a `has_outcome=False` row and is excluded from the scored denominator (not a 0); `status().scorecard_count`/`projection_run_count` reflect the build.
- [ ] Drive to GREEN. Document Package 4A in the operations doc (analytics is re-computable/keep-last-good; six provenance columns; five scorecards with 1–3 here; no single total; `brier_skill=None` on zero prior denom).
- [ ] Full suite: `uv run pytest -q`; `uv run ruff check .`; `uv run python -m compileall -q nutmeg scripts`; `bash scripts/verify.sh`.
- [ ] Project verify: 4A adds no code to the old decision path and never writes operational truth; state so.
- [ ] Commit `test(analytics): verify package 4a substrate and scoring`; inspect branch; hand back for review.

---

## Package 4A Spec Coverage
| Design (§) | Task |
|---|---|
| Analytics re-computable, six provenance cols (§2.1) | 3, 7 |
| High-watermark drives builds (§2.1) | 1, 3 |
| Keep-last-good on failure (§2.1) | 3 |
| Pure versioned scoring; zero-denom → None (§2.2) | 2 |
| Closing excluded from denom when missing (§2.2) | 4, 5 |
| forecast_scores projection (§3.2) | 4 |
| Three scorecards, no single total (§2.3, §3.3) | 5, 7 |
| calibrate facade read-only over SQLite (§5) | 6 |

Package 4A is complete when Task 7 passes. Package 4B (factor learning + regime + integrity/action) receives its own plan and consumes `forecast_scores` + factor deltas.
