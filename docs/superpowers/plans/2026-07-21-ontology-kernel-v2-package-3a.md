# Ontology Kernel v2 Package 3A Implementation Plan — Belief Layer

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn a market prior into an auditable, leak-proof, factor-decomposed belief: freeze an EvidenceBundle at a cutoff, draft/commit a ForecastRevision whose factor deltas sum exactly to belief−prior, with a single current committed revision per series enforced by optimistic concurrency.

**Architecture:** Package 3A adds the belief layer on the delivered Package 1 kernel and Packages 2A/2B facts. It touches no kernel/2A/2B write semantics: new tables extend `schema.metadata` via migration 7; a new `.decision` repository hangs off `OntologyUnitOfWork`; every write is an `ActionService.execute` handler. The EvidenceBundle only freezes evidence recorded at/before the cutoff (no future leak); ForecastRevision anchors `prior` to a 2A read-time MarketSnapshot fair distribution, and `belief=prior` is a legal "follow market" commit. FactorApplication deltas are validated to reconstruct `belief−prior` exactly. Commit/revise use the Action envelope's `expected_versions` (dormant since Package 1) to enforce a single current committed revision.

**Tech Stack:** Python 3.13, frozen dataclasses, SQLAlchemy 2 Core, SQLite WAL, pytest, ruff; Package 1 kernel; 2A identity/market (`MarketSnapshot` fair, `MarketRepository.latest_fair`); 2B evidence (`Observation`, `verification_method`).

**Design Spec:** `docs/superpowers/specs/2026-07-21-ontology-kernel-v2-package-3-design.md` (§1 scope 3A, §2.1/§2.2/§2.3 decisions, §3 tables 3A, §4 actions 3A, §6 acceptance 3A).

**Depends on:** Packages 1, 2A, 2B (merged). Uses: `ActionCommand.create` (incl. `expected_versions`), `ActionService(uow_factory).execute`, `ActorRole`, `OntologyUnitOfWork.{identity,market,evidence}`, `MarketRepository.latest_fair`, `schema.metadata`, `Migration`/`MIGRATIONS`/`run_migrations`, `canonical_json`, `OntologyKernelStatus`.

---

## Scope Boundary

Package 3A includes:

- decision tables (migration 7): decision_sessions, evidence_bundles, evidence_bundle_items,
  forecast_series, forecast_revisions, factor_families, factor_definitions, factor_applications, scenarios;
- decision action permissions (graded: ai_analyst drafts/proposes, judge_operator commits/applies);
- a `DecisionRepository` and `OntologyUnitOfWork.decision`;
- a pure distribution/delta validator (normalization, `Σ delta == belief − prior`, simplex);
- Actions: `open_decision_session`, `freeze_evidence_bundle`, `draft_forecast`, `commit_forecast`,
  `revise_forecast`, `withdraw_forecast`, `propose_factor_status`, `apply_factor_status`;
- optimistic single-current-committed-revision enforcement via `expected_versions`;
- a read-flow orchestration (session → bundle → draft → commit), kernel counts, and a real-Match replay gate.

Package 3A excludes (3B / 4 / 5):

- TicketProposal/Ticket/BetLeg/Ledger/Outcome/Settlement (3B);
- Brier/CLV/calibration/FactorEstimate/RegimeVector *computation* and DuckDB projections (4) — 3A builds only
  the factor lifecycle **state machine** (propose/apply), not aggregate verdicts;
- historical migration, old-write-path shutdown, schedule restore (5).

Only **additive** changes to Package 1/2 modules: one `MIGRATIONS` entry, one `OntologyUnitOfWork.decision`
property, new `OntologyKernelStatus` counts (`forecast_count`, `bundle_count`), and `build_ontology_kernel`
exposing a decision read facade. Do not change any existing signature, table, or test except decoupling a
migration-count assertion if one is hard-coded (see Task 2).

---

## File Structure

### New production modules

- `nutmeg/ontology/decision/__init__.py`: decision public exports.
- `nutmeg/ontology/decision/models.py`: ForecastStatus, FactorStatus, CommitmentTier, SessionStatus enums; id minting.
- `nutmeg/ontology/decision/distributions.py`: pure distribution/delta validation helpers.
- `nutmeg/ontology/repository/schema_decision.py`: decision Core tables on the shared `metadata`.
- `nutmeg/ontology/repository/decision.py`: DecisionRepository + row dataclasses.
- `nutmeg/ontology/actions/session_actions.py`: OpenDecisionSession.
- `nutmeg/ontology/actions/bundle_actions.py`: FreezeEvidenceBundle.
- `nutmeg/ontology/actions/forecast_actions.py`: DraftForecast / CommitForecast / ReviseForecast / WithdrawForecast.
- `nutmeg/ontology/actions/factor_actions.py`: ProposeFactorStatus / ApplyFactorStatus.
- `nutmeg/ontology/decision/read_flow.py`: DecisionReadService orchestration (session→bundle→draft→commit).

