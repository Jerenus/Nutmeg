# Ontology Kernel v2 Package 2B Implementation Plan — Evidence & Context

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the football world graded, lineage-bearing evidence — people (Person/Role/status/lineup), deterministic Observations, and provisional Claims with evidence spans and auditable status transitions — so Package 3's EvidenceBundle can freeze a real as-of input set.

**Architecture:** Package 2B adds the context (people) and evidence (claim/observation) layers on the delivered Package 1 kernel and Package 2A identity/market facts. It touches no kernel or 2A write semantics: new tables extend the shared `schema.metadata` via migrations 5–6; new repositories hang off the same `OntologyUnitOfWork`; every write is an `ActionService.execute` handler reusing permission/idempotency/rollback. Person resolution reuses 2A's provider-ID-first `resolve_entity` over the generic `external_identifiers`/`entity_aliases` tables. Evidence is **graded**: connectors/deterministic-systems write official/deterministic Observations; AI extractors write only *provisional* Claims with evidence spans and cannot self-verify.

**Tech Stack:** Python 3.13, frozen dataclasses, SQLAlchemy 2 Core, SQLite WAL, Typer, pytest, ruff; Package 1 `nutmeg.ontology` kernel; Package 2A identity/market (`EntityType`, `resolve_entity`, `IdentityRepository`, `MarketActions`, migrations 1–4).

**Design Spec:** `docs/superpowers/specs/2026-07-21-ontology-kernel-v2-package-2-design.md` (§1 scope 2B, §2.4 graded write-back, §3 tables 2B, §4 actions 2B, §7 acceptance 2B).

**Depends on:** Package 2A (merged, commit `8fb5424`). It uses these verified interfaces:
`resolve_entity(repo, EntityType.PERSON, ...)`, `IdentityRepository.link_external_identifier/add_alias/entity_by_external_id`,
`OntologyUnitOfWork.identity`, `ActionService(uow_factory).execute(command, handler)`, `ActionCommand.create`,
`ActorRole`, `Migration`/`MIGRATIONS`/`run_migrations`, `schema.metadata`, `canonical_json`, `OntologyKernelStatus`.

---

## Scope Boundary

Package 2B includes:

- context tables: persons, role_assignments, person_match_statuses, lineup_entries (migration 5);
- evidence tables: claims, claim_status_events, claim_evidence_spans, observations, observation_sources,
  observation_claims (migration 6);
- Person resolution (provider-id-first, provisional) reusing 2A's resolver/identifier/alias tables;
- domain Actions: `upsert_person`, `record_observation`, `extract_claim`, `verify_claim`, `dispute_claim`,
  `retract_claim`, `record_person_match_status`, `record_lineup_entry`;
- graded permissions: deterministic Observations for connector/deterministic_system; provisional Claims for
  ai_extractor; Claim adjudication for deterministic_system(official policy)/judge_operator;
- one representative evidence adapter end-to-end (lineup/availability snapshot → Observation +
  PersonMatchStatus), plus a weather Observation and a news→provisional-Claim path;
- an evidence-day ingest orchestration, a `nutmeg ontology ingest-evidence-day` CLI, kernel counts;
- a synthetic + real acceptance gate (conflicting claims coexist, AI cannot verify, status events replay).

Package 2B explicitly excludes (Package 3 / 4 / 5):

- EvidenceBundle freeze and `information_cutoff` semantics (Package 3 read layer);
- Forecast, Factor, Ticket, Ledger, Outcome, Settlement, scoring, RegimeVector (3 / 4);
- full wiring of every adapter payload shape (transfermarkt player-ability import beyond a minimal Person
  seed is a follow-on within 2B; note what is deferred with `log`-style comments, never silently);
- historical migration and old-write-path shutdown, schedule restore (Package 5).

Do not change any existing Package 1 or 2A signature, table, or test except the **additive** changes named in
File Structure (two UoW properties, appended `MIGRATIONS`, new `OntologyKernelStatus` counts, wiring exposure).

---

## File Structure

### New production modules

- `nutmeg/ontology/evidence/__init__.py`: evidence public exports.
- `nutmeg/ontology/evidence/models.py`: Availability, StatusKind, LineupStatus, LineupRole, ClaimStatus, VerificationMethod enums + id minting.
- `nutmeg/ontology/repository/schema_context.py`: context Core tables on the shared `metadata`.
- `nutmeg/ontology/repository/schema_evidence.py`: evidence Core tables on the shared `metadata`.
- `nutmeg/ontology/repository/context.py`: ContextRepository (role/status/lineup).
- `nutmeg/ontology/repository/evidence.py`: EvidenceRepository (claims/status events/spans/observations).
- `nutmeg/ontology/actions/person_actions.py`: UpsertPerson service.
- `nutmeg/ontology/actions/observation_actions.py`: RecordObservation / RecordPersonMatchStatus / RecordLineupEntry services.
- `nutmeg/ontology/actions/claim_actions.py`: ExtractClaim / VerifyClaim / DisputeClaim / RetractClaim services.
- `nutmeg/ontology/ingest/lineup.py`: parse a lineup/availability snapshot into typed inputs.
- `nutmeg/ontology/ingest/evidence_day.py`: EvidenceDayIngestService orchestration.
- `nutmeg/interfaces/cli/ontology_evidence.py`: `nutmeg ontology ingest-evidence-day` subcommand.

### New tests

- `tests/ontology/test_evidence_models.py`
- `tests/ontology/test_schema_context_migration.py`
- `tests/ontology/test_schema_evidence_migration.py`
- `tests/ontology/test_person_actions.py`
- `tests/ontology/test_context_repository.py`
- `tests/ontology/test_record_observation.py`
- `tests/ontology/test_extract_claim.py`
- `tests/ontology/test_claim_adjudication.py`
- `tests/ontology/test_person_match_status.py`
- `tests/ontology/test_ingest_lineup.py`
- `tests/ontology/test_evidence_day_ingest.py`
- `tests/ontology/test_evidence_cli.py`
- `tests/ontology/test_package2b_e2e.py`

### Existing files modified (additive only)

- `nutmeg/ontology/repository/migrations.py`: import schema_context/schema_evidence; append migrations 5 (context) and 6 (evidence + evidence action permissions).
- `nutmeg/ontology/repository/identity.py`: add `insert_person`, `get_person`, `count_persons` (Person is an identity entity; its aliases/ids already live in the shared tables).
- `nutmeg/ontology/repository/unit_of_work.py`: add `.context` and `.evidence` properties (lazy import + TYPE_CHECKING).
- `nutmeg/ontology/kernel.py`: add `person_count`, `observation_count`, `claim_count` to `OntologyKernelStatus`; add `evidence_day_ingest` to `OntologyKernel`.
- `nutmeg/ontology/wiring.py`: build person/observation/claim actions + `EvidenceDayIngestService`, expose it.
- `nutmeg/interfaces/cli/__init__.py`: register `ontology_evidence` at the bottom.
- `docs/ontology-kernel-operations.md`: add a Package 2B section.

### User-owned files that must not be reverted

The worktree starts with unrelated edits to `SOUL.md` and the three decision launchd plists plus untracked
`media/`, memory and research-script files. Package 2B does not modify or stage them. Execute in the
dedicated worktree created in Task 0.

