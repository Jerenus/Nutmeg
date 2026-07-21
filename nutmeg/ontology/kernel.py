"""Kernel initialization and read-only integrity status.

``initialize`` creates the owned directories and applies migrations; it is
idempotent. ``status`` is strictly read-only: it never applies a migration and
never creates the database — it reports ``initialized=False`` when the database
file is absent, and only when it exists does it run ``PRAGMA integrity_check``,
read the migration high-water mark, and count Actions/artifacts/retrievals.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import Engine, func, select

from nutmeg.ontology.actions.artifact_ingest import ArtifactIngestService
from nutmeg.ontology.decision.read_flow import DecisionReadService
from nutmeg.ontology.finance.express_flow import ExpressService
from nutmeg.ontology.finance.reconcile_flow import ReconcileService
from nutmeg.ontology.ingest.evidence_day import EvidenceDayIngestService
from nutmeg.ontology.ingest.market_day import MarketDayIngestService
from nutmeg.ontology.paths import OntologyPaths
from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository.artifacts import ArtifactRepository
from nutmeg.ontology.repository.decision import DecisionRepository
from nutmeg.ontology.repository.evidence import EvidenceRepository
from nutmeg.ontology.repository.finance import FinanceRepository
from nutmeg.ontology.repository.identity import IdentityRepository
from nutmeg.ontology.repository.market import MarketRepository
from nutmeg.ontology.repository.migrations import (
    MIGRATIONS,
    MigrationReport,
    migration_status,
    run_migrations,
)

if TYPE_CHECKING:
    from nutmeg.analytics.calibrate_flow import CalibrateService


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
    person_count: int
    observation_count: int
    claim_count: int
    forecast_count: int
    bundle_count: int
    ticket_count: int
    settlement_count: int
    projection_run_count: int
    scorecard_count: int

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
            'person_count': self.person_count,
            'observation_count': self.observation_count,
            'claim_count': self.claim_count,
            'forecast_count': self.forecast_count,
            'bundle_count': self.bundle_count,
            'ticket_count': self.ticket_count,
            'settlement_count': self.settlement_count,
            'projection_run_count': self.projection_run_count,
            'scorecard_count': self.scorecard_count,
        }


class OntologyKernel:
    def __init__(
        self,
        *,
        paths: OntologyPaths,
        engine: Engine,
        artifact_ingest: ArtifactIngestService,
        market_day_ingest: MarketDayIngestService,
        evidence_day_ingest: EvidenceDayIngestService,
        decision_read: DecisionReadService,
        express: ExpressService,
        reconcile: ReconcileService,
        calibrate: CalibrateService,
    ) -> None:
        self._paths = paths
        self._engine = engine
        self.artifact_ingest = artifact_ingest
        self.market_day_ingest = market_day_ingest
        self.evidence_day_ingest = evidence_day_ingest
        self.decision_read = decision_read
        self.express = express
        self.reconcile = reconcile
        self.calibrate = calibrate

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
                person_count=0,
                observation_count=0,
                claim_count=0,
                forecast_count=0,
                bundle_count=0,
                ticket_count=0,
                settlement_count=0,
                projection_run_count=0,
                scorecard_count=0,
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
            person_count = identity.count_persons()
            market = MarketRepository(connection)
            quote_count = market.count_quotes()
            snapshot_count = market.count_snapshots()
            evidence = EvidenceRepository(connection)
            observation_count = evidence.count_observations()
            claim_count = evidence.count_claims()
            decision = DecisionRepository(connection)
            forecast_count = decision.count_committed_revisions()
            bundle_count = decision.count_bundles()
            finance = FinanceRepository(connection)
            ticket_count = finance.count_tickets()
            settlement_count = finance.count_settlements()
        from nutmeg.analytics.substrate import projection_counts

        projection_run_count, scorecard_count = projection_counts(self._paths.analytics)

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
            person_count=person_count,
            observation_count=observation_count,
            claim_count=claim_count,
            forecast_count=forecast_count,
            bundle_count=bundle_count,
            ticket_count=ticket_count,
            settlement_count=settlement_count,
            projection_run_count=projection_run_count,
            scorecard_count=scorecard_count,
        )