### New tests

- `tests/ontology/test_decision_models.py`
- `tests/ontology/test_schema_decision_migration.py`
- `tests/ontology/test_distributions.py`
- `tests/ontology/test_decision_repository.py`
- `tests/ontology/test_session_actions.py`
- `tests/ontology/test_freeze_bundle.py`
- `tests/ontology/test_draft_forecast.py`
- `tests/ontology/test_commit_forecast.py`
- `tests/ontology/test_revise_withdraw.py`
- `tests/ontology/test_factor_actions.py`
- `tests/ontology/test_decision_read_flow.py`
- `tests/ontology/test_package3a_e2e.py`

### Existing files modified (additive)

- `nutmeg/ontology/repository/migrations.py`: import schema_decision; append migration 7 + decision permissions.
- `nutmeg/ontology/repository/unit_of_work.py`: add `.decision` (lazy import + TYPE_CHECKING).
- `nutmeg/ontology/kernel.py`: add `forecast_count`/`bundle_count` to `OntologyKernelStatus`; add `decision_read` to `OntologyKernel`.
- `nutmeg/ontology/wiring.py`: build the decision actions + `DecisionReadService`, expose it.
- `docs/ontology-kernel-operations.md`: add a Package 3A section.

### User-owned files that must not be reverted

Unrelated edits to `SOUL.md` and the three decision launchd plists plus untracked `media/`, memory and
research-script files. Package 3A does not modify or stage them. Execute in the dedicated worktree (Task 0).

---

### Task 0: Create a clean implementation worktree

**Files:** Worktree only: `.claude/worktrees/ontology-kernel-v2-package3a/`

- [ ] **Step 1: Confirm Package 2 is merged and the tree is clean of in-scope files**

Run `git -C /Users/jz71/Projects/Nutmeg log --oneline -1` and `git -C /Users/jz71/Projects/Nutmeg status --short`.
Expected: HEAD is the Package 2B merge or later docs; dirty entries are only the user-owned files. Otherwise stop and ask.

- [ ] **Step 2: Do not touch the paused decision schedules or the freeze archive** (Package 5 gate).

- [ ] **Step 3: Create the worktree**

```bash
cd /Users/jz71/Projects/Nutmeg
git worktree add .claude/worktrees/ontology-kernel-v2-package3a -b feature/ontology-kernel-v2-package3a
(cd .claude/worktrees/ontology-kernel-v2-package3a && uv sync --extra dev)
```
Expected: clean worktree on `feature/ontology-kernel-v2-package3a`; deps synced. All tasks run there.

---

### Task 1: Decision value objects

**Files:** Create `nutmeg/ontology/decision/__init__.py`, `nutmeg/ontology/decision/models.py`; Test `tests/ontology/test_decision_models.py`

- [ ] **Step 1: Write the failing test**

```python
from nutmeg.ontology.decision.models import (
    CommitmentTier, FactorStatus, ForecastStatus, SessionStatus, mint_decision_id,
)


def test_enum_values_are_stable_snake_case() -> None:
    assert ForecastStatus.DRAFT.value == "draft"
    assert ForecastStatus.COMMITTED.value == "committed"
    assert ForecastStatus.SUPERSEDED.value == "superseded"
    assert ForecastStatus.WITHDRAWN.value == "withdrawn"
    assert FactorStatus.PROBATION.value == "probation"
    assert FactorStatus.ACTIVE.value == "active"
    assert FactorStatus.RETIRED.value == "retired"
    assert CommitmentTier.FOLLOW.value == "follow"
    assert SessionStatus.OPEN.value == "open"


def test_mint_decision_id_is_prefixed_and_unique() -> None:
    a = mint_decision_id("fr")
    assert a.startswith("fr-")
    assert a != mint_decision_id("fr")
```

- [ ] **Step 2: Run and verify RED** — `uv run pytest tests/ontology/test_decision_models.py -q` → ModuleNotFoundError.

- [ ] **Step 3: Implement**

`StrEnum`s with exactly: `ForecastStatus{DRAFT=draft, COMMITTED=committed, SUPERSEDED=superseded, WITHDRAWN=withdrawn}`,
`FactorStatus{PROBATION=probation, ACTIVE=active, RETIRED=retired}`,
`CommitmentTier{FOLLOW=follow, LEAN=lean, COMMIT=commit}`,
`SessionStatus{OPEN=open, CLOSED=closed}`; `mint_decision_id(prefix) -> f"{prefix}-{uuid4().hex}"`.
Export all from `decision/__init__.py`.

- [ ] **Step 4: Run tests and ruff** — `uv run pytest tests/ontology/test_decision_models.py -q` and `uv run ruff check nutmeg/ontology/decision tests/ontology/test_decision_models.py`. Expected: pass.

