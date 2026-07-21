# Ontology Kernel v2 — Package 4 Design (Learning & Regime)

> Self-contained design for Package 4 of the umbrella
> `docs/superpowers/specs/2026-07-20-ontology-kernel-v2-design.md` (§8.4 DuckDB
> projections, §9 scoring, §10 factor learning, §11 RegimeVector). Packages 1/2/3
> are merged: the SQLite operational kernel holds committed ForecastRevisions,
> EvidenceBundles, MarketSnapshots/Quotes, MatchOutcomes, Tickets/BetLegs and
> Settlements. Package 4 reads that operational truth and builds **re-computable
> analytical projections** — it never writes operational truth except through one
> typed factor-lifecycle Action.

## 1. Scope

Package 4 is the **calibrate** verb: rebuild analytical projections from the SQLite
high-watermark, and produce evaluation — five scorecards, factor estimates and
lifecycle proposals, and RegimeVectors — without silently mutating the world.

Split into two executable sub-packages, each working software on its own:

- **Package 4A — Analytical substrate + Forecast scoring.** A versioned DuckDB
  projection framework (§2.1), pure scoring primitives (Brier/skill/log/RPS/closing/
  CLV, §2.2), the `forecast_scores` projection, and three scorecards: **Forecast
  Truth**, **Market Information**, **Calibration & Selectivity**. Facade
  `kernel.calibrate.build(...)` returns a scorecard bundle and stamps provenance.
- **Package 4B — Factor learning + Regime + Integrity/Action.** Per-outcome factor
  delta attribution (single-factor paired + multi-factor Shapley with the
  `confounded_not_attributable` guard), shrinkage `factor_estimates`, factor
  **lifecycle proposals** and their application through one typed Action, the
  **Evidence & Process Integrity** and **Action & Finance** scorecards, and the
  pre-match **RegimeVector** sensors (post-match research labels kept separate).

Package 4 **excludes**: historical JSONL/DuckDB migration and old-write-path
shutdown and schedule restore (Package 5); any change to sense/read/express/reconcile
operational semantics.

## 2. Key design decisions

### 2.1 DuckDB is re-computable, never business truth (§8.4)

- A second DuckDB database `analytics.duckdb` lives at `OntologyPaths.analytics`
  (`<data_dir>/ontology/analytics.duckdb`), opened through the existing
  `nutmeg.storage.duckdb_utils.connect_analytics_db` (POSIX file lock). Business
  Actions never write it.
- Every projection **row** carries six provenance columns: `projection_name`,
  `projection_version`, `source_high_watermark`, `built_at`, `cohort_definition_version`,
  `metric_version`. A `projection_runs` table records each build (`run_id`, name,
  version, high-watermark, `status ∈ {succeeded, failed}`, started/finished, row_count,
  error).
- The **high-watermark** is the maximum committed Action sequence in SQLite at build
  start (`actions` are append-only and monotonically sequenced). A build reads a
  consistent SQLite snapshot, computes projections in memory, and writes them in one
  DuckDB transaction that first deletes the prior rows *for that projection_version*.
- **Keep-last-good.** A failed build marks its `projection_runs` row `failed` and
  leaves the previous succeeded projection rows intact — analytics never half-updates.
- Projections are **pure functions of immutable inputs**: rebuilding at the same
  high-watermark yields byte-identical rows (no wall-clock inside metrics; `built_at`
  is passed in, not read from the clock).

### 2.2 Scoring primitives are pure and versioned (§9.2–§9.3)

All in `nutmeg/analytics/scoring.py`, `metric_version = 'scoring-v1'`:

- `brier(q, y)` = Σ_k (q_k − y_k)² over a K-outcome distribution vs one-hot outcome.
- `brier_skill(scores, prior_scores)` = 1 − Σ BS(q,y) / Σ BS(p,y); if the prior
  denominator is 0 → return `None` (skill **unavailable**, never divide-by-zero or a
  default). Report raw, prior, skill, n, coverage.
