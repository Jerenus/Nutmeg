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
from nutmeg.ontology.actions.claim_actions import ClaimActions
from nutmeg.ontology.actions.entity_actions import EntityActions
from nutmeg.ontology.actions.factor_actions import FactorActions
from nutmeg.ontology.actions.forecast_actions import ForecastActions
from nutmeg.ontology.actions.protected_ticket_actions import ProtectedTicketActions
from nutmeg.ontology.actions.reliability_actions import ReliabilityActions
from nutmeg.ontology.actions.scoreboard_actions import ScoreboardActions
from nutmeg.ontology.actions.workflow_actions import WorkflowActions
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
from nutmeg.ontology.repository.outbox import OutboxRepository
from nutmeg.ontology.repository.reliability import ReliabilityRepository
from nutmeg.ontology.repository.scoreboard import ScoreboardRepository

if TYPE_CHECKING:
    from nutmeg.analytics.calibrate_flow import CalibrateService


@dataclass(frozen=True, slots=True)
class OntologyKernelStatus:
    initialized: bool
    schema_version: int
    pending_migrations: tuple[int, ...]
    integrity_check: str
    action_counts: dict[str, int]
    outbox_event_count: int
    outbox_latest_sequence: int
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
    factor_estimate_count: int
    regime_vector_count: int
    lifecycle_proposal_count: int
    scoreboard_observation_count: int
    scoreboard_shadow_review_count: int
    scoreboard_authority_state: str
    reliability_evidence_count: int
    release_approval_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            'initialized': self.initialized,
            'schema_version': self.schema_version,
            'pending_migrations': list(self.pending_migrations),
            'integrity_check': self.integrity_check,
            'action_counts': dict(self.action_counts),
            'outbox_event_count': self.outbox_event_count,
            'outbox_latest_sequence': self.outbox_latest_sequence,
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
            'factor_estimate_count': self.factor_estimate_count,
            'regime_vector_count': self.regime_vector_count,
            'lifecycle_proposal_count': self.lifecycle_proposal_count,
            'scoreboard_observation_count': self.scoreboard_observation_count,
            'scoreboard_shadow_review_count': self.scoreboard_shadow_review_count,
            'scoreboard_authority_state': self.scoreboard_authority_state,
            'reliability_evidence_count': self.reliability_evidence_count,
            'release_approval_count': self.release_approval_count,
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
        entity_actions: EntityActions,
        claim_actions: ClaimActions,
        factor_actions: FactorActions,
        forecast_actions: ForecastActions,
        workflow: WorkflowActions,
        protected_tickets: ProtectedTicketActions,
        scoreboard_actions: ScoreboardActions,
        reliability_actions: ReliabilityActions,
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
        self.entity_actions = entity_actions
        self.claim_actions = claim_actions
        self.factor_actions = factor_actions
        self.forecast_actions = forecast_actions
        self.workflow = workflow
        self.protected_tickets = protected_tickets
        self.scoreboard_actions = scoreboard_actions
        self.reliability_actions = reliability_actions

    @property
    def engine(self) -> Engine:
        return self._engine

    @property
    def paths(self) -> OntologyPaths:
        return self._paths

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
                outbox_event_count=0,
                outbox_latest_sequence=0,
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
                factor_estimate_count=0,
                regime_vector_count=0,
                lifecycle_proposal_count=0,
                scoreboard_observation_count=0,
                scoreboard_shadow_review_count=0,
                scoreboard_authority_state='uninitialized',
                reliability_evidence_count=0,
                release_approval_count=0,
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
            if 10 in applied:
                outbox = OutboxRepository(connection)
                outbox_event_count = outbox.count()
                outbox_latest_sequence = outbox.latest_sequence()
            else:
                outbox_event_count = 0
                outbox_latest_sequence = 0
            if 13 in applied:
                scoreboard = ScoreboardRepository(connection)
                scoreboard_observation_count = scoreboard.count_observations()
                scoreboard_shadow_review_count = scoreboard.count_shadow_reviews()
                scoreboard_authority_state = scoreboard.authority().state
            else:
                scoreboard_observation_count = 0
                scoreboard_shadow_review_count = 0
                scoreboard_authority_state = 'unavailable'
            if 14 in applied:
                reliability = ReliabilityRepository(connection)
                reliability_evidence_count = reliability.count_evidence()
                release_approval_count = reliability.count_approvals()
            else:
                reliability_evidence_count = 0
                release_approval_count = 0
        from nutmeg.analytics.substrate import projection_counts

        counts = projection_counts(self._paths.analytics)

        return OntologyKernelStatus(
            initialized=True,
            schema_version=migration.current_version,
            pending_migrations=pending,
            integrity_check=integrity,
            action_counts=action_counts,
            outbox_event_count=outbox_event_count,
            outbox_latest_sequence=outbox_latest_sequence,
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
            projection_run_count=counts['projection_run_count'],
            scorecard_count=counts['scorecard_count'],
            factor_estimate_count=counts['factor_estimate_count'],
            regime_vector_count=counts['regime_vector_count'],
            lifecycle_proposal_count=counts['lifecycle_proposal_count'],
            scoreboard_observation_count=scoreboard_observation_count,
            scoreboard_shadow_review_count=scoreboard_shadow_review_count,
            scoreboard_authority_state=scoreboard_authority_state,
            reliability_evidence_count=reliability_evidence_count,
            release_approval_count=release_approval_count,
        )