- [ ] **Step 5: Commit** — `git add nutmeg/ontology/decision tests/ontology/test_decision_models.py && git commit -m "feat(ontology): add decision value objects"`

---

### Task 2: Decision schema and migration 7

**Files:** Create `nutmeg/ontology/repository/schema_decision.py`; Modify `migrations.py`; Test `tests/ontology/test_schema_decision_migration.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from sqlalchemy import inspect, select

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import migration_status, run_migrations
from nutmeg.ontology.repository.schema import action_permissions


def test_decision_migration_creates_tables_and_seeds_permissions(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    assert migration_status(engine).current_version >= 7
    names = set(inspect(engine).get_table_names())
    assert {"decision_sessions", "evidence_bundles", "evidence_bundle_items", "forecast_series",
            "forecast_revisions", "factor_families", "factor_definitions", "factor_applications",
            "scenarios"} <= names
    with engine.connect() as connection:
        pairs = {(r["action_type"], r["actor_role"])
                 for r in connection.execute(select(action_permissions)).mappings().all()}
    assert ("draft_forecast", "ai_analyst") in pairs
    assert ("commit_forecast", "judge_operator") in pairs
    assert ("commit_forecast", "ai_analyst") not in pairs   # AI cannot commit
```

- [ ] **Step 2: Run and verify RED** — import error for `schema_decision`.

- [ ] **Step 3: Declare decision tables** on the shared `metadata` exactly per design §3 (3A). All TEXT unless
  noted; JSON columns hold canonical documents; FKs reference 2A/2B tables (match_id→matches,
  market_definition_id→market_definitions, market_snapshot_id→market_snapshots,
  evidence_bundle_id→evidence_bundles, forecast_series_id→forecast_series). Constraints:
  `forecast_series UNIQUE(match_id, market_definition_id)`,
  `forecast_revisions UNIQUE(forecast_series_id, revision_no)`,
  `factor_definitions UNIQUE(factor_family_id, version)`. Index `forecast_revisions(forecast_series_id)`.

- [ ] **Step 4: Add migration 7** — import `schema_decision`; `_apply_decision(connection)` creates the nine
  tables in FK order (factor_families → factor_definitions before factor_applications; forecast_series before
  forecast_revisions; decision_sessions/evidence_bundles before dependents) and seeds `action_permissions`
  (governance-v1):

```text
open_decision_session:  judge_operator, deterministic_system
freeze_evidence_bundle: deterministic_system
draft_forecast:         ai_analyst, judge_operator
commit_forecast:        judge_operator
revise_forecast:        judge_operator
withdraw_forecast:      judge_operator
propose_factor_status:  ai_analyst, judge_operator
apply_factor_status:    judge_operator
```

Append `Migration(version=7, name='decision', fingerprint='decision_sessions..scenarios+decision_permissions', apply=_apply_decision)`.

- [ ] **Step 5: Run tests + migration/kernel regression** — `uv run pytest tests/ontology/test_schema_decision_migration.py tests/ontology/test_migrations.py tests/ontology/test_kernel.py -q` and ruff. The Package 1/2 tests assert against `MIGRATIONS` (decoupled), so they keep passing.

- [ ] **Step 6: Commit** — `git add nutmeg/ontology/repository/schema_decision.py nutmeg/ontology/repository/migrations.py tests/ontology/test_schema_decision_migration.py && git commit -m "feat(ontology): add decision schema and permissions"`

---

### Task 3: DecisionRepository and `.decision`

**Files:** Create `nutmeg/ontology/repository/decision.py`; Modify `unit_of_work.py`; Test `tests/ontology/test_decision_repository.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.decision import (
    DecisionRepository, ForecastRevisionRow, SessionRow,
)
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _prepare(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.identity.insert_match_minimal("match-1")
    return engine


def test_session_series_and_revision_persist(tmp_path: Path) -> None:
    engine = _prepare(tmp_path)
    now = datetime(2026, 7, 19, tzinfo=UTC).isoformat()
    with OntologyUnitOfWork(engine) as uow:
        repo: DecisionRepository = uow.decision
        repo.insert_session(SessionRow(
            decision_session_id="sess-1", opened_at=now, operator_id="op",
            cutoff_at=now, scope={"matches": ["match-1"]}, status="open", closed_at=None))
        series_id = repo.ensure_series("match-1", "md-had")
        again = repo.ensure_series("match-1", "md-had")
        assert series_id == again        # one series per (match, market)
        repo.insert_revision(ForecastRevisionRow(
            forecast_revision_id="fr-1", forecast_series_id=series_id, decision_session_id="sess-1",
            revision_no=1, status="committed", made_at=now, information_cutoff_at=now,
            prior_snapshot_id=None, prior_distribution={"home": 0.5, "draw": 0.3, "away": 0.2},
            belief_distribution={"home": 0.5, "draw": 0.3, "away": 0.2}, evidence_bundle_id=None,
            falsifier=None, actor_id="op", model_name=None, model_version=None,
            policy_version="governance-v1", commitment_tier="follow", evidence_coverage=None,
            evidence_quality=None, forecast_stability=None, supersedes_revision_id=None))
    with OntologyUnitOfWork(engine) as uow:
        current = uow.decision.current_committed_revision(series_id)
        assert current is not None
        assert current.forecast_revision_id == "fr-1"
        assert uow.decision.count_committed_revisions() == 1
```

