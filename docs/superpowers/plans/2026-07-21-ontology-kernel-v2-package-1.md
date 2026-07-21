# Ontology Kernel v2 Package 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the transactional Ontology Kernel foundation: an independent SQLite operational database, content-addressed evidence storage, explicit migrations, typed/idempotent Actions, permission enforcement, and minimal `nutmeg ontology init/status` operations.

**Architecture:** Package 1 creates no football-domain objects. It establishes the write boundary that later packages must use: SQLAlchemy Core typed tables behind a short-lived Unit of Work, immutable SHA-256 artifacts on disk, and an Action service that commits business rows and audit state atomically. A single `IngestArtifact` vertical slice proves permissions, idempotency, rollback, CAS persistence, CLI wiring, and restart safety without coupling the kernel to Match, Team, Person, Forecast, or Ticket.

**Tech Stack:** Python 3.12, frozen dataclasses, SQLAlchemy 2 Core, SQLite WAL, Typer, pytest, ruff, SHA-256 content-addressed files, existing `AppSettings` and CLI package.

**Design Spec:** `docs/superpowers/specs/2026-07-20-ontology-kernel-v2-design.md` (§0–§8, §12–§16).

---

## Scope Boundary

Package 1 includes:

- `.nutmeg-data/ontology/ontology.db` as a separate SQLite operational database;
- `.nutmeg-data/ontology/artifacts/sha256/<prefix>/<digest>` immutable evidence blobs;
- explicit numbered schema migrations with drift checks;
- governance tables: Actions, PolicyVersion, ActionPermission;
- evidence-kernel tables: SourceRun, SourceArtifact and ArtifactRetrieval;
- Action value objects, permission guard, idempotency, failure audit, rollback and optimistic-version envelope;
- `IngestArtifact` as the only production Action handler in this package;
- kernel initialization/status services and `nutmeg ontology init/status`;
- Package 1 operations documentation, current-plan pointers and quality hooks.

Package 1 explicitly excludes:

- Match, Team, Person, CompetitionEdition, Venue and identity resolution;
- Claim, Observation, EvidenceBundle and market adapters;
- Forecast, Factor, Ticket, Transaction, Outcome and Settlement;
- DuckDB score, factor or Regime projections;
- legacy JSONL/DuckDB data migration and production cutover.

Those belong to Packages 2–5. Do not add generic object payload tables as a shortcut.

---

## File Structure

### New production modules

- `nutmeg/ontology/__init__.py`: stable Package 1 public exports only.
- `nutmeg/ontology/errors.py`: kernel-specific typed errors.
- `nutmeg/ontology/paths.py`: deterministic ontology DB/artifact paths and directory creation.
- `nutmeg/ontology/artifacts.py`: SHA-256 CAS byte/file persistence with atomic publication.
- `nutmeg/ontology/kernel.py`: initialization and read-only status facade.
- `nutmeg/ontology/wiring.py`: `AppSettings` to engine, UoW, Action and artifact services.
- `nutmeg/ontology/actions/__init__.py`: stable Action exports.
- `nutmeg/ontology/actions/models.py`: ActorRole, ActionStatus, ActionCommand, ObjectRef and ActionOutcome.
- `nutmeg/ontology/actions/permissions.py`: database-backed permission guard.
- `nutmeg/ontology/actions/service.py`: idempotent Action execution and failure audit.
- `nutmeg/ontology/actions/artifact_ingest.py`: `IngestArtifact` command builder and handler.
- `nutmeg/ontology/repository/__init__.py`: repository public exports.
- `nutmeg/ontology/repository/schema.py`: SQLAlchemy Core table declarations.
- `nutmeg/ontology/repository/connection.py`: SQLite engine and PRAGMA setup.
- `nutmeg/ontology/repository/migrations.py`: numbered migration registry, apply/status/drift logic.
- `nutmeg/ontology/repository/unit_of_work.py`: transaction boundary.
- `nutmeg/ontology/repository/actions.py`: Action persistence and idempotency queries.
- `nutmeg/ontology/repository/artifacts.py`: SourceArtifact/ArtifactRetrieval persistence.
- `nutmeg/interfaces/cli/ontology.py`: `ontology init` and `ontology status` subcommands.
- `docs/ontology-kernel-operations.md`: Package 1 operator contract.

### New tests

- `tests/ontology/test_paths.py`
- `tests/ontology/test_connection.py`
- `tests/ontology/test_migrations.py`
- `tests/ontology/test_action_models.py`
- `tests/ontology/test_permissions.py`
- `tests/ontology/test_action_service.py`
- `tests/ontology/test_artifacts.py`
- `tests/ontology/test_artifact_ingest.py`
- `tests/ontology/test_kernel.py`
- `tests/ontology/test_cli.py`
- `tests/ontology/test_governance_docs.py`
- `tests/ontology/test_kernel_e2e.py`

### Existing files modified

- `nutmeg/config/settings.py`: ontology directory/database/artifact properties.
- `nutmeg/interfaces/cli/__init__.py`: register the ontology Typer sub-app and expose wiring used by CLI tests.
- `nutmeg/interfaces/cli/core.py`: add read-only ontology status to `doctor` without auto-initializing it.
- `.pre-commit-config.yaml`: run ontology tests whenever kernel/ontology CLI files change.
- `README.md`: document Package 1 experimental operations without claiming v2 cutover.
- `AGENTS.md` and `CLAUDE.md`: point both harness copies at this plan. `AGENTS.md` already has a `<!-- SPECKIT START -->` block holding the retired `.specify/specs/046-jczq-mixed-parlay-report-v0/plan.md` pointer (replace the path in place); `CLAUDE.md` has no such block and no current-plan pointer today (add an identical block), so the two copies end up carrying the same pointer.

### User-owned files that must not be reverted

The starting worktree contains unrelated edits to `SOUL.md` and the three decision launchd plists plus
untracked `media/`, memory and research-script files. Package 1 does not modify or stage them. Execution
must happen in the dedicated worktree created in Task 0.

---

### Task 0: Freeze v1 inputs and create a clean implementation worktree

**Files:**
- Runtime archive only: `.nutmeg-data/archive/<timestamp>-ontology-v2-freeze/`
- Worktree only: `.claude/worktrees/ontology-kernel-v2-package1/`

- [ ] **Step 1: Record the current branch, commit and dirty state**

Run:

```bash
git branch --show-current
git rev-parse HEAD
git status --short
```

Expected: branch `main`; HEAD contains the confirmed v2 spec and this plan; dirty entries are limited to
the user-owned files listed above. If any additional path appears, stop and ask before continuing.

- [ ] **Step 2: Enumerate every loaded schedule, then stop only the v1-data writers**

Spec §13.1 Phase 0 requires stopping the decision am/close/settle jobs **and any related football-lottery
(zucai) auto tasks** before the freeze; a freeze is only sound if no scheduler can still write into the data
this task is about to hash read-only. So first enumerate, do not assume the writer set:

```bash
launchctl print "gui/$(id -u)" | grep -i 'com\.nutmeg'
```

Classify every loaded `com.nutmeg.*` service:

- **v1-data writers that must be stopped** — the three decision jobs plus any loaded zucai/jczq writer
  (`com.nutmeg.zucai.afternoon`, `com.nutmeg.zucai.revision`, or any `com.nutmeg.jczq.*` job that actually
  runs a `decision`/`zucai`/`jczq` command). As of 2026-07-21 only the three decision jobs are loaded; the
  `com.nutmeg.jczq.daily-*` names that show up as `enabled` are stale enable-state with **no installed plist**
  and the two `com.nutmeg.zucai.*` plists in `ops/launchd/` are **not loaded** — but re-verify at run time,
  because a loaded zucai/jczq writer here would silently mutate the archive Step 3 creates.
