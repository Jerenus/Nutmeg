# Ontology Kernel v2 Package 2A Implementation Plan — Identity & Market Facts

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn a Match into a cross-channel object with resolved team/competition/venue identities and typed market snapshots, sourced through the Package 1 kernel's typed Actions, so the decision loop (Package 3) has a real football-fact base.

**Architecture:** Package 2A adds football-domain Objects, Links and identity resolution *on top of* the delivered Package 1 kernel — it does not touch kernel write semantics. Domain tables extend the same `schema.metadata` via new numbered migrations; domain repositories hang off the same `OntologyUnitOfWork`; every domain write is an `ActionService.execute` handler reusing Package 1's permission/idempotency/rollback. Identity resolution is provider-ID-first, then curated alias, with provisional entities and reversible `MergeEntity` — never a silent fuzzy merge. Deterministic market math (`nutmeg.decision.market_data`) is reused unchanged behind typed Actions.

**Tech Stack:** Python 3.13, frozen dataclasses, SQLAlchemy 2 Core, SQLite WAL, Typer, pytest, ruff; Package 1 `nutmeg.ontology` kernel (ActionCommand/ActionService/PermissionGuard/OntologyUnitOfWork/migrations/ContentAddressedArtifactStore); reused `nutmeg.decision.market_data` devig functions; curated alias seeds `nutmeg/data/jczq_*_aliases.json`.

**Design Spec:** `docs/superpowers/specs/2026-07-21-ontology-kernel-v2-package-2-design.md` (§1 scope 2A, §2 decisions, §3 tables 2A, §4 actions, §5 reuse, §6 lineage, §7 acceptance).

**Depends on:** Package 1 (merged, commit `4e57b1e`). This plan uses its verified interfaces:
`ActionCommand.create(...)`, `ActionService(uow_factory).execute(command, handler)`,
handler `= (OntologyUnitOfWork, ActionCommand) -> tuple[ObjectRef, ...]`, `ActorRole`,
`OntologyUnitOfWork.connection/.actions`, `schema.metadata`, `Migration`/`MIGRATIONS`/`run_migrations`,
`ContentAddressedArtifactStore`, `OntologyKernelStatus`.

---

## Scope Boundary

Package 2A includes:

- identity tables: competitions, competition_editions, teams, venues, matches, match_revisions,
  team_appearances, external_identifiers, entity_aliases, entity_merges (migration 3);
- market tables: market_definitions, selection_definitions, market_quotes, market_snapshots,
  market_snapshot_quotes (migration 4);
- provider-ID-first identity resolver with curated-alias fallback (read-only decision);
- domain Actions: `upsert_provisional_entity`, `link_external_identifier`, `propose_identity_link`,
  `merge_entity`, `record_match`, `record_market_quote`, `build_market_snapshot`;
- deterministic market snapshot build reusing `nutmeg.decision.market_data` devig;
- sporttery + one international-odds parser producing real `scheduled_at` and provider external ids;
- market-day ingest orchestration (IngestArtifact → parse → resolve → Match + Quotes + Snapshot),
  a `nutmeg ontology ingest-market-day` CLI, and doctor counts;
- a real-jczq-day replay acceptance gate.

Package 2A explicitly excludes (Package 2B / 3 / 4 / 5):

- Person, RoleAssignment, PersonMatchStatus, LineupEntry (2B);
- Claim, ClaimStatusEvent, Observation, EvidenceBundle (2B / 3);
- Forecast, Factor, Ticket, Ledger, Outcome, Settlement, scoring, RegimeVector (3 / 4);
- historical migration of the 116 Match / 331 Snapshot corpus and old-write-path shutdown (5);
- re-enabling launchd schedules (5 cutover gate).

Do not write to `nutmeg/decision/store.py` (JSONL) or reuse `canonical_match_id`; Package 2A is a fresh
typed path. Package 1 kernel modules stay behaviorally frozen; the only permitted changes are **additive**:
two new `OntologyUnitOfWork` properties (`.identity`, `.market`), appended entries in the `MIGRATIONS`
tuple, new count fields on `OntologyKernelStatus` with a public `.engine` accessor on `OntologyKernel`, and
`build_ontology_kernel` exposing the market-day ingest service. Do not change any existing Package 1
signature, table, or test.

---

## File Structure

### New production modules

- `nutmeg/ontology/identity/__init__.py`: identity public exports.
- `nutmeg/ontology/identity/models.py`: EntityType, ResolutionStatus, TeamKind, MatchSide, MatchStatus, id minting, resolver value objects.
- `nutmeg/ontology/identity/resolver.py`: read-only provider-id → alias resolution.
- `nutmeg/ontology/repository/schema_identity.py`: identity Core tables on the shared `metadata`.
- `nutmeg/ontology/repository/schema_market.py`: market Core tables on the shared `metadata`.
- `nutmeg/ontology/repository/identity.py`: IdentityRepository.
- `nutmeg/ontology/repository/market.py`: MarketRepository.
- `nutmeg/ontology/actions/entity_actions.py`: UpsertProvisionalEntity/LinkExternalIdentifier/ProposeIdentityLink/MergeEntity services.
- `nutmeg/ontology/actions/match_actions.py`: RecordMatch service.
- `nutmeg/ontology/market/__init__.py`: market public exports.
- `nutmeg/ontology/market/models.py`: MarketQuoteRequest, SnapshotBuildRequest, MarketDefinition value objects.
- `nutmeg/ontology/actions/market_actions.py`: RecordMarketQuote/BuildMarketSnapshot services.
- `nutmeg/ontology/ingest/__init__.py`: ingest public exports.
- `nutmeg/ontology/ingest/sporttery.py`: sporttery JSON → parsed matches (real scheduled_at) + quotes.
- `nutmeg/ontology/ingest/intl_odds.py`: bold_odds/500 JSON → parsed quotes aligned by external id/alias.
- `nutmeg/ontology/ingest/market_day.py`: MarketDayIngestService orchestration.
- `nutmeg/interfaces/cli/ontology_ingest.py`: `nutmeg ontology ingest-market-day` subcommand.

### New tests

- `tests/ontology/test_identity_models.py`
- `tests/ontology/test_schema_identity_migration.py`
- `tests/ontology/test_identity_repository.py`
- `tests/ontology/test_resolver.py`
- `tests/ontology/test_entity_actions.py`
- `tests/ontology/test_merge_entity.py`
- `tests/ontology/test_record_match.py`
- `tests/ontology/test_schema_market_migration.py`
- `tests/ontology/test_market_repository.py`
- `tests/ontology/test_market_actions.py`
- `tests/ontology/test_ingest_sporttery.py`
- `tests/ontology/test_ingest_intl_odds.py`
- `tests/ontology/test_market_day_ingest.py`
- `tests/ontology/test_ingest_cli.py`

### Existing files modified

- `nutmeg/ontology/repository/migrations.py`: append migrations 3 (identity + alias seed) and 4 (market + definition seed) to `MIGRATIONS`; import the new schema modules.
- `nutmeg/ontology/repository/unit_of_work.py`: add `.identity` and `.market` repository properties (lazy import + TYPE_CHECKING), mirroring `.actions`/`.artifacts`.
- `nutmeg/ontology/kernel.py`: `build`/status already generic; add identity/market/match counts to `OntologyKernelStatus`.
- `nutmeg/ontology/wiring.py`: expose the market-day ingest service on the kernel.
- `nutmeg/interfaces/cli/__init__.py`: register `ontology_ingest` at the bottom.
- `docs/ontology-kernel-operations.md`: add a Package 2A section (identity/market objects, ingest command).

### Reused, not modified

- `nutmeg/decision/market_data.py`: `devig`, `fair_1x2`, `_had_from_pool`, `_ttg_from_pool`, `_crs_from_pool`, `snapshots_from_sporttery`, `euro_snapshot_from_bold_odds` — imported as deterministic functions with a pinned `method_version`. Do not edit.
- `nutmeg/data/jczq_club_team_aliases.json`, `jczq_national_team_aliases.json`, `jczq_league_aliases.json` — read at migration time to seed `entity_aliases`.

### User-owned files that must not be reverted

The worktree starts with unrelated edits to `SOUL.md` and the three decision launchd plists plus untracked
`media/`, memory and research-script files. Package 2A does not modify or stage them. Execute in a dedicated
worktree (Task 0).

---

### Task 0: Create a clean implementation worktree

**Files:** Worktree only: `.claude/worktrees/ontology-kernel-v2-package2a/`

- [ ] **Step 1: Confirm Package 1 is merged and the tree is clean of in-scope files**

Run:

```bash
git -C /Users/jz71/Projects/Nutmeg log --oneline -1
git -C /Users/jz71/Projects/Nutmeg status --short
```

Expected: HEAD is the Package 1 merge (or later docs); dirty entries are limited to the user-owned
`SOUL.md` / three plists / untracked `media/` `memory/` `scripts/`. If any other path appears, stop and ask.

- [ ] **Step 2: Do not touch the paused decision schedules or the freeze archive**

The three `com.nutmeg.decision.*` schedules stay paused and the `*-ontology-v2-freeze` archive stays
read-only (Package 5 gate). Do not re-enable or delete them in this plan.

- [ ] **Step 3: Create the worktree**

```bash
cd /Users/jz71/Projects/Nutmeg
git worktree add .claude/worktrees/ontology-kernel-v2-package2a -b feature/ontology-kernel-v2-package2a
git -C .claude/worktrees/ontology-kernel-v2-package2a status --short
```