- [ ] **Step 2: Run and verify RED** — import error for `DecisionRepository`.

- [ ] **Step 3: Implement DecisionRepository and `.decision`**

`decision.py` defines frozen row dataclasses `SessionRow`, `EvidenceBundleRow`, `ForecastRevisionRow`,
`FactorDefinitionRow`, `FactorApplicationRow` (JSON fields as dicts/lists, serialized with `canonical_json`)
and `DecisionRepository(connection)` with at least: `insert_session`, `ensure_series(match_id,
market_definition_id) -> str` (mint + insert if absent, else return existing id — the `UNIQUE(match_id,
market_definition_id)` guarantees one), `insert_revision`, `insert_bundle`, `add_bundle_item`,
`bundle_item_ids(bundle_id)`, `insert_factor_definition`, `insert_factor_application`,
`current_committed_revision(series_id) -> ForecastRevisionRow | None`,
`max_revision_no(series_id) -> int`, `set_revision_status(forecast_revision_id, status)`,
`count_committed_revisions()`, `count_bundles()`. Add `.decision` to `OntologyUnitOfWork` (lazy import + TYPE_CHECKING).

- [ ] **Step 4: Run tests and ruff.**
- [ ] **Step 5: Commit** — `feat(ontology): add decision repository`

---

### Task 4: Distribution & delta validation

**Files:** Create `nutmeg/ontology/decision/distributions.py`; Test `tests/ontology/test_distributions.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest

from nutmeg.ontology.decision.distributions import (
    delta_from, is_normalized, reconstructs_belief, validate_simplex,
)


def test_normalization_and_reconstruction() -> None:
    prior = {"home": 0.5, "draw": 0.3, "away": 0.2}
    belief = {"home": 0.6, "draw": 0.25, "away": 0.15}
    d = delta_from(prior, belief)
    assert abs(sum(d.values())) < 1e-9          # deltas sum to zero
    assert reconstructs_belief(prior, [d], belief)
    assert is_normalized(belief)
    assert not is_normalized({"home": 0.6, "draw": 0.6, "away": 0.6})


def test_reconstruct_rejects_wrong_delta_sum() -> None:
    prior = {"home": 0.5, "draw": 0.3, "away": 0.2}
    belief = {"home": 0.6, "draw": 0.25, "away": 0.15}
    wrong = {"home": 0.2, "draw": 0.0, "away": 0.0}   # does not reach belief
    assert not reconstructs_belief(prior, [wrong], belief)


def test_validate_simplex_rejects_negative_or_unnormalized() -> None:
    with pytest.raises(ValueError):
        validate_simplex({"home": 1.2, "draw": -0.2, "away": 0.0})
```

- [ ] **Step 2: Run and verify RED.**

- [ ] **Step 3: Implement pure helpers**

`is_normalized(dist, tol=1e-6)` → `abs(sum − 1) <= tol` and all values in `[−tol, 1+tol]`.
`validate_simplex(dist)` raises `ValueError` if any value `< −tol` or `abs(sum − 1) > tol`.
`delta_from(prior, belief)` → `{k: belief[k] − prior[k]}` over the union of keys (missing = 0).
`reconstructs_belief(prior, deltas, belief, tol=1e-6)` → for every outcome key,
`abs(prior[k] + Σ delta[k] − belief[k]) <= tol` **and** each delta sums to ~0. Return bool.

- [ ] **Step 4: Run tests and ruff.**
- [ ] **Step 5: Commit** — `feat(ontology): add distribution and delta validation`

---

### Task 5: OpenDecisionSession Action

**Files:** Create `nutmeg/ontology/actions/session_actions.py`; Test `tests/ontology/test_session_actions.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.actions.session_actions import OpenSessionRequest, SessionActions
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _actions(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    return SessionActions(ActionService(lambda: OntologyUnitOfWork(engine))), engine


def _req(key: str, role: ActorRole = ActorRole.JUDGE_OPERATOR) -> OpenSessionRequest:
    return OpenSessionRequest(
        operator_id="op:owner", cutoff_at="2026-07-19T15:00:00+08:00", scope={"matches": ["m1"]},
        actor_id="op:owner", actor_role=role, idempotency_key=key,
        requested_at=datetime(2026, 7, 19, 8, tzinfo=UTC))


def test_open_session_commits(tmp_path: Path) -> None:
    actions, engine = _actions(tmp_path)
    outcome = actions.open_session(_req("s:1"))
    assert outcome.status is ActionStatus.COMMITTED
    assert outcome.result_refs[0].object_id.startswith("sess-")


def test_ai_analyst_cannot_open_session(tmp_path: Path) -> None:
    actions, _engine = _actions(tmp_path)
    assert actions.open_session(_req("s:d", ActorRole.AI_ANALYST)).status is ActionStatus.REJECTED
```