- **Unrelated jobs that must be left alone** — Telegram/OpenClaw and anything not writing `.nutmeg-data`
  decision/zucai state.

Read each writer you intend to stop first:

```bash
launchctl print "gui/$(id -u)/com.nutmeg.decision.am"
launchctl print "gui/$(id -u)/com.nutmeg.decision.close"
launchctl print "gui/$(id -u)/com.nutmeg.decision.settle"
```

Then bootout every loaded v1-data writer (reversible). For the current state that is exactly:

```bash
launchctl bootout "gui/$(id -u)/com.nutmeg.decision.am"
launchctl bootout "gui/$(id -u)/com.nutmeg.decision.close"
launchctl bootout "gui/$(id -u)/com.nutmeg.decision.settle"
```

If the enumeration surfaced any additional loaded zucai/jczq writer, bootout it the same way and record it in
the progress notes. Expected: every v1-data writer is removed. A service that was already absent needs no
bootout. Do not modify the plist files and do not stop Telegram/OpenClaw or unrelated launchd jobs.

- [ ] **Step 3: Create a read-only evidence-first freeze copy and hash manifest**

Run from the repository root:

```bash
STAMP=$(date +%Y%m%d-%H%M%S)
ARCHIVE=".nutmeg-data/archive/${STAMP}-ontology-v2-freeze"
mkdir -p "$ARCHIVE"
rsync -a .nutmeg-data/jczq/ "$ARCHIVE/jczq/"
rsync -a .nutmeg-data/zucai/ "$ARCHIVE/zucai/"
rsync -a .nutmeg-data/notifications/ "$ARCHIVE/notifications/"
cp -p .nutmeg-data/analytics/analytics.duckdb "$ARCHIVE/analytics.duckdb"
sqlite3 .nutmeg-data/state/state.db ".backup '$ARCHIVE/state.db'"
MANIFEST=$(mktemp)
find "$ARCHIVE" -type f -exec shasum -a 256 {} + | LC_ALL=C sort > "$MANIFEST"
mv "$MANIFEST" "$ARCHIVE/SHA256SUMS"
chmod -R a-w "$ARCHIVE"
wc -l "$ARCHIVE/SHA256SUMS"
```

Expected: a non-empty manifest. This is a copy-only operation; the live `.nutmeg-data` sources remain in
place. Record the resolved `$ARCHIVE` path in the implementation progress notes, not in git.

- [ ] **Step 4: Verify schedules are stopped and the archive is readable**

Run:

```bash
ARCHIVE=$(find .nutmeg-data/archive -maxdepth 1 -type d \
  -name '*-ontology-v2-freeze' | LC_ALL=C sort | tail -1)
launchctl print "gui/$(id -u)/com.nutmeg.decision.am"
launchctl print "gui/$(id -u)/com.nutmeg.decision.close"
launchctl print "gui/$(id -u)/com.nutmeg.decision.settle"
launchctl print "gui/$(id -u)" | grep -iE 'com\.nutmeg\.(decision|zucai|jczq)' || echo "no loaded decision/zucai/jczq writer"
find "$ARCHIVE" -type f | wc -l
head -5 "$ARCHIVE/SHA256SUMS"
```

Expected: all three `launchctl print` calls report that the service cannot be found; the grep prints
`no loaded decision/zucai/jczq writer` (any remaining match is a writer Step 2 missed — stop it and rehash
before proceeding); the archive has files and hashes. Do not re-enable schedules until Package 5 cutover
gates pass.

- [ ] **Step 5: Create the dedicated implementation worktree**

Run:

```bash
git worktree add .claude/worktrees/ontology-kernel-v2-package1 \
  -b feature/ontology-kernel-v2-package1
cd .claude/worktrees/ontology-kernel-v2-package1
git status --short
```

Expected: a clean worktree on `feature/ontology-kernel-v2-package1`. All subsequent tasks run there.

### Task 1: Ontology filesystem and settings contract

**Files:**
- Create: `nutmeg/ontology/__init__.py`
- Create: `nutmeg/ontology/errors.py`
- Create: `nutmeg/ontology/paths.py`
- Modify: `nutmeg/config/settings.py`
- Test: `tests/ontology/test_paths.py`

- [ ] **Step 1: Write failing path/settings tests**

```python
from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.paths import OntologyPaths


def test_settings_exposes_separate_ontology_paths(tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    assert settings.ontology_dir == tmp_path / "data" / "ontology"
    assert settings.ontology_db_path == tmp_path / "data" / "ontology" / "ontology.db"
    assert settings.ontology_artifact_dir == tmp_path / "data" / "ontology" / "artifacts"
    assert settings.ontology_db_url.startswith("sqlite+pysqlite:///")


def test_ontology_paths_create_only_owned_directories(tmp_path: Path) -> None:
    paths = OntologyPaths.from_data_dir(tmp_path / "data")
    paths.ensure_directories()
    assert paths.root.is_dir()
    assert paths.artifacts.is_dir()
    assert not paths.database.exists()
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `uv run pytest tests/ontology/test_paths.py -q`
Expected: collection fails because `nutmeg.ontology` and settings properties do not exist.

- [ ] **Step 3: Implement typed paths and errors**

Create the error hierarchy exactly:

```python
class OntologyError(Exception):
    """Base error for the v2 ontology kernel."""


class MigrationDriftError(OntologyError):
    pass


class PermissionDeniedError(OntologyError):
    pass


class IdempotencyConflictError(OntologyError):
    pass
```

Create `OntologyPaths` as a frozen, slotted dataclass:

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class OntologyPaths:
    root: Path
    database: Path
    artifacts: Path

    @classmethod
    def from_data_dir(cls, data_dir: Path | str) -> "OntologyPaths":
        root = Path(data_dir) / "ontology"
        return cls(root=root, database=root / "ontology.db", artifacts=root / "artifacts")

    def ensure_directories(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.artifacts.mkdir(parents=True, exist_ok=True)
```

Add `ontology_dir`, `ontology_db_path`, `ontology_artifact_dir` and
`ontology_db_url` properties to `AppSettings`; use `sqlite+pysqlite:///` and a resolved path.
Export only `OntologyPaths` and the four errors from `nutmeg/ontology/__init__.py`.

- [ ] **Step 4: Run focused tests and settings regressions**

Run: `uv run pytest tests/ontology/test_paths.py tests/test_provider_health_persistence.py -q`
Expected: all tests pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add nutmeg/ontology nutmeg/config/settings.py tests/ontology/test_paths.py
git commit -m "feat(ontology): add kernel paths and settings"
```

### Task 2: SQLite connection policy and Unit of Work

**Files:**
- Create: `nutmeg/ontology/repository/__init__.py`
- Create: `nutmeg/ontology/repository/connection.py`
- Create: `nutmeg/ontology/repository/unit_of_work.py`
- Test: `tests/ontology/test_connection.py`

- [ ] **Step 1: Write failing SQLite policy and rollback tests**

```python
from pathlib import Path

