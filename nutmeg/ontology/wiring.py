"""Compose ``AppSettings`` into a ready ontology kernel.

One engine and Action service back every domain facade: IngestArtifact, the
identity/match/market Actions and market-day ingest, and the person/observation/
claim Actions and evidence-day ingest — wired but not initialized. Construction is
side-effect-light: it never applies migrations, so ``status`` on a fresh kernel
still reports uninitialized.
"""

from __future__ import annotations

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.artifact_ingest import ArtifactIngestService
from nutmeg.ontology.actions.bundle_actions import BundleActions
from nutmeg.ontology.actions.capital_actions import CapitalActions
from nutmeg.ontology.actions.claim_actions import ClaimActions
from nutmeg.ontology.actions.entity_actions import EntityActions
from nutmeg.ontology.actions.factor_actions import FactorActions
from nutmeg.ontology.actions.forecast_actions import ForecastActions
from nutmeg.ontology.actions.market_actions import MarketActions
from nutmeg.ontology.actions.match_actions import MatchActions
from nutmeg.ontology.actions.observation_actions import ObservationActions
from nutmeg.ontology.actions.outcome_actions import OutcomeActions
from nutmeg.ontology.actions.person_actions import PersonActions
from nutmeg.ontology.actions.protected_ticket_actions import ProtectedTicketActions
from nutmeg.ontology.actions.reliability_actions import ReliabilityActions
from nutmeg.ontology.actions.rsi_actions import RsiActions
from nutmeg.ontology.actions.scoreboard_actions import ScoreboardActions
from nutmeg.ontology.actions.service import ActionService, ReplayActionContext
from nutmeg.ontology.actions.session_actions import SessionActions
from nutmeg.ontology.actions.ticket_actions import TicketActions
from nutmeg.ontology.actions.workflow_actions import WorkflowActions
from nutmeg.ontology.artifacts import ContentAddressedArtifactStore
from nutmeg.ontology.decision.read_flow import DecisionReadService
from nutmeg.ontology.finance.express_flow import ExpressService
from nutmeg.ontology.finance.reconcile_flow import ReconcileService
from nutmeg.ontology.ingest.evidence_day import EvidenceDayIngestService
from nutmeg.ontology.ingest.market_day import MarketDayIngestService
from nutmeg.ontology.kernel import OntologyKernel
from nutmeg.ontology.operator.decision_actions import OperatorDecisionActions
from nutmeg.ontology.operator.evidence_actions import EvidenceActions
from nutmeg.ontology.operator.result_actions import OperatorResultActions
from nutmeg.ontology.operator.review_actions import OperatorReviewActions
from nutmeg.ontology.operator.sale_actions import SaleActions
from nutmeg.ontology.paths import OntologyPaths
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.unit_of_work import (
    OntologyUnitOfWork,
    register_writer_lease_factory,
)


def build_ontology_kernel(settings: AppSettings) -> OntologyKernel:
    from nutmeg.analytics.calibrate_flow import CalibrateService
    from nutmeg.product.operator_runtime import OntologyWriterLease

    paths = OntologyPaths.from_data_dir(settings.data_dir)
    engine = build_ontology_engine(settings.ontology_db_path)
    register_writer_lease_factory(
        engine,
        lambda: OntologyWriterLease.shared(settings.data_dir),
    )
    unit_of_work_factory = lambda: OntologyUnitOfWork(engine)  # noqa: E731
    action_service = ActionService(unit_of_work_factory)
    artifact_store = ContentAddressedArtifactStore(settings.ontology_artifact_dir)
    artifact_ingest = ArtifactIngestService(
        action_service=action_service,
        artifact_store=artifact_store,
    )
    entity_actions = EntityActions(action_service)
    claim_actions = ClaimActions(action_service)
    factor_actions = FactorActions(action_service)
    forecast_actions = ForecastActions(action_service)
    market_day_ingest = MarketDayIngestService(
        artifact_ingest=artifact_ingest,
        entity_actions=entity_actions,
        match_actions=MatchActions(action_service),
        market_actions=MarketActions(action_service),
    )
    evidence_day_ingest = EvidenceDayIngestService(
        person_actions=PersonActions(action_service),
        observation_actions=ObservationActions(action_service),
        claim_actions=claim_actions,
    )
    decision_read = DecisionReadService(
        session_actions=SessionActions(action_service),
        bundle_actions=BundleActions(action_service),
        forecast_actions=forecast_actions,
    )
    express = ExpressService(ticket_actions=TicketActions(action_service))
    reconcile = ReconcileService(
        outcome_actions=OutcomeActions(action_service),
        unit_of_work_factory=unit_of_work_factory,
    )
    calibrate = CalibrateService(engine=engine, analytics_path=paths.analytics)
    workflow = WorkflowActions(action_service)
    scoreboard_actions = ScoreboardActions(action_service)
    reliability_actions = ReliabilityActions(action_service)
    rsi_actions = RsiActions(action_service)
    capital_actions = CapitalActions(action_service)
    decision_actions = OperatorDecisionActions(
        action_service,
        audit_token_signing_key=settings.operator_token_signing_key,
    )
    sale_actions = SaleActions(
        action_service,
        operator_decisions=decision_actions,
    )
    evidence_actions = EvidenceActions(action_service)
    protected_tickets = ProtectedTicketActions(
        action_service,
        artifact_store,
        operator_decisions=decision_actions,
    )
    result_actions = OperatorResultActions(action_service)
    review_actions = OperatorReviewActions(
        action_service,
        shadow_token_signing_key=settings.operator_token_signing_key,
    )
    return OntologyKernel(
        paths=paths,
        engine=engine,
        artifact_ingest=artifact_ingest,
        market_day_ingest=market_day_ingest,
        evidence_day_ingest=evidence_day_ingest,
        decision_read=decision_read,
        express=express,
        reconcile=reconcile,
        calibrate=calibrate,
        entity_actions=entity_actions,
        claim_actions=claim_actions,
        factor_actions=factor_actions,
        forecast_actions=forecast_actions,
        workflow=workflow,
        protected_tickets=protected_tickets,
        scoreboard_actions=scoreboard_actions,
        reliability_actions=reliability_actions,
        rsi_actions=rsi_actions,
        capital_actions=capital_actions,
        sale_actions=sale_actions,
        evidence_actions=evidence_actions,
        decision_actions=decision_actions,
        result_actions=result_actions,
        review_actions=review_actions,
    )


def build_replay_action_service(
    settings: AppSettings,
    context: ReplayActionContext,
) -> ActionService:
    """Build an Action service explicitly bound to one isolated replay run."""
    engine = build_ontology_engine(settings.ontology_db_path)
    return ActionService(
        lambda: OntologyUnitOfWork(engine),
        replay_context=context,
    )