- [ ] **Step 2: Run and verify RED.**

- [ ] **Step 3: Implement** frozen `OpenSessionRequest` (aware time, non-empty operator) and
  `SessionActions.open_session`: `ActionCommand(action_type="open_decision_session")`, handler mints
  `mint_decision_id("sess")`, inserts a `decision_sessions` row (status open, opened_at = requested_at),
  returns `(ObjectRef("decision_session", id),)`. Permission (`open_decision_session`:
  judge_operator/deterministic_system) rejects ai_analyst.

- [ ] **Step 4: Run tests and ruff.** — [ ] **Step 5: Commit** — `feat(ontology): open decision sessions`

---

### Task 6: FreezeEvidenceBundle Action (no future leak)

**Files:** Create `nutmeg/ontology/actions/bundle_actions.py`; Test `tests/ontology/test_freeze_bundle.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.actions.bundle_actions import BundleActions, FreezeBundleRequest
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.evidence.models import VerificationMethod
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.evidence import ObservationRow
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _setup(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.identity.insert_match_minimal("match-1")
        for oid, recorded in (("obs-early", "2026-07-19T14:00:00+08:00"),
                              ("obs-late", "2026-07-19T16:00:00+08:00")):
            uow.evidence.insert_observation(ObservationRow(
                observation_id=oid, observation_type="availability", subject_type="person",
                subject_id="p", scope_match_id="match-1", value={"availability": "out"},
                schema_version="1", valid_from="2026-07-19T00:00:00+08:00", valid_to=None,
                observed_at=recorded, recorded_at=recorded,
                verification_method=VerificationMethod.OFFICIAL.value, quality={}))
    return BundleActions(ActionService(lambda: OntologyUnitOfWork(engine))), engine


def test_freeze_excludes_evidence_recorded_after_cutoff(tmp_path: Path) -> None:
    actions, engine = _setup(tmp_path)
    outcome = actions.freeze_bundle(FreezeBundleRequest(
        match_id="match-1", decision_session_id="sess-x", cutoff_at="2026-07-19T15:00:00+08:00",
        market_snapshot_id=None, prior_distribution={"home": 0.5, "draw": 0.3, "away": 0.2},
        candidate_observation_ids=["obs-early", "obs-late"], caveat_claim_ids=[],
        actor_id="system:freeze", actor_role=ActorRole.DETERMINISTIC_SYSTEM, idempotency_key="b:1",
        requested_at=datetime(2026, 7, 19, 8, tzinfo=UTC)))
    assert outcome.status is ActionStatus.COMMITTED
    bundle_id = outcome.result_refs[0].object_id
    with OntologyUnitOfWork(engine) as uow:
        items = uow.decision.bundle_item_ids(bundle_id)
        assert "obs-early" in items          # recorded 14:00 <= cutoff 15:00
        assert "obs-late" not in items       # recorded 16:00 > cutoff — no future leak
```

- [ ] **Step 2: Run and verify RED.**

- [ ] **Step 3: Implement** frozen `FreezeBundleRequest` and `BundleActions.freeze_bundle`
  (`deterministic_system`). Handler: filter `candidate_observation_ids` to those whose stored
  `observations.recorded_at <= cutoff_at` (string ISO compare is valid for same-offset timestamps; add
  `DecisionRepository`/`EvidenceRepository` helper `observation_recorded_at(observation_id) -> str | None`),
  insert one `evidence_bundles` row (prior_distribution_json, `content_hash` = sha256 of
  `canonical_json({cutoff, prior, sorted included observation ids, sorted caveat claim ids})`), then one
  `evidence_bundle_items` row per included observation (item_type=observation) and per caveat claim
  (item_type=caveat_claim). Return `(ObjectRef("evidence_bundle", bundle_id),)`.

- [ ] **Step 4: Run tests and ruff.** — [ ] **Step 5: Commit** — `feat(ontology): freeze leak-proof evidence bundles`

---

### Task 7: DraftForecast Action (validator)

