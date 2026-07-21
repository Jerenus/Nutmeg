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
from nutmeg.ontology.actions.claim_actions import ClaimActions
from nutmeg.ontology.actions.entity_actions import EntityActions
from nutmeg.ontology.actions.forecast_actions import ForecastActions
from nutmeg.ontology.actions.market_actions import MarketActions
from nutmeg.ontology.actions.match_actions import MatchActions
from nutmeg.ontology.actions.observation_actions import ObservationActions
from nutmeg.ontology.actions.outcome_actions import OutcomeActions
from nutmeg.ontology.actions.person_actions import PersonActions
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.actions.session_actions import SessionActions
from nutmeg.ontology.actions.ticket_actions import TicketActions
from nutmeg.ontology.artifacts import ContentAddressedArtifactStore
from nutmeg.ontology.decision.read_flow import DecisionReadService
from nutmeg.ontology.finance.express_flow import ExpressService
from nutmeg.ontology.finance.reconcile_flow import ReconcileService
from nutmeg.ontology.ingest.evidence_day import EvidenceDayIngestService
from nutmeg.ontology.ingest.market_day import MarketDayIngestService
from nutmeg.ontology.kernel import OntologyKernel
from nutmeg.ontology.paths import OntologyPaths
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def build_ontology_kernel(settings: AppSettings) -> OntologyKernel:
    paths = OntologyPaths.from_data_dir(settings.data_dir)
    engine = build_ontology_engine(settings.ontology_db_path)
    unit_of_work_factory = lambda: OntologyUnitOfWork(engine)  # noqa: E731
    action_service = ActionService(unit_of_work_factory)
    artifact_store = ContentAddressedArtifactStore(settings.ontology_artifact_dir)
    artifact_ingest = ArtifactIngestService(
        action_service=action_service,
        artifact_store=artifact_store,
    )
    market_day_ingest = MarketDayIngestService(
        artifact_ingest=artifact_ingest,
        entity_actions=EntityActions(action_service),
        match_actions=MatchActions(action_service),
        market_actions=MarketActions(action_service),
    )
    evidence_day_ingest = EvidenceDayIngestService(
        person_actions=PersonActions(action_service),
        observation_actions=ObservationActions(action_service),
        claim_actions=ClaimActions(action_service),
    )
    decision_read = DecisionReadService(
        session_actions=SessionActions(action_service),
        bundle_actions=BundleActions(action_service),
        forecast_actions=ForecastActions(action_service),
    )
    express = ExpressService(ticket_actions=TicketActions(action_service))
    reconcile = ReconcileService(
        outcome_actions=OutcomeActions(action_service),
        unit_of_work_factory=unit_of_work_factory,
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
    )
