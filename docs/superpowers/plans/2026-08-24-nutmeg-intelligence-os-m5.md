# Nutmeg Intelligence OS M5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Deliver ontology-backed settlement review, calibration, ontology browsing, and a governed migration from the manual scoreboard to deterministic projections plus attributable observations.

**Architecture:** Migration 13 adds typed scoreboard state to the operational SQLite ontology. Existing scoring, settlement, ledger, factor, and lifecycle implementations remain authoritative; M5 adds read-only DuckDB projections and product DTOs around them, while every manual fact and authority change passes through a typed Action. A CLI-only authority service compares exact legacy bytes, blocks unexplained differences, switches only an isolated store after human approval, and exports canonical compatibility JSON atomically.

**Tech Stack:** Python 3.12, SQLAlchemy 2 Core, SQLite WAL, DuckDB, FastAPI, Pydantic v2, Jinja2 SSR, progressive JavaScript, pytest, Ruff, Playwright browser verification.

**Design Spec:** `docs/superpowers/specs/2026-08-24-nutmeg-intelligence-os-m5-design.md`

**Execution note:** Repository instructions prohibit subagents. Execute inline in the current dedicated worktree, one RED-GREEN-REFACTOR slice at a time. Prefix every `uv`, pre-commit, and hook-triggering commit command with `UV_FROZEN=1`. Never mutate production `.nutmeg-data`, invoke providers/connectors, dispatch Telegram, change schedules, place a ticket, or write the user-owned production SOP files.

---

## Scope and locked decisions

- M1-M4 are closed and change only at explicit M5 integration points or for a proven regression.
- Migration 13 is additive; migrations 1-12 and their fingerprints never change.
- Forecast truth, money ledger, and intervention quality remain separate planes with separate coverage.
- `brier`, existing forecast projectors, odds-faithful settlement, ledger rows, factor estimates, and lifecycle proposals are imported or read. M5 does not reimplement their arithmetic.
- A counterfactual is scoreable only when a strict distribution was durably recorded before the current Outcome.
- Lifecycle projection is advisory. Only the existing judge-only `apply_factor_status` Action mutates factor state.
- Manual scoreboard content becomes typed observations with evidence. Opaque prose is never parsed into synthetic numeric facts.
- Cutover is CLI-only, human-only, optimistic, exact-hash bound, and blocked by stale or unexplained shadow results.
- After cutover, `scoreboard.json` is canonical compatibility output; drift is an error, never an import source.
- Product JavaScript performs no score, settlement, ledger, projection, or lifecycle arithmetic.
- Production cutover refuses to run until all five authority documents contain the required statements. Tests use fixture copies only.

## File structure

### New production files

- `nutmeg/ontology/scoreboard/__init__.py`: stable M5 scoreboard exports.
- `nutmeg/ontology/scoreboard/models.py`: immutable observation, review, authority, and export rows.
- `nutmeg/ontology/repository/schema_scoreboard.py`: migration-13 tables only.
- `nutmeg/ontology/repository/scoreboard.py`: typed scoreboard persistence and optimistic authority operations.
- `nutmeg/ontology/actions/scoreboard_actions.py`: four typed scoreboard Actions.
- `nutmeg/analytics/intervention_projection.py`: intervention coverage and preregistered counterfactual replay.
- `nutmeg/analytics/scoreboard_projection.py`: deterministic three-plane/lifecycle/manual scoreboard projection.
- `nutmeg/scoreboard/__init__.py`: stable authority workflow exports.
- `nutmeg/scoreboard/authority.py`: legacy CAS ingest, shadow comparison, cutover gates, atomic export, drift checks, and SOP authority checker.
- `nutmeg/interfaces/cli/scoreboard.py`: fixture-safe import/shadow/cutover/export/status commands.
- `nutmeg/interfaces/web/templates/product/review.html`: Settlement and Review Center.
- `nutmeg/interfaces/web/templates/product/calibration.html`: Rule and Calibration Center.
- `nutmeg/interfaces/web/templates/product/ontology.html`: allowlisted Ontology Browser.
- `docs/nutmeg-intelligence-os-m5-operations.md`: migration, recovery, authority, and production precondition runbook.

