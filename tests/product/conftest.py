from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.workflow_actions import CreateAgentProposalRequest
from nutmeg.ontology.identity.models import ResolutionStatus, TeamKind
from nutmeg.ontology.repository.decision import ForecastRevisionRow
from nutmeg.ontology.repository.evidence import ClaimRow, ObservationRow
from nutmeg.ontology.repository.identity import (
    MatchRevisionRow,
    TeamAppearanceRow,
    TeamRow,
)
from nutmeg.ontology.repository.market import SnapshotRow
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel

CLOCK = datetime(2026, 8, 24, 10, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class SeededProduct:
    kernel: object
    clock: datetime
    settings: AppSettings


@dataclass(frozen=True, slots=True)
class ProductTestServices:
    kernel: object
    queries: object
    actions: object
    settings: AppSettings


@pytest.fixture
def seeded_product(tmp_path: Path) -> SeededProduct:
    settings = AppSettings(data_dir=tmp_path / "data")
    kernel = build_ontology_kernel(settings)
    kernel.initialize()
    with OntologyUnitOfWork(kernel.engine) as uow:
        for team_id, name in (("team-home", "Home FC"), ("team-away", "Away FC")):
            uow.identity.insert_team(
                TeamRow(
                    team_id=team_id,
                    team_kind=TeamKind.CLUB,
                    canonical_name=name,
                    country="CN",
                    resolution_status=ResolutionStatus.RESOLVED,
                    created_at="2026-08-24T08:00:00+00:00",
                )
            )
        uow.identity.insert_match("match-1")
        uow.identity.insert_match_revision(
            MatchRevisionRow(
                match_revision_id="mr-before",
                match_id="match-1",
                version=1,
                competition_edition_id=None,
                scheduled_at="2026-08-24T12:00:00+00:00",
                schedule_status="confirmed",
                venue_id=None,
                status="scheduled",
                round_label=None,
                recorded_at="2026-08-24T08:00:00+00:00",
                supersedes_revision_id=None,
            )
        )
        uow.identity.insert_match_revision(
            MatchRevisionRow(
                match_revision_id="mr-future",
                match_id="match-1",
                version=2,
                competition_edition_id=None,
                scheduled_at="2026-08-24T13:00:00+00:00",
                schedule_status="confirmed",
                venue_id=None,
                status="scheduled",
                round_label=None,
                recorded_at="2026-08-24T11:00:00+00:00",
                supersedes_revision_id="mr-before",
            )
        )
        uow.identity.insert_team_appearance(
            TeamAppearanceRow("appearance-home", "match-1", "team-home", "home")
        )
        uow.identity.insert_team_appearance(
            TeamAppearanceRow("appearance-away", "match-1", "team-away", "away")
        )
        uow.market.insert_snapshot(
            SnapshotRow(
                market_snapshot_id="snapshot-before",
                match_id="match-1",
                market_definition_id="md-had",
                snapshot_kind="read_time",
                as_of="2026-08-24T09:00:00+00:00",
                fair_distribution={"home": 0.5, "draw": 0.3, "away": 0.2},
                devig_method="proportional",
                method_version="1",
                source_coverage={"sources": 3},
                freshness={},
                disagreement={},
            )
        )
        uow.market.insert_snapshot(
            SnapshotRow(
                market_snapshot_id="snapshot-future",
                match_id="match-1",
                market_definition_id="md-had",
                snapshot_kind="read_time",
                as_of="2026-08-24T10:30:00+00:00",
                fair_distribution={"home": 0.45, "draw": 0.3, "away": 0.25},
                devig_method="proportional",
                method_version="1",
                source_coverage={"sources": 3},
                freshness={},
                disagreement={},
            )
        )
        uow.evidence.insert_observation(
            ObservationRow(
                observation_id="obs-before",
                observation_type="availability",
                subject_type="match",
                subject_id="match-1",
                scope_match_id="match-1",
                value={"home_absent": 1},
                schema_version="1",
                valid_from="2026-08-24T09:00:00+00:00",
                valid_to=None,
                observed_at="2026-08-24T09:15:00+00:00",
                recorded_at="2026-08-24T09:30:00+00:00",
                verification_method="official",
                quality={"grade": "A"},
            )
        )
        uow.evidence.insert_observation(
            ObservationRow(
                observation_id="obs-future",
                observation_type="lineup",
                subject_type="match",
                subject_id="match-1",
                scope_match_id="match-1",
                value={"confirmed": True},
                schema_version="1",
                valid_from="2026-08-24T10:30:00+00:00",
                valid_to=None,
                observed_at="2026-08-24T10:30:00+00:00",
                recorded_at="2026-08-24T10:31:00+00:00",
                verification_method="official",
                quality={"grade": "A"},
            )
        )
        uow.evidence.insert_claim(
            ClaimRow(
                claim_id="claim-before",
                subject_type="match",
                subject_id="match-1",
                predicate="availability_risk",
                value={"risk": "medium"},
                scope_match_id="match-1",
                valid_from="2026-08-24T09:00:00+00:00",
                valid_to=None,
                status="provisional",
                extractor="fixture",
                extractor_version="1",
                created_at="2026-08-24T09:20:00+00:00",
                adjudicated_at=None,
            )
        )
        series_id = uow.decision.ensure_series("match-1", "md-had")
        uow.decision.insert_revision(
            ForecastRevisionRow(
                forecast_revision_id="fr-legacy",
                forecast_series_id=series_id,
                decision_session_id=None,
                revision_no=1,
                status="committed",
                made_at="2026-08-24T09:45:00+00:00",
                information_cutoff_at=None,
                prior_snapshot_id="snapshot-before",
                prior_distribution={"home": 0.5, "draw": 0.3, "away": 0.2},
                belief_distribution={"home": 0.52, "draw": 0.28, "away": 0.2},
                evidence_bundle_id=None,
                falsifier="lineup changes",
                actor_id="operator:owner",
                model_name=None,
                model_version=None,
                policy_version="governance-v1",
                commitment_tier="judged",
                evidence_coverage=None,
                evidence_quality=None,
                forecast_stability=None,
                supersedes_revision_id=None,
            )
        )
    kernel.workflow.create_agent_proposal(
        CreateAgentProposalRequest(
            subject_type="match",
            subject_id="match-1",
            proposal_type="investigation_note",
            payload={"note": "check lineup"},
            citation_refs=[{"object_type": "observation", "object_id": "obs-before"}],
            model_name="fixture-agent",
            model_version="1",
            actor_id="model:fixture",
            actor_role=ActorRole.AI_ANALYST,
            idempotency_key="fixture:proposal:1",
            requested_at=datetime(2026, 8, 24, 9, 50, tzinfo=UTC),
        )
    )
    kernel.workflow.create_agent_proposal(
        CreateAgentProposalRequest(
            subject_type="match",
            subject_id="match-1",
            proposal_type="scenario_note",
            payload={"note": "late home pressure"},
            citation_refs=[{"object_type": "observation", "object_id": "obs-before"}],
            model_name="fixture-agent",
            model_version="1",
            actor_id="model:fixture",
            actor_role=ActorRole.AI_ANALYST,
            idempotency_key="fixture:proposal:2",
            requested_at=datetime(2026, 8, 24, 9, 51, tzinfo=UTC),
        )
    )
    return SeededProduct(kernel=kernel, clock=CLOCK, settings=settings)


@pytest.fixture
def product_services(seeded_product: SeededProduct):
    from nutmeg.product.actions import ProductActionGateway
    from nutmeg.product.queries import ProductQueryService
    from nutmeg.product.repository import ProductReadRepository

    repository = ProductReadRepository(seeded_product.kernel.engine)
    return ProductTestServices(
        kernel=seeded_product.kernel,
        queries=ProductQueryService(repository, seeded_product.kernel),
        actions=ProductActionGateway(
            seeded_product.kernel, repository, clock=lambda: seeded_product.clock
        ),
        settings=seeded_product.settings,
    )