---

### Task 0: Create a clean implementation worktree

**Files:** Worktree only: `.claude/worktrees/ontology-kernel-v2-package2b/`

- [ ] **Step 1: Confirm 2A is merged and the tree is clean of in-scope files**

Run:
```bash
git -C /Users/jz71/Projects/Nutmeg log --oneline -1
git -C /Users/jz71/Projects/Nutmeg status --short
```
Expected: HEAD is the Package 2A merge (`8fb5424`) or later docs; dirty entries are only the user-owned
`SOUL.md` / three plists / untracked `media/` `memory/` `scripts/`. Otherwise stop and ask.

- [ ] **Step 2: Do not touch the paused decision schedules or the freeze archive**

They stay paused/read-only until the Package 5 gate. Do not re-enable or delete them.

- [ ] **Step 3: Create the worktree**

```bash
cd /Users/jz71/Projects/Nutmeg
git worktree add .claude/worktrees/ontology-kernel-v2-package2b -b feature/ontology-kernel-v2-package2b
git -C .claude/worktrees/ontology-kernel-v2-package2b status --short
(cd .claude/worktrees/ontology-kernel-v2-package2b && uv sync --extra dev)
```
Expected: clean worktree on `feature/ontology-kernel-v2-package2b`; deps synced.

---

### Task 1: Evidence & context value objects

**Files:**
- Create: `nutmeg/ontology/evidence/__init__.py`, `nutmeg/ontology/evidence/models.py`
- Test: `tests/ontology/test_evidence_models.py`

- [ ] **Step 1: Write the failing test**

```python
from nutmeg.ontology.evidence.models import (
    Availability,
    ClaimStatus,
    LineupRole,
    LineupStatus,
    StatusKind,
    VerificationMethod,
    mint_evidence_id,
)


def test_enum_values_are_stable_snake_case() -> None:
    assert Availability.OUT.value == "out"
    assert Availability.DOUBTFUL.value == "doubtful"
    assert StatusKind.INJURY.value == "injury"
    assert LineupStatus.CONFIRMED.value == "confirmed"
    assert LineupRole.STARTER.value == "starter"
    assert ClaimStatus.PROVISIONAL.value == "provisional"
    assert ClaimStatus.VERIFIED.value == "verified"
    assert VerificationMethod.DETERMINISTIC.value == "deterministic"


def test_mint_evidence_id_is_prefixed_and_unique() -> None:
    first = mint_evidence_id("claim")
    assert first.startswith("claim-")
    assert first != mint_evidence_id("claim")
    assert mint_evidence_id("obs").startswith("obs-")
```

- [ ] **Step 2: Run and verify RED**

Run: `uv run pytest tests/ontology/test_evidence_models.py -q`
Expected: `ModuleNotFoundError: No module named 'nutmeg.ontology.evidence'`.

- [ ] **Step 3: Implement the value objects**

In `models.py` define `StrEnum`s with exactly these members/values, and `mint_evidence_id(prefix) ->
f"{prefix}-{uuid4().hex}"`:

```text
Availability: EXPECTED=expected, AVAILABLE=available, DOUBTFUL=doubtful, OUT=out,
              SUSPENDED=suspended, RETURNED=returned
StatusKind: INJURY=injury, SUSPENSION=suspension, ROTATION=rotation, SELECTION=selection,
            COACH_STATUS=coach_status
LineupStatus: EXPECTED=expected, CONFIRMED=confirmed
LineupRole: STARTER=starter, SUBSTITUTE=substitute, UNAVAILABLE=unavailable
ClaimStatus: PROVISIONAL=provisional, CORROBORATED=corroborated, VERIFIED=verified,
             DISPUTED=disputed, EXPIRED=expired, RETRACTED=retracted
VerificationMethod: DETERMINISTIC=deterministic, OFFICIAL=official, CORROBORATED=corroborated,
                    ADJUDICATED=adjudicated
```

Export all enums and `mint_evidence_id` from `evidence/__init__.py`.

- [ ] **Step 4: Run tests and ruff**

Run:
```bash
uv run pytest tests/ontology/test_evidence_models.py -q
uv run ruff check nutmeg/ontology/evidence tests/ontology/test_evidence_models.py
```
Expected: pass; clean.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/ontology/evidence tests/ontology/test_evidence_models.py
git commit -m "feat(ontology): add evidence and context value objects"
```

---

### Task 2: Context schema and migration 5

**Files:**
- Create: `nutmeg/ontology/repository/schema_context.py`
- Modify: `nutmeg/ontology/repository/migrations.py`
- Test: `tests/ontology/test_schema_context_migration.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from sqlalchemy import inspect

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import migration_status, run_migrations