import pytest
from sqlalchemy import text

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def test_engine_enables_foreign_keys_wal_and_busy_timeout(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar_one().lower() == "wal"
        assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == 5000


def test_unit_of_work_rolls_back_the_whole_transaction(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE probe (value TEXT NOT NULL)"))

    with pytest.raises(RuntimeError, match="rollback probe"):
        with OntologyUnitOfWork(engine) as uow:
            uow.connection.execute(text("INSERT INTO probe(value) VALUES ('written')"))
            raise RuntimeError("rollback probe")

    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM probe")).scalar_one() == 0
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `uv run pytest tests/ontology/test_connection.py -q`
Expected: import failure for the repository modules.

- [ ] **Step 3: Implement the engine and transaction boundary**

`build_ontology_engine()` must create the parent directory and use:

```python
engine = create_engine(
    f"sqlite+pysqlite:///{database_path.resolve()}",
    future=True,
    connect_args={"check_same_thread": False},
)
```

Install a SQLAlchemy `connect` event that executes, in order:

```sql
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;
PRAGMA journal_mode=WAL;
```

Implement `OntologyUnitOfWork` with `engine.connect()`, `connection.begin()`, commit on a clean exit,
rollback on any exception, and unconditional connection close. Accessing `.connection` before entering or
after exiting raises `RuntimeError("unit of work is not active")`.

- [ ] **Step 4: Run focused tests and ruff**

Run:

```bash
uv run pytest tests/ontology/test_connection.py -q
uv run ruff check nutmeg/ontology/repository tests/ontology/test_connection.py
```

Expected: all tests pass and ruff reports no errors.

- [ ] **Step 5: Commit Task 2**

```bash
git add nutmeg/ontology/repository tests/ontology/test_connection.py
git commit -m "feat(ontology): add SQLite unit of work"
```

### Task 3: Explicit schema migrations and governance tables

**Files:**
- Create: `nutmeg/ontology/repository/schema.py`
- Create: `nutmeg/ontology/repository/migrations.py`
- Test: `tests/ontology/test_migrations.py`

- [ ] **Step 1: Write failing migration/idempotency/drift tests**

```python
from pathlib import Path

import pytest
from sqlalchemy import inspect, select

from nutmeg.ontology.errors import MigrationDriftError
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import (
    MIGRATIONS,
    Migration,
    migration_status,
    run_migrations,
)
from nutmeg.ontology.repository.schema import action_permissions, policy_versions


def test_migrations_apply_once_and_seed_governance_policy(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    first = run_migrations(engine)
    second = run_migrations(engine)
    assert first.applied_versions == (1, 2)
    assert second.applied_versions == ()
    assert migration_status(engine).current_version == 2
    assert {"actions", "policy_versions", "action_permissions", "source_runs",
            "source_artifacts", "artifact_retrievals"} <= set(
                inspect(engine).get_table_names()
            )
    with engine.connect() as connection:
        assert connection.execute(select(policy_versions.c.policy_version_id)).scalar_one() == (
            "governance-v1"
        )
        rows = connection.execute(select(action_permissions)).mappings().all()
        assert ("ingest_artifact", "connector") in {
            (row["action_type"], row["actor_role"]) for row in rows
        }


def test_changed_fingerprint_is_rejected_as_migration_drift(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    original = MIGRATIONS[0]
    changed = Migration(
        version=original.version,
        name=original.name,
        fingerprint="changed-after-apply",
        apply=original.apply,
    )
    with pytest.raises(MigrationDriftError, match="migration 1 checksum drift"):
        run_migrations(engine, migrations=(changed, *MIGRATIONS[1:]))
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `uv run pytest tests/ontology/test_migrations.py -q`
Expected: import failure for schema/migration modules.

- [ ] **Step 3: Declare exact Core tables**

Use one `MetaData()` and declare these columns/constraints:

```text
actions:
  action_id TEXT PK
  action_type TEXT NOT NULL INDEX
  actor_id TEXT NOT NULL
  actor_role TEXT NOT NULL INDEX
  requested_at TEXT NOT NULL
  idempotency_key TEXT NOT NULL UNIQUE
  request_hash TEXT NOT NULL
  expected_versions_json TEXT NOT NULL DEFAULT '{}'
  payload_json TEXT NOT NULL
  policy_version TEXT NOT NULL FK policy_versions ON DELETE RESTRICT
  status TEXT NOT NULL INDEX
  result_refs_json TEXT NOT NULL DEFAULT '[]'
  error_code TEXT NULL
  error_detail TEXT NULL
  committed_at TEXT NULL

policy_versions:
  policy_version_id TEXT PK
  policy_kind TEXT NOT NULL
  version INTEGER NOT NULL
  payload_json TEXT NOT NULL
  status TEXT NOT NULL
  effective_at TEXT NOT NULL
  created_at TEXT NOT NULL
  UNIQUE(policy_kind, version)

action_permissions:
  policy_version_id TEXT FK policy_versions ON DELETE CASCADE
  action_type TEXT
  actor_role TEXT
  PRIMARY KEY(policy_version_id, action_type, actor_role)

source_runs:
  source_run_id TEXT PK
  source_name TEXT NOT NULL
  source_type TEXT NOT NULL
  started_at TEXT NOT NULL
  finished_at TEXT NULL
  status TEXT NOT NULL
  error_code TEXT NULL
  error_detail TEXT NULL

source_artifacts:
  artifact_id TEXT PK
  first_recorded_at TEXT NOT NULL
  content_type TEXT NOT NULL
  storage_path TEXT NOT NULL UNIQUE
  byte_size INTEGER NOT NULL CHECK(byte_size >= 0)
  content_hash TEXT NOT NULL UNIQUE

artifact_retrievals:
  artifact_retrieval_id TEXT PK
  artifact_id TEXT NOT NULL FK source_artifacts ON DELETE RESTRICT
  source_run_id TEXT NULL FK source_runs ON DELETE RESTRICT
  source_name TEXT NOT NULL
  source_type TEXT NOT NULL
  reported_content_type TEXT NOT NULL
  canonical_url TEXT NULL
  requested_url TEXT NULL
  published_at TEXT NULL
  retrieved_at TEXT NOT NULL
  status TEXT NOT NULL
```

The `schema_migrations` bootstrap table is created by the runner with
`version INTEGER PRIMARY KEY, name TEXT, checksum TEXT, applied_at TEXT`.

`actions.request_hash` is an intentional superset of the spec §6.1 envelope field list: the spec names the
envelope fields but idempotency (§8.2) needs a stored canonical hash to detect "same idempotency key, different
request" conflicts (Task 6). It is a persistence-layer necessity, not a semantic addition.

- [ ] **Step 4: Implement two numbered migrations**

Create frozen `Migration`, `MigrationReport` and `MigrationStatus` dataclasses. Migration 1 creates
`actions`, `policy_versions`, `action_permissions` and seeds:

```json
{"policy_version_id":"governance-v1","policy_kind":"governance","version":1,
 "payload":{"name":"kernel-default"},"status":"active"}
```

Seed permissions exactly:

```text
ingest_artifact: connector, judge_operator
change_policy: judge_operator
```

This is the tightest seed the spec justifies: §6.2's permission matrix grants raw Artifact write only to
`connector` (live source fetch), and §4.3 makes user-uploaded files Artifacts, so `judge_operator` (the
operator uploading a file) is also allowed. `deterministic_system` is deliberately **not** seeded — the spec
matrix lists its writes as snapshots/settlements/evaluations, not raw artifact ingestion, and deny-by-default
means any future need (e.g. a Package 5 migration re-ingesting archived artifacts) must arrive through an
explicit policy Action rather than a pre-granted role. `ai_extractor`/`ai_analyst` remain denied, exercising
the deny path in Task 5.

Migration 2 creates `source_runs`, `source_artifacts` and `artifact_retrievals`. Create tables in foreign-key
order; Migration 1 likewise creates policy versions before Actions/permissions and seeds only after all three
tables exist. Each migration checksum is SHA-256
of `version:name:fingerprint`. `run_migrations()` must:

1. create/read `schema_migrations` in one engine transaction;
2. reject checksum drift for an applied version;
3. apply pending migrations in ascending, gap-free order;
4. write the migration row in the same transaction as its schema/data changes;
5. return only versions applied in this invocation.

- [ ] **Step 5: Run migration tests and verify schema from a reopened engine**

Run:

```bash
uv run pytest tests/ontology/test_migrations.py -q
uv run python -c "from pathlib import Path; from tempfile import TemporaryDirectory; from nutmeg.ontology.repository.connection import build_ontology_engine; from nutmeg.ontology.repository.migrations import run_migrations, migration_status; d=TemporaryDirectory(); e=build_ontology_engine(Path(d.name)/'ontology.db'); run_migrations(e); print(migration_status(e).current_version)"
```

Expected: tests pass and the smoke command prints `2`.

- [ ] **Step 6: Commit Task 3**

```bash
git add nutmeg/ontology/repository/schema.py nutmeg/ontology/repository/migrations.py tests/ontology/test_migrations.py
git commit -m "feat(ontology): add versioned kernel migrations"
```

### Task 4: Typed Action value objects and canonical request hashing

**Files:**
- Create: `nutmeg/ontology/actions/__init__.py`
- Create: `nutmeg/ontology/actions/models.py`
- Test: `tests/ontology/test_action_models.py`

- [ ] **Step 1: Write failing Action model tests**

```python
from datetime import UTC, datetime

import pytest

from nutmeg.ontology.actions.models import (
    ActionCommand,
    ActionStatus,
    ActorRole,
    ObjectRef,
)


def test_request_hash_is_stable_across_mapping_order() -> None:
    now = datetime(2026, 7, 21, 8, tzinfo=UTC)
    left = ActionCommand.create(
        action_type="ingest_artifact",
        actor_id="source:sporttery",
        actor_role=ActorRole.CONNECTOR,
        idempotency_key="sporttery:payload:1",
        payload={"source": "sporttery", "meta": {"b": 2, "a": 1}},
        requested_at=now,
    )
    right = ActionCommand.create(
        action_type="ingest_artifact",
        actor_id="source:sporttery",
        actor_role=ActorRole.CONNECTOR,
        idempotency_key="sporttery:payload:1",
        payload={"meta": {"a": 1, "b": 2}, "source": "sporttery"},
        requested_at=now,
    )
    assert left.request_hash == right.request_hash
    assert left.action_id != right.action_id


def test_command_rejects_naive_time_and_blank_identity() -> None:
    with pytest.raises(ValueError, match="requested_at must be timezone-aware"):
        ActionCommand.create(
            action_type="ingest_artifact",
            actor_id="source",
            actor_role=ActorRole.CONNECTOR,
            idempotency_key="key",
            payload={},
            requested_at=datetime(2026, 7, 21, 8),
        )
    with pytest.raises(ValueError, match="idempotency_key is required"):
        ActionCommand.create(
            action_type="ingest_artifact",
            actor_id="source",
            actor_role=ActorRole.CONNECTOR,
            idempotency_key=" ",
            payload={},
            requested_at=datetime.now(UTC),
        )
    with pytest.raises(ValueError, match="expected version must be a non-negative integer"):
        ActionCommand.create(
            action_type="ingest_artifact",
            actor_id="source",
            actor_role=ActorRole.CONNECTOR,
            idempotency_key="version-key",
            payload={},
            expected_versions={"source_artifact:sha256:abc": -1},
            requested_at=datetime.now(UTC),
        )


def test_object_ref_and_status_contract() -> None:
    ref = ObjectRef("source_artifact", "sha256:abc")
    assert ref.to_dict() == {"object_type": "source_artifact", "object_id": "sha256:abc"}
    assert ActionStatus.COMMITTED.is_success is True
    assert ActionStatus.FAILED.is_success is False
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `uv run pytest tests/ontology/test_action_models.py -q`
Expected: import failure for `nutmeg.ontology.actions`.

- [ ] **Step 3: Implement immutable Action contracts**

Define these exact enum values:

```python
class ActorRole(StrEnum):
    CONNECTOR = "connector"
    AI_EXTRACTOR = "ai_extractor"
    AI_ANALYST = "ai_analyst"
    JUDGE_OPERATOR = "judge_operator"
    DETERMINISTIC_SYSTEM = "deterministic_system"


class ActionStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    COMMITTED = "committed"
    FAILED = "failed"

    @property
    def is_success(self) -> bool:
        return self is ActionStatus.COMMITTED
```

`ActionCommand` is frozen/slotted, normalizes payload and expected versions to plain copied dicts, rejects
negative/non-integer expected versions, stores UTC ISO timestamps, defaults `policy_version` to
`governance-v1`, and uses `uuid4().hex` with prefix `ACT-` in `.create()`. Its request hash is canonical
JSON over action type, actor identity/role, expected versions, payload and policy version; exclude action id,
requested time and idempotency key. Use UTF-8 SHA-256, `sort_keys=True`, compact separators and
`ensure_ascii=False`.

Define frozen `ObjectRef` and `ActionOutcome`. `ActionOutcome` contains command identity, status,
result refs, error code/detail and committed time, plus `is_success`.

- [ ] **Step 4: Run focused tests and ruff**

Run:

```bash
uv run pytest tests/ontology/test_action_models.py -q
uv run ruff check nutmeg/ontology/actions tests/ontology/test_action_models.py
```

Expected: all pass.

- [ ] **Step 5: Commit Task 4**

```bash
git add nutmeg/ontology/actions tests/ontology/test_action_models.py
git commit -m "feat(ontology): define typed action contracts"
```

### Task 5: Database-backed permission guard

**Files:**
- Create: `nutmeg/ontology/actions/permissions.py`
- Test: `tests/ontology/test_permissions.py`

- [ ] **Step 1: Write failing allow/deny tests**

```python
from pathlib import Path

import pytest

from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.permissions import PermissionGuard
from nutmeg.ontology.errors import PermissionDeniedError
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations


def test_guard_uses_versioned_database_permissions(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with engine.connect() as connection:
        guard = PermissionGuard(connection)
        guard.assert_allowed("governance-v1", "ingest_artifact", ActorRole.CONNECTOR)
        with pytest.raises(PermissionDeniedError, match="ai_analyst.*ingest_artifact"):
            guard.assert_allowed("governance-v1", "ingest_artifact", ActorRole.AI_ANALYST)


def test_unknown_policy_is_denied_not_fallen_back(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with engine.connect() as connection:
        with pytest.raises(PermissionDeniedError, match="unknown-policy"):
            PermissionGuard(connection).assert_allowed(
                "unknown-policy", "ingest_artifact", ActorRole.CONNECTOR
            )
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `uv run pytest tests/ontology/test_permissions.py -q`
Expected: import failure for `PermissionGuard`.

- [ ] **Step 3: Implement deny-by-default permission lookup**

`PermissionGuard` receives a SQLAlchemy `Connection` and joins `action_permissions` to an **active**
`policy_versions` row for the exact `(policy_version_id, action_type, actor_role)` tuple. It never falls back
to another policy or role, and an inactive/unknown policy is denied. Raise
`PermissionDeniedError` with this stable message:

```text
actor role <role> is not allowed to execute <action_type> under <policy_version>
```

Do not cache permission rows in Package 1; later Policy Actions must become visible to the next transaction.

- [ ] **Step 4: Run permission and migration tests**

Run: `uv run pytest tests/ontology/test_permissions.py tests/ontology/test_migrations.py -q`
Expected: all pass.

- [ ] **Step 5: Commit Task 5**

```bash
git add nutmeg/ontology/actions/permissions.py tests/ontology/test_permissions.py
git commit -m "feat(ontology): enforce action permissions"
```

### Task 6: Idempotent Action repository and execution service

**Files:**
- Create: `nutmeg/ontology/repository/actions.py`
- Create: `nutmeg/ontology/actions/service.py`
- Modify: `nutmeg/ontology/repository/unit_of_work.py`
- Test: `tests/ontology/test_action_service.py`

- [ ] **Step 1: Write failing commit/idempotency/rollback tests**

```python
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text

from nutmeg.ontology.actions.models import ActionCommand, ActionStatus, ActorRole, ObjectRef
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.errors import IdempotencyConflictError
from nutmeg.ontology.repository.actions import ActionRepository
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _service(tmp_path: Path) -> tuple[ActionService, object]:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE probe (value TEXT NOT NULL)"))
    return ActionService(lambda: OntologyUnitOfWork(engine)), engine


def _command(payload: dict[str, object] | None = None) -> ActionCommand:
    return ActionCommand.create(
        action_type="ingest_artifact",
        actor_id="source:test",
        actor_role=ActorRole.CONNECTOR,
        idempotency_key="probe:one",
        payload=payload or {"value": "one"},
        requested_at=datetime(2026, 7, 21, 8, tzinfo=UTC),
    )


def test_action_commits_once_and_replays_stored_outcome(tmp_path: Path) -> None:
    service, engine = _service(tmp_path)
    calls = 0

    def handler(uow, command):
        nonlocal calls
        calls += 1
        uow.connection.execute(text("INSERT INTO probe(value) VALUES (:value)"), command.payload)
        return (ObjectRef("probe", str(command.payload["value"])),)

    first = service.execute(_command(), handler)
    second = service.execute(_command(), handler)
    assert first.status is ActionStatus.COMMITTED
    assert second.action_id == first.action_id
    assert calls == 1
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM probe")).scalar_one() == 1


def test_same_key_with_different_request_is_rejected(tmp_path: Path) -> None:
    service, _engine = _service(tmp_path)
    service.execute(_command(), lambda _uow, _command: ())
    with pytest.raises(IdempotencyConflictError, match="probe:one"):
        service.execute(_command({"value": "different"}), lambda _uow, _command: ())


def test_handler_failure_rolls_back_business_rows_but_persists_failed_action(
    tmp_path: Path,
) -> None:
    service, engine = _service(tmp_path)

    def failing(uow, command):
        uow.connection.execute(text("INSERT INTO probe(value) VALUES ('partial')"))
        raise RuntimeError("handler exploded")

    with pytest.raises(RuntimeError, match="handler exploded"):
        service.execute(_command(), failing)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM probe")).scalar_one() == 0
        record = ActionRepository(connection).get_by_idempotency_key("probe:one")
        assert record is not None
        assert record.status is ActionStatus.FAILED


def test_permission_denial_is_audited_without_calling_handler(tmp_path: Path) -> None:
    service, _engine = _service(tmp_path)
    command = ActionCommand.create(
        action_type="ingest_artifact",
        actor_id="model:test",
        actor_role=ActorRole.AI_ANALYST,
        idempotency_key="probe:denied",
        payload={},
        requested_at=datetime.now(UTC),
    )
    outcome = service.execute(command, lambda _uow, _command: pytest.fail("handler called"))
    assert outcome.status is ActionStatus.REJECTED
    assert outcome.error_code == "permission_denied"
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `uv run pytest tests/ontology/test_action_service.py -q`
Expected: import failure for repository/service classes.

- [ ] **Step 3: Implement Action persistence**

Create frozen `ActionRecord` and repository methods:

```text
get_by_idempotency_key(key) -> ActionRecord | None
insert_accepted(command, request_hash)
mark_committed(action_id, result_refs, committed_at)
insert_terminal(command, status, error_code, error_detail)
to_outcome(record) -> ActionOutcome
```

All JSON uses the canonical serializer from Action models. Convert database enum strings back to
`ActorRole`/`ActionStatus`; malformed persisted values raise instead of silently defaulting.

- [ ] **Step 4: Implement ActionService transaction semantics**

Use this exact order:

1. open a read UoW and look up the idempotency key;
2. if found, compare `request_hash`; return its stored outcome or raise `IdempotencyConflictError`;
3. open a write UoW, assert permission, insert `accepted`, invoke handler, mark `committed`, commit;
4. on `PermissionDeniedError`, roll back and insert one `rejected` row in a fresh UoW, then return it;
5. on any other exception, roll back and insert one `failed` row in a fresh UoW, then re-raise the original.

Terminal outcomes are sticky under their idempotency key: because the `failed`/`rejected` row carries the
`idempotency_key`, a later call with the same key and matching `request_hash` takes path 2 and **returns** the
stored terminal outcome instead of re-running (so the first attempt raises, a replay returns). This is the
intended contract — one idempotency key means "this exact request was already terminally attempted", and it
upholds invariant §14.1.1 (a partial/failed run never masquerades as success). A caller that wants to retry a
transient failure must issue a new idempotency key; do not silently re-execute a stored terminal action.

Package 1 deliberately adds concurrent unique-key race recovery under the RED test in Task 12; do not add
untested retry logic in this task.

Expose repositories on an active UoW as `.actions`; instantiate them from the same transaction connection.
The handler signature is:

```python
ActionHandler = Callable[
    [OntologyUnitOfWork, ActionCommand],
    tuple[ObjectRef, ...],
]
```

- [ ] **Step 5: Run tests and verify GREEN**

Run:

```bash
uv run pytest tests/ontology/test_action_service.py tests/ontology/test_permissions.py -q
uv run ruff check nutmeg/ontology tests/ontology/test_action_service.py
```

Expected: all pass.

- [ ] **Step 6: Commit Task 6**

```bash
git add nutmeg/ontology/actions/service.py nutmeg/ontology/repository/actions.py \
  nutmeg/ontology/repository/unit_of_work.py tests/ontology/test_action_service.py
git commit -m "feat(ontology): add idempotent action service"
```

### Task 7: Immutable SHA-256 content-addressed artifact store

**Files:**
- Create: `nutmeg/ontology/artifacts.py`
- Test: `tests/ontology/test_artifacts.py`

- [ ] **Step 1: Write failing CAS tests**

```python
from pathlib import Path

import pytest

from nutmeg.ontology.artifacts import ContentAddressedArtifactStore


def test_put_bytes_uses_hash_path_and_does_not_rewrite(tmp_path: Path) -> None:
    store = ContentAddressedArtifactStore(tmp_path / "artifacts")
    first = store.put_bytes(b"same evidence")
    first_mtime = first.absolute_path.stat().st_mtime_ns
    second = store.put_bytes(b"same evidence")
    assert first.artifact_id == f"sha256:{first.content_hash}"
    assert first.relative_path == Path("sha256") / first.content_hash[:2] / first.content_hash
    assert first.absolute_path.read_bytes() == b"same evidence"
    assert second == first
    assert second.absolute_path.stat().st_mtime_ns == first_mtime
    assert list((tmp_path / "artifacts").rglob("*.tmp")) == []


def test_put_file_rejects_non_file_and_preserves_bytes(tmp_path: Path) -> None:
    store = ContentAddressedArtifactStore(tmp_path / "artifacts")
    source = tmp_path / "source.json"
    source.write_bytes(b'{"ok":true}')
    blob = store.put_file(source)
    assert blob.byte_size == len(b'{"ok":true}')
    assert blob.absolute_path.read_bytes() == source.read_bytes()
    with pytest.raises(FileNotFoundError):
        store.put_file(tmp_path / "missing.json")
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `uv run pytest tests/ontology/test_artifacts.py -q`
Expected: import failure for `ContentAddressedArtifactStore`.

- [ ] **Step 3: Implement atomic CAS publication**

Define frozen `ArtifactBlob` with `artifact_id`, `content_hash`, `byte_size`, `relative_path` and
`absolute_path`. `put_bytes()` must:

1. hash the exact bytes with SHA-256;
2. derive `sha256/<first-two>/<digest>` below the configured root;
3. return immediately without writing if the destination already exists with matching size;
4. create a `NamedTemporaryFile(delete=False, dir=destination.parent, suffix=".tmp")`;
5. write, flush and `os.fsync()` the temporary file;
6. atomically publish without overwriting an existing destination (`os.link(temp, destination)` and handle
   `FileExistsError` as a concurrent identical writer);
7. unlink the temporary file in `finally` and fsync the containing directory;
8. verify the published size and raise `OntologyError` on mismatch.

This deliberately publishes with `os.link` rather than spec §8.3's literal "atomic rename": for a
content-addressed store the destination must never be silently replaced, and `os.rename` onto an existing path
would clobber the blob and refresh its mtime, breaking the `st_mtime_ns` no-rewrite invariant asserted in
Step 1. `os.link` is equally atomic and preserves immutability by failing (`FileExistsError`) when the
identical blob already exists.

`put_file()` resolves the source, requires `is_file()`, and streams it once in 1 MiB chunks into a temporary
file while computing bytes/hash. It then publishes that temporary file through the same link/fsync helper;
it does not hash and reopen a changing source in two passes. It never accepts a directory as evidence.

- [ ] **Step 4: Run tests and ruff**

Run:

```bash
uv run pytest tests/ontology/test_artifacts.py -q
uv run ruff check nutmeg/ontology/artifacts.py tests/ontology/test_artifacts.py
```

Expected: all pass.

- [ ] **Step 5: Commit Task 7**

```bash
git add nutmeg/ontology/artifacts.py tests/ontology/test_artifacts.py
git commit -m "feat(ontology): add content-addressed artifact store"
```

### Task 8: Artifact repository and `IngestArtifact` vertical slice

**Files:**
- Create: `nutmeg/ontology/repository/artifacts.py`
- Create: `nutmeg/ontology/actions/artifact_ingest.py`
- Modify: `nutmeg/ontology/repository/unit_of_work.py`
- Modify: `nutmeg/ontology/actions/__init__.py`
- Test: `tests/ontology/test_artifact_ingest.py`

- [ ] **Step 1: Write failing end-to-end artifact Action tests**

```python
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

from nutmeg.ontology.actions.artifact_ingest import ArtifactIngestRequest, ArtifactIngestService
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.artifacts import ContentAddressedArtifactStore
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.schema import artifact_retrievals, source_artifacts
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _ingest_service(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    actions = ActionService(lambda: OntologyUnitOfWork(engine))
    return ArtifactIngestService(
        action_service=actions,
        artifact_store=ContentAddressedArtifactStore(tmp_path / "artifacts"),
    ), engine


def _request(key: str, role: ActorRole = ActorRole.CONNECTOR) -> ArtifactIngestRequest:
    return ArtifactIngestRequest(
        content=b'{"match":"A-B"}',
        content_type="application/json",
        source_name="sporttery",
        source_type="api",
        actor_id="source:sporttery",
        actor_role=role,
        idempotency_key=key,
        retrieved_at=datetime(2026, 7, 21, 8, tzinfo=UTC),
        requested_url="https://example.test/odds",
    )


def test_ingest_is_idempotent_and_keeps_one_blob_and_retrieval(tmp_path: Path) -> None:
    service, engine = _ingest_service(tmp_path)
    first = service.ingest(_request("sporttery:one"))
    second = service.ingest(_request("sporttery:one"))
    assert first.status is ActionStatus.COMMITTED
    assert second.action_id == first.action_id
    with engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(source_artifacts)).scalar_one() == 1
        assert connection.execute(select(func.count()).select_from(artifact_retrievals)).scalar_one() == 1


def test_same_content_from_two_retrievals_reuses_artifact(tmp_path: Path) -> None:
    service, engine = _ingest_service(tmp_path)
    service.ingest(_request("sporttery:one"))
    service.ingest(_request("sporttery:two"))
    with engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(source_artifacts)).scalar_one() == 1
        assert connection.execute(select(func.count()).select_from(artifact_retrievals)).scalar_one() == 2


def test_unauthorized_ingest_writes_neither_db_nor_blob(tmp_path: Path) -> None:
    service, engine = _ingest_service(tmp_path)
    outcome = service.ingest(_request("model:denied", ActorRole.AI_ANALYST))
    assert outcome.status is ActionStatus.REJECTED
    with engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(source_artifacts)).scalar_one() == 0
    assert not any((tmp_path / "artifacts").rglob("*"))
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `uv run pytest tests/ontology/test_artifact_ingest.py -q`
Expected: import failure for artifact repository/ingest service.