### Existing production files modified

- `nutmeg/ontology/repository/migrations.py`: append migration 13 and exact role permissions.
- `nutmeg/ontology/repository/unit_of_work.py`: expose `.scoreboard` repository.
- `nutmeg/ontology/repository/workflow.py`: typed iteration needed by intervention projection.
- `nutmeg/ontology/kernel.py`: expose ScoreboardActions and M5 status counts.
- `nutmeg/ontology/wiring.py`: wire ScoreboardActions.
- `nutmeg/analytics/calibrate_flow.py`: register intervention and scoreboard projectors.
- `nutmeg/analytics/substrate.py`: expose M5 projection counts without changing substrate semantics.
- `nutmeg/product/contracts.py`: strict review, calibration, ontology, scoreboard, and lifecycle-action DTOs.
- `nutmeg/product/repository.py`: read operational planes, DuckDB projections, allowlisted object detail, lineage, and `as_of` history.
- `nutmeg/product/queries.py`: assemble M5 responses and explicit degraded projection states.
- `nutmeg/product/actions.py`: map manual observation and existing factor lifecycle Actions without accepting actor roles.
- `nutmeg/product/wiring.py`: pass the analytics path and scoreboard services.
- `nutmeg/interfaces/product_api.py`: five read endpoints plus existing generic Action mapping.
- `nutmeg/interfaces/product_ui.py`: `/review`, `/calibration`, and `/ontology` SSR routes.
- `nutmeg/interfaces/web/templates/product/layout.html`: M5 navigation.
- `nutmeg/interfaces/web/static/product/app.js`: human apply/reject and observation forms only.
- `nutmeg/interfaces/web/static/product/app.css`: dense responsive M5 workspace states.
- `nutmeg/interfaces/cli/__init__.py`: register scoreboard commands.

### Tests and evidence

- `tests/ontology/test_m5_scoreboard_migration.py`
- `tests/ontology/test_scoreboard_actions.py`
- `tests/analytics/test_intervention_projection.py`
- `tests/analytics/test_scoreboard_projection.py`
- `tests/scoreboard/test_authority.py`
- `tests/product/test_m5_contracts.py`
- `tests/product/test_m5_repository.py`
- `tests/product/test_m5_queries.py`
- `tests/product/test_m5_api.py`
- `tests/product/test_m5_ui.py`
- `tests/product/test_m5_e2e.py`
- `tests/fixtures/m5/sop/`: fixture authority documents; never copied to production.
- `docs/superpowers/evidence/m5/`: final desktop/mobile/offline browser evidence.

## Task 1: Migration 13, scoreboard models, and repository

**Files:** create the scoreboard model/schema/repository files; modify migrations and UoW; test `tests/ontology/test_m5_scoreboard_migration.py`.

- [x] **Step 1: Write failing migration and repository tests**

Assert `run_migrations()` ends at 13, creates the three design tables, seeds a singleton legacy authority row at version 1, grants observation/cutover only to `judge_operator`, grants shadow/export only to `deterministic_system`, and grants none to AI roles. Exercise exact JSON round-trips, observation supersession, evidence non-emptiness, review insertion, latest review, authority optimistic conflict, and current authority lookup:

```python
def test_migration_13_seeds_legacy_authority_and_permissions(tmp_path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    assert run_migrations(engine).applied_versions[-1] == 13
    with OntologyUnitOfWork(engine) as uow:
        authority = uow.scoreboard.authority()
    assert authority.state == "legacy"
    assert authority.version == 1
```

- [x] **Step 2: Run and verify RED**

Run: `UV_FROZEN=1 uv run pytest tests/ontology/test_m5_scoreboard_migration.py -q`

Expected: current schema version is 12 and scoreboard modules are absent.

- [x] **Step 3: Declare exact schema and immutable rows**

Implement the three tables exactly as design spec section 6, including all FKs, uniqueness, the singleton authority check, non-negative count checks, and authority version. Define `ScoreboardObservationRow`, `ScoreboardShadowReviewRow`, and `ScoreboardAuthorityRow` as frozen/slotted dataclasses. Store JSON only through `canonical_json()` and reject malformed persisted JSON instead of defaulting.