def test_context_migration_creates_tables(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    assert migration_status(engine).current_version >= 5
    names = set(inspect(engine).get_table_names())
    assert {"persons", "role_assignments", "person_match_statuses", "lineup_entries"} <= names


def test_context_migration_is_idempotent(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    assert run_migrations(engine).applied_versions == ()
```

- [ ] **Step 2: Run and verify RED**

Run: `uv run pytest tests/ontology/test_schema_context_migration.py -q`
Expected: import error for `schema_context`.

- [ ] **Step 3: Declare context tables on the shared MetaData**

In `schema_context.py`, `from nutmeg.ontology.repository.schema import metadata` and declare (TEXT unless
noted; FKs reference 2A identity tables):

```text
persons:               person_id PK, canonical_name NOT NULL, birth_date?, nationality?,
                       resolution_status NOT NULL, created_at NOT NULL
role_assignments:      role_assignment_id PK, person_id NOT NULL FK persons RESTRICT,
                       team_id NOT NULL FK teams RESTRICT, role_type NOT NULL, position_group?,
                       valid_from NOT NULL, valid_to?, source_observation_id?
person_match_statuses: person_match_status_id PK, match_id NOT NULL FK matches RESTRICT,
                       person_id NOT NULL FK persons RESTRICT,
                       team_appearance_id? FK team_appearances RESTRICT,
                       availability NOT NULL, status_kind NOT NULL, valid_from NOT NULL, valid_to?,
                       observation_id?
lineup_entries:        lineup_entry_id PK, match_id NOT NULL FK matches RESTRICT,
                       person_id NOT NULL FK persons RESTRICT,
                       team_appearance_id? FK team_appearances RESTRICT,
                       lineup_status NOT NULL, role NOT NULL, position?, shirt_number?,
                       captain INTEGER NOT NULL DEFAULT 0, observed_at NOT NULL, observation_id?
```

Index `role_assignments(person_id)`, `person_match_statuses(match_id)`, `lineup_entries(match_id)`.

- [ ] **Step 4: Add migration 5**

In `migrations.py`, import `schema_context`, add `_apply_context(connection)` creating the four tables in FK
order (persons → role_assignments → person_match_statuses → lineup_entries), and append:

```python
Migration(version=5, name='football_context',
          fingerprint='persons+role_assignments+person_match_statuses+lineup_entries',
          apply=_apply_context),
```

- [ ] **Step 5: Run tests + migration regression**

Run:
```bash
uv run pytest tests/ontology/test_schema_context_migration.py tests/ontology/test_migrations.py tests/ontology/test_kernel.py -q
uv run ruff check nutmeg/ontology/repository/schema_context.py nutmeg/ontology/repository/migrations.py
```
Expected: pass (the Package 1/2A migration tests are already decoupled from the migration count via
`MIGRATIONS`, so they keep passing).

- [ ] **Step 6: Commit**

```bash
git add nutmeg/ontology/repository/schema_context.py nutmeg/ontology/repository/migrations.py \
  tests/ontology/test_schema_context_migration.py
git commit -m "feat(ontology): add context schema"
```

---

### Task 3: Evidence schema, migration 6 and evidence permissions

**Files:**
- Create: `nutmeg/ontology/repository/schema_evidence.py`
- Modify: `nutmeg/ontology/repository/migrations.py`
- Test: `tests/ontology/test_schema_evidence_migration.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from sqlalchemy import func, inspect, select

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import migration_status, run_migrations
from nutmeg.ontology.repository.schema import action_permissions


def test_evidence_migration_creates_tables_and_seeds_permissions(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    assert migration_status(engine).current_version >= 6
    names = set(inspect(engine).get_table_names())
    assert {"claims", "claim_status_events", "claim_evidence_spans", "observations",
            "observation_sources", "observation_claims"} <= names
    with engine.connect() as connection:
        rows = connection.execute(select(action_permissions)).mappings().all()
        pairs = {(row["action_type"], row["actor_role"]) for row in rows}
    assert ("extract_claim", "ai_extractor") in pairs
    assert ("record_observation", "connector") in pairs
    assert ("verify_claim", "judge_operator") in pairs
    assert ("extract_claim", "connector") not in pairs   # AI-only path stays AI-only
```

- [ ] **Step 2: Run and verify RED**

Run: `uv run pytest tests/ontology/test_schema_evidence_migration.py -q`
Expected: import error for `schema_evidence`.

- [ ] **Step 3: Declare evidence tables**

In `schema_evidence.py`, `from nutmeg.ontology.repository.schema import metadata` and declare:

```text
claims:               claim_id PK, subject_type NOT NULL, subject_id NOT NULL, predicate NOT NULL,
                      value_json NOT NULL, scope_match_id? FK matches RESTRICT, valid_from NOT NULL,
                      valid_to?, status NOT NULL, extractor NOT NULL, extractor_version NOT NULL,
                      created_at NOT NULL, adjudicated_at?
claim_status_events:  claim_status_event_id PK, claim_id NOT NULL FK claims RESTRICT, from_status?,
                      to_status NOT NULL, action_id NOT NULL, at NOT NULL
claim_evidence_spans: claim_evidence_span_id PK, claim_id NOT NULL FK claims RESTRICT,
                      artifact_id NOT NULL FK source_artifacts RESTRICT,
                      artifact_retrieval_id NOT NULL FK artifact_retrievals RESTRICT,
                      quote NOT NULL, locator?
observations:         observation_id PK, observation_type NOT NULL, subject_type NOT NULL,
                      subject_id NOT NULL, scope_match_id? FK matches RESTRICT, value_json NOT NULL,
                      schema_version NOT NULL, valid_from NOT NULL, valid_to?, observed_at NOT NULL,
                      recorded_at NOT NULL, verification_method NOT NULL, quality_json NOT NULL
observation_sources:  observation_id NOT NULL FK observations RESTRICT,
                      artifact_retrieval_id NOT NULL FK artifact_retrievals RESTRICT,
                      PRIMARY KEY(observation_id, artifact_retrieval_id)
observation_claims:   observation_id NOT NULL FK observations RESTRICT,
                      claim_id NOT NULL FK claims RESTRICT,
                      PRIMARY KEY(observation_id, claim_id)
```

Index `claims(subject_type, subject_id)`, `claim_status_events(claim_id)`, `observations(subject_type,
subject_id)`.

- [ ] **Step 4: Add migration 6 with evidence permissions**

`_apply_evidence(connection)` creates the six tables in FK order and seeds `action_permissions`
(governance-v1) exactly:

```text
upsert_person:            connector, deterministic_system
record_observation:       connector, deterministic_system
record_person_match_status: connector, deterministic_system
record_lineup_entry:      connector, deterministic_system
extract_claim:            ai_extractor
verify_claim:             deterministic_system, judge_operator
dispute_claim:            judge_operator
retract_claim:            judge_operator
```

Append:
```python
Migration(version=6, name='football_evidence',
          fingerprint='claims..observation_claims+evidence_permissions',
          apply=_apply_evidence),
```

Note the graded matrix (design §2.4): `extract_claim` is ai_extractor-only; `record_observation` is not
granted to any AI role, so an AI extractor can never write a verified fact.

- [ ] **Step 5: Run tests + ruff**

Run:
```bash
uv run pytest tests/ontology/test_schema_evidence_migration.py tests/ontology/test_migrations.py -q
uv run ruff check nutmeg/ontology/repository/schema_evidence.py nutmeg/ontology/repository/migrations.py
```
Expected: pass; clean.

- [ ] **Step 6: Commit**

```bash
git add nutmeg/ontology/repository/schema_evidence.py nutmeg/ontology/repository/migrations.py \
  tests/ontology/test_schema_evidence_migration.py
git commit -m "feat(ontology): add evidence schema and graded permissions"
```

---

### Task 4: Person entity + UpsertPerson Action

**Files:**
- Modify: `nutmeg/ontology/repository/identity.py` (add `insert_person`/`get_person`/`count_persons` + `PersonRow`)
- Create: `nutmeg/ontology/actions/person_actions.py`
- Test: `tests/ontology/test_person_actions.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.person_actions import PersonActions, UpsertPersonRequest
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _actions(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    return PersonActions(ActionService(lambda: OntologyUnitOfWork(engine))), engine


def _req(key: str, role: ActorRole = ActorRole.CONNECTOR) -> UpsertPersonRequest:
    return UpsertPersonRequest(
        canonical_name="Lionel Messi", provider="api-football", external_id="P-154",
        actor_id="source:api", actor_role=role, idempotency_key=key,
        requested_at=datetime(2026, 7, 21, 8, tzinfo=UTC),
    )


def test_upsert_person_resolves_same_entity_on_provider_id(tmp_path: Path) -> None:
    actions, _engine = _actions(tmp_path)
    first = actions.upsert_person(_req("p:1"))
    second = actions.upsert_person(_req("p:2"))
    assert first.status is ActionStatus.COMMITTED
    person_id = first.result_refs[0].object_id
    assert person_id.startswith("person-")
    assert second.result_refs[0].object_id == person_id


def test_ai_analyst_cannot_upsert_person(tmp_path: Path) -> None:
    actions, _engine = _actions(tmp_path)
    outcome = actions.upsert_person(_req("p:denied", ActorRole.AI_ANALYST))
    assert outcome.status is ActionStatus.REJECTED
```

- [ ] **Step 2: Run and verify RED**

Run: `uv run pytest tests/ontology/test_person_actions.py -q`
Expected: import error for `person_actions`.

- [ ] **Step 3: Add Person persistence and the Action**

In `identity.py` add frozen `PersonRow(person_id, canonical_name, birth_date, nationality,
resolution_status, created_at)`, `insert_person(row)`, `get_person(person_id) -> PersonRow`, and
`count_persons() -> int` (persons are identity entities; their external ids and aliases already use the shared
`external_identifiers`/`entity_aliases` tables via `EntityType.PERSON`).

`person_actions.py` defines frozen `UpsertPersonRequest` (validated aware time, non-empty name/actor) and
`PersonActions(action_service)`. `upsert_person(request)` mirrors `EntityActions.upsert_team`:
`ActionCommand(action_type="upsert_person")`, a handler that `resolve_entity(uow.identity,
EntityType.PERSON, provider=..., external_id=..., aliases=(name.casefold(),))`; if resolved return
`(ObjectRef("person", id),)`; else mint `mint_id(EntityType.PERSON)`, insert the provisional person, link the
provider id, add the canonical alias, return the ref. Permission (`upsert_person`: connector/
deterministic_system) is seeded in migration 6, so an ai_analyst is rejected.

- [ ] **Step 4: Run tests and ruff**

Run:
```bash
uv run pytest tests/ontology/test_person_actions.py -q
uv run ruff check nutmeg/ontology/actions/person_actions.py nutmeg/ontology/repository/identity.py
```
Expected: pass; clean.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/ontology/actions/person_actions.py nutmeg/ontology/repository/identity.py \
  tests/ontology/test_person_actions.py
git commit -m "feat(ontology): add provisional-person actions"
```

---

### Task 5: ContextRepository and EvidenceRepository

**Files:**
- Create: `nutmeg/ontology/repository/context.py`, `nutmeg/ontology/repository/evidence.py`
- Modify: `nutmeg/ontology/repository/unit_of_work.py` (add `.context`, `.evidence`)
- Test: `tests/ontology/test_context_repository.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.context import ContextRepository, PersonMatchStatusRow
from nutmeg.ontology.repository.evidence import EvidenceRepository, ObservationRow
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _prepare(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.identity.insert_match_minimal("match-1")
        uow.identity.insert_person(_person("person-1"))
    return engine


def _person(person_id: str):
    from nutmeg.ontology.identity.models import ResolutionStatus
    from nutmeg.ontology.repository.identity import PersonRow
    return PersonRow(
        person_id=person_id, canonical_name="X", birth_date=None, nationality=None,
        resolution_status=ResolutionStatus.PROVISIONAL,
        created_at=datetime(2026, 7, 21, tzinfo=UTC).isoformat(),
    )


def test_context_and_evidence_rows_persist(tmp_path: Path) -> None:
    engine = _prepare(tmp_path)
    with OntologyUnitOfWork(engine) as uow:
        uow.evidence.insert_observation(ObservationRow(
            observation_id="obs-1", observation_type="availability", subject_type="person",
            subject_id="person-1", scope_match_id="match-1", value={"availability": "out"},
            schema_version="1", valid_from="2026-07-19T00:00:00+08:00", valid_to=None,
            observed_at="2026-07-19T12:00:00+08:00", recorded_at="2026-07-19T12:05:00+08:00",
            verification_method="official", quality={"source": "club"},
        ), artifact_retrieval_ids=())
        uow.context.insert_person_match_status(PersonMatchStatusRow(
            person_match_status_id="pms-1", match_id="match-1", person_id="person-1",
            team_appearance_id=None, availability="out", status_kind="injury",
            valid_from="2026-07-19T00:00:00+08:00", valid_to=None, observation_id="obs-1",
        ))
    with OntologyUnitOfWork(engine) as uow:
        assert uow.evidence.count_observations() == 1
        assert uow.context.person_match_status_ids("match-1") == ("pms-1",)
```

- [ ] **Step 2: Run and verify RED**

Run: `uv run pytest tests/ontology/test_context_repository.py -q`
Expected: import error for `context`/`evidence`.

- [ ] **Step 3: Implement both repositories and the UoW properties**

`context.py` defines frozen `RoleAssignmentRow`, `PersonMatchStatusRow`, `LineupEntryRow` (fields mirror the
schema) and `ContextRepository(connection)` with `insert_role_assignment`, `insert_person_match_status`,
`insert_lineup_entry`, `person_match_status_ids(match_id) -> tuple[str, ...]`, `count_person_match_statuses`.
`evidence.py` defines frozen `ClaimRow`, `ClaimEvidenceSpanRow`, `ObservationRow` (JSON fields as dicts,
serialized with `canonical_json`) and `EvidenceRepository(connection)` with `insert_claim`,
`insert_claim_status_event`, `insert_evidence_span`, `insert_observation(row, artifact_retrieval_ids)` (writes
one `observation_sources` row per retrieval id), `link_observation_claim`, `claims_for(subject_type,
subject_id) -> list[ClaimRow]`, `claim_status(claim_id) -> str`, `count_claims`, `count_observations`. Add
`.context` and `.evidence` to `OntologyUnitOfWork` (lazy import + TYPE_CHECKING), mirroring `.identity`.

- [ ] **Step 4: Run tests and ruff**

Run:
```bash
uv run pytest tests/ontology/test_context_repository.py -q
uv run ruff check nutmeg/ontology/repository/context.py nutmeg/ontology/repository/evidence.py \
  nutmeg/ontology/repository/unit_of_work.py
```
Expected: pass; clean.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/ontology/repository/context.py nutmeg/ontology/repository/evidence.py \
  nutmeg/ontology/repository/unit_of_work.py tests/ontology/test_context_repository.py
git commit -m "feat(ontology): add context and evidence repositories"
```

---

### Task 6: RecordObservation Action

**Files:**
- Create: `nutmeg/ontology/actions/observation_actions.py`
- Test: `tests/ontology/test_record_observation.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.observation_actions import ObservationActions, RecordObservationRequest
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.evidence.models import VerificationMethod
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _actions(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.identity.insert_match_minimal("match-1")
    return ObservationActions(ActionService(lambda: OntologyUnitOfWork(engine))), engine


def _req(key: str, role: ActorRole = ActorRole.CONNECTOR) -> RecordObservationRequest:
    return RecordObservationRequest(
        observation_type="weather", subject_type="match", subject_id="match-1",
        scope_match_id="match-1", value={"temp_c": 21}, verification_method=VerificationMethod.OFFICIAL,
        valid_from="2026-07-19T00:00:00+08:00", observed_at="2026-07-19T12:00:00+08:00",
        actor_id="source:open-meteo", actor_role=role, idempotency_key=key,
        requested_at=datetime(2026, 7, 19, 8, tzinfo=UTC),
    )


def test_record_observation_commits_and_counts(tmp_path: Path) -> None:
    actions, engine = _actions(tmp_path)
    outcome = actions.record_observation(_req("obs:1"))
    assert outcome.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        assert uow.evidence.count_observations() == 1


def test_ai_extractor_cannot_record_observation(tmp_path: Path) -> None:
    actions, _engine = _actions(tmp_path)
    outcome = actions.record_observation(_req("obs:denied", ActorRole.AI_EXTRACTOR))
    assert outcome.status is ActionStatus.REJECTED
```

- [ ] **Step 2: Run and verify RED**

Run: `uv run pytest tests/ontology/test_record_observation.py -q`
Expected: import error for `observation_actions`.

- [ ] **Step 3: Implement RecordObservation**

`observation_actions.py` defines frozen `RecordObservationRequest` (validated aware `requested_at`, non-empty
subject, ISO strings for `valid_from`/`observed_at`, optional `artifact_retrieval_ids` tuple,
`schema_version` default "1") and `ObservationActions(action_service)`. `record_observation(request)` builds
`ActionCommand(action_type="record_observation")` and a handler that mints `mint_evidence_id("obs")`, inserts
one `observations` row (`recorded_at=command.requested_at`, `quality_json`, `verification_method`), and one
`observation_sources` row per retrieval id, returning `(ObjectRef("observation", observation_id),)`.
Permission (`record_observation`: connector/deterministic_system) means an ai_extractor is rejected — AI never
writes a verified fact.

- [ ] **Step 4: Run tests and ruff**

Run:
```bash
uv run pytest tests/ontology/test_record_observation.py -q
uv run ruff check nutmeg/ontology/actions/observation_actions.py
```
Expected: pass; clean.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/ontology/actions/observation_actions.py tests/ontology/test_record_observation.py
git commit -m "feat(ontology): record deterministic observations"
```

---

### Task 7: ExtractClaim Action (AI-only, provisional, with spans)

**Files:**
- Create: `nutmeg/ontology/actions/claim_actions.py`
- Test: `tests/ontology/test_extract_claim.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.actions.claim_actions import ClaimActions, ExtractClaimRequest, EvidenceSpanInput
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.artifacts import ContentAddressedArtifactStore
from nutmeg.ontology.actions.artifact_ingest import ArtifactIngestRequest, ArtifactIngestService
from nutmeg.ontology.evidence.models import ClaimStatus
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _setup(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    service = ActionService(lambda: OntologyUnitOfWork(engine))
    with OntologyUnitOfWork(engine) as uow:
        uow.identity.insert_match_minimal("match-1")
    ingest = ArtifactIngestService(
        action_service=service, artifact_store=ContentAddressedArtifactStore(tmp_path / "artifacts")
    )
    ingested = ingest.ingest(ArtifactIngestRequest(
        content=b"club statement: striker OUT with injury", content_type="text/plain",
        source_name="club-site", source_type="web", actor_id="source:club",
        actor_role=ActorRole.CONNECTOR, idempotency_key="art:1",
        retrieved_at=datetime(2026, 7, 19, 8, tzinfo=UTC),
    ))
    artifact_id = ingested.result_refs[0].object_id
    retrieval_id = ingested.result_refs[1].object_id
    return ClaimActions(service), engine, artifact_id, retrieval_id


def test_extract_claim_is_provisional_with_span(tmp_path: Path) -> None:
    actions, engine, artifact_id, retrieval_id = _setup(tmp_path)
    outcome = actions.extract_claim(ExtractClaimRequest(
        subject_type="person", subject_id="person-striker", predicate="availability",
        value={"availability": "out"}, scope_match_id="match-1",
        valid_from="2026-07-19T00:00:00+08:00", extractor="news-nlp", extractor_version="1",
        spans=[EvidenceSpanInput(artifact_id=artifact_id, artifact_retrieval_id=retrieval_id,
                                 quote="striker OUT with injury", locator="p1")],
        actor_id="model:extractor", actor_role=ActorRole.AI_EXTRACTOR, idempotency_key="claim:1",
        requested_at=datetime(2026, 7, 19, 9, tzinfo=UTC),
    ))
    assert outcome.status is ActionStatus.COMMITTED
    claim_id = outcome.result_refs[0].object_id
    with OntologyUnitOfWork(engine) as uow:
        assert uow.evidence.claim_status(claim_id) == ClaimStatus.PROVISIONAL.value
        claims = uow.evidence.claims_for("person", "person-striker")
        assert len(claims) == 1


def test_connector_cannot_extract_claim(tmp_path: Path) -> None:
    actions, _engine, artifact_id, retrieval_id = _setup(tmp_path)
    outcome = actions.extract_claim(ExtractClaimRequest(
        subject_type="person", subject_id="p", predicate="availability", value={}, scope_match_id=None,
        valid_from="2026-07-19T00:00:00+08:00", extractor="x", extractor_version="1",
        spans=[EvidenceSpanInput(artifact_id=artifact_id, artifact_retrieval_id=retrieval_id,
                                 quote="q", locator=None)],
        actor_id="source:club", actor_role=ActorRole.CONNECTOR, idempotency_key="claim:denied",
        requested_at=datetime(2026, 7, 19, 9, tzinfo=UTC),
    ))
    assert outcome.status is ActionStatus.REJECTED
```

- [ ] **Step 2: Run and verify RED**

Run: `uv run pytest tests/ontology/test_extract_claim.py -q`
Expected: import error for `claim_actions`.

- [ ] **Step 3: Implement ExtractClaim**

`claim_actions.py` defines frozen `EvidenceSpanInput(artifact_id, artifact_retrieval_id, quote, locator)`,
`ExtractClaimRequest` (validated aware time, non-empty subject/predicate/extractor, at least one span) and
`ClaimActions(action_service)`. `extract_claim(request)` builds `ActionCommand(action_type="extract_claim")`
and a handler that mints `mint_evidence_id("claim")`, inserts one `claims` row with
`status=ClaimStatus.PROVISIONAL`, one `claim_evidence_spans` row per span, and one `claim_status_events` row
`(from_status=None, to_status="provisional", action_id=command.action_id)`, returning
`(ObjectRef("claim", claim_id),)`. Permission (`extract_claim`: ai_extractor only) means a connector is
rejected — the AI path stays provisional and AI-only.

- [ ] **Step 4: Run tests and ruff**

Run:
```bash
uv run pytest tests/ontology/test_extract_claim.py -q
uv run ruff check nutmeg/ontology/actions/claim_actions.py
```
Expected: pass; clean.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/ontology/actions/claim_actions.py tests/ontology/test_extract_claim.py
git commit -m "feat(ontology): extract provisional claims with evidence spans"
```

---

### Task 8: Claim adjudication (Verify / Dispute / Retract)

**Files:**
- Modify: `nutmeg/ontology/actions/claim_actions.py`
- Test: `tests/ontology/test_claim_adjudication.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.actions.claim_actions import (
    ClaimActions, ClaimAdjudicationRequest, EvidenceSpanInput, ExtractClaimRequest,
)
from nutmeg.ontology.actions.artifact_ingest import ArtifactIngestRequest, ArtifactIngestService
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.artifacts import ContentAddressedArtifactStore
from nutmeg.ontology.evidence.models import ClaimStatus
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _claim(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    service = ActionService(lambda: OntologyUnitOfWork(engine))
    ingest = ArtifactIngestService(
        action_service=service, artifact_store=ContentAddressedArtifactStore(tmp_path / "artifacts"))
    art = ingest.ingest(ArtifactIngestRequest(
        content=b"statement", content_type="text/plain", source_name="s", source_type="web",
        actor_id="source:s", actor_role=ActorRole.CONNECTOR, idempotency_key="a:1",
        retrieved_at=datetime(2026, 7, 19, 8, tzinfo=UTC)))
    actions = ClaimActions(service)
    claim_id = actions.extract_claim(ExtractClaimRequest(
        subject_type="person", subject_id="p", predicate="availability", value={"availability": "out"},
        scope_match_id=None, valid_from="2026-07-19T00:00:00+08:00", extractor="x", extractor_version="1",
        spans=[EvidenceSpanInput(art.result_refs[0].object_id, art.result_refs[1].object_id, "q", None)],
        actor_id="model:x", actor_role=ActorRole.AI_EXTRACTOR, idempotency_key="c:1",
        requested_at=datetime(2026, 7, 19, 9, tzinfo=UTC))).result_refs[0].object_id
    return actions, engine, claim_id


def _adj(claim_id: str, key: str, role: ActorRole) -> ClaimAdjudicationRequest:
    return ClaimAdjudicationRequest(
        claim_id=claim_id, actor_id="op:owner", actor_role=role, idempotency_key=key,
        requested_at=datetime(2026, 7, 19, 10, tzinfo=UTC))


def test_verify_records_status_event_and_current_status(tmp_path: Path) -> None:
    actions, engine, claim_id = _claim(tmp_path)
    outcome = actions.verify_claim(_adj(claim_id, "v:1", ActorRole.JUDGE_OPERATOR))
    assert outcome.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        assert uow.evidence.claim_status(claim_id) == ClaimStatus.VERIFIED.value
        assert uow.evidence.claim_status_history(claim_id)[-1] == ("provisional", "verified")


def test_ai_extractor_cannot_verify_its_own_claim(tmp_path: Path) -> None:
    actions, _engine, claim_id = _claim(tmp_path)
    outcome = actions.verify_claim(_adj(claim_id, "v:denied", ActorRole.AI_EXTRACTOR))
    assert outcome.status is ActionStatus.REJECTED
```

- [ ] **Step 2: Run and verify RED**

Run: `uv run pytest tests/ontology/test_claim_adjudication.py -q`
Expected: import error for `ClaimAdjudicationRequest`.

- [ ] **Step 3: Implement adjudication**

Add frozen `ClaimAdjudicationRequest` and methods `verify_claim`, `dispute_claim`, `retract_claim` to
`ClaimActions`. Each builds `ActionCommand(action_type="verify_claim"|"dispute_claim"|"retract_claim")` and a
handler that reads the current status, updates `claims.status` (and `adjudicated_at`) to
`verified`/`disputed`/`retracted`, and appends a `claim_status_events` row `(from_status, to_status,
action_id=command.action_id)`. Add `EvidenceRepository.update_claim_status(claim_id, to_status,
adjudicated_at)` and `claim_status_history(claim_id) -> list[tuple[str | None, str]]`. Permissions
(`verify_claim`: deterministic_system/judge_operator; `dispute_claim`/`retract_claim`: judge_operator) mean an
ai_extractor cannot verify — Claim content is immutable and the status trail is replayable.

- [ ] **Step 4: Run tests and ruff**

Run:
```bash
uv run pytest tests/ontology/test_claim_adjudication.py tests/ontology/test_extract_claim.py -q
uv run ruff check nutmeg/ontology/actions/claim_actions.py nutmeg/ontology/repository/evidence.py
```
Expected: pass; clean.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/ontology/actions/claim_actions.py nutmeg/ontology/repository/evidence.py \
  tests/ontology/test_claim_adjudication.py
git commit -m "feat(ontology): adjudicate claims with replayable status events"
```

---

### Task 9: PersonMatchStatus and LineupEntry Actions

**Files:**
- Modify: `nutmeg/ontology/actions/observation_actions.py`
- Test: `tests/ontology/test_person_match_status.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.observation_actions import (
    ObservationActions, PersonMatchStatusRequest,
)
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.evidence.models import Availability, StatusKind
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _actions(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    from nutmeg.ontology.identity.models import ResolutionStatus
    from nutmeg.ontology.repository.identity import PersonRow
    with OntologyUnitOfWork(engine) as uow:
        uow.identity.insert_match_minimal("match-1")
        uow.identity.insert_person(PersonRow(
            person_id="person-1", canonical_name="X", birth_date=None, nationality=None,
            resolution_status=ResolutionStatus.PROVISIONAL,
            created_at=datetime(2026, 7, 19, tzinfo=UTC).isoformat()))
    return ObservationActions(ActionService(lambda: OntologyUnitOfWork(engine))), engine


def test_record_person_match_status_links_observation(tmp_path: Path) -> None:
    actions, engine = _actions(tmp_path)
    outcome = actions.record_person_match_status(PersonMatchStatusRequest(
        match_id="match-1", person_id="person-1", team_appearance_id=None,
        availability=Availability.OUT, status_kind=StatusKind.INJURY,
        valid_from="2026-07-19T00:00:00+08:00", observed_at="2026-07-19T12:00:00+08:00",
        actor_id="source:api", actor_role=ActorRole.CONNECTOR, idempotency_key="pms:1",
        requested_at=datetime(2026, 7, 19, 8, tzinfo=UTC)))
    assert outcome.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        ids = uow.context.person_match_status_ids("match-1")
        assert len(ids) == 1
        # a backing observation was recorded and linked
        assert uow.evidence.count_observations() == 1
```

- [ ] **Step 2: Run and verify RED**

Run: `uv run pytest tests/ontology/test_person_match_status.py -q`
Expected: import error for `PersonMatchStatusRequest`.

- [ ] **Step 3: Implement PersonMatchStatus (and LineupEntry) as observation-backed context**

Add frozen `PersonMatchStatusRequest` and `LineupEntryRequest` and methods
`record_person_match_status`/`record_lineup_entry` to `ObservationActions`. Each Action, in one handler:
records a backing deterministic `Observation` (subject_type `person`, `verification_method='official'`), then
inserts the `person_match_statuses`/`lineup_entries` row with `observation_id` pointing at it, returning the
context object ref. This keeps "状态≠null" and every status traceable to an Observation. Permissions
(`record_person_match_status`/`record_lineup_entry`: connector/deterministic_system) are seeded in migration 6.

- [ ] **Step 4: Run tests and ruff**

Run:
```bash
uv run pytest tests/ontology/test_person_match_status.py tests/ontology/test_record_observation.py -q
uv run ruff check nutmeg/ontology/actions/observation_actions.py
```
Expected: pass; clean.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/ontology/actions/observation_actions.py tests/ontology/test_person_match_status.py
git commit -m "feat(ontology): record observation-backed person match status"
```

---

### Task 10: Lineup/availability adapter parser

**Files:**
- Create: `nutmeg/ontology/ingest/lineup.py`
- Test: `tests/ontology/test_ingest_lineup.py`

> Before writing the fixture, inspect a real availability/lineup snapshot if one exists under
> `.nutmeg-data/jczq/daily/<D>/` (e.g. an information/lineup JSON) and shape the parser to the **real**
> structure — do not guess. If none exists for the target day, use a minimal synthetic shape and note in the
> parser docstring that the real adapter payload must be confirmed before production wiring.

- [ ] **Step 1: Write the failing test**

```python
from nutmeg.ontology.ingest.lineup import ParsedAvailability, parse_availability_snapshot


SNAPSHOT = {"match_no": "周日001", "team": "哈马比", "players": [
    {"name": "Striker A", "provider_id": "P-1", "availability": "out", "status_kind": "injury"},
    {"name": "Mid B", "provider_id": "P-2", "availability": "available", "status_kind": "selection"},
]}


def test_parses_availability_rows() -> None:
    parsed = parse_availability_snapshot(SNAPSHOT)
    assert all(isinstance(p, ParsedAvailability) for p in parsed)
    out = next(p for p in parsed if p.availability == "out")
    assert out.player_name == "Striker A"
    assert out.provider_id == "P-1"
    assert out.status_kind == "injury"
    assert out.match_no == "周日001"
```

- [ ] **Step 2: Run and verify RED**

Run: `uv run pytest tests/ontology/test_ingest_lineup.py -q`
Expected: import error for `lineup`.

- [ ] **Step 3: Implement the parser**

`lineup.py` defines frozen `ParsedAvailability(match_no, team_name, player_name, provider_id, availability,
status_kind)` and `parse_availability_snapshot(value) -> list[ParsedAvailability]`, iterating the players list
and emitting one row per player with normalized availability/status_kind strings. Unknown/missing fields are
skipped, never guessed. Keep the parser pure (no DB).

- [ ] **Step 4: Run tests and ruff**

Run:
```bash
uv run pytest tests/ontology/test_ingest_lineup.py -q
uv run ruff check nutmeg/ontology/ingest/lineup.py
```
Expected: pass; clean.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/ontology/ingest/lineup.py tests/ontology/test_ingest_lineup.py
git commit -m "feat(ontology): parse availability snapshots"
```

---

### Task 11: Evidence-day ingest orchestration + CLI + wiring

**Files:**
- Create: `nutmeg/ontology/ingest/evidence_day.py`, `nutmeg/interfaces/cli/ontology_evidence.py`
- Modify: `nutmeg/ontology/wiring.py`, `nutmeg/ontology/kernel.py`, `nutmeg/interfaces/cli/__init__.py`, `nutmeg/ontology/repository/identity.py`
- Test: `tests/ontology/test_evidence_day_ingest.py`, `tests/ontology/test_evidence_cli.py`

- [ ] **Step 1: Write the failing orchestration test**

```python
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.ingest.evidence_day import EvidenceDayIngestRequest
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel

AVAIL = [{"match_no": "周日001", "team": "哈马比", "players": [
    {"name": "Striker A", "provider_id": "P-1", "availability": "out", "status_kind": "injury"}]}]


def test_ingest_evidence_day_records_person_status(tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    kernel = build_ontology_kernel(settings)
    kernel.initialize()
    # a real match (from a prior market-day ingest) the availability rows attach to;
    # here pre-seed a bare match so the person_match_statuses FK holds.
    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.identity.insert_match_minimal("match-preseeded")
    result = kernel.evidence_day_ingest.ingest(EvidenceDayIngestRequest(
        business_date="2026-07-19",
        match_no_to_id={"周日001": "match-preseeded"},
        availability=AVAIL, weather=[], news=[],
        actor_id="source:api", actor_role=ActorRole.CONNECTOR,
        requested_at=datetime(2026, 7, 19, 8, tzinfo=UTC)))
    assert result.person_statuses == 1
    status = kernel.status()
    assert status.person_count >= 1
    assert status.observation_count >= 1
```

> The orchestration receives the `match_no -> match_id` map from a prior market-day ingest (2A), so evidence
> attaches to real matches. For the isolated test, pre-seed a bare match via
> `uow.identity.insert_match_minimal("match-preseeded")` inside a `build_ontology_kernel` UoW before calling
> ingest (adjust the test setup accordingly), or accept a `match_no_to_id` the caller supplies.

- [ ] **Step 2: Run and verify RED**

Run: `uv run pytest tests/ontology/test_evidence_day_ingest.py -q`
Expected: import error / missing kernel attributes.

- [ ] **Step 3: Implement the orchestration**

`evidence_day.py` defines frozen `EvidenceDayIngestRequest` (business_date, `match_no_to_id: dict[str, str]`,
availability/weather/news lists, actor, aware requested_at) and `EvidenceDayIngestResult(person_statuses,
observations, claims)`. `EvidenceDayIngestService` holds `PersonActions`, `ObservationActions`,
`ClaimActions`. `ingest`:

1. for each `ParsedAvailability` (via `parse_availability_snapshot`): resolve the match via
   `match_no_to_id[match_no]` (skip if absent, `log`-style comment — do not silently drop without counting);
   `upsert_person(name, provider_id)`; `record_person_match_status(match_id, person_id, availability,
   status_kind)`;
2. for each weather entry: `record_observation(observation_type="weather", subject=match, ...)`;
3. for each news entry: `extract_claim(...)` as an ai_extractor provisional Claim with its evidence span;
4. return counts.

Add `IdentityRepository.all_person_ids`/`count_persons` (count added in Task 4). Extend
`OntologyKernelStatus` with `person_count`, `observation_count`, `claim_count`; extend
`build_ontology_kernel` to construct and expose `evidence_day_ingest`; the market-day and evidence-day ingests
compose (Package 3 will chain them behind `sense`).

- [ ] **Step 4: Write the failing CLI test and implement the command**

```python
import json
from typer.testing import CliRunner
from nutmeg.interfaces.cli import app

runner = CliRunner()


def test_ingest_evidence_day_cli(tmp_path) -> None:
    avail = tmp_path / "avail.json"
    avail.write_text(json.dumps([{"match_no": "周日001", "team": "哈马比", "players": [
        {"name": "Striker A", "provider_id": "P-1", "availability": "out", "status_kind": "injury"}]}]),
        encoding="utf-8")
    runner.invoke(app, ["ontology", "init", "--format", "json"])
    result = runner.invoke(app, ["ontology", "ingest-evidence-day", "--business-date", "2026-07-19",
        "--availability", str(avail), "--format", "json"])
    assert result.exit_code == 0
    assert "person_statuses" in json.loads(result.stdout)
```

`ontology_evidence.py` adds `ingest-evidence-day` to the `ontology` sub-app (options: `--business-date`,
`--availability <path>`, optional `--weather`/`--news`, `--format`), initializes the kernel, and runs the
evidence-day ingest as connector. With no prior market day the `match_no_to_id` is empty and rows are counted
as skipped, printed explicitly (never hidden). Register `from nutmeg.interfaces.cli import ontology_evidence`
at the bottom of `__init__.py`.

- [ ] **Step 5: Run tests and ruff**

Run:
```bash
uv run pytest tests/ontology/test_evidence_day_ingest.py tests/ontology/test_evidence_cli.py \
  tests/ontology/test_kernel.py -q
uv run ruff check nutmeg/ontology tests/ontology nutmeg/interfaces/cli/ontology_evidence.py
```
Expected: pass; clean.

- [ ] **Step 6: Commit**

```bash
git add nutmeg/ontology/ingest/evidence_day.py nutmeg/ontology/wiring.py nutmeg/ontology/kernel.py \
  nutmeg/ontology/repository/identity.py nutmeg/interfaces/cli/ontology_evidence.py \
  nutmeg/interfaces/cli/__init__.py tests/ontology/test_evidence_day_ingest.py \
  tests/ontology/test_evidence_cli.py
git commit -m "feat(ontology): ingest an evidence day into typed facts"
```

---

### Task 12: Conflicting-claims and graded-write e2e gate, docs, full verification

**Files:**
- Create: `tests/ontology/test_package2b_e2e.py`
- Modify: `docs/ontology-kernel-operations.md`
- Modify only if a failure exposes a bug: Package 2B modules

- [ ] **Step 1: Write the failing e2e test**

```python
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.artifact_ingest import ArtifactIngestRequest
from nutmeg.ontology.actions.claim_actions import ClaimActions, EvidenceSpanInput, ExtractClaimRequest
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel


def test_conflicting_claims_coexist_and_ai_cannot_verify(tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    kernel = build_ontology_kernel(settings)
    kernel.initialize()
    service = ActionService(lambda: OntologyUnitOfWork(kernel.engine))
    claims = ClaimActions(service)

    def _art(text: str, key: str):
        outcome = kernel.artifact_ingest.ingest(ArtifactIngestRequest(
            content=text.encode(), content_type="text/plain", source_name="s", source_type="web",
            actor_id="source:s", actor_role=ActorRole.CONNECTOR, idempotency_key=key,
            retrieved_at=datetime(2026, 7, 19, 8, tzinfo=UTC)))
        return outcome.result_refs[0].object_id, outcome.result_refs[1].object_id

    def _extract(value, key, art_key, text):
        aid, rid = _art(text, art_key)
        return claims.extract_claim(ExtractClaimRequest(
            subject_type="person", subject_id="p", predicate="availability", value=value,
            scope_match_id=None, valid_from="2026-07-19T00:00:00+08:00", extractor="nlp",
            extractor_version="1",
            spans=[EvidenceSpanInput(aid, rid, text, None)],
            actor_id="model:x", actor_role=ActorRole.AI_EXTRACTOR, idempotency_key=key,
            requested_at=datetime(2026, 7, 19, 9, tzinfo=UTC))).result_refs[0].object_id

    c_out = _extract({"availability": "out"}, "c:out", "a:out", "OUT injured")
    c_fit = _extract({"availability": "available"}, "c:fit", "a:fit", "fit to play")

    with OntologyUnitOfWork(kernel.engine) as uow:
        # both provisional claims coexist — no auto-overwrite
        assert len(uow.evidence.claims_for("person", "p")) == 2

    # AI cannot verify its own claim
    from nutmeg.ontology.actions.claim_actions import ClaimAdjudicationRequest
    from nutmeg.ontology.actions.models import ActionStatus
    denied = claims.verify_claim(ClaimAdjudicationRequest(
        claim_id=c_out, actor_id="model:x", actor_role=ActorRole.AI_EXTRACTOR,
        idempotency_key="v:denied", requested_at=datetime(2026, 7, 19, 10, tzinfo=UTC)))
    assert denied.status is ActionStatus.REJECTED

    # operator verifies one; status trail is replayable
    ok = claims.verify_claim(ClaimAdjudicationRequest(
        claim_id=c_out, actor_id="op:owner", actor_role=ActorRole.JUDGE_OPERATOR,
        idempotency_key="v:ok", requested_at=datetime(2026, 7, 19, 10, tzinfo=UTC)))
    assert ok.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.evidence.claim_status(c_out) == "verified"
        assert uow.evidence.claim_status(c_fit) == "provisional"   # the other is untouched
        assert kernel.status().claim_count == 2
```

- [ ] **Step 2: Run and drive to GREEN**

Run: `uv run pytest tests/ontology/test_package2b_e2e.py -q`
Expected: initially fails only on a real bug; fix minimal Package 2B code and re-run to GREEN.

- [ ] **Step 3: Document Package 2B operations**

Add a "Package 2B — Evidence & Context" section to `docs/ontology-kernel-operations.md`: Person resolution,
graded write-back (deterministic Observation vs provisional Claim), the claim status machine and its
replayable events, and:

```bash
uv run nutmeg ontology ingest-evidence-day --business-date <D> --availability <path> [--weather <path>] [--news <path>] --format json
```

State that conflicting claims coexist and are never auto-overwritten, and that AI extractors can never
verify a fact.

- [ ] **Step 4: Full suite and adjacent regressions**

Run:
```bash
uv run pytest tests/ontology -q
uv run pytest tests/test_cli.py::test_doctor_reports_ready_workflow_and_harness tests/decision/ -q
```
Expected: all pass; the decision suite is unchanged.

- [ ] **Step 5: Repository quality gates**

Run:
```bash
uv run ruff check .
uv run python -m compileall -q nutmeg scripts
bash scripts/verify.sh
```
Expected: ruff and compileall clean; full pytest suite passes.

- [ ] **Step 6: Project verify — real evidence-day smoke if data exists**

If a real availability/lineup/weather snapshot exists under `.nutmeg-data/jczq/daily/<D>/`, ingest it from an
isolated temp data dir with this branch's code (read-only on production, no push) and confirm person statuses
and observations land with source lineage. If no real evidence snapshot exists for any recent day, state that
explicitly and rely on the synthetic e2e gate — never claim a real run happened when it did not.

- [ ] **Step 7: Commit and inspect the branch**

```bash
git add tests/ontology/test_package2b_e2e.py docs/ontology-kernel-operations.md nutmeg/ontology
git commit -m "test(ontology): verify package 2b evidence and context"
git status --short
git log --oneline main..HEAD
git diff --stat main...HEAD | tail -30
```
Expected: clean worktree, one focused commit per task, no files outside scope. Do not merge — hand back for
review.

---

## Package 2B Spec Coverage

| Design (§) requirement | Implemented by |
|---|---|
| Person resolution reusing provider-id-first resolver (§1, §2.1) | Task 4 |
| Context tables: role/status/lineup (§1, §3) | Tasks 2, 5, 9 |
| Evidence tables: claim/status-event/span/observation (§3) | Tasks 3, 5 |
| Deterministic Observation vs provisional Claim, graded permissions (§2.4, §4) | Tasks 3, 6, 7 |
| AI extractor cannot write verified facts / self-verify (§0.1, §2.4, §7) | Tasks 6, 7, 8, 12 |
| Conflicting claims coexist, no auto-overwrite (§2.4, §7) | Tasks 7, 12 |
| Claim status transitions append replayable events (§3) | Tasks 8, 12 |
| Observation-backed person match status (状态≠null) (§3) | Task 9 |
| Every claim/observation traces to ArtifactRetrieval (§6) | Tasks 6, 7, 11 |
| One adapter end-to-end into typed evidence (§1, §5) | Tasks 10, 11 |
| Real/synthetic acceptance gate (§7) | Task 12 |

Package 2B is complete only when Task 12 passes. Together with Package 2A it closes umbrella Package 2
(Football World & Evidence). Package 3 (Decision & Finance Loop) receives its own spec/plan and consumes 2A+2B
verified interfaces (EvidenceBundle freeze, Forecast revisions, Ticket/Ledger). Deferred within 2B and to be
scoped as a short follow-on: full transfermarkt player-ability import and any remaining adapter payload shapes
not covered by the representative lineup/weather/news paths above.