- [ ] **Step 3: Implement ArtifactRepository**

Add `.artifacts` to an active UoW. The repository must:

```text
upsert_blob(blob, content_type, first_recorded_at)
  - insert one SourceArtifact
  - on existing artifact_id, require identical hash/size/path
  - retain the first canonical SourceArtifact content_type; each retrieval stores its reported content type
  - raise OntologyError on metadata disagreement

insert_retrieval(retrieval)
  - insert exact retrieval id and foreign-key artifact id
  - never overwrite a prior retrieval

count_artifacts() / count_retrievals()
```

Use UTC ISO strings and relative CAS storage paths. Persist the request's `content_type` in
`ArtifactRetrieval.reported_content_type`. Do not persist absolute project paths.

- [ ] **Step 4: Implement ArtifactIngestRequest and handler**

`ArtifactIngestRequest` is frozen/slotted and contains exactly the fields used in the test plus nullable
`source_run_id`, `canonical_url` and `published_at`. It validates aware times, non-empty content type/source
identity and non-empty content bytes.

`ArtifactIngestService.ingest()` must:

1. calculate the SHA-256 and byte size in memory without writing the CAS;
2. derive deterministic retrieval id `RET-<first 32 hex chars of sha256(idempotency_key)>`;
3. build an `ActionCommand(action_type="ingest_artifact")` whose payload contains metadata/hash/size but
   never raw content;
