"""Kernel initialization and read-only integrity status.

``initialize`` creates the owned directories and applies migrations; it is
idempotent. ``status`` is strictly read-only: it never applies a migration and
never creates the database — it reports ``initialized=False`` when the database
file is absent, and only when it exists does it run ``PRAGMA integrity_check``,
read the migration high-water mark, and count Actions/artifacts/retrievals.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine, func, select

from nutmeg.ontology.actions.artifact_ingest import ArtifactIngestService
from nutmeg.ontology.ingest.market_day import MarketDayIngestService
from nutmeg.ontology.paths import OntologyPaths
from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository.artifacts import ArtifactRepository
from nutmeg.ontology.repository.identity import IdentityRepository
from nutmeg.ontology.repository.market import MarketRepository
from nutmeg.ontology.repository.migrations import (
    MIGRATIONS,
    MigrationReport,
    migration_status,
    run_migrations,
)


@dataclass(frozen=True, slots=True)
class OntologyKernelStatus:
    initialized: bool
    schema_version: int
    pending_migrations: tuple[int, ...]
    integrity_check: str
    action_counts: dict[str, int]
    artifact_count: int
    retrieval_count: int
    team_count: int
    match_count: int
    quote_count: int
    snapshot_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            'initialized': self.initialized,
            'schema_version': self.schema_version,
            'pending_migrations': list(self.pending_migrations),
            'integrity_check': self.integrity_check,
            'action_counts': dict(self.action_counts),
            'artifact_count': self.artifact_count,
            'retrieval_count': self.retrieval_count,
            'team_count': self.team_count,
            'match_count': self.match_count,
            'quote_count': self.quote_count,
            'snapshot_count': self.snapshot_count,
        }


class OntologyKernel:
    def __init__(
        self,
        *,
        paths: OntologyPaths,
        engine: Engine,
        artifact_ingest: ArtifactIngestService,
        market_day_ingest: MarketDayIngestService,
    ) -> None:
        self._paths = paths
        self._engine = engine
        self.artifact_ingest = artifact_ingest
        self.market_day_ingest = market_day_ingest

    @property
    def engine(self) -> Engine:
        return self._engine

    def initialize(self) -> MigrationReport:
        self._paths.ensure_directories()
        return run_migrations(self._engine)

    def status(self) -> OntologyKernelStatus:
        if not self._paths.database.exists():
            return OntologyKernelStatus(
                initialized=False,
                schema_version=0,
                pending_migrations=tuple(migration.version for migration in MIGRATIONS),
                integrity_check='uninitialized',
                action_counts={},
                artifact_count=0,
                retrieval_count=0,
                team_count=0,
                match_count=0,
                quote_count=0,
                snapshot_count=0,
            )

        migration = migration_status(self._engine)
        applied = set(migration.applied_versions)
        pending = tuple(m.version for m in MIGRATIONS if m.version not in applied)
        with self._engine.connect() as connection:
            integrity = connection.exec_driver_sql('PRAGMA integrity_check').scalar_one()
            action_counts = {
                status: count
                for status, count in connection.execute(
                    select(schema.actions.c.status, func.count()).group_by(
                        schema.actions.c.status
                    )
                ).all()
            }
            artifacts = ArtifactRepository(connection)
            artifact_count = artifacts.count_artifacts()
            retrieval_count = artifacts.count_retrievals()
            identity = IdentityRepository(connection)
            team_count = identity.count_teams()
            match_count = identity.count_matches()
            market = MarketRepository(connection)
            quote_count = market.count_quotes()
            snapshot_count = market.count_snapshots()

        return OntologyKernelStatus(
            initialized=True,
            schema_version=migration.current_version,
            pending_migrations=pending,
            integrity_check=integrity,
            action_counts=action_counts,
            artifact_count=artifact_count,
            retrieval_count=retrieval_count,
            team_count=team_count,
            match_count=match_count,
            quote_count=quote_count,
            snapshot_count=snapshot_count,
        )
