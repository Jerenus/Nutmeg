"""Kernel initialization and read-only integrity status.

``initialize`` creates the owned directories and applies migrations; it is
idempotent. ``status`` is strictly read-only: it never applies a migration and
never creates the database — it reports ``initialized=False`` when the database
file is absent, and only when it exists does it run ``PRAGMA integrity_check``,
read the migration high-water mark, and count Actions/artifacts/retrievals.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy import Engine, func, select

from nutmeg.ontology.actions.artifact_ingest import ArtifactIngestService
from nutmeg.ontology.actions.forecast_actions import ForecastActions
from nutmeg.ontology.actions.rsi_actions import RsiActions
from nutmeg.ontology.actions.scoreboard_actions import ScoreboardActions
from nutmeg.ontology.actions.workflow_actions import WorkflowActions
from nutmeg.ontology.finance.reconcile_flow import ReconcileService
from nutmeg.ontology.ingest.market_day import MarketDayIngestService
from nutmeg.ontology.paths import OntologyPaths
from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository.artifacts import ArtifactRepository
from nutmeg.ontology.repository.decision import DecisionRepository
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
from nutmeg.ontology.repository.scoreboard import ScoreboardRepository

if TYPE_CHECKING:
    from nutmeg.analytics.calibrate_flow import CalibrateService


@dataclass(frozen=True, slots=True)
class OntologyKernelStatus:
    initialized: bool = False
    schema_version: int = 0
    pending_migrations: tuple[int, ...] = ()
    integrity_check: str = "uninitialized"
    action_counts: dict[str, int] = field(default_factory=dict)
    outbox_event_count: int = 0
    outbox_latest_sequence: int = 0
    artifact_count: int = 0
    retrieval_count: int = 0
    team_count: int = 0
    match_count: int = 0
    quote_count: int = 0
    snapshot_count: int = 0
    forecast_count: int = 0
    ticket_count: int = 0
    settlement_count: int = 0
    projection_run_count: int = 0
    scorecard_count: int = 0
    factor_estimate_count: int = 0
    regime_vector_count: int = 0
    lifecycle_proposal_count: int = 0
    scoreboard_observation_count: int = 0
    scoreboard_shadow_review_count: int = 0
    scoreboard_authority_state: str = "uninitialized"

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "pending_migrations": list(self.pending_migrations)}


class OntologyKernel:
    def __init__(
        self,
        *,
        paths: OntologyPaths,
        engine: Engine,
        artifact_ingest: ArtifactIngestService,
        market_day_ingest: MarketDayIngestService,
        reconcile: ReconcileService,
        calibrate: CalibrateService,
        forecast_actions: ForecastActions,
        workflow: WorkflowActions,
        scoreboard_actions: ScoreboardActions,
        rsi_actions: RsiActions,
    ) -> None:
        self._paths = paths
        self._engine = engine
        self.artifact_ingest = artifact_ingest
        self.market_day_ingest = market_day_ingest
        self.reconcile = reconcile
        self.calibrate = calibrate
        self.forecast_actions = forecast_actions
        self.workflow = workflow
        self.scoreboard_actions = scoreboard_actions
        self.rsi_actions = rsi_actions

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
                pending_migrations=tuple(migration.version for migration in MIGRATIONS),
            )

        migration = migration_status(self._engine)
        applied = set(migration.applied_versions)
        counts: dict[str, object] = {}
        with self._engine.connect() as connection:
            integrity = connection.exec_driver_sql("PRAGMA integrity_check").scalar_one()
            counts["action_counts"] = {
                status: count
                for status, count in connection.execute(
                    select(schema.actions.c.status, func.count()).group_by(schema.actions.c.status)
                ).all()
            }
            artifacts = ArtifactRepository(connection)
            identity = IdentityRepository(connection)
            market = MarketRepository(connection)
            finance = FinanceRepository(connection)
            counts.update(
                artifact_count=artifacts.count_artifacts(),
                retrieval_count=artifacts.count_retrievals(),
                team_count=identity.count_teams(),
                match_count=identity.count_matches(),
                quote_count=market.count_quotes(),
                snapshot_count=market.count_snapshots(),
                forecast_count=DecisionRepository(connection).count_committed_revisions(),
                ticket_count=finance.count_tickets(),
                settlement_count=finance.count_settlements(),
            )
            outbox = OutboxRepository(connection)
            scoreboard = ScoreboardRepository(connection)
            counts.update(
                outbox_event_count=outbox.count(),
                outbox_latest_sequence=outbox.latest_sequence(),
                scoreboard_observation_count=scoreboard.count_observations(),
                scoreboard_shadow_review_count=scoreboard.count_shadow_reviews(),
                scoreboard_authority_state=scoreboard.authority().state,
            )
        from nutmeg.analytics.substrate import projection_counts

        projections = projection_counts(self._paths.analytics)
        for key in ("projection_run_count", "scorecard_count", "factor_estimate_count",
                    "regime_vector_count", "lifecycle_proposal_count"):
            counts[key] = projections[key]
        return OntologyKernelStatus(
            initialized=True,
            schema_version=migration.current_version,
            pending_migrations=tuple(m.version for m in MIGRATIONS if m.version not in applied),
            integrity_check=integrity,
            **counts,
        )