Expected: a clean worktree on `feature/ontology-kernel-v2-package2a`. All subsequent tasks run there. Run
`uv sync --extra dev` once inside it so `ruff`/`pytest` resolve.

---

### Task 1: Identity value objects

**Files:**
- Create: `nutmeg/ontology/identity/__init__.py`
- Create: `nutmeg/ontology/identity/models.py`
- Test: `tests/ontology/test_identity_models.py`

- [ ] **Step 1: Write the failing test**

```python
from nutmeg.ontology.identity.models import (
    EntityType,
    MatchSide,
    MatchStatus,
    ResolutionStatus,
    TeamKind,
    mint_id,
)


def test_enum_values_are_stable_snake_case() -> None:
    assert EntityType.TEAM.value == "team"
    assert EntityType.MATCH.value == "match"
    assert ResolutionStatus.PROVISIONAL.value == "provisional"
    assert TeamKind.NATIONAL.value == "national"
    assert MatchSide.NEUTRAL_DESIGNATED_HOME.value == "neutral_designated_home"
    assert MatchStatus.SCHEDULED.value == "scheduled"


def test_mint_id_is_prefixed_and_unique() -> None:
    first = mint_id(EntityType.TEAM)
    second = mint_id(EntityType.TEAM)
    assert first.startswith("team-")
    assert first != second
    assert mint_id(EntityType.MATCH).startswith("match-")
```

- [ ] **Step 2: Run the test and verify RED**

Run: `uv run pytest tests/ontology/test_identity_models.py -q`
Expected: `ModuleNotFoundError: No module named 'nutmeg.ontology.identity'`.

- [ ] **Step 3: Implement the value objects**

In `models.py` define `StrEnum`s with exactly these members/values:

```text
EntityType: COMPETITION=competition, COMPETITION_EDITION=competition_edition, TEAM=team,
            VENUE=venue, PERSON=person, MATCH=match
ResolutionStatus: PROVISIONAL=provisional, RESOLVED=resolved, MERGED=merged, RETIRED=retired
TeamKind: CLUB=club, NATIONAL=national, SELECTION=selection
MatchSide: HOME=home, AWAY=away, NEUTRAL_DESIGNATED_HOME=neutral_designated_home,
           NEUTRAL_DESIGNATED_AWAY=neutral_designated_away
MatchStatus: SCHEDULED=scheduled, LIVE=live, FINISHED=finished, POSTPONED=postponed, CANCELLED=cancelled
```

`mint_id(entity_type: EntityType) -> str` returns `f"{entity_type.value}-{uuid4().hex}"`. Export all enums,
`mint_id`, and (empty for now) from `identity/__init__.py`.

- [ ] **Step 4: Run tests and ruff**

Run:
```bash
uv run pytest tests/ontology/test_identity_models.py -q
uv run ruff check nutmeg/ontology/identity tests/ontology/test_identity_models.py
```
Expected: pass; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/ontology/identity tests/ontology/test_identity_models.py
git commit -m "feat(ontology): add identity value objects"
```

---

### Task 2: Identity schema and migration 3 (with curated alias seed)

**Files:**
- Create: `nutmeg/ontology/repository/schema_identity.py`
- Modify: `nutmeg/ontology/repository/migrations.py`
- Test: `tests/ontology/test_schema_identity_migration.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from sqlalchemy import func, inspect, select

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import migration_status, run_migrations
from nutmeg.ontology.repository.schema_identity import entity_aliases, teams