4. pass a handler closure to `ActionService.execute()`;
5. inside the already-authorized handler, publish the CAS blob, upsert SourceArtifact, insert retrieval and
   return ObjectRefs in this fixed order: SourceArtifact first, ArtifactRetrieval second.

Because permission is checked before handler invocation, a rejected AI role creates no blob. A database
failure after CAS publication may leave an unreferenced hash blob; this is safe and reusable, and no cleanup
is attempted inside the failed transaction.

- [ ] **Step 5: Run artifact Action tests and all Package 1 tests so far**

Run: `uv run pytest tests/ontology -q`
Expected: all tests pass.

- [ ] **Step 6: Commit Task 8**

```bash
git add nutmeg/ontology/repository/artifacts.py nutmeg/ontology/repository/unit_of_work.py \
  nutmeg/ontology/actions/artifact_ingest.py nutmeg/ontology/actions/__init__.py \
  tests/ontology/test_artifact_ingest.py
git commit -m "feat(ontology): ingest artifacts through typed actions"
```

### Task 9: Kernel initialization, integrity status and wiring

**Files:**
- Create: `nutmeg/ontology/kernel.py`
- Create: `nutmeg/ontology/wiring.py`
- Modify: `nutmeg/ontology/__init__.py`
- Test: `tests/ontology/test_kernel.py`