- [x] **Step 4: Append migration 13 and repository operations**

Append `Migration(version=13, name="scoreboard_authority", ...)`. Seed only the four declared permission/role pairs and one legacy authority row. Provide:

```text
insert_observation(row) / observation(id) / latest_observations(as_of)
insert_shadow_review(row) / shadow_review(id) / latest_shadow_review()
authority()
approve_authority(expected_version, review_id, projection_version,
                  source_high_watermark, legacy_sha256, approved_at, action_id)
record_export(expected_version, export_sha256, action_id)
count_observations() / count_shadow_reviews()
```

Every update checks the singleton's expected version and raises `OptimisticConcurrencyError` on zero updated rows.

- [x] **Step 5: Run migration and repository regressions**

Run:

```bash
UV_FROZEN=1 uv run pytest tests/ontology/test_m5_scoreboard_migration.py tests/ontology/test_migrations.py tests/ontology/test_m4_ticket_migration.py -q
UV_FROZEN=1 uv run ruff check nutmeg/ontology/scoreboard nutmeg/ontology/repository tests/ontology/test_m5_scoreboard_migration.py
```

Expected: all pass.

- [x] **Step 6: Commit Task 1**

```bash
UV_FROZEN=1 git add nutmeg/ontology/scoreboard nutmeg/ontology/repository tests/ontology/test_m5_scoreboard_migration.py
UV_FROZEN=1 git commit -m "feat(ontology): add scoreboard authority persistence"
```

## Task 2: Typed scoreboard Actions and permissions

**Files:** create `nutmeg/ontology/actions/scoreboard_actions.py`; modify action exports, kernel, wiring; test `tests/ontology/test_scoreboard_actions.py`.

- [x] **Step 1: Write failing Action tests**

Cover `RecordScoreboardObservation`, `RecordScoreboardShadowReview`, `ApproveScoreboardCutover`, and `RecordScoreboardExport`. Tests must prove evidence-required observation validation, immutable revision via `supersedes`, idempotent replay, AI denial/audit, role separation, zero-unexplained and succeeded-review cutover, exact legacy hash, exact current projection watermark, stale authority rejection, and outbox emission.

```python
def test_ai_cannot_record_observation(kernel, request):
    denied = kernel.scoreboard_actions.record_observation(
        replace(request, actor_role=ActorRole.AI_ANALYST)
    )
    assert denied.status is ActionStatus.REJECTED
    assert kernel.status().scoreboard_observation_count == 0
```

- [x] **Step 2: Run and verify RED**

Run: `UV_FROZEN=1 uv run pytest tests/ontology/test_scoreboard_actions.py -q`

Expected: scoreboard Actions do not exist.

- [x] **Step 3: Implement strict requests and handlers**

All request types require aware timestamps, non-blank identities/keys, and exact actor roles through database permissions. Observation validation requires non-empty group/metric/tally/detail/status and at least one `ObjectRef`; numeric denominator cannot be negative and numerator cannot exceed a non-null non-negative denominator. Shadow records require canonical classifications whose counts exactly equal the list contents. Cutover re-reads authority/review inside the Action transaction and checks the review ID, status, zero unexplained count, exact legacy hash, exact projection version, and exact source watermark.

- [x] **Step 4: Emit deterministic outbox topics**

Emit `scoreboard.observation_recorded`, `scoreboard.shadow_reviewed`, `scoreboard.authority_changed`, and `scoreboard.export_recorded`, using object refs only and no legacy file bodies.

- [x] **Step 5: Run Action and kernel regressions**

Run:

```bash
UV_FROZEN=1 uv run pytest tests/ontology/test_scoreboard_actions.py tests/ontology/test_action_service.py tests/ontology/test_kernel.py -q
UV_FROZEN=1 uv run ruff check nutmeg/ontology/actions/scoreboard_actions.py nutmeg/ontology/kernel.py nutmeg/ontology/wiring.py
```

- [x] **Step 6: Commit Task 2**

```bash
UV_FROZEN=1 git add nutmeg/ontology/actions nutmeg/ontology/kernel.py nutmeg/ontology/wiring.py tests/ontology/test_scoreboard_actions.py
UV_FROZEN=1 git commit -m "feat(ontology): govern scoreboard actions"
```