**Files:** Create `nutmeg/ontology/actions/forecast_actions.py`; Test `tests/ontology/test_draft_forecast.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.actions.forecast_actions import (
    DraftForecastRequest, FactorInput, ForecastActions,
)
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _actions(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.identity.insert_match_minimal("match-1")
    return ForecastActions(ActionService(lambda: OntologyUnitOfWork(engine))), engine


def _req(key, belief, factors, role=ActorRole.AI_ANALYST) -> DraftForecastRequest:
    return DraftForecastRequest(
        match_id="match-1", market_definition_id="md-had", decision_session_id="sess-x",
        prior_distribution={"home": 0.5, "draw": 0.3, "away": 0.2}, belief_distribution=belief,
        factors=factors, commitment_tier="lean", evidence_bundle_id=None, prior_snapshot_id=None,
        falsifier="home xG < 1.0", actor_id="model:a", actor_role=role, idempotency_key=key,
        requested_at=datetime(2026, 7, 19, 9, tzinfo=UTC))


def test_draft_with_conserving_deltas_commits(tmp_path: Path) -> None:
    actions, _engine = _actions(tmp_path)
    outcome = actions.draft_forecast(_req(
        "d:1", {"home": 0.6, "draw": 0.25, "away": 0.15},
        [FactorInput(factor_definition_id="fd-x", delta={"home": 0.1, "draw": -0.05, "away": -0.05},
                     scope_entity_ids=[], supporting_observation_ids=[], note="rest edge")]))
    assert outcome.status is ActionStatus.DRAFT_LIKE_COMMITTED if False else True
    assert outcome.status is ActionStatus.COMMITTED   # the Action itself commits a draft row


def test_draft_rejects_nonconserving_deltas(tmp_path: Path) -> None:
    actions, _engine = _actions(tmp_path)
    import pytest
    with pytest.raises(ValueError, match="delta"):
        actions.draft_forecast(_req(
            "d:2", {"home": 0.6, "draw": 0.25, "away": 0.15},
            [FactorInput(factor_definition_id="fd-x", delta={"home": 0.2, "draw": 0.0, "away": 0.0},
                         scope_entity_ids=[], supporting_observation_ids=[], note="wrong")]))


def test_connector_cannot_draft(tmp_path: Path) -> None:
    actions, _engine = _actions(tmp_path)
    outcome = actions.draft_forecast(_req(
        "d:3", {"home": 0.5, "draw": 0.3, "away": 0.2}, [], ActorRole.CONNECTOR))
    assert outcome.status is ActionStatus.REJECTED
```

> Note: keep the first assertion simple — `outcome.status is ActionStatus.COMMITTED`. The Action *commits* a
> `forecast_revisions` row whose **row** status is `draft`; the Action envelope status is COMMITTED. Delete
> the confusing `DRAFT_LIKE_COMMITTED` line when writing the real test.

- [ ] **Step 2: Run and verify RED.**

- [ ] **Step 3: Implement** frozen `FactorInput`, `DraftForecastRequest`, `ForecastActions.draft_forecast`
  (`ai_analyst`/`judge_operator`). The request `__post_init__` (or the handler pre-check) validates:
  `validate_simplex(belief)`, `validate_simplex(prior)`, and `reconstructs_belief(prior, [f.delta for f in
  factors], belief)` when factors are present — raise `ValueError("factor delta must reconstruct belief−prior")`
  on failure (raised **before** the Action so it surfaces to the caller, mirroring `ActionCommand.create`
  validation). Handler: `ensure_series`, `revision_no = max_revision_no(series) + 1`, insert
  `forecast_revisions` (status=`draft`), one `factor_applications` per `FactorInput`. Return
  `(ObjectRef("forecast_revision", id),)`. A non-conserving delta raises `ValueError`; a connector is rejected.

- [ ] **Step 4: Run tests and ruff.** — [ ] **Step 5: Commit** — `feat(ontology): draft forecasts with delta validation`

---

### Task 8: CommitForecast Action (single current via optimistic concurrency)

**Files:** Modify `nutmeg/ontology/actions/forecast_actions.py`; Test `tests/ontology/test_commit_forecast.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.actions.forecast_actions import CommitForecastRequest, ForecastActions
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _actions(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.identity.insert_match_minimal("match-1")
    return ForecastActions(ActionService(lambda: OntologyUnitOfWork(engine))), engine


def _commit(key, belief) -> CommitForecastRequest:
    return CommitForecastRequest(
        match_id="match-1", market_definition_id="md-had", decision_session_id="sess-x",
        prior_distribution={"home": 0.5, "draw": 0.3, "away": 0.2}, belief_distribution=belief,
        factors=[], commitment_tier="follow", evidence_bundle_id=None, prior_snapshot_id=None,
        falsifier=None, actor_id="op:owner", actor_role=ActorRole.JUDGE_OPERATOR, idempotency_key=key,
        requested_at=datetime(2026, 7, 19, 10, tzinfo=UTC))


def test_commit_follow_market_belief_equals_prior(tmp_path: Path) -> None:
    actions, engine = _actions(tmp_path)
    outcome = actions.commit_forecast(_commit("c:1", {"home": 0.5, "draw": 0.3, "away": 0.2}))
    assert outcome.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        series = uow.decision.ensure_series("match-1", "md-had")
        current = uow.decision.current_committed_revision(series)
        assert current.status == "committed"
        assert current.commitment_tier == "follow"


def test_second_commit_supersedes_and_keeps_single_current(tmp_path: Path) -> None:
    actions, engine = _actions(tmp_path)
    actions.commit_forecast(_commit("c:1", {"home": 0.5, "draw": 0.3, "away": 0.2}))
    actions.commit_forecast(_commit("c:2", {"home": 0.55, "draw": 0.28, "away": 0.17}))
    with OntologyUnitOfWork(engine) as uow:
        series = uow.decision.ensure_series("match-1", "md-had")
        assert uow.decision.count_committed_revisions() == 1   # exactly one current committed
        current = uow.decision.current_committed_revision(series)
        assert abs(current.belief_distribution["home"] - 0.55) < 1e-9
```