- [ ] **Step 1: Write failing initialize/status tests**

```python
from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.wiring import build_ontology_kernel


def test_status_does_not_create_an_uninitialized_database(tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    kernel = build_ontology_kernel(settings)
    status = kernel.status()
    assert status.initialized is False
    assert status.schema_version == 0
    assert not settings.ontology_db_path.exists()


def test_initialize_is_idempotent_and_status_is_healthy(tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    kernel = build_ontology_kernel(settings)
    first = kernel.initialize()
    second = kernel.initialize()
    status = kernel.status()
    assert first.applied_versions == (1, 2)
    assert second.applied_versions == ()
    assert status.initialized is True
    assert status.schema_version == 2
    assert status.pending_migrations == ()
    assert status.integrity_check == "ok"
    assert status.action_counts == {}
    assert status.artifact_count == 0
    assert status.retrieval_count == 0
    assert settings.ontology_artifact_dir.is_dir()
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `uv run pytest tests/ontology/test_kernel.py -q`
Expected: import failure for kernel/wiring.

- [ ] **Step 3: Implement kernel facade and status**

Create frozen `OntologyKernelStatus` with fields from the assertions and `.to_dict()` returning only JSON
types. `OntologyKernel.status()` checks path existence before opening an engine. For an initialized DB it
runs `PRAGMA integrity_check`, reads migration status, groups Actions by status and counts artifacts/retrievals.
It is read-only and never applies migrations.

`OntologyKernel.initialize()` calls `paths.ensure_directories()` then `run_migrations(engine)`.

`build_ontology_kernel(settings)` constructs one engine, paths, ActionService, CAS and
ArtifactIngestService. It does not initialize implicitly. Export `OntologyKernel`, `OntologyKernelStatus` and
`build_ontology_kernel` from the package.

- [ ] **Step 4: Run kernel and artifact integration tests**

Run:

```bash
uv run pytest tests/ontology/test_kernel.py tests/ontology/test_artifact_ingest.py -q
uv run ruff check nutmeg/ontology tests/ontology
```

Expected: all pass.

- [ ] **Step 5: Commit Task 9**

```bash
git add nutmeg/ontology/kernel.py nutmeg/ontology/wiring.py nutmeg/ontology/__init__.py \
  tests/ontology/test_kernel.py