## Task 3: Intervention and preregistered counterfactual projections

**Files:** create `nutmeg/analytics/intervention_projection.py`; modify workflow repository and calibrate registration; test `tests/analytics/test_intervention_projection.py`.

- [x] **Step 1: Write failing projection tests**

Build fixtures with confirmed/refuted/void/pending Predictions, directional and non-directional Flags, accepted/rejected Adjudications, current and corrected Outcomes, and alternatives that are valid, late, malformed, unlinked, or absent. Assert counts and coverage precede rates and each counterfactual row has an explicit `eligibility_code`.

```python
def test_counterfactual_scores_only_preregistered_distribution(fixture):
    rows = compute_counterfactual_rows(fixture.engine)
    eligible = next(row for row in rows if row["adjudication_id"] == "adj-early")
    late = next(row for row in rows if row["adjudication_id"] == "adj-late")
    assert eligible["eligibility_code"] == "eligible"
    assert eligible["brier"] == brier({"home": .5, "draw": .3, "away": .2}, {"home": 1, "draw": 0, "away": 0})
    assert late["eligibility_code"] == "recorded_after_outcome"
    assert late["brier"] is None
```

- [x] **Step 2: Run and verify RED**

Run: `UV_FROZEN=1 uv run pytest tests/analytics/test_intervention_projection.py -q`

Expected: projection module is absent.

- [x] **Step 3: Add typed workflow iteration and explicit linking**

Add read-only iterators for Adjudications, Predictions, and FlagInstances. Resolve a match only through declared subject types (`match`, `forecast_revision`, `prediction`, `flag_instance`, `ticket`); unsupported or missing links return `unlinked_subject`. Validate the alternative object has exactly `market_definition_id`, `distribution`, and `label`, use the existing distribution contract, translate the current Outcome with `outcome_one_hot()`, and calculate only with existing `brier()`.

- [x] **Step 4: Project two tables and register them**

Write `intervention_scorecards` for coverage/count/rate rows and `counterfactual_replays` for per-Adjudication eligibility/score/provenance. Register `intervention_quality` version `iq-v1` in `CalibrateService`; failed builds retain last-good projection through the existing substrate.

- [x] **Step 5: Run analytics regressions**

Run:

```bash
UV_FROZEN=1 uv run pytest tests/analytics/test_intervention_projection.py tests/analytics/test_calibrate_flow.py tests/analytics/test_forecast_projection.py tests/analytics/test_scorecards.py -q
UV_FROZEN=1 uv run ruff check nutmeg/analytics/intervention_projection.py nutmeg/ontology/repository/workflow.py
```

- [x] **Step 6: Commit Task 3**

```bash
UV_FROZEN=1 git add nutmeg/analytics nutmeg/ontology/repository/workflow.py tests/analytics/test_intervention_projection.py
UV_FROZEN=1 git commit -m "feat(analytics): project intervention quality"
```

## Task 4: Deterministic scoreboard projection, shadow review, cutover, and export

**Files:** create analytics scoreboard projection and scoreboard authority package; modify calibrate/counts; test `tests/analytics/test_scoreboard_projection.py` and `tests/scoreboard/test_authority.py`.

- [x] **Step 1: Write failing projection tests**

Assert `scoreboard_metrics` contains separate forecast, money, intervention, lifecycle, and manual rows, each with provenance and coverage. Money rows must equal authoritative Ticket/Settlement/CashTransaction values; missing data stays null/unscored. Manual rows come only from latest non-superseded observations at `as_of`.

- [x] **Step 2: Run projection test and verify RED**

Run: `UV_FROZEN=1 uv run pytest tests/analytics/test_scoreboard_projection.py -q`

Expected: scoreboard projector is absent.

- [x] **Step 3: Implement projection without replacement arithmetic**

Read existing DuckDB forecast/intervention/factor/lifecycle tables and operational settlement/ledger rows. Emit canonical metric records with `plane`, `group_key`, `metric_key`, structured values, coverage numerator/denominator, source refs, and the substrate provenance columns. Register `scoreboard` version `sb-v1` after all source projectors in `CalibrateService`.