- [ ] **Step 2: Run and verify RED.**

- [ ] **Step 3: Implement `commit_forecast`** (`judge_operator`). Handler, in one transaction:
  `ensure_series`; read the current committed revision (if any); insert a new `forecast_revisions` with
  `status=committed`, `revision_no = max+1`, `supersedes_revision_id = current?.id`; if a current existed,
  `set_revision_status(current.id, "superseded")`. Use the Action's `expected_versions` map keyed by
  `f"forecast_series:{series_id}"` = the prior current `revision_no` (0 if none) so a concurrent second commit
  against a stale version is rejected; `count_committed_revisions()` counts rows with status `committed`
  (exactly one per series after each commit). `belief=prior` is accepted (validate_simplex only; deltas empty).

- [ ] **Step 4: Run tests and ruff.** — [ ] **Step 5: Commit** — `feat(ontology): commit single-current forecasts`

---

### Task 9: ReviseForecast and WithdrawForecast

**Files:** Modify `forecast_actions.py`; Test `tests/ontology/test_revise_withdraw.py`

- [ ] **Step 1: Write the failing test** (revise creates a new committed revision that supersedes the prior and
  keeps one current; withdraw sets the current to `withdrawn` and leaves zero current committed):

```python
# ... build committed revision via commit_forecast, then:
def test_revise_then_withdraw(tmp_path):
    # revise -> still one committed, belief updated, prior superseded
    # withdraw -> zero committed current, status withdrawn
    ...
```
Write concrete assertions: after `revise_forecast`, `count_committed_revisions() == 1` and the belief matches
the revision; after `withdraw_forecast`, `current_committed_revision(series) is None` and the last revision
row status is `withdrawn`.

- [ ] **Step 2: Run and verify RED.**

- [ ] **Step 3: Implement** `revise_forecast` (same as commit but requires an existing current committed to
  supersede — reject with `ValueError` if none) and `withdraw_forecast` (`set_revision_status(current.id,
  "withdrawn")`; if no current, `ValueError`). Both `judge_operator`; both use `expected_versions`.

- [ ] **Step 4: Run tests and ruff.** — [ ] **Step 5: Commit** — `feat(ontology): revise and withdraw forecasts`

---

### Task 10: FactorDefinition and Factor status lifecycle

**Files:** Create `nutmeg/ontology/actions/factor_actions.py`; Test `tests/ontology/test_factor_actions.py`

- [ ] **Step 1: Write the failing test** — `propose_factor_status` (ai_analyst allowed) records a proposal;
  `apply_factor_status` (judge_operator) transitions a `factor_definitions.status`
  probation→active→retired; a connector proposing and an ai_analyst applying are both rejected.

```python
def test_factor_lifecycle_probation_to_active(tmp_path):
    # seed a factor_family + factor_definition(status=probation) via DecisionRepository
    # apply_factor_status(judge, target=active) -> status active
    # ai_analyst apply -> rejected
    ...
```

- [ ] **Step 2: Run and verify RED.**

- [ ] **Step 3: Implement** `FactorActions.propose_factor_status` (records the proposal as an Action; the
  aggregate verdict computation is Package 4 — here it only records intent) and `apply_factor_status`
  (`judge_operator`; `DecisionRepository.set_factor_status(factor_definition_id, status)` transitions the
  status; reject an illegal transition target with `ValueError`). Seed helpers
  `insert_factor_family`/`insert_factor_definition` already exist from Task 3.

- [ ] **Step 4: Run tests and ruff.** — [ ] **Step 5: Commit** — `feat(ontology): factor status lifecycle actions`

---

### Task 11: Decision read-flow orchestration + wiring + counts