git commit -m "feat(ontology): add kernel initialization and status"
```

### Task 10: `nutmeg ontology` CLI and doctor visibility

**Files:**
- Create: `nutmeg/interfaces/cli/ontology.py`
- Modify: `nutmeg/interfaces/cli/__init__.py`
- Modify: `nutmeg/interfaces/cli/core.py`
- Test: `tests/ontology/test_cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI tests**

```python
import json

from typer.testing import CliRunner

from nutmeg.config.settings import get_settings
from nutmeg.interfaces.cli import app

runner = CliRunner()


def test_ontology_status_is_read_only_before_init() -> None:
    result = runner.invoke(app, ["ontology", "status", "--format", "json"])
    payload = json.loads(result.stdout)
    assert result.exit_code == 1
    assert payload["initialized"] is False
    assert not get_settings().ontology_db_path.exists()


def test_ontology_init_then_status_and_doctor() -> None:
    initialized = runner.invoke(app, ["ontology", "init", "--format", "json"])
    status = runner.invoke(app, ["ontology", "status", "--format", "json"])
    doctor = runner.invoke(app, ["doctor", "--format", "json"])
    assert initialized.exit_code == 0
    assert json.loads(initialized.stdout)["applied_versions"] == [1, 2]
    assert status.exit_code == 0
    assert json.loads(status.stdout)["integrity_check"] == "ok"
    assert json.loads(doctor.stdout)["ontology"]["initialized"] is True
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/ontology/test_cli.py -q`
Expected: Typer reports no `ontology` command.

- [ ] **Step 3: Register the ontology sub-app**

In `nutmeg/interfaces/cli/ontology.py` create:

```python
ontology_app = _cli.typer.Typer(help="Ontology Kernel v2 operations")
_cli.app.add_typer(ontology_app, name="ontology")
```

Implement:

- `ontology init --format text|json`: build kernel, apply migrations, print applied/current versions and
  paths; invalid format exits 2;
- `ontology status --format text|json`: never initialize; JSON is `OntologyKernelStatus.to_dict()`; exit 1
  when uninitialized or integrity is not `ok`, otherwise 0.

Import the new registration module at the bottom of CLI `__init__.py`. Expose
`build_ontology_kernel` through the CLI package so monkeypatch conventions remain consistent.

- [ ] **Step 4: Add read-only ontology status to doctor**

`doctor` calls `build_ontology_kernel(settings).status()` without initialization. Add:

```python
"ontology": ontology_status.to_dict(),
```

to the JSON report and one text line with initialized/schema/integrity. Add ontology DB/artifact paths under
the existing `storage` block. The existing doctor exit behavior stays unchanged when ontology is not yet
initialized.

- [ ] **Step 5: Run CLI tests and existing doctor regression**

Run:

```bash
uv run pytest tests/ontology/test_cli.py tests/test_cli.py::test_doctor_reports_ready_workflow_and_harness -q
uv run nutmeg ontology --help
```

Expected: tests pass; help lists `init` and `status`.

- [ ] **Step 6: Commit Task 10**

```bash
git add nutmeg/interfaces/cli/ontology.py nutmeg/interfaces/cli/__init__.py \
  nutmeg/interfaces/cli/core.py tests/ontology/test_cli.py tests/test_cli.py
git commit -m "feat(cli): expose ontology kernel operations"
```

### Task 11: Governance docs, current-plan pointers and pre-commit gate

**Files:**
- Create: `docs/ontology-kernel-operations.md`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `.pre-commit-config.yaml`
- Create: `tests/ontology/test_governance_docs.py`

- [ ] **Step 1: Write failing governance-pointer tests**

```python
from pathlib import Path

PLAN = "docs/superpowers/plans/2026-07-21-ontology-kernel-v2-package-1.md"
RETIRED_PLAN = ".specify/specs/046-jczq-mixed-parlay-report-v0/plan.md"


def test_agent_harnesses_point_to_the_current_package_plan() -> None:
    for path in (Path("AGENTS.md"), Path("CLAUDE.md")):
        text = path.read_text(encoding="utf-8")
        assert PLAN in text
        assert RETIRED_PLAN not in text


def test_operations_doc_names_non_mutating_status_contract() -> None:
    text = Path("docs/ontology-kernel-operations.md").read_text(encoding="utf-8")
    assert "uv run nutmeg ontology init --format json" in text
    assert "uv run nutmeg ontology status --format json" in text
    assert "status never initializes or migrates the database" in text
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/ontology/test_governance_docs.py -q`
Expected: missing operations doc and retired plan pointer assertions fail.

- [ ] **Step 3: Write the Package 1 operations contract**

Document these exact sections in `docs/ontology-kernel-operations.md`:

1. status: Package 1 foundation only, not v2 cutover;
2. filesystem paths and ownership;
3. `ontology init` and idempotency;
4. `ontology status` read-only/exit-code contract, including the exact sentence asserted above;
5. Action roles and deny-by-default permission policy;
6. Artifact CAS immutability and orphan-blob safety;
7. backup sequence: stop writers, copy `ontology.db` plus artifacts, hash, then resume only when authorized;
8. direct SQL/file edits prohibited;
9. later packages and current non-goals.

Add a short README section linking the umbrella spec and operations doc. State explicitly that existing
decision commands remain the current interface until Package 5 cutover and schedules are intentionally
paused during the approved rebuild.

- [ ] **Step 4: Synchronize AGENTS/CLAUDE plan pointers**

The two harness copies are asymmetric today: `AGENTS.md` already carries a `<!-- SPECKIT START -->` /
`<!-- SPECKIT END -->` block whose body points at the retired mixed-parlay plan, while `CLAUDE.md` has
**neither the block nor any current-plan pointer**. Because `test_governance_docs.py` asserts the new plan
path appears in *both* files, a pure in-place replace is not enough for `CLAUDE.md`.

- In `AGENTS.md`: replace only the path inside the existing block so the body reads:

```text
docs/superpowers/plans/2026-07-21-ontology-kernel-v2-package-1.md
```

- In `CLAUDE.md`: add an identical `<!-- SPECKIT START -->` … `<!-- SPECKIT END -->` block carrying the
  same pointer. Place it near the top (before the JCZQ SOP) so it reads as the current-plan header, mirroring
  `AGENTS.md`'s wording. Do not otherwise touch the JCZQ SOP body.