- [x] **Step 4: Write failing authority workflow tests**

Use a copied legacy JSON file, fixture SOP documents, temporary CAS, temporary SQLite, and temporary DuckDB. Cover exact-byte hashing, explicit `--acknowledge-manual-source`, one Action per retained manual metric, classification into only `matched|formal_manual|source_correction|unexplained`, unexplained block, stale hash/watermark/version conflict, clean isolated cutover, canonical repeated export, atomic failure preserving prior bytes, and drift detection preventing overwrite.

- [x] **Step 5: Run authority tests and verify RED**

Run: `UV_FROZEN=1 uv run pytest tests/scoreboard/test_authority.py -q`

Expected: authority service is absent.

- [x] **Step 6: Implement SOP checker and authority workflow**

The checker requires these semantic statements in each of `CONSTITUTION.md`, `RUNBOOK.md`, `RULEBOOK.md`, `AGENTS.md`, and `CLAUDE.md`: ontology/projections are authority; JSON is generated read-only compatibility output; reconcile/calibrate rebuilds and exports; manual facts use `RecordScoreboardObservation`; direct JSON edits are errors. Production-like cutover checks all five paths before invoking the Action. The checker never writes documents.

Legacy ingest stores exact bytes as a SourceArtifact, requires explicit acknowledgement, and never infers numbers from tally prose. Shadow input is an explicit classification document mapping every legacy group/metric to a formal observation or deterministic metric. Comparison rejects missing/duplicate/unknown keys and records a deterministic canonical review. Export content includes schema/authority/projection metadata, all planes, latest manual observations, content hash, and generation Action reference. Publish through a same-directory temp file, `fsync`, and `os.replace`; refuse overwrite when existing bytes do not match recorded authority hash.

- [x] **Step 7: Run focused verification**

Run:

```bash
UV_FROZEN=1 uv run pytest tests/analytics/test_scoreboard_projection.py tests/scoreboard/test_authority.py tests/analytics/test_calibrate_flow.py -q
UV_FROZEN=1 uv run ruff check nutmeg/analytics/scoreboard_projection.py nutmeg/scoreboard tests/scoreboard
```

- [x] **Step 8: Commit Task 4**

```bash
UV_FROZEN=1 git add nutmeg/analytics nutmeg/scoreboard tests/analytics/test_scoreboard_projection.py tests/scoreboard
UV_FROZEN=1 git commit -m "feat(scoreboard): add governed authority workflow"
```

## Task 5: Strict M5 product DTOs and read repository

**Files:** modify product contracts/repository/wiring; test `tests/product/test_m5_contracts.py` and `tests/product/test_m5_repository.py`.

- [x] **Step 1: Write failing strict-contract tests**

Define and reject extras for `ProjectionHealth`, `MetricValue`, `ScorePlane`, `ReviewResponse`, `FactorEstimateSummary`, `LifecycleProposalSummary`, `CalibrationResponse`, `OntologyObjectSummary`, `OntologyObjectDetail`, `OntologyObjectPage`, and `ScoreboardResponse`. Assert nullable metrics and coverage cannot be silently coerced to zero.

- [x] **Step 2: Write failing repository tests**

Prove read-only behavior, DuckDB-absent degraded response, last-good provenance, three separate planes, settlement/leg lineage, factor estimates/proposals/regimes, stable `(recorded_at, object_type, object_id)` cursor pagination, allowlisted types, strict `as_of`, Action history, source lineage, and no raw table/blob/secret fields.

- [x] **Step 3: Run and verify RED**

Run: `UV_FROZEN=1 uv run pytest tests/product/test_m5_contracts.py tests/product/test_m5_repository.py -q`

Expected: DTOs and repository methods are absent.

- [x] **Step 4: Implement DTOs and read methods**

Allowed browser types are an explicit mapping from public names to typed select builders: `match`, `team`, `competition`, `person`, `claim`, `observation`, `market_snapshot`, `forecast_revision`, `factor_definition`, `ticket`, `outcome`, `settlement`, `adjudication`, `flag_instance`, `prediction`, and `action`. Search is parameterized and limited to public identity fields. The repository receives `analytics_path`, checks file/table/projection health without creating DuckDB, and returns `projection_unavailable` or `projection_stale` with a rebuild instruction while continuing operational reads.

