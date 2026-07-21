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

from sqlalchemy import Connection, Engine, insert, inspect, select

from nutmeg.ontology.errors import MigrationDriftError
from nutmeg.ontology.repository import schema


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