- `log_score(q, y, clip)` = −log(clip(q_y)); clip rule versioned.
- `rps(q, y)` ordered-outcome Ranked Probability Score for ttg/net-goals cohorts.
- `closing_skill_delta(q, p, c)` = BS(q,c) − BS(p,c) (negative ⇒ belief closer to
  closing than the read-time prior). `c` = same-market closing fair.
- `directional_alignment(q, p, c)` = (q−p)·(c−p) (probability-squared units; **not**
  called clv_pp).
- `ticket_clv_log(entry_odds, closing_odds)` = log(entry/closing), only when market+
  selection+line are comparable; otherwise the caller records `not_comparable`.
- Missing closing ⇒ excluded from that metric's denominator (never counted as 0).

### 2.3 Five scorecards, no single total (§9.1)

`ScorecardBundle` groups five independent scorecards; earning money never launders a
bad probability, and Brier skill never launders a lineage/finance violation. 4A ships
scorecards 1–3, 4B ships 4–5. Each scorecard reports per-cohort metrics with n,
coverage and an interval; cohorts are cut by market/competition/judge-or-model
version/time-to-kickoff/evidence-coverage (`cohort_definition_version = 'cohort-v1'`).

### 2.4 Factor attribution conserves and refuses to fake it (§10)

- Each `FactorApplication` already stores a per-outcome `delta_distribution` with
  Σ_outcome delta = 0 and Σ_factor delta = belief − prior (enforced at commit).
- Single-factor revisions get a direct paired score contribution. Multi-factor
  revisions use **Shapley** attribution over factor-delta subsets to split the joint
  Brier/closing-skill gain fairly. If **any** subset produces a distribution off the
  probability simplex, that revision's multi-factor attribution is marked
  `confounded_not_attributable` and contributes to **no** FactorEstimate — never
  projected or pruned on fabricated credit.
- `factor_estimates` are stratified by factor family/version, scope and market, with
  **shrinkage** toward the global mean and an uncertainty interval; small samples pull
  to the mean (no extreme hit-rates). Raw cohort estimates are kept alongside so
  Shapley is not misread as causal.

### 2.5 Lifecycle proposes, then a typed Action applies (§10.3)

- A versioned lifecycle **policy** reads effective sample size, Brier/closing skill
  contribution intervals, cross-cohort stability, evidence integrity and lexicon
  capacity — thresholds are `PolicyVersion` data, not hard-coded `n=30/CLV>55%`.
- calibrate emits `FactorLifecycleProposal`s (probation→active, active→retired). It
  **does not** mutate factor status directly; applying a proposal is the existing
  `apply_factor_status` judge_operator Action (Package 3A) — calibrate only proposes.

### 2.6 RegimeVector is a thermometer, not a thermostat (§11)

