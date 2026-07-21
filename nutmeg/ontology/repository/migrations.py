"""Explicit, numbered schema migrations with drift detection.

Migrations are ordinary Python callables carrying a stable ``fingerprint``. The
runner records a SHA-256 checksum of ``version:name:fingerprint`` per applied
migration and refuses to run again if a previously applied migration's checksum
changed — a change to already-shipped DDL is a drift bug, not a silent upgrade.
Each migration's schema/data change and its ``schema_migrations`` row commit in
one transaction, so a partially applied migration cannot survive a crash.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Connection, Engine, insert, inspect, select

from nutmeg.ontology.errors import MigrationDriftError
from nutmeg.ontology.identity.models import EntityType, TeamKind, mint_id
from nutmeg.ontology.repository import schema, schema_identity


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    fingerprint: str
    apply: Callable[[Connection], None]

    @property
    def checksum(self) -> str:
        material = f'{self.version}:{self.name}:{self.fingerprint}'
        return hashlib.sha256(material.encode('utf-8')).hexdigest()


@dataclass(frozen=True, slots=True)
class MigrationReport:
    applied_versions: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class MigrationStatus:
    current_version: int
    applied_versions: tuple[int, ...]


def _canonical_json(document: dict[str, object]) -> str:
    return json.dumps(document, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def _apply_governance_kernel(connection: Connection) -> None:
    # Foreign-key order: policy_versions before actions/action_permissions.
    schema.policy_versions.create(connection)
    schema.actions.create(connection)
    schema.action_permissions.create(connection)

    now = datetime.now(UTC).isoformat()
    connection.execute(
        insert(schema.policy_versions).values(
            policy_version_id='governance-v1',
            policy_kind='governance',
            version=1,
            payload_json=_canonical_json({'name': 'kernel-default'}),
            status='active',
            effective_at=now,
            created_at=now,
        )
    )
    # Seed after all three tables exist so action_permissions FK resolves.
    permissions = (
        ('ingest_artifact', 'connector'),
        ('ingest_artifact', 'judge_operator'),
        ('change_policy', 'judge_operator'),
    )
    connection.execute(
        insert(schema.action_permissions),
        [
            {
                'policy_version_id': 'governance-v1',
                'action_type': action_type,
                'actor_role': actor_role,
            }
            for action_type, actor_role in permissions
        ],
    )


def _apply_evidence_kernel(connection: Connection) -> None:
    # Foreign-key order: source_runs + source_artifacts before artifact_retrievals.
    schema.source_runs.create(connection)
    schema.source_artifacts.create(connection)
    schema.artifact_retrievals.create(connection)


def _load_team_alias_seed() -> dict[tuple[str, str], set[str]]:
    """Curated `{chinese_alias: english_canonical}` files -> {(canonical, kind): aliases}."""
    root = Path(__file__).resolve().parents[2] / 'data'
    seed: dict[tuple[str, str], set[str]] = {}
    for filename, kind in (
        ('jczq_club_team_aliases.json', TeamKind.CLUB.value),
        ('jczq_national_team_aliases.json', TeamKind.NATIONAL.value),
    ):
        raw = json.loads((root / filename).read_text(encoding='utf-8'))
        for alias, canonical in raw.items():
            if alias == '_comment' or not isinstance(canonical, str):
                continue
            aliases = seed.setdefault((canonical, kind), set())
            aliases.add(alias.strip().casefold())
            aliases.add(canonical.strip().casefold())
    return seed


_IDENTITY_ACTION_PERMISSIONS = (
    ('upsert_provisional_entity', 'connector'),
    ('upsert_provisional_entity', 'deterministic_system'),
    ('link_external_identifier', 'connector'),
    ('link_external_identifier', 'deterministic_system'),
    ('propose_identity_link', 'connector'),
    ('propose_identity_link', 'ai_extractor'),
    ('merge_entity', 'judge_operator'),
    ('record_match', 'connector'),
    ('record_match', 'deterministic_system'),
)


def _apply_football_identity(connection: Connection) -> None:
    # Foreign-key order.
    for table in (
        schema_identity.competitions,
        schema_identity.competition_editions,
        schema_identity.teams,
        schema_identity.venues,
        schema_identity.matches,
        schema_identity.match_revisions,
        schema_identity.team_appearances,
        schema_identity.external_identifiers,
        schema_identity.entity_aliases,
        schema_identity.entity_merges,
    ):
        table.create(connection)

    now = datetime.now(UTC).isoformat()
    team_rows: list[dict[str, object]] = []
    alias_rows: list[dict[str, object]] = []
    for (canonical, kind), aliases in _load_team_alias_seed().items():
        team_id = mint_id(EntityType.TEAM)
        team_rows.append({
            'team_id': team_id, 'team_kind': kind, 'canonical_name': canonical,
            'country': None, 'resolution_status': 'provisional', 'created_at': now,
        })
        for alias in sorted(aliases):
            alias_rows.append({
                'entity_id': team_id, 'entity_type': EntityType.TEAM.value,
                'normalized_alias': alias, 'language': None, 'provider': None,
            })
    if team_rows:
        connection.execute(insert(schema_identity.teams), team_rows)
    if alias_rows:
        connection.execute(insert(schema_identity.entity_aliases), alias_rows)

    connection.execute(
        insert(schema.action_permissions),
        [
            {
                'policy_version_id': 'governance-v1',
                'action_type': action_type,
                'actor_role': actor_role,
            }
            for action_type, actor_role in _IDENTITY_ACTION_PERMISSIONS
        ],
    )


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=1,
        name='governance_kernel',
        fingerprint='policy_versions+actions+action_permissions+seed(governance-v1)',
        apply=_apply_governance_kernel,
    ),
    Migration(
        version=2,
        name='evidence_kernel',
        fingerprint='source_runs+source_artifacts+artifact_retrievals',
        apply=_apply_evidence_kernel,
    ),
    Migration(
        version=3,
        name='football_identity',
        fingerprint='competitions..entity_merges+team_alias_seed+identity_permissions',
        apply=_apply_football_identity,
    ),
)


def _validate_sequence(migrations: tuple[Migration, ...]) -> None:
    versions = [migration.version for migration in migrations]
    if versions != list(range(1, len(versions) + 1)):
        raise MigrationDriftError(
            f'migration versions must be a gap-free ascending sequence from 1, got {versions}'
        )


def _applied_checksums(connection: Connection) -> dict[int, str]:
    rows = connection.execute(
        select(schema.schema_migrations.c.version, schema.schema_migrations.c.checksum)
    ).all()
    return {row.version: row.checksum for row in rows}


def run_migrations(
    engine: Engine,
    migrations: tuple[Migration, ...] = MIGRATIONS,
) -> MigrationReport:
    _validate_sequence(migrations)
    applied: list[int] = []
    with engine.begin() as connection:
        schema.schema_migrations.create(connection, checkfirst=True)
        existing = _applied_checksums(connection)
        for migration in migrations:
            recorded = existing.get(migration.version)
            if recorded is not None:
                if recorded != migration.checksum:
                    raise MigrationDriftError(
                        f'migration {migration.version} checksum drift'
                    )
                continue
            migration.apply(connection)
            connection.execute(
                insert(schema.schema_migrations).values(
                    version=migration.version,
                    name=migration.name,
                    checksum=migration.checksum,
                    applied_at=datetime.now(UTC).isoformat(),
                )
            )
            applied.append(migration.version)
    return MigrationReport(applied_versions=tuple(applied))


def migration_status(engine: Engine) -> MigrationStatus:
    if not inspect(engine).has_table('schema_migrations'):
        return MigrationStatus(current_version=0, applied_versions=())
    with engine.connect() as connection:
        versions = tuple(
            sorted(connection.execute(select(schema.schema_migrations.c.version)).scalars().all())
        )
    current = versions[-1] if versions else 0
    return MigrationStatus(current_version=current, applied_versions=versions)