**Files:** Create `nutmeg/ontology/decision/read_flow.py`; Modify `wiring.py`, `kernel.py`, `repository/unit_of_work.py`; Test `tests/ontology/test_decision_read_flow.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.decision.read_flow import ReadMatchRequest
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel


def test_read_flow_commits_a_forecast(tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    kernel = build_ontology_kernel(settings)
    kernel.initialize()
    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.identity.insert_match_minimal("match-1")
    result = kernel.decision_read.read_match(ReadMatchRequest(
        match_id="match-1", market_definition_id="md-had", operator_id="op:owner",
        cutoff_at="2026-07-19T15:00:00+08:00",
        prior_distribution={"home": 0.5, "draw": 0.3, "away": 0.2},
        belief_distribution={"home": 0.5, "draw": 0.3, "away": 0.2}, factors=[],
        actor_id="op:owner", actor_role=ActorRole.JUDGE_OPERATOR,
        requested_at=datetime(2026, 7, 19, 10, tzinfo=UTC)))
    assert result.committed is True
    status = kernel.status()
    assert status.forecast_count == 1
    assert status.bundle_count == 1
```

- [ ] **Step 2: Run and verify RED.**

- [ ] **Step 3: Implement** `read_flow.py`: frozen `ReadMatchRequest`, `ReadMatchResult(committed,
  forecast_revision_id, bundle_id)`, and `DecisionReadService` holding `SessionActions`, `BundleActions`,
  `ForecastActions`. `read_match`: open a session (deterministic keys from match+cutoff), freeze a bundle
  (prior from request; candidate observations = none for the minimal flow), commit a forecast referencing the
  bundle. Extend `OntologyKernelStatus` with `forecast_count` (committed revisions) and `bundle_count`; extend
  `build_ontology_kernel` to expose `decision_read`; add `DecisionRepository.count_bundles`.

- [ ] **Step 4: Run tests and ruff.** — [ ] **Step 5: Commit** — `feat(ontology): decision read flow`

---

### Task 12: Temporal-leak + single-current + delta e2e gate, docs, full verification

**Files:** Create `tests/ontology/test_package3a_e2e.py`; Modify `docs/ontology-kernel-operations.md`

- [ ] **Step 1: Write the failing e2e test** covering, against a real Match with a 2A market snapshot and 2B
  observations: (a) a committed forecast whose factor deltas reconstruct belief−prior; (b) an observation
  recorded after cutoff never enters the bundle; (c) a second commit keeps exactly one current committed and
  supersedes the first; (d) an ai_analyst cannot commit. Build the market snapshot via `MarketActions` and the
  observations via `ObservationActions`, then drive the forecast actions.

- [ ] **Step 2: Run and drive to GREEN** (fix minimal Package 3A code if a real bug surfaces).

- [ ] **Step 3: Document Package 3A** in `docs/ontology-kernel-operations.md`: DecisionSession, leak-proof
  EvidenceBundle, market-anchored prior→belief with factor delta decomposition, single current committed
  revision, graded permissions (ai_analyst drafts, judge_operator commits).

- [ ] **Step 4: Full suite + adjacent regressions** — `uv run pytest tests/ontology -q` and
  `uv run pytest tests/test_cli.py::test_doctor_reports_ready_workflow_and_harness tests/decision/ -q`.

- [ ] **Step 5: Repository quality gates** — `uv run ruff check .`, `uv run python -m compileall -q nutmeg scripts`, `bash scripts/verify.sh`.

- [ ] **Step 6: Project verify** — the decision replay chains (`tests/decision`) are unchanged (Package 3A adds
  no code to the old decision path). If a real Match with a 2A snapshot can be replayed through the new read
  flow from an isolated temp data dir, do so; otherwise rely on the e2e gate and state that explicitly.

- [ ] **Step 7: Commit and inspect** — `git add tests/ontology/test_package3a_e2e.py docs/ontology-kernel-operations.md nutmeg/ontology && git commit -m "test(ontology): verify package 3a belief layer"`; then `git status --short`, `git log --oneline main..HEAD`, `git diff --stat main...HEAD`. Do not merge — hand back for review.

---

## Package 3A Spec Coverage

| Design (§) requirement | Implemented by |
|---|---|
| Leak-proof EvidenceBundle (recorded_at ≤ cutoff) (§2.1) | Tasks 6, 12 |
| Market-anchored prior; belief=prior follow-market (§2.2) | Tasks 7, 8 |
| Factor delta decomposition Σ=belief−prior (§2.2) | Tasks 4, 7, 12 |
| Single current committed revision via optimistic concurrency (§2.2) | Tasks 8, 12 |
| Revise supersedes; withdraw clears current (§2.2) | Task 9 |
| Graded write-back: analyst drafts, judge commits (§2.3, §4) | Tasks 2, 7, 8 |
| Factor lifecycle state machine (verdicts deferred to Pkg 4) (§1, §5) | Task 10 |
| Read-flow session→bundle→draft→commit (§5) | Task 11 |
| Real-Match acceptance (§6) | Task 12 |

Package 3A is complete only when Task 12 passes. It does not authorize 3B; 3B (Ticket/Ledger/Outcome/
Settlement) receives its own plan using 3A's committed-forecast interface. Calibrate/scoring is Package 4.