- A pre-match `RegimeVector` per match|slate with five sensor axes (market_shape,
  information_weather, fixture_pressure, data_health, portfolio_risk), each
  `{raw, cohort_percentile, coverage, uncertainty}`, plus free labels. Percentiles are
  relative to a comparable cohort; when cohort history is thin the axis reports raw +
  coverage + `percentile_unavailable` (never borrow an unrelated league's baseline).
- Post-match research labels (Brier residual, upset/goal surprise, closing realization)
  live in a **separate** projection to prevent future leakage. Regime never changes a
  direction or stake — promotion to Factor/Policy needs independent validation.

## 3. Projection tables (DuckDB `analytics.duckdb`)

All tables carry the six §2.1 provenance columns. 4A creates 1–3; 4B creates 4–8.

1. `projection_runs(run_id, projection_name, projection_version, source_high_watermark,
   status, started_at, finished_at, row_count, error)` — build ledger.
2. `forecast_scores(forecast_revision_id, match_id, market_definition_id, made_at,
   n_outcomes, brier, prior_brier, closing_skill_delta, directional_alignment,
   log_score, rps, has_outcome, has_closing, commitment_tier, judge_or_model, …prov)`.
3. `forecast_scorecards(scorecard, cohort_key, cohort_value, n, coverage, raw_brier,
   prior_brier, brier_skill, skill_low, skill_high, extra_json, …prov)` — the three
   4A scorecards' aggregated rows.
4. `factor_score_contributions(forecast_revision_id, factor_definition_id, method,
   brier_contribution, closing_contribution, confounded, …prov)` (4B).
5. `factor_estimates(factor_definition_id, factor_family, factor_version, scope_key,
   market_definition_id, cohort_key, n_eff, raw_mean, shrunk_mean, interval_low,
   interval_high, …prov)` (4B).
6. `factor_lifecycle_proposals(proposal_id, factor_definition_id, from_status,
   to_status, rationale_json, policy_version, …prov)` (4B).
7. `regime_vectors(regime_id, scope_type, scope_id, as_of, axes_json, labels_json,
   …prov)` (4B).
8. `regime_postmatch_labels(match_id, labels_json, …prov)` (4B, separate table).

## 4. Projectors, scoring & facade

- `nutmeg/analytics/paths.py` extension: `OntologyPaths.analytics`.
- `nutmeg/analytics/substrate.py`: `AnalyticsProjectionBuilder` — opens SQLite at a
  frozen high-watermark, opens DuckDB, runs registered projectors in one transaction,
  writes `projection_runs`, keeps-last-good on failure.
- `nutmeg/analytics/scoring.py`: the §2.2 pure primitives.
- `nutmeg/analytics/forecast_projection.py` (4A): builds `forecast_scores` from
  committed revisions joined to outcomes and closing snapshots.
- `nutmeg/analytics/scorecards.py` (4A): aggregates cohorts into `forecast_scorecards`.
- `nutmeg/analytics/factors.py`, `regime.py`, `integrity_action.py` (4B).
- `nutmeg/analytics/read_high_watermark.py`: `high_watermark(engine) -> int`.
- Facade: `kernel.calibrate.build(CalibrateRequest{as_of, high_watermark?, built_at})
  -> CalibrateResult{run_id, scorecards, …}`; `kernel.status()` gains
  `projection_run_count` / `scorecard_count`. calibrate is read-only over SQLite and
  writes only DuckDB (4A/4B) plus, in 4B, emits proposals (no status mutation).

## 5. Acceptance

**4A.** (a) Two projector builds at the same high-watermark produce identical
`forecast_scores` rows; (b) a build whose projector raises leaves the prior succeeded
rows intact and marks the run `failed`; (c) `brier_skill` returns `None` when prior
Brier is 0 (no divide-by-zero); (d) closing metrics exclude revisions with no closing
from their denominator; (e) a cohort with a market prior strictly worse than belief
reports positive Brier skill; (f) `kernel.calibrate.build` returns the three
scorecards and `status().scorecard_count` reflects them; (g) missing outcome ⇒ that
revision scored only where inputs exist, never a fabricated 0.

**4B.** (h) single-factor revision gets a direct paired contribution; (i) a
multi-factor revision whose factor subset leaves the simplex is marked
`confounded_not_attributable` and feeds no estimate; (j) a small-sample factor
estimate is shrunk toward the global mean (no extreme rate); (k) a lifecycle proposal
is emitted but factor status is unchanged until the judge_operator Action applies it;
an ai_analyst apply is rejected; (l) a RegimeVector reports five axes, and a thin
cohort marks `percentile_unavailable` rather than borrowing a baseline; (m) post-match
labels live in a separate projection (no pre-match leakage); (n) Action/Integrity
scorecards compute ledger balance and coverage from real Transactions.

## 6. Non-goals / follow-ons

Bootstrap/Bayesian interval sophistication beyond a documented method; full
reliability-curve rendering; the CLI rewire and old-writer shutdown (Package 5). Each
is named, not silently skipped.