- [x] **Step 5: Run product read regressions**

Run:

```bash
UV_FROZEN=1 uv run pytest tests/product/test_m5_contracts.py tests/product/test_m5_repository.py tests/product/test_queries.py tests/product/test_m4_queries.py -q
UV_FROZEN=1 uv run ruff check nutmeg/product/contracts.py nutmeg/product/repository.py nutmeg/product/wiring.py
```

- [x] **Step 6: Commit Task 5**

```bash
UV_FROZEN=1 git add nutmeg/product tests/product/test_m5_contracts.py tests/product/test_m5_repository.py
UV_FROZEN=1 git commit -m "feat(product): expose learning read model"
```

## Task 6: Query assembly, API endpoints, and Action mapping

**Files:** modify product queries/actions and API; test `tests/product/test_m5_queries.py` and `tests/product/test_m5_api.py`.

- [x] **Step 1: Write failing query/API tests**

Exercise:

```text
GET /api/v1/review?as_of=...
GET /api/v1/calibration?as_of=...
GET /api/v1/ontology/objects?type=...&q=...&after=...&limit=...
GET /api/v1/ontology/objects/{object_type}/{object_id}?as_of=...
GET /api/v1/scoreboard?as_of=...
```

Assert strict responses, aware `as_of`, stable cursor, type/query/limit validation, 404 for absent object, 422 for disallowed type, operational content when DuckDB is missing, and no browser authority-switch endpoint. Add generic Action tests proving `record_scoreboard_observation` and existing `apply_factor_status` derive judge identity server-side, require reason/evidence/adjudication fields, and reject stale lifecycle proposals or AI role payloads.

- [x] **Step 2: Run and verify RED**

Run: `UV_FROZEN=1 uv run pytest tests/product/test_m5_queries.py tests/product/test_m5_api.py -q`

Expected: endpoints return 404 and Action mapping is absent.

- [x] **Step 3: Assemble M5 queries and route them**

Add `review(as_of)`, `calibration(as_of)`, `ontology_objects(...)`, `ontology_object(...)`, and `scoreboard(as_of)` to `ProductQueryService`. Add the five exact API routes. Keep all read routes side-effect free. Map only the declared user-facing Actions through `ProductActionGateway`; shadow/cutover/export remain CLI-only. Return existing stable ProductError shapes for validation, not-found, permission, and optimistic conflicts.

- [x] **Step 4: Run API/security regressions**

Run:

```bash
UV_FROZEN=1 uv run pytest tests/product/test_m5_queries.py tests/product/test_m5_api.py tests/product/test_api.py tests/product/test_actions.py tests/product/test_m4_api.py -q
UV_FROZEN=1 uv run ruff check nutmeg/product/queries.py nutmeg/product/actions.py nutmeg/interfaces/product_api.py
```

- [x] **Step 5: Commit Task 6**

```bash
UV_FROZEN=1 git add nutmeg/product nutmeg/interfaces/product_api.py tests/product/test_m5_queries.py tests/product/test_m5_api.py
UV_FROZEN=1 git commit -m "feat(api): add M5 learning endpoints"
```

## Task 7: Review, calibration, and ontology workspaces

**Files:** create three templates; modify UI, layout, CSS, and JS; test `tests/product/test_m5_ui.py`.

- [x] **Step 1: Write failing SSR and narrow-state tests**

Assert `/review`, `/calibration`, and `/ontology` render without JavaScript; active navigation is correct; all metric values show coverage/provenance; the three score planes are visibly separate; settlement and counterfactual rows preserve empty/unscored states; lifecycle controls include expected versions and adjudication reasons; ontology search uses allowlisted filters and cursor links; IDs/hashes wrap; controls are at least 44 pixels; and JavaScript contains no arithmetic primitives or client-supplied actor role.

- [x] **Step 2: Run and verify RED**

Run: `UV_FROZEN=1 uv run pytest tests/product/test_m5_ui.py -q`

Expected: the three routes return 404.

- [x] **Step 3: Implement SSR workspaces**