Do not rewrite either JCZQ SOP in Package 1. Verify with
`grep -n 'ontology-kernel-v2-package-1' AGENTS.md CLAUDE.md` that both copies now carry the same plan pointer
and that neither still references `.specify/specs/046-jczq-mixed-parlay-report-v0/plan.md`.

- [ ] **Step 5: Add the ontology pre-commit hook**

Append this local hook without changing the existing decision hook:

```yaml
      - id: pytest-ontology
        name: pytest (ontology kernel subset when touched)
        entry: bash -c 'uv run pytest tests/ontology/ -q'
        language: system
        files: ^(nutmeg/ontology/|nutmeg/interfaces/cli/ontology\.py|tests/ontology/)
        pass_filenames: false
```

- [ ] **Step 6: Run docs and hook checks**

Run:

```bash
uv run pytest tests/ontology/test_governance_docs.py -q
uv run pre-commit run pytest-ontology --all-files
git diff --check
```

Expected: tests and hook pass; no whitespace errors.

- [ ] **Step 7: Commit Task 11**

```bash
git add docs/ontology-kernel-operations.md README.md AGENTS.md CLAUDE.md \
  .pre-commit-config.yaml tests/ontology/test_governance_docs.py
git commit -m "docs(ontology): establish package one operations contract"
```

### Task 12: Restart-safe end-to-end gate and full verification

**Files:**
- Create: `tests/ontology/test_kernel_e2e.py`
- Modify only if failures expose a Package 1 bug: Package 1 modules listed above

- [ ] **Step 1: Write failing restart/idempotency/concurrency e2e tests**

```python
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.artifact_ingest import ArtifactIngestRequest
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.wiring import build_ontology_kernel


def _request(key: str) -> ArtifactIngestRequest:
    return ArtifactIngestRequest(
        content=b"restart-safe-evidence",
        content_type="application/octet-stream",
        source_name="package1-e2e",
        source_type="test",
        actor_id="source:e2e",
        actor_role=ActorRole.CONNECTOR,
        idempotency_key=key,
        retrieved_at=datetime(2026, 7, 21, 9, tzinfo=UTC),
    )


def test_kernel_reopens_with_same_schema_action_and_artifact(tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    first = build_ontology_kernel(settings)
    first.initialize()
    outcome = first.artifact_ingest.ingest(_request("e2e:restart"))
    assert outcome.status is ActionStatus.COMMITTED

    reopened = build_ontology_kernel(settings)
    assert reopened.initialize().applied_versions == ()
    status = reopened.status()
    assert status.integrity_check == "ok"
    assert status.action_counts == {"committed": 1}
    assert status.artifact_count == 1
    assert status.retrieval_count == 1
    digest = outcome.result_refs[0].object_id.removeprefix("sha256:")
    assert (settings.ontology_artifact_dir / "sha256" / digest[:2] / digest).read_bytes() == (
        b"restart-safe-evidence"
    )


def test_concurrent_same_key_commits_one_action_and_retrieval(tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    kernel = build_ontology_kernel(settings)
    kernel.initialize()
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _index: kernel.artifact_ingest.ingest(
            _request("e2e:concurrent")
        ), range(2)))
    assert len({outcome.action_id for outcome in outcomes}) == 1
    assert kernel.status().action_counts == {"committed": 1}
    assert kernel.status().artifact_count == 1
    assert kernel.status().retrieval_count == 1
```

- [ ] **Step 2: Run e2e tests and verify any missing race handling**

Run: `uv run pytest tests/ontology/test_kernel_e2e.py -q -x`
Expected: restart test passes; concurrent test fails with an idempotency-key `IntegrityError` or bounded
SQLite lock error. No artifact corruption, permission or migration failure is acceptable.

- [ ] **Step 3: Complete bounded race recovery if the RED test exposed it**

In `ActionService`, catch only an Actions `idempotency_key` unique race or SQLite `database is locked` while
another same-key writer is committing. After rollback, retry the winner-row lookup at most 5 times with
delays `0.01, 0.02, 0.03, 0.04, 0.05` seconds; compare request hash and replay. If no same-key row appears,
re-raise the original error. Do not catch unrelated integrity/operational violations. In the CAS publisher,
`FileExistsError` returns the hash/size-verified existing blob.

The test must finish with one Action row, one SourceArtifact, one ArtifactRetrieval and the same action id in
both outcomes.

- [ ] **Step 4: Run all Package 1 tests**

Run: `uv run pytest tests/ontology -q`
Expected: all Package 1 tests pass.

- [ ] **Step 5: Run adjacent regressions**

Run:

```bash
uv run pytest tests/test_cli.py::test_doctor_reports_ready_workflow_and_harness \
  tests/test_notification_repository.py tests/test_duckdb_connection.py -q
```

Expected: all pass; the separate state SQLite and DuckDB behavior remains unchanged.

- [ ] **Step 6: Run repository quality gates**

Run:

```bash
uv run ruff check .
uv run python -m compileall -q nutmeg scripts
bash scripts/verify.sh
```

Expected: ruff and compileall exit 0; the full pytest suite passes.

- [ ] **Step 7: Run the project completion verification recipe**

Invoke the project `verify` skill. Package 1 does not change decision outputs, so its decision-am replay,
decision-settle and decision-close checks must remain behaviorally unchanged. Expected: all required
verification stages pass or any external-source unavailability is explicitly reported rather than hidden.

- [ ] **Step 8: Commit the e2e gate and any bounded race fix**

```bash
git add tests/ontology/test_kernel_e2e.py nutmeg/ontology
git commit -m "test(ontology): verify restart-safe kernel foundation"
```

- [ ] **Step 9: Inspect the final branch without merging**

Run:

```bash
git status --short
git log --oneline --decorate main..HEAD
git diff --stat main...HEAD
```

Expected: clean Package 1 worktree, one focused commit per task, and no files outside the plan's declared
scope. Do not merge, restore schedules or delete the freeze archive in this task.

---

## Package 1 Spec Coverage

| Umbrella requirement | Implemented by |
|---|---|
| Separate `.nutmeg-data/ontology/ontology.db` | Tasks 1–3, 9 |
| SQLAlchemy Core typed tables, no generic object payload store | Task 3 |
| Foreign keys, WAL, short Unit of Work | Task 2 |
| Explicit numbered migrations and drift detection | Task 3 |
| Action envelope, status, actor, policy, idempotency and audit | Tasks 4–6 |
| Deny-by-default, database-backed permissions | Tasks 3, 5 |
| Atomic business rows + Action commit/rollback | Task 6 |
| SHA-256 immutable Artifact Store | Task 7 |
| Artifact metadata/retrieval separation | Task 8 |
| AI cannot directly write verified facts | Task 5 permission baseline; Claim state arrives in Package 2 |
| No raw source body in Action JSON | Task 8 |
| Initialization and read-only health/status | Tasks 9–10 |
| One current plan and matching AGENTS/CLAUDE pointer | Task 11 |
| TDD, idempotent restart and concurrency evidence | Tasks 1–12 |
| v1 evidence freeze without destructive deletion | Task 0 |

One envelope field is intentionally **defined but dormant** in Package 1: `expected_versions{}` (spec §8.2
optimistic concurrency) is stored on every Action and validated as non-negative integers in Task 4, but
Package 1 has no mutable/versioned object to lock against — Artifacts are immutable and content-addressed. Its
conflict-rejection path therefore has no handler and no test here; it is first exercised when a mutable
versioned object (Match/Forecast revisions) arrives in Package 2/3. This row is deliberately absent from the
coverage table above so nobody expects optimistic-lock behaviour from the Package 1 kernel.

Package 1 is complete only when Task 12 passes. It does not authorize Package 2 implementation; Package 2
must receive its own focused spec/plan using this kernel's actual verified interfaces.