def test_identity_migration_creates_tables_and_seeds_aliases(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    assert migration_status(engine).current_version >= 3
    names = set(inspect(engine).get_table_names())
    assert {"competitions", "competition_editions", "teams", "venues", "matches",
            "match_revisions", "team_appearances", "external_identifiers", "entity_aliases",
            "entity_merges"} <= names
    with engine.connect() as connection:
        alias_count = connection.execute(select(func.count()).select_from(entity_aliases)).scalar_one()
        assert alias_count > 0
        # aliases seeded against team entities only in this migration
        assert connection.execute(
            select(func.count()).select_from(entity_aliases).where(
                entity_aliases.c.entity_type == "team"
            )
        ).scalar_one() > 0
    # tables table objects are usable for later repositories
    assert teams.c.resolution_status is not None


def test_identity_migration_is_idempotent(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    second = run_migrations(engine)
    assert second.applied_versions == ()
```

- [ ] **Step 2: Run the test and verify RED**

Run: `uv run pytest tests/ontology/test_schema_identity_migration.py -q`
Expected: import error for `schema_identity`.

- [ ] **Step 3: Declare identity tables on the shared MetaData**

In `schema_identity.py`, `from nutmeg.ontology.repository.schema import metadata` and declare tables
(all TEXT unless noted, ISO-8601 UTC timestamps):

```text
competitions:          competition_id PK, name NOT NULL, country?, kind NOT NULL
competition_editions:  competition_edition_id PK, competition_id NOT NULL FK competitions RESTRICT,
                       name NOT NULL, country?, format?, season_label?, stage?,
                       valid_from?, valid_to?
teams:                 team_id PK, team_kind NOT NULL, canonical_name NOT NULL, country?,
                       resolution_status NOT NULL, created_at NOT NULL
venues:                venue_id PK, canonical_name NOT NULL, country?, latitude REAL?, longitude REAL?,
                       timezone?, resolution_status NOT NULL, created_at NOT NULL
matches:               match_id PK, current_revision_id?  (nullable until first revision recorded)
match_revisions:       match_revision_id PK, match_id NOT NULL FK matches RESTRICT, version INT NOT NULL,
                       competition_edition_id? FK competition_editions RESTRICT,
                       scheduled_at?, schedule_status NOT NULL, venue_id? FK venues RESTRICT,
                       status NOT NULL, round_label?, recorded_at NOT NULL, supersedes_revision_id?,
                       UNIQUE(match_id, version)
team_appearances:      team_appearance_id PK, match_id NOT NULL FK matches RESTRICT,
                       team_id NOT NULL FK teams RESTRICT, side NOT NULL,
                       UNIQUE(match_id, side)
external_identifiers:  entity_id NOT NULL, entity_type NOT NULL, provider NOT NULL, external_id NOT NULL,
                       valid_from?, valid_to?, PRIMARY KEY(provider, entity_type, external_id)
entity_aliases:        entity_id NOT NULL, entity_type NOT NULL, normalized_alias NOT NULL, language?,
                       provider?, PRIMARY KEY(entity_type, normalized_alias, entity_id)
entity_merges:         merge_id PK, from_id NOT NULL, into_id NOT NULL, entity_type NOT NULL,
                       reason NOT NULL, evidence_retrieval_ids_json NOT NULL DEFAULT '[]',
                       actor_id NOT NULL, at NOT NULL, reversible INTEGER NOT NULL DEFAULT 1
```

Index `external_identifiers(entity_type, entity_id)` and `team_appearances(match_id)`. The
`external_identifiers` PK `(provider, entity_type, external_id)` is what makes provider-id resolution a
unique lookup and blocks two entities claiming the same provider id.

- [ ] **Step 4: Add migration 3 with the alias seed**

In `migrations.py`, import `schema_identity`, add a helper that loads the three alias JSON files and a
`_apply_football_identity(connection)` that creates the 10 identity tables in FK order (competitions →
competition_editions → teams → venues → matches → match_revisions → team_appearances →
external_identifiers → entity_aliases → entity_merges), then seeds `entity_aliases` for team entities:

```python
def _load_alias_seed() -> list[tuple[str, str]]:
    # returns (normalized_alias, canonical_name) for club + national team aliases
    root = Path(__file__).resolve().parents[2] / 'data'
    pairs: list[tuple[str, str]] = []
    for name in ('jczq_club_team_aliases.json', 'jczq_national_team_aliases.json'):
        raw = json.loads((root / name).read_text(encoding='utf-8'))
        for canonical, aliases in raw.items():
            for alias in aliases:
                pairs.append((alias.strip().casefold(), canonical))
    return pairs
```

For each distinct canonical team name in the seed, mint one provisional `teams` row (via
`identity.models.mint_id(EntityType.TEAM)`, `resolution_status='provisional'`, `team_kind` = `club` for the
club file, `national` for the national file) and one `entity_aliases` row per alias plus one for the
canonical name itself, all with `entity_type='team'`. Append to `MIGRATIONS`:

```python
Migration(version=3, name='football_identity',
          fingerprint='competitions..entity_merges+alias_seed',
          apply=_apply_football_identity),
```

Migration 3's checksum covers only `version:name:fingerprint`; changing the seed logic without bumping the
fingerprint is a drift bug the runner already rejects.

- [ ] **Step 5: Run tests and reopen check**

Run:
```bash
uv run pytest tests/ontology/test_schema_identity_migration.py tests/ontology/test_migrations.py -q
uv run ruff check nutmeg/ontology/repository/schema_identity.py nutmeg/ontology/repository/migrations.py
```
Expected: pass; Package 1's migration tests still pass (they assert `>= (1, 2)` semantics via
`current_version`, unaffected by new versions — verify the Package 1 test still passes and, if it hard-codes
`applied_versions == (1, 2)`, that assertion runs against its own two-migration tuple, not `MIGRATIONS`; do
not weaken it).

- [ ] **Step 6: Commit**

```bash
git add nutmeg/ontology/repository/schema_identity.py nutmeg/ontology/repository/migrations.py \
  tests/ontology/test_schema_identity_migration.py
git commit -m "feat(ontology): add identity schema and alias seed"
```

---

### Task 3: IdentityRepository

**Files:**
- Create: `nutmeg/ontology/repository/identity.py`
- Modify: `nutmeg/ontology/repository/unit_of_work.py` (add `.identity`)
- Test: `tests/ontology/test_identity_repository.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.identity.models import EntityType, ResolutionStatus, TeamKind
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.identity import IdentityRepository, TeamRow
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _repo(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    return engine


def test_insert_team_and_lookup_by_external_id(tmp_path: Path) -> None:
    engine = _repo(tmp_path)
    with OntologyUnitOfWork(engine) as uow:
        repo = uow.identity
        repo.insert_team(TeamRow(
            team_id="team-x", team_kind=TeamKind.CLUB, canonical_name="Hammarby",
            country="SE", resolution_status=ResolutionStatus.PROVISIONAL,
            created_at=datetime(2026, 7, 21, tzinfo=UTC).isoformat(),
        ))
        repo.link_external_identifier(
            entity_id="team-x", entity_type=EntityType.TEAM,
            provider="api-football", external_id="377",
        )
    with OntologyUnitOfWork(engine) as uow:
        found = uow.identity.entity_by_external_id(
            EntityType.TEAM, provider="api-football", external_id="377"
        )
        assert found == "team-x"
        assert uow.identity.entity_by_external_id(
            EntityType.TEAM, provider="api-football", external_id="999"
        ) is None


def test_alias_lookup_is_case_folded(tmp_path: Path) -> None:
    engine = _repo(tmp_path)
    with OntologyUnitOfWork(engine) as uow:
        # a seeded alias resolves; casing is normalized by the repository
        hit = uow.identity.entity_by_alias(EntityType.TEAM, "hammarby")
        miss = uow.identity.entity_by_alias(EntityType.TEAM, "no-such-team-xyz")
    assert miss is None
    # seed contains Hammarby under the club alias file
    assert hit is not None
```

- [ ] **Step 2: Run the test and verify RED**

Run: `uv run pytest tests/ontology/test_identity_repository.py -q`
Expected: import error for `IdentityRepository`.

- [ ] **Step 3: Implement IdentityRepository and add `.identity` to the UoW**

`identity.py` defines frozen row dataclasses `TeamRow`, `VenueRow`, `CompetitionRow`,
`CompetitionEditionRow` (fields mirror the schema columns) and `IdentityRepository(connection)` with:

```text
insert_team(row) / insert_venue(row) / insert_competition(row) / insert_competition_edition(row)
link_external_identifier(entity_id, entity_type, provider, external_id, valid_from=None)
    -> INSERT into external_identifiers; on duplicate (provider, entity_type, external_id) referencing the
       SAME entity_id it is a no-op, referencing a DIFFERENT entity_id it raises OntologyError
add_alias(entity_id, entity_type, normalized_alias, provider=None, language=None)  -> casefolds the alias
entity_by_external_id(entity_type, provider, external_id) -> str | None
entity_by_alias(entity_type, normalized_alias) -> str | None   # casefolds the query, returns any match
mark_resolution_status(entity_id, entity_type, status)          # for merge/retire in Task 6
record_merge(merge_row) / redirect(entity_id, entity_type) -> str  # Task 6 uses these
```

`entity_by_alias` casefolds the query and matches `entity_aliases.normalized_alias`. Add to
`OntologyUnitOfWork` an `.identity` property mirroring `.actions` (lazy import, TYPE_CHECKING annotation).

- [ ] **Step 4: Run tests and ruff**

Run:
```bash
uv run pytest tests/ontology/test_identity_repository.py -q
uv run ruff check nutmeg/ontology/repository/identity.py nutmeg/ontology/repository/unit_of_work.py
```
Expected: pass; clean.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/ontology/repository/identity.py nutmeg/ontology/repository/unit_of_work.py \
  tests/ontology/test_identity_repository.py
git commit -m "feat(ontology): add identity repository"
```

---

### Task 4: Read-only identity resolver

**Files:**
- Create: `nutmeg/ontology/identity/resolver.py`
- Modify: `nutmeg/ontology/identity/__init__.py`
- Test: `tests/ontology/test_resolver.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.identity.models import EntityType, ResolutionStatus, TeamKind
from nutmeg.ontology.identity.resolver import ResolutionMethod, resolve_entity
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.identity import IdentityRepository, TeamRow
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _seed_team(engine) -> None:
    with OntologyUnitOfWork(engine) as uow:
        uow.identity.insert_team(TeamRow(
            team_id="team-known", team_kind=TeamKind.CLUB, canonical_name="Known FC",
            country="SE", resolution_status=ResolutionStatus.RESOLVED,
            created_at=datetime(2026, 7, 21, tzinfo=UTC).isoformat(),
        ))
        uow.identity.link_external_identifier(
            entity_id="team-known", entity_type=EntityType.TEAM,
            provider="sporttery", external_id="SWE-KNOWN",
        )
        uow.identity.add_alias("team-known", EntityType.TEAM, "known fc")


def test_provider_id_wins_over_alias(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    _seed_team(engine)
    with OntologyUnitOfWork(engine) as uow:
        outcome = resolve_entity(
            uow.identity, EntityType.TEAM,
            provider="sporttery", external_id="SWE-KNOWN", aliases=("known fc",),
        )
    assert outcome.entity_id == "team-known"
    assert outcome.method is ResolutionMethod.PROVIDER_ID


def test_alias_used_when_no_provider_id(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    _seed_team(engine)
    with OntologyUnitOfWork(engine) as uow:
        outcome = resolve_entity(uow.identity, EntityType.TEAM, aliases=("Known FC",))
    assert outcome.entity_id == "team-known"
    assert outcome.method is ResolutionMethod.ALIAS


def test_unresolved_returns_none_never_guesses(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        outcome = resolve_entity(
            uow.identity, EntityType.TEAM,
            provider="sporttery", external_id="UNKNOWN", aliases=("mystery utd",),
        )
    assert outcome.entity_id is None
    assert outcome.method is None
```

- [ ] **Step 2: Run the test and verify RED**

Run: `uv run pytest tests/ontology/test_resolver.py -q`
Expected: import error for `resolver`.

- [ ] **Step 3: Implement the read-only resolver**

`resolver.py` defines `ResolutionMethod(StrEnum)` = `PROVIDER_ID='provider_id'`, `ALIAS='alias'`, and a
frozen `Resolution(entity_id: str | None, method: ResolutionMethod | None)`. `resolve_entity(repo,
entity_type, *, provider=None, external_id=None, aliases=())`:

1. if `provider` and `external_id` and `repo.entity_by_external_id(...)` returns an id → `Resolution(id,
   PROVIDER_ID)`;
2. else for each alias (in order) if `repo.entity_by_alias(entity_type, alias)` returns an id →
   `Resolution(id, ALIAS)`;
3. else `Resolution(None, None)`.

The resolver never writes and never fabricates an id. Export `resolve_entity`, `Resolution`,
`ResolutionMethod` from `identity/__init__.py`.

- [ ] **Step 4: Run tests and ruff**

Run:
```bash
uv run pytest tests/ontology/test_resolver.py -q
uv run ruff check nutmeg/ontology/identity
```
Expected: pass; clean.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/ontology/identity/resolver.py nutmeg/ontology/identity/__init__.py \
  tests/ontology/test_resolver.py
git commit -m "feat(ontology): add provider-id-first identity resolver"
```

---

### Task 5: Entity Actions and permission seed

**Files:**
- Create: `nutmeg/ontology/actions/entity_actions.py`
- Modify: `nutmeg/ontology/repository/migrations.py` (seed new action permissions in migration 3)
- Test: `tests/ontology/test_entity_actions.py`

> Note: fold the permission seed into migration 3's `apply` (it already runs before any Package 2 data). If
> Task 2 is already committed, extend `_apply_football_identity` to also insert the `action_permissions`
> rows below and bump migration 3's `fingerprint` (drift is expected and correct here since 3 is not yet in
> production). Re-run Task 2's test after editing.

- [ ] **Step 1: Write the failing test**

```python
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.actions.entity_actions import EntityActions, UpsertTeamRequest
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.identity.models import TeamKind
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _actions(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    return EntityActions(ActionService(lambda: OntologyUnitOfWork(engine))), engine


def _req(key: str, role: ActorRole = ActorRole.CONNECTOR) -> UpsertTeamRequest:
    return UpsertTeamRequest(
        canonical_name="Djurgarden", team_kind=TeamKind.CLUB, country="SE",
        provider="sporttery", external_id="SWE-DIF",
        actor_id="source:sporttery", actor_role=role, idempotency_key=key,
        requested_at=datetime(2026, 7, 21, 8, tzinfo=UTC),
    )


def test_upsert_creates_provisional_then_resolves_same_entity(tmp_path: Path) -> None:
    actions, engine = _actions(tmp_path)
    first = actions.upsert_team(_req("dif:1"))
    second = actions.upsert_team(_req("dif:2"))   # same provider id, different key
    assert first.status is ActionStatus.COMMITTED
    team_id = first.result_refs[0].object_id
    assert second.result_refs[0].object_id == team_id   # provider id resolved to the same team


def test_connector_cannot_merge_but_can_upsert(tmp_path: Path) -> None:
    actions, _engine = _actions(tmp_path)
    outcome = actions.upsert_team(_req("dif:analyst", ActorRole.AI_ANALYST))
    assert outcome.status is ActionStatus.REJECTED
    assert outcome.error_code == "permission_denied"
```

- [ ] **Step 2: Run the test and verify RED**

Run: `uv run pytest tests/ontology/test_entity_actions.py -q`
Expected: import error for `entity_actions`.

- [ ] **Step 3: Seed permissions and implement the entity actions**

Extend migration 3 `apply` to insert into `action_permissions` (policy `governance-v1`) exactly:

```text
upsert_provisional_entity: connector, deterministic_system
link_external_identifier:  connector, deterministic_system
propose_identity_link:     connector, ai_extractor
merge_entity:              judge_operator
record_match:              connector, deterministic_system
```

`entity_actions.py` defines frozen `UpsertTeamRequest` (validated aware time, non-empty name/source) and
`EntityActions(action_service)`. `upsert_team(request)`:

1. build an `ActionCommand(action_type="upsert_provisional_entity", ...)` whose payload has the resolve keys
   (provider/external_id/canonical_name/team_kind/country) — never mutating identity outside the handler;
2. the handler: `resolve_entity(uow.identity, EntityType.TEAM, provider=..., external_id=...,
   aliases=(canonical_name.casefold(),))`; if resolved, return `(ObjectRef("team", entity_id),)` without
   writing; else mint a provisional team (`mint_id`, `resolution_status='provisional'`), insert it,
   `link_external_identifier` (if provider id present), `add_alias(canonical_name)`, and return
   `(ObjectRef("team", entity_id),)`.

Because permission is checked before the handler, an `ai_analyst` request is rejected without touching the
DB (Package 1 behavior). Idempotency: two calls with the same provider id but different idempotency keys both
commit but resolve to the same team (the second finds it via the resolver). Also implement analogous
`link_external_identifier(...)` and `propose_identity_link(...)` methods (propose writes nothing but records
an `entity_merges`-adjacent proposal row — for 2A, model a proposal as a `propose_identity_link` Action whose
payload is the candidate and whose committed result ref is the provisional entity; a real review queue is
2B). Keep 2A's proposal minimal: it records the Action (audit) and returns the provisional entity ref.

- [ ] **Step 4: Run tests and ruff**

Run:
```bash
uv run pytest tests/ontology/test_entity_actions.py tests/ontology/test_schema_identity_migration.py -q
uv run ruff check nutmeg/ontology/actions/entity_actions.py nutmeg/ontology/repository/migrations.py
```
Expected: pass; clean.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/ontology/actions/entity_actions.py nutmeg/ontology/repository/migrations.py \
  tests/ontology/test_entity_actions.py
git commit -m "feat(ontology): add provisional-entity actions"
```

---

### Task 6: Reversible MergeEntity

**Files:**
- Create/extend: `nutmeg/ontology/actions/entity_actions.py`
- Test: `tests/ontology/test_merge_entity.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.actions.entity_actions import EntityActions, MergeEntityRequest, UpsertTeamRequest
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.identity.models import EntityType, ResolutionStatus, TeamKind
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _two_teams(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    actions = EntityActions(ActionService(lambda: OntologyUnitOfWork(engine)))
    a = actions.upsert_team(UpsertTeamRequest(
        canonical_name="AIK", team_kind=TeamKind.CLUB, country="SE",
        provider="sporttery", external_id="SWE-AIK-A",
        actor_id="source:sporttery", actor_role=ActorRole.CONNECTOR, idempotency_key="aik:a",
        requested_at=datetime(2026, 7, 21, 8, tzinfo=UTC),
    )).result_refs[0].object_id
    b = actions.upsert_team(UpsertTeamRequest(
        canonical_name="AIK Stockholm", team_kind=TeamKind.CLUB, country="SE",
        provider="api-football", external_id="INT-AIK-B",
        actor_id="source:api", actor_role=ActorRole.CONNECTOR, idempotency_key="aik:b",
        requested_at=datetime(2026, 7, 21, 8, tzinfo=UTC),
    )).result_refs[0].object_id
    return actions, engine, a, b


def test_merge_redirects_and_is_reversible(tmp_path: Path) -> None:
    actions, engine, survivor, duplicate = _two_teams(tmp_path)
    outcome = actions.merge_entity(MergeEntityRequest(
        entity_type=EntityType.TEAM, from_id=duplicate, into_id=survivor,
        reason="same club two providers", actor_id="op:owner", actor_role=ActorRole.JUDGE_OPERATOR,
        idempotency_key="merge:1", requested_at=datetime(2026, 7, 21, 9, tzinfo=UTC),
    ))
    assert outcome.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        assert uow.identity.redirect(duplicate, EntityType.TEAM) == survivor
        assert uow.identity.redirect(survivor, EntityType.TEAM) == survivor
        row = uow.identity.get_team(duplicate)
        assert row.resolution_status is ResolutionStatus.MERGED
        # old provider id of the duplicate now resolves to the survivor via redirect
        merged_from = uow.identity.entity_by_external_id(
            EntityType.TEAM, provider="api-football", external_id="INT-AIK-B"
        )
        assert uow.identity.redirect(merged_from, EntityType.TEAM) == survivor


def test_connector_cannot_merge(tmp_path: Path) -> None:
    actions, _engine, survivor, duplicate = _two_teams(tmp_path)
    outcome = actions.merge_entity(MergeEntityRequest(
        entity_type=EntityType.TEAM, from_id=duplicate, into_id=survivor, reason="x",
        actor_id="source:sporttery", actor_role=ActorRole.CONNECTOR,
        idempotency_key="merge:denied", requested_at=datetime(2026, 7, 21, 9, tzinfo=UTC),
    ))
    assert outcome.status is ActionStatus.REJECTED
```

- [ ] **Step 2: Run the test and verify RED**

Run: `uv run pytest tests/ontology/test_merge_entity.py -q`
Expected: import error for `MergeEntityRequest`.

- [ ] **Step 3: Implement merge with redirect**

Add to `IdentityRepository`: `record_merge(from_id, into_id, entity_type, reason, evidence_retrieval_ids,
actor_id, at, reversible=True)` inserts an `entity_merges` row and sets the from-entity's
`resolution_status='merged'`. `redirect(entity_id, entity_type)` follows `entity_merges.from_id -> into_id`
transitively (guard against cycles with a visited set) and returns the survivor id (or the input if no merge
row). `get_team(team_id) -> TeamRow`.

`EntityActions.merge_entity(request)` builds `ActionCommand(action_type="merge_entity", ...)` and a handler
that calls `record_merge(...)` and returns `(ObjectRef("team", into_id),)`. Permission (`judge_operator`
only) is enforced by the seed from Task 5, so a connector is rejected. Merge does not delete rows; the
duplicate stays as a `merged` tombstone resolvable through `redirect`.

- [ ] **Step 4: Run tests and ruff**

Run:
```bash
uv run pytest tests/ontology/test_merge_entity.py tests/ontology/test_entity_actions.py -q
uv run ruff check nutmeg/ontology/actions/entity_actions.py nutmeg/ontology/repository/identity.py
```
Expected: pass; clean.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/ontology/actions/entity_actions.py nutmeg/ontology/repository/identity.py \
  tests/ontology/test_merge_entity.py
git commit -m "feat(ontology): add reversible entity merge"
```

---

### Task 7: RecordMatch (real scheduled_at + two appearances)

**Files:**
- Create: `nutmeg/ontology/actions/match_actions.py`
- Test: `tests/ontology/test_record_match.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.actions.match_actions import MatchActions, RecordMatchRequest, MatchSideRef
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.identity.models import EntityType, MatchSide, MatchStatus
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _actions(tmp_path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    return MatchActions(ActionService(lambda: OntologyUnitOfWork(engine))), engine


def _req(key: str, scheduled_at: str | None) -> RecordMatchRequest:
    return RecordMatchRequest(
        provider="sporttery", external_id="2026071900123",
        scheduled_at=scheduled_at, schedule_status="scheduled" if scheduled_at else "unknown",
        status=MatchStatus.SCHEDULED,
        home=MatchSideRef(team_id="team-home", side=MatchSide.HOME),
        away=MatchSideRef(team_id="team-away", side=MatchSide.AWAY),
        actor_id="source:sporttery", actor_role=ActorRole.CONNECTOR,
        idempotency_key=key, requested_at=datetime(2026, 7, 19, 8, tzinfo=UTC),
    )


def test_record_match_stores_real_schedule_and_two_appearances(tmp_path: Path) -> None:
    actions, engine = _actions(tmp_path)
    outcome = actions.record_match(_req("m:1", "2026-07-19T19:00:00+02:00"))
    assert outcome.status is ActionStatus.COMMITTED
    match_id = outcome.result_refs[0].object_id
    with OntologyUnitOfWork(engine) as uow:
        rev = uow.identity.current_match_revision(match_id)
        assert rev.scheduled_at == "2026-07-19T19:00:00+02:00"
        assert rev.schedule_status == "scheduled"
        sides = uow.identity.appearance_sides(match_id)
        assert sides == {"home": "team-home", "away": "team-away"}
    # same provider id -> same match, no second match row
    again = actions.record_match(_req("m:2", "2026-07-19T19:00:00+02:00"))
    assert again.result_refs[0].object_id == match_id


def test_unknown_schedule_is_explicit_never_ingestion_time(tmp_path: Path) -> None:
    actions, engine = _actions(tmp_path)
    outcome = actions.record_match(_req("m:unknown", None))
    match_id = outcome.result_refs[0].object_id
    with OntologyUnitOfWork(engine) as uow:
        rev = uow.identity.current_match_revision(match_id)
        assert rev.scheduled_at is None
        assert rev.schedule_status == "unknown"
```

- [ ] **Step 2: Run the test and verify RED**

Run: `uv run pytest tests/ontology/test_record_match.py -q`
Expected: import error for `match_actions`.

- [ ] **Step 3: Implement RecordMatch**

Add to `IdentityRepository`: `insert_match(match_id)`, `insert_match_revision(row)` (sets version 1 and
updates `matches.current_revision_id`), `insert_team_appearance(row)`, `current_match_revision(match_id) ->
MatchRevisionRow`, `appearance_sides(match_id) -> dict[str, str]` (side.value -> team_id).

`match_actions.py` defines frozen `MatchSideRef(team_id, side)` and `RecordMatchRequest` (validated aware
`requested_at`; `scheduled_at` is a string or None; if None then `schedule_status='unknown'`; exactly one
home and one away). `MatchActions.record_match(request)`:

1. resolve the match by provider id: if `entity_by_external_id(EntityType.MATCH, provider, external_id)`
   returns an id, return `(ObjectRef("match", id),)` without writing;
2. else the handler mints `match_id` (`mint_id(EntityType.MATCH)`), inserts `matches`, one
   `match_revisions` (version 1, real `scheduled_at`/`schedule_status`, `recorded_at=command.requested_at`),
   two `team_appearances` (home + away), and `link_external_identifier(match_id, MATCH, provider,
   external_id)`; return `(ObjectRef("match", match_id),)`.

`scheduled_at` is stored verbatim as provided by the caller (the sporttery parser in Task 11 computes the
real value); the Action never substitutes ingestion time. `record_match` is `connector`/`deterministic_system`
only.

- [ ] **Step 4: Run tests and ruff**

Run:
```bash
uv run pytest tests/ontology/test_record_match.py -q
uv run ruff check nutmeg/ontology/actions/match_actions.py nutmeg/ontology/repository/identity.py
```
Expected: pass; clean.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/ontology/actions/match_actions.py nutmeg/ontology/repository/identity.py \
  tests/ontology/test_record_match.py
git commit -m "feat(ontology): record matches with real schedule and appearances"
```

---

### Task 8: Market schema and migration 4 (with definition seed)

**Files:**
- Create: `nutmeg/ontology/repository/schema_market.py`
- Modify: `nutmeg/ontology/repository/migrations.py`
- Test: `tests/ontology/test_schema_market_migration.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from sqlalchemy import inspect, select

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import migration_status, run_migrations
from nutmeg.ontology.repository.schema_market import market_definitions


def test_market_migration_creates_tables_and_seeds_definitions(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    assert migration_status(engine).current_version >= 4
    names = set(inspect(engine).get_table_names())
    assert {"market_definitions", "selection_definitions", "market_quotes", "market_snapshots",
            "market_snapshot_quotes"} <= names
    with engine.connect() as connection:
        kinds = set(
            connection.execute(select(market_definitions.c.market_kind)).scalars().all()
        )
    assert {"had", "hhad", "ttg", "crs"} <= kinds
```

- [ ] **Step 2: Run the test and verify RED**

Run: `uv run pytest tests/ontology/test_schema_market_migration.py -q`
Expected: import error for `schema_market`.

- [ ] **Step 3: Declare market tables on the shared MetaData**

In `schema_market.py`, `from nutmeg.ontology.repository.schema import metadata` and declare:

```text
market_definitions:    market_definition_id PK, market_kind NOT NULL, settlement_scope NOT NULL,
                       ordered INTEGER NOT NULL DEFAULT 0, line_schema?, outcome_schema_version NOT NULL
selection_definitions: selection_id PK, market_definition_id NOT NULL FK market_definitions RESTRICT,
                       outcome_key NOT NULL, line?
market_quotes:         quote_id PK, match_id NOT NULL FK matches RESTRICT,
                       market_definition_id NOT NULL FK market_definitions RESTRICT,
                       selection_id NOT NULL FK selection_definitions RESTRICT, provider NOT NULL,
                       bookmaker?, decimal_odds REAL NOT NULL CHECK(decimal_odds > 1.0),
                       captured_at NOT NULL,
                       artifact_retrieval_id? FK artifact_retrievals RESTRICT, quote_status NOT NULL
market_snapshots:      market_snapshot_id PK, match_id NOT NULL FK matches RESTRICT,
                       market_definition_id NOT NULL FK market_definitions RESTRICT,
                       snapshot_kind NOT NULL, as_of NOT NULL, fair_distribution_json NOT NULL,
                       devig_method NOT NULL, method_version NOT NULL, source_coverage_json NOT NULL,
                       freshness_json NOT NULL, disagreement_json NOT NULL
market_snapshot_quotes:market_snapshot_id NOT NULL FK market_snapshots RESTRICT,
                       quote_id NOT NULL FK market_quotes RESTRICT,
                       PRIMARY KEY(market_snapshot_id, quote_id)
```

`market_quotes.artifact_retrieval_id` is nullable so replay from a pre-parsed snapshot (no CAS retrieval)
still records quotes; live ingest (Task 13) always sets it.

- [ ] **Step 4: Add migration 4 with the definition seed**

`_apply_market(connection)` creates the five tables in FK order and seeds `market_definitions` +
`selection_definitions` for the four kinds:

```text
had  (settlement_scope=regular_time, ordered=0): selections home/draw/away
hhad (settlement_scope=regular_time, ordered=0): selections home/draw/away, line carried per quote
ttg  (settlement_scope=regular_time, ordered=1): selections total_0..total_7
crs  (settlement_scope=regular_time, ordered=0): selections from the correct-score grid (0:0..)
```

Use fixed ids (e.g. `md-had`, `sel-had-home`) so later tasks reference them deterministically. Append:

```python
Migration(version=4, name='market_definitions',
          fingerprint='market_defs+selection_defs(had,hhad,ttg,crs)',
          apply=_apply_market),
```

- [ ] **Step 5: Run tests and ruff**

Run:
```bash
uv run pytest tests/ontology/test_schema_market_migration.py -q
uv run ruff check nutmeg/ontology/repository/schema_market.py nutmeg/ontology/repository/migrations.py
```
Expected: pass; clean.

- [ ] **Step 6: Commit**

```bash
git add nutmeg/ontology/repository/schema_market.py nutmeg/ontology/repository/migrations.py \
  tests/ontology/test_schema_market_migration.py
git commit -m "feat(ontology): add market schema and definition seed"
```

---

### Task 9: MarketRepository

**Files:**
- Create: `nutmeg/ontology/repository/market.py`
- Modify: `nutmeg/ontology/repository/unit_of_work.py` (add `.market`)
- Test: `tests/ontology/test_market_repository.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.market import MarketRepository, QuoteRow, SnapshotRow
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _prepare(tmp_path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.identity.insert_match_minimal("match-1")   # helper: matches row only, for FK
    return engine


def test_insert_quote_and_snapshot_links(tmp_path: Path) -> None:
    engine = _prepare(tmp_path)
    with OntologyUnitOfWork(engine) as uow:
        repo = uow.market
        repo.insert_quote(QuoteRow(
            quote_id="q1", match_id="match-1", market_definition_id="md-had",
            selection_id="sel-had-home", provider="sporttery", bookmaker=None,
            decimal_odds=2.1, captured_at="2026-07-19T15:00:00+08:00",
            artifact_retrieval_id=None, quote_status="active",
        ))
        repo.insert_snapshot(SnapshotRow(
            market_snapshot_id="s1", match_id="match-1", market_definition_id="md-had",
            snapshot_kind="read_time", as_of="2026-07-19T15:00:00+08:00",
            fair_distribution={"home": 0.5, "draw": 0.3, "away": 0.2},
            devig_method="proportional", method_version="1",
            source_coverage={"providers": 1}, freshness={"age_s": 0}, disagreement={},
        ), quote_ids=("q1",))
    with OntologyUnitOfWork(engine) as uow:
        assert uow.market.count_quotes() == 1
        assert uow.market.count_snapshots() == 1
        assert uow.market.snapshot_quote_ids("s1") == ("q1",)
```

- [ ] **Step 2: Run the test and verify RED**

Run: `uv run pytest tests/ontology/test_market_repository.py -q`
Expected: import error for `MarketRepository` (and `insert_match_minimal`).

- [ ] **Step 3: Implement MarketRepository, `.market`, and the FK test helper**

`market.py` defines frozen `QuoteRow` and `SnapshotRow` (JSON fields as dicts; the repository serializes them
with Package 1's `canonical_json`) and `MarketRepository(connection)` with `insert_quote`, `insert_snapshot`
(inserts the snapshot then one `market_snapshot_quotes` row per quote id), `count_quotes`, `count_snapshots`,
`snapshot_quote_ids(id) -> tuple[str, ...]`. Add `.market` to `OntologyUnitOfWork`. Add
`IdentityRepository.insert_match_minimal(match_id)` (inserts a bare `matches` row) so market tests can satisfy
the `match_id` FK without a full RecordMatch.

- [ ] **Step 4: Run tests and ruff**

Run:
```bash
uv run pytest tests/ontology/test_market_repository.py -q
uv run ruff check nutmeg/ontology/repository/market.py nutmeg/ontology/repository/unit_of_work.py
```
Expected: pass; clean.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/ontology/repository/market.py nutmeg/ontology/repository/unit_of_work.py \
  nutmeg/ontology/repository/identity.py tests/ontology/test_market_repository.py
git commit -m "feat(ontology): add market repository"
```

---

### Task 10: RecordMarketQuote and BuildMarketSnapshot Actions

**Files:**
- Create: `nutmeg/ontology/market/__init__.py`
- Create: `nutmeg/ontology/market/models.py`
- Create: `nutmeg/ontology/actions/market_actions.py`
- Test: `tests/ontology/test_market_actions.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.actions.market_actions import MarketActions
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.market.models import QuoteInput, SnapshotBuildRequest
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _actions(tmp_path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.identity.insert_match_minimal("match-1")
    return MarketActions(ActionService(lambda: OntologyUnitOfWork(engine))), engine


def test_build_snapshot_devigs_had_from_quotes(tmp_path: Path) -> None:
    actions, engine = _actions(tmp_path)
    quotes = [
        QuoteInput(market_definition_id="md-had", selection_id="sel-had-home", decimal_odds=2.0),
        QuoteInput(market_definition_id="md-had", selection_id="sel-had-draw", decimal_odds=3.5),
        QuoteInput(market_definition_id="md-had", selection_id="sel-had-away", decimal_odds=4.0),
    ]
    outcome = actions.build_snapshot(SnapshotBuildRequest(
        match_id="match-1", market_definition_id="md-had", snapshot_kind="read_time",
        as_of="2026-07-19T15:00:00+08:00", provider="sporttery", quotes=quotes,
        actor_id="system:devig", actor_role=ActorRole.DETERMINISTIC_SYSTEM,
        idempotency_key="snap:1", requested_at=datetime(2026, 7, 19, 8, tzinfo=UTC),
    ))
    assert outcome.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        fair = uow.market.latest_fair("match-1", "md-had")
        assert abs(sum(fair.values()) - 1.0) < 1e-9
        assert fair["home"] > fair["away"]   # 2.0 vs 4.0 implies home more likely
        assert uow.market.count_quotes() == 3


def test_ai_analyst_cannot_build_snapshot(tmp_path: Path) -> None:
    actions, _engine = _actions(tmp_path)
    outcome = actions.build_snapshot(SnapshotBuildRequest(
        match_id="match-1", market_definition_id="md-had", snapshot_kind="read_time",
        as_of="2026-07-19T15:00:00+08:00", provider="sporttery",
        quotes=[QuoteInput(market_definition_id="md-had", selection_id="sel-had-home", decimal_odds=2.0)],
        actor_id="model:x", actor_role=ActorRole.AI_ANALYST,
        idempotency_key="snap:denied", requested_at=datetime(2026, 7, 19, 8, tzinfo=UTC),
    ))
    assert outcome.status is ActionStatus.REJECTED
```

- [ ] **Step 2: Run the test and verify RED**

Run: `uv run pytest tests/ontology/test_market_actions.py -q`
Expected: import error for `market_actions`.

- [ ] **Step 3: Seed permissions and implement the market actions**

Extend migration 4 `apply` to seed `action_permissions` (governance-v1):

```text
record_market_quote:  connector
build_market_snapshot: deterministic_system
```

`market/models.py` defines frozen `QuoteInput(market_definition_id, selection_id, decimal_odds, bookmaker=None)`,
`SnapshotBuildRequest` and `QuoteRecordRequest` (validated aware `requested_at`, non-empty ids, `quotes`
non-empty, all `decimal_odds > 1.0`). `MarketActions.build_snapshot(request)` builds an
`ActionCommand(action_type="build_market_snapshot", ...)` and a handler that:

1. inserts each `QuoteInput` as a `market_quotes` row (mint quote ids, `quote_status='active'`,
   `artifact_retrieval_id` from the request if present else None);
2. computes the fair distribution by calling `nutmeg.decision.market_data.devig` on the
   `{selection_outcome_key: decimal_odds}` map (map selection ids to outcome keys via the seeded
   `selection_definitions`); pin `devig_method='proportional'`, `method_version='1'`;
3. inserts one `market_snapshots` row (`fair_distribution_json`, coverage/freshness/disagreement as JSON)
   and `market_snapshot_quotes` links;
4. returns `(ObjectRef("market_snapshot", snapshot_id),)`.

Add `MarketRepository.latest_fair(match_id, market_definition_id) -> dict[str, float]` reading the newest
snapshot's `fair_distribution_json`. Reusing `market_data.devig` keeps the devig math single-sourced (no
re-implementation, no mental arithmetic). `record_market_quote` is a thinner Action recording a single quote;
implement it analogously for the ingest path.

- [ ] **Step 4: Run tests and ruff**

Run:
```bash
uv run pytest tests/ontology/test_market_actions.py tests/ontology/test_schema_market_migration.py -q
uv run ruff check nutmeg/ontology/market nutmeg/ontology/actions/market_actions.py \
  nutmeg/ontology/repository/migrations.py
```
Expected: pass; clean.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/ontology/market nutmeg/ontology/actions/market_actions.py \
  nutmeg/ontology/repository/migrations.py nutmeg/ontology/repository/market.py \
  tests/ontology/test_market_actions.py
git commit -m "feat(ontology): devig market snapshots through typed actions"
```

---

### Task 11: Sporttery parser (real scheduled_at + timezone trap)

**Files:**
- Create: `nutmeg/ontology/ingest/__init__.py`
- Create: `nutmeg/ontology/ingest/sporttery.py`
- Test: `tests/ontology/test_ingest_sporttery.py`

- [ ] **Step 1: Write the failing test**

```python
from nutmeg.ontology.ingest.sporttery import ParsedMatch, parse_sporttery_markets


SPORTTERY_FIXTURE = {
    "value": {
        "matchInfoList": [
            {
                "businessDate": "2026-07-19",
                "matchList": [
                    {
                        "matchNumStr": "周六001",
                        "matchNum": "2026071900001",
                        "matchTime": "2026-07-19 23:30:00",
                        "homeTeamAbbName": "Hammarby",
                        "awayTeamAbbName": "AIK",
                        "leagueAbbName": "瑞典超",
                        "had": {"h": "2.10", "d": "3.30", "a": "3.10"},
                    },
                    {
                        "matchNumStr": "周日005",
                        "matchNum": "2026072000005",
                        "matchTime": "2026-07-20 03:00:00",
                        "homeTeamAbbName": "LAFC",
                        "awayTeamAbbName": "Seattle",
                        "leagueAbbName": "美职",
                        "had": {"h": "1.80", "d": "3.60", "a": "4.20"},
                    },
                ],
            }
        ]
    }
}


def test_parses_matchno_provider_id_and_teams() -> None:
    parsed = parse_sporttery_markets(SPORTTERY_FIXTURE, business_date="2026-07-19")
    first = parsed[0]
    assert isinstance(first, ParsedMatch)
    assert first.provider == "sporttery"
    assert first.external_id == "2026071900001"
    assert first.home_name == "Hammarby"
    assert first.away_name == "AIK"
    assert first.league_name == "瑞典超"
    # a 23:30 Beijing kickoff on the business date keeps that date
    assert first.scheduled_at.startswith("2026-07-19T23:30:00")


def test_early_morning_kickoff_is_next_calendar_day_not_business_date() -> None:
    parsed = parse_sporttery_markets(SPORTTERY_FIXTURE, business_date="2026-07-19")
    lafc = next(m for m in parsed if m.home_name == "LAFC")
    # matchTime 2026-07-20 03:00 is already the real calendar instant; must not collapse to business date
    assert lafc.scheduled_at.startswith("2026-07-20T03:00:00")
    assert lafc.schedule_status == "scheduled"


def test_missing_time_yields_unknown_not_a_guess() -> None:
    fixture = {"value": {"matchInfoList": [{"businessDate": "2026-07-19", "matchList": [
        {"matchNumStr": "周六009", "matchNum": "2026071900009", "matchTime": "",
         "homeTeamAbbName": "A", "awayTeamAbbName": "B", "leagueAbbName": "X", "had": {}},
    ]}]}}
    parsed = parse_sporttery_markets(fixture, business_date="2026-07-19")
    assert parsed[0].scheduled_at is None
    assert parsed[0].schedule_status == "unknown"
```

- [ ] **Step 2: Run the test and verify RED**

Run: `uv run pytest tests/ontology/test_ingest_sporttery.py -q`
Expected: import error for `sporttery`.

- [ ] **Step 3: Implement the parser**

`sporttery.py` defines frozen `ParsedQuote(market_kind, outcome_key, decimal_odds, line=None)` and
`ParsedMatch(provider, external_id, business_date, home_name, away_name, league_name, scheduled_at,
schedule_status, quotes: tuple[ParsedQuote, ...])`. `parse_sporttery_markets(value, *, business_date)`:

- iterate `matchInfoList[].matchList[]`;
- `external_id = matchNum`, names from `homeTeamAbbName`/`awayTeamAbbName`, league from `leagueAbbName`;
- `scheduled_at`: parse `matchTime` (`YYYY-MM-DD HH:MM:SS`, Beijing `+08:00`) to an ISO string with offset;
  the raw `matchTime` already carries the true calendar date, so an early-morning kickoff naturally lands on
  the next calendar day — never clamp it to `business_date`. Empty/absent `matchTime` →
  `scheduled_at=None, schedule_status='unknown'`; otherwise `schedule_status='scheduled'`.
- quotes: from `had` (h/d/a → home/draw/away). (hhad/ttg/crs parsing follows the same shape and reuses
  `nutmeg.decision.market_data._had_from_pool` / `_ttg_from_pool` / `_crs_from_pool` where a pool object is
  present; for 2A wiring, `had` is sufficient and the others are additive.)

The Beijing-`+08:00` interpretation plus never-clamping is the codified fix for the "周X0NN = 北京次日" trap
(design §2.2 / §8).

- [ ] **Step 4: Run tests and ruff**

Run:
```bash
uv run pytest tests/ontology/test_ingest_sporttery.py -q
uv run ruff check nutmeg/ontology/ingest/sporttery.py
```
Expected: pass; clean.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/ontology/ingest tests/ontology/test_ingest_sporttery.py
git commit -m "feat(ontology): parse sporttery markets with real kickoff time"
```

---

### Task 12: International-odds parser and cross-channel alignment

**Files:**
- Create: `nutmeg/ontology/ingest/intl_odds.py`
- Test: `tests/ontology/test_ingest_intl_odds.py`

- [ ] **Step 1: Write the failing test**

```python
from nutmeg.ontology.ingest.intl_odds import ParsedIntlQuote, parse_bold_odds


BOLD_FIXTURE = {
    "2026071900001": {
        "match_no": "2026071900001",
        "home": "Hammarby", "away": "AIK",
        "had": {"h": "2.05", "d": "3.40", "a": "3.20"},
    }
}


def test_bold_odds_carry_the_sporttery_match_no_for_alignment() -> None:
    quotes = parse_bold_odds(BOLD_FIXTURE)
    assert quotes[0].align_provider == "sporttery"
    assert quotes[0].align_external_id == "2026071900001"
    assert quotes[0].market_kind == "had"
    assert quotes[0].outcome_key == "home"
    assert abs(quotes[0].decimal_odds - 2.05) < 1e-9
    # three had outcomes per match
    assert {q.outcome_key for q in quotes} == {"home", "draw", "away"}
```

- [ ] **Step 2: Run the test and verify RED**

Run: `uv run pytest tests/ontology/test_ingest_intl_odds.py -q`
Expected: import error for `intl_odds`.

- [ ] **Step 3: Implement the parser**

`intl_odds.py` defines frozen `ParsedIntlQuote(align_provider, align_external_id, market_kind, outcome_key,
decimal_odds, line=None)` and `parse_bold_odds(value)` that, for each keyed match, emits had quotes tagged
with `align_provider="sporttery"` and `align_external_id=<match_no>`. This is the cross-channel key: the
international book's quotes align to the **same** sporttery match number, so downstream ingest resolves both
to one opaque `match_id` (design §7.1 acceptance: 竞彩+足彩 same opaque match_id). Do not invent identity from
team-name string matching here — alignment is by provider id, with team names available only as an alias
fallback for the ingest resolver.

- [ ] **Step 4: Run tests and ruff**

Run:
```bash
uv run pytest tests/ontology/test_ingest_intl_odds.py -q
uv run ruff check nutmeg/ontology/ingest/intl_odds.py
```
Expected: pass; clean.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/ontology/ingest/intl_odds.py tests/ontology/test_ingest_intl_odds.py
git commit -m "feat(ontology): align international odds by provider match id"
```

---

### Task 13: Market-day ingest orchestration + CLI + wiring

**Files:**
- Create: `nutmeg/ontology/ingest/market_day.py`
- Create: `nutmeg/interfaces/cli/ontology_ingest.py`
- Modify: `nutmeg/ontology/wiring.py`, `nutmeg/ontology/kernel.py`, `nutmeg/interfaces/cli/__init__.py`
- Test: `tests/ontology/test_market_day_ingest.py`, `tests/ontology/test_ingest_cli.py`

- [ ] **Step 1: Write the failing orchestration test**

```python
import json
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.ingest.market_day import MarketDayIngestRequest
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel

SPORTTERY = {"value": {"matchInfoList": [{"businessDate": "2026-07-19", "matchList": [
    {"matchNumStr": "周六001", "matchNum": "2026071900001", "matchTime": "2026-07-19 23:30:00",
     "homeTeamAbbName": "Hammarby", "awayTeamAbbName": "AIK", "leagueAbbName": "瑞典超",
     "had": {"h": "2.10", "d": "3.30", "a": "3.10"}}]}]}}
BOLD = {"2026071900001": {"match_no": "2026071900001", "home": "Hammarby", "away": "AIK",
                          "had": {"h": "2.05", "d": "3.40", "a": "3.20"}}}


def test_ingest_market_day_builds_matches_and_snapshots(tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    kernel = build_ontology_kernel(settings)
    kernel.initialize()
    outcome = kernel.market_day_ingest.ingest(MarketDayIngestRequest(
        business_date="2026-07-19",
        sporttery_value=SPORTTERY, intl_value=BOLD,
        actor_id="source:sporttery", actor_role=ActorRole.CONNECTOR,
        requested_at=datetime(2026, 7, 19, 8, tzinfo=UTC),
    ))
    assert outcome.matches == 1
    assert outcome.snapshots >= 1
    status = kernel.status()
    assert status.match_count == 1
    assert status.team_count >= 2
    # both channels resolved to the same match; real schedule stored
    with OntologyUnitOfWork(kernel.engine) as uow:
        [match_id] = uow.identity.all_match_ids()
        rev = uow.identity.current_match_revision(match_id)
        assert rev.scheduled_at.startswith("2026-07-19T23:30:00")
        assert rev.schedule_status == "scheduled"
        fair = uow.market.latest_fair(match_id, "md-had")
        assert abs(sum(fair.values()) - 1.0) < 1e-9


def test_ingest_is_idempotent_on_rerun(tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    kernel = build_ontology_kernel(settings)
    kernel.initialize()
    req = MarketDayIngestRequest(
        business_date="2026-07-19", sporttery_value=SPORTTERY, intl_value=BOLD,
        actor_id="source:sporttery", actor_role=ActorRole.CONNECTOR,
        requested_at=datetime(2026, 7, 19, 8, tzinfo=UTC),
    )
    kernel.market_day_ingest.ingest(req)
    kernel.market_day_ingest.ingest(req)
    assert kernel.status().match_count == 1
```

- [ ] **Step 2: Run the test and verify RED**

Run: `uv run pytest tests/ontology/test_market_day_ingest.py -q`
Expected: import error for `market_day` / missing kernel attributes.

- [ ] **Step 3: Implement the orchestration**

`market_day.py` defines frozen `MarketDayIngestRequest` (business_date, sporttery_value, intl_value?, actor,
aware requested_at) and `MarketDayIngestResult(matches, snapshots, teams)`. `MarketDayIngestService` holds the
`ArtifactIngestService`, `EntityActions`, `MatchActions`, `MarketActions` (all built in wiring). `ingest`:

1. `IngestArtifact` the raw sporttery bytes (and intl bytes) to CAS — one `ArtifactRetrieval` each, keyed by
   `f"sporttery:{business_date}"` / `f"intl:{business_date}"` (idempotent);
2. `parse_sporttery_markets`; for each `ParsedMatch`:
   - `upsert_team` for home and away (provider id + canonical name); collect team ids;
   - `record_match` (provider id = matchNum, real `scheduled_at`/`schedule_status`, the two team ids);
   - `build_snapshot` for `md-had` from the sporttery quotes → read_time snapshot;
3. `parse_bold_odds`; group by `align_external_id`; for each aligned match resolve the `match_id` by
   `entity_by_external_id(MATCH, "sporttery", align_external_id)` and `build_snapshot` (or add quotes) for the
   international read — same opaque `match_id`, no new match;
4. return counts.

Idempotency is inherited: each `upsert_team`/`record_match`/`build_snapshot` uses a deterministic
idempotency key derived from `business_date` + provider id + market kind, so a rerun commits nothing new
(Package 1 replay semantics). Extend `OntologyKernelStatus` with `match_count`, `team_count`,
`quote_count`, `snapshot_count`; extend `wiring.build_ontology_kernel` to expose `market_day_ingest` and
`engine`; add `all_match_ids()` to `IdentityRepository`.

- [ ] **Step 4: Write the failing CLI test**

```python
import json

from typer.testing import CliRunner

from nutmeg.interfaces.cli import app

runner = CliRunner()


def test_ingest_market_day_cli_reports_counts(tmp_path, monkeypatch) -> None:
    sporttery = tmp_path / "sporttery.json"
    intl = tmp_path / "bold.json"
    sporttery.write_text(json.dumps({"value": {"matchInfoList": [{"businessDate": "2026-07-19",
        "matchList": [{"matchNumStr": "周六001", "matchNum": "2026071900001",
        "matchTime": "2026-07-19 23:30:00", "homeTeamAbbName": "Hammarby", "awayTeamAbbName": "AIK",
        "leagueAbbName": "瑞典超", "had": {"h": "2.10", "d": "3.30", "a": "3.10"}}]}]}}), encoding="utf-8")
    intl.write_text(json.dumps({"2026071900001": {"match_no": "2026071900001", "home": "Hammarby",
        "away": "AIK", "had": {"h": "2.05", "d": "3.40", "a": "3.20"}}}), encoding="utf-8")
    init = runner.invoke(app, ["ontology", "init", "--format", "json"])
    result = runner.invoke(app, ["ontology", "ingest-market-day", "--business-date", "2026-07-19",
        "--sporttery", str(sporttery), "--intl", str(intl), "--format", "json"])
    assert init.exit_code == 0
    assert result.exit_code == 0
    assert json.loads(result.stdout)["matches"] == 1
```

- [ ] **Step 5: Implement the CLI and register it**

`ontology_ingest.py` adds `ingest-market-day` to the `ontology` sub-app (reach it via
`_cli.ontology.ontology_app` — expose `ontology_app` from `nutmeg/interfaces/cli/ontology.py`, or add the
command under the same Typer). Options: `--business-date`, `--sporttery <path>`, `--intl <path>` (optional),
`--format text|json`. It reads the JSON files, calls `build_ontology_kernel(get_settings())` (init first if
needed via `--init`, else assume initialized), runs `market_day_ingest.ingest(...)` as `connector`, and
prints the result counts. Register `from nutmeg.interfaces.cli import ontology_ingest` at the bottom of
`__init__.py`. Expose `build_ontology_kernel` is already on `_cli` from Package 1.

- [ ] **Step 6: Run tests and ruff**

Run:
```bash
uv run pytest tests/ontology/test_market_day_ingest.py tests/ontology/test_ingest_cli.py \
  tests/ontology/test_kernel.py -q
uv run ruff check nutmeg/ontology tests/ontology nutmeg/interfaces/cli/ontology_ingest.py
```
Expected: pass; clean.

- [ ] **Step 7: Commit**

```bash
git add nutmeg/ontology/ingest/market_day.py nutmeg/ontology/wiring.py nutmeg/ontology/kernel.py \
  nutmeg/ontology/repository/identity.py nutmeg/interfaces/cli/ontology_ingest.py \
  nutmeg/interfaces/cli/__init__.py nutmeg/interfaces/cli/ontology.py \
  tests/ontology/test_market_day_ingest.py tests/ontology/test_ingest_cli.py
git commit -m "feat(ontology): ingest a market day into typed facts"
```

---

### Task 14: Real-jczq-day replay gate, docs, and full verification

**Files:**
- Create: `tests/ontology/test_package2a_e2e.py`
- Modify: `docs/ontology-kernel-operations.md`
- Modify only if a failure exposes a bug: Package 2A modules

- [ ] **Step 1: Write the failing e2e/temporal test**

```python
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.identity.models import EntityType
from nutmeg.ontology.ingest.market_day import MarketDayIngestRequest
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel

TWO_MATCHES = {"value": {"matchInfoList": [{"businessDate": "2026-07-19", "matchList": [
    {"matchNumStr": "周六001", "matchNum": "2026071900001", "matchTime": "2026-07-19 23:30:00",
     "homeTeamAbbName": "Hammarby", "awayTeamAbbName": "AIK", "leagueAbbName": "瑞典超",
     "had": {"h": "2.10", "d": "3.30", "a": "3.10"}},
    {"matchNumStr": "周日005", "matchNum": "2026072000005", "matchTime": "2026-07-20 03:00:00",
     "homeTeamAbbName": "LAFC", "awayTeamAbbName": "Seattle", "leagueAbbName": "美职",
     "had": {"h": "1.80", "d": "3.60", "a": "4.20"}}]}]}}


def test_full_day_has_no_null_identity_and_real_schedule(tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    kernel = build_ontology_kernel(settings)
    kernel.initialize()
    kernel.market_day_ingest.ingest(MarketDayIngestRequest(
        business_date="2026-07-19", sporttery_value=TWO_MATCHES, intl_value=None,
        actor_id="source:sporttery", actor_role=ActorRole.CONNECTOR,
        requested_at=datetime(2026, 7, 19, 8, tzinfo=UTC),
    ))
    status = kernel.status()
    assert status.match_count == 2
    with OntologyUnitOfWork(kernel.engine) as uow:
        for match_id in uow.identity.all_match_ids():
            rev = uow.identity.current_match_revision(match_id)
            assert rev.schedule_status in {"scheduled", "unknown"}
            if rev.schedule_status == "scheduled":
                assert rev.scheduled_at is not None       # never ingestion time
            sides = uow.identity.appearance_sides(match_id)
            assert set(sides) == {"home", "away"}
            for team_id in sides.values():
                assert team_id is not None                 # no silent null identity
        # the early-morning match kept the next calendar day
        lafc_match = uow.identity.entity_by_external_id(
            EntityType.MATCH, provider="sporttery", external_id="2026072000005",
        )
        assert uow.identity.current_match_revision(lafc_match).scheduled_at.startswith("2026-07-20T03:00")
```

- [ ] **Step 2: Run the e2e test and verify RED then GREEN**

Run: `uv run pytest tests/ontology/test_package2a_e2e.py -q`
Expected: initially fails only if a real bug exists; fix the minimal Package 2A code and re-run to GREEN.

- [ ] **Step 3: Document the Package 2A operations**

Add a "Package 2A — Identity & Market Facts" section to `docs/ontology-kernel-operations.md`: the identity
objects (provisional entities, provider-id-first resolution, reversible merge), the market objects, and:

```bash
uv run nutmeg ontology ingest-market-day --business-date <D> --sporttery <path> [--intl <path>] --format json
```

State that ingest is idempotent and that identity is never inferred from team-name string matching without a
logged `propose_identity_link`/`merge_entity`.

- [ ] **Step 4: Run the full Package 2A suite and adjacent regressions**

Run:
```bash
uv run pytest tests/ontology -q
uv run pytest tests/test_cli.py::test_doctor_reports_ready_workflow_and_harness \
  tests/decision/ -q
```
Expected: all pass; the decision suite is unchanged (Package 2A adds no decision code).

- [ ] **Step 5: Repository quality gates**

Run:
```bash
uv run ruff check .
uv run python -m compileall -q nutmeg scripts
bash scripts/verify.sh
```
Expected: ruff and compileall clean; full pytest suite passes.

- [ ] **Step 6: Project verify — real jczq-day replay against Package 2A**

From the worktree, copy a recent production day's snapshots to a temp dir (read-only on `.nutmeg-data`) and
run the ingest with this branch's code, confirming real `scheduled_at`, no null identity, cross-channel
alignment, and devig fair snapshots:

```bash
MAIN=/Users/jz71/Projects/Nutmeg; D=2026-07-19; TMP=$(mktemp -d)
uv run nutmeg ontology init --format json
uv run nutmeg ontology ingest-market-day --business-date $D \
  --sporttery "$MAIN/.nutmeg-data/jczq/daily/$D/sporttery_markets.json" \
  --intl "$MAIN/.nutmeg-data/jczq/daily/$D/bold_odds.json" --format json
uv run nutmeg ontology status --format json
```

Expected: `matches` > 0, `status.match_count`/`team_count` > 0, integrity `ok`; every match has a real
`scheduled_at` or explicit `unknown`. Report any external-source shape mismatch explicitly rather than hiding
it. Do not push, do not mutate `.nutmeg-data`, do not re-enable schedules.

- [ ] **Step 7: Commit and inspect the branch**

```bash
git add tests/ontology/test_package2a_e2e.py docs/ontology-kernel-operations.md nutmeg/ontology
git commit -m "test(ontology): verify package 2a identity and market facts"
git status --short
git log --oneline main..HEAD
git diff --stat main...HEAD | tail -30
```

Expected: clean worktree, one focused commit per task, no files outside this plan's scope. Do not merge in
this task — hand back for review.

---

## Package 2A Spec Coverage

| Design (§) requirement | Implemented by |
|---|---|
| Provider-ID-first resolution, no silent fuzzy merge (§2.1) | Tasks 4, 5 |
| Provisional entities, never null identity (§2.1, §7) | Tasks 3, 5, 14 |
| Reversible MergeEntity with redirect (§2.1) | Task 6 |
| Real `scheduled_at`; unknown is explicit (§2.2) | Tasks 7, 11, 14 |
| Timezone "周X0NN = next day" trap (§2.2, §8) | Task 11 |
| Opaque `match_id`; provider ids in ExternalIdentifier (§2.2) | Tasks 2, 7 |
| Curated alias seed reused (§5) | Task 2 |
| MarketDefinition/Selection with settlement_scope (§2.3, §3) | Task 8 |
| MarketQuote + deterministic devig MarketSnapshot reusing market_data (§2.3, §5) | Tasks 9, 10 |
| Cross-channel same opaque match_id (§7.1) | Tasks 12, 13, 14 |
| Every quote/snapshot traces to ArtifactRetrieval (§6) | Task 13 |
| Domain writes are typed Actions on Package 1 kernel; deny-by-default (§0.1, §4) | Tasks 5, 6, 7, 10 |
| Real jczq-day replay acceptance (§7) | Task 14 |

Package 2A is complete only when Task 14 passes. It does not authorize Package 2B; 2B receives its own plan
using 2A's verified interfaces (Person/Role/Lineup, Claim/Observation, adapter wiring).