`review.html` uses three full-width score bands, then dense settlement and counterfactual tables. `calibration.html` shows projection health, factor estimate interval/sample/cohort, proposal/current status, regime summaries, and human apply/reject forms. `ontology.html` shows type/search controls, stable pages, typed properties, links, versions, source lineage, and Action history. Reuse existing layout tokens and Lucide-compatible icon style; do not add nested cards, decorative gradients, client-side calculations, raw SQL controls, or blob viewers.

- [x] **Step 4: Implement progressive mutations and responsive CSS**

Use the existing session/CSRF helper for lifecycle and observation forms. The browser never supplies actor IDs/roles and never switches scoreboard authority. At 390px, document order is forecast/money/intervention then tables; every control remains usable and long IDs wrap without horizontal viewport overflow.

- [x] **Step 5: Run UI regressions**

Run:

```bash
UV_FROZEN=1 uv run pytest tests/product/test_m5_ui.py tests/product/test_m4_ui.py tests/product/test_m3_ui.py -q
UV_FROZEN=1 uv run ruff check nutmeg/interfaces/product_ui.py
```

- [x] **Step 6: Commit Task 7**

```bash
UV_FROZEN=1 git add nutmeg/interfaces/product_ui.py nutmeg/interfaces/web tests/product/test_m5_ui.py
UV_FROZEN=1 git commit -m "feat(ui): add settlement learning workspaces"
```

## Task 8: CLI authority operations, full M5 E2E, and operations contract

**Files:** create CLI and operations doc; modify CLI registration; test `tests/product/test_m5_e2e.py`, `tests/product/test_cli.py`, and `tests/scoreboard/test_authority.py`.

- [x] **Step 1: Write failing CLI and lifecycle E2E tests**

CLI tests cover `scoreboard status`, `observe`, `shadow`, `cutover`, `export`, and `verify-export`; all accept explicit `--data-dir`, all machine-readable output is canonical JSON, and mutating commands require explicit acknowledgement/expected hashes/versions. The E2E creates an isolated store and drives Ticket placement -> Outcome -> odds-faithful Settlement -> calibrate -> three-plane review -> lifecycle proposal -> judge `apply_factor_status` -> manual observation -> shadow -> clean cutover -> export -> ontology lineage. It asserts AI cannot apply factor state or change authority and source hashes remain unchanged.

- [x] **Step 2: Run and verify RED**

Run: `UV_FROZEN=1 uv run pytest tests/product/test_cli.py tests/product/test_m5_e2e.py -q`

Expected: scoreboard CLI commands and M5 E2E behavior are absent.

- [x] **Step 3: Implement guarded CLI commands**

Every command resolves explicit paths, prints planned targets, and performs no network action. `observe` requires `--acknowledge-manual-source`; `shadow` requires the exact legacy file and explicit classification file; `cutover` requires expected authority version, review ID, exact legacy SHA, projection version/watermark, all five SOP paths, and `--approve`; `export` requires ontology authority and drift-free destination. No command defaults to the production data root when a mutating operation is invoked from tests.

- [x] **Step 4: Write the operations contract**

Document authority states, role matrix, manual observation procedure, calibrate/shadow/cutover/export sequence, required five-document SOP statements, exact-hash and watermark gates, drift recovery, atomic write recovery, rollback boundary, isolated rehearsal commands, production prohibition during feature verification, and M6 handoff. State that M5 code completion does not itself authorize production cutover.

- [x] **Step 5: Run E2E, CLI, and frozen-store migration checks**

Copy an M4 fixture/store to a temporary directory, hash the source copy, migrate the destination to 13, build projections, run the E2E, and verify the source hash is unchanged:

```bash
UV_FROZEN=1 uv run pytest tests/product/test_cli.py tests/product/test_m5_e2e.py tests/scoreboard/test_authority.py -q
UV_FROZEN=1 uv run ruff check nutmeg/interfaces/cli/scoreboard.py tests/product/test_m5_e2e.py
```

- [x] **Step 6: Commit Task 8**

```bash
UV_FROZEN=1 git add nutmeg/interfaces/cli docs/nutmeg-intelligence-os-m5-operations.md tests/product/test_cli.py tests/product/test_m5_e2e.py tests/fixtures/m5
UV_FROZEN=1 git commit -m "test(product): prove M5 settlement learning lifecycle"
```

## Task 9: Independent critique, browser evidence, replay, and completion gate

**Files:** modify only defects exposed by verification; create `docs/superpowers/evidence/m5/README.md` plus screenshots.

- [x] **Step 1: Run focused M5 suites**

```bash
UV_FROZEN=1 uv run pytest tests/ontology/test_m5_scoreboard_migration.py tests/ontology/test_scoreboard_actions.py tests/analytics/test_intervention_projection.py tests/analytics/test_scoreboard_projection.py tests/scoreboard tests/product/test_m5_contracts.py tests/product/test_m5_repository.py tests/product/test_m5_queries.py tests/product/test_m5_api.py tests/product/test_m5_ui.py tests/product/test_m5_e2e.py -q
```

Expected: zero failures.

- [x] **Step 2: Run independent spec critique**

Use `speckit-superb-critique` against the M5 design, this plan, base-to-head diff, and full test output. Fix every Critical and Important finding with a new RED-GREEN cycle. Record the resolved findings in the evidence README.

- [x] **Step 3: Run full repository quality gates**

```bash
UV_FROZEN=1 uv run pytest -q
UV_FROZEN=1 uv run ruff check .
UV_FROZEN=1 uv run python -m compileall -q nutmeg scripts
UV_FROZEN=1 uv run pre-commit run --all-files
git diff --check main...HEAD
git diff --check
```

Expected: zero failures/errors and clean whitespace.

- [x] **Step 4: Run safe project replay**

Use the project `verify` recipe only against a fresh temporary replay root: decision-am snapshot replay, decision-settle, and decision-close without `--dispatch-telegram` or `--no-dry-run`. Capture behavioral summaries and produced paths; never modify production data.

- [x] **Step 5: Verify desktop, mobile, degraded, and restored browser states**

Start the local app over a fixture data root on an unused localhost port. Capture `/review`, `/calibration`, and `/ontology` at 1440x1000 and 390x844. Verify no blank sections, overflow, overlap, console errors, failed assets, or client arithmetic. Remove/rename only the fixture DuckDB to capture degraded projection states, restore it, and verify the UI recovers. Record URLs, viewport sizes, screenshot names, and findings in the evidence README.

- [x] **Step 6: Verify no production or authority mutation**

Hash the production `.nutmeg-data/scoreboard.json`, ontology DB, SOP trilogy, `AGENTS.md`, and `CLAUDE.md` before and after M5 verification. The hashes must match. Inspect `git status`, base-to-head diff, migration sequence, and commit list.

- [x] **Step 7: Commit M5 verification evidence**

```bash
UV_FROZEN=1 git add docs/superpowers/evidence/m5
UV_FROZEN=1 git commit -m "docs(product): record M5 verification"
```

## M5 spec coverage

| Design requirement | Implemented by |
|---|---|
| Three separate score planes and explicit coverage | Tasks 3-7 |
| Existing scoring/settlement/ledger arithmetic remains authoritative | Tasks 3-5, 8 |
| Preregistered-only counterfactual replay and corrected Outcome rebuild | Task 3 |
| Human-only factor lifecycle mutation | Tasks 2, 6, 8 |
| Typed manual observations with evidence and supersession | Tasks 1-2 |
| Exact legacy hash, shadow classification, zero-unexplained gate | Task 4 |
| Human-only optimistic authority switch | Tasks 1-4 |
| Canonical atomic compatibility export and drift detection | Task 4 |
| Review, calibration, ontology, and scoreboard APIs | Tasks 5-6 |
| Dense SSR workspaces and no client arithmetic | Task 7 |
| DuckDB absence/staleness degrades without hiding SQLite truth | Tasks 5-7 |
| SOP authority precondition without mutating user-owned files | Tasks 4, 8-9 |
| Full isolated lifecycle, replay, browser, and non-mutation proof | Tasks 8-9 |

M5 is complete only after Task 9 has fresh evidence and all Critical/Important critique findings are resolved. Completion does not approve a production scoreboard cutover; that remains a separate operator action after the user-owned SOP documents are updated.
