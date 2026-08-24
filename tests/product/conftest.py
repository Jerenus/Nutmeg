import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, insert, select

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.artifact_ingest import ArtifactIngestRequest
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.workflow_actions import (
    CreateAgentProposalRequest,
    RecordAdjudicationRequest,
)
from nutmeg.ontology.identity.models import EntityType, ResolutionStatus, TeamKind
from nutmeg.ontology.repository import schema_evidence as se
from nutmeg.ontology.repository import schema_identity as si
from nutmeg.ontology.repository.decision import EvidenceBundleRow, ForecastRevisionRow
from nutmeg.ontology.repository.evidence import (
    ClaimEvidenceSpanRow,
    ClaimRow,
    ObservationRow,
)
from nutmeg.ontology.repository.identity import (
    MatchRevisionRow,
    TeamAppearanceRow,
    TeamRow,
)
from nutmeg.ontology.repository.market import SnapshotRow
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel
from nutmeg.ontology.workflow.models import (
    AdjudicationRow,
    FlagInstanceRow,
    PrecedentLinkRow,
    PredictionRow,
    PredictionStatus,
)

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
            information_cutoff_at="2026-08-24T09:45:00+00:00",
            operator_prompt="Check the lineup evidence.",
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
            information_cutoff_at="2026-08-24T09:45:00+00:00",
            operator_prompt="Assess late home pressure.",
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
def m2_seeded_product(seeded_product: SeededProduct) -> SeededProduct:
    kernel = seeded_product.kernel
    with OntologyUnitOfWork(kernel.engine) as uow:
        latest_team_created_at = uow.connection.execute(
            select(func.max(si.teams.c.created_at))
        ).scalar_one()
        assert latest_team_created_at is not None
        queue_created_at = (
            datetime.fromisoformat(latest_team_created_at) + timedelta(microseconds=1)
        ).isoformat()
        uow.identity.insert_team(
            TeamRow(
                team_id="team-duplicate",
                team_kind=TeamKind.CLUB,
                canonical_name="Home Football Club",
                country="CN",
                resolution_status=ResolutionStatus.PROVISIONAL,
                created_at=queue_created_at,
            )
        )
        uow.identity.link_external_identifier(
            entity_id="team-duplicate",
            entity_type=EntityType.TEAM,
            provider="api-football",
            external_id="duplicate-home-1",
        )
        uow.identity.add_alias(
            "team-duplicate",
            EntityType.TEAM,
            "Home FC Duplicate",
            provider="api-football",
        )
    for source_name, content, retrieved_at in (
        (
            "sporttery",
            b"sporttery-fresh",
            datetime(2026, 8, 24, 9, 30, tzinfo=UTC),
        ),
        (
            "intl",
            b"international-stale",
            datetime(2026, 8, 24, 1, 0, tzinfo=UTC),
        ),
    ):
        kernel.artifact_ingest.ingest(
            ArtifactIngestRequest(
                content=content,
                content_type="application/json",
                source_name=source_name,
                source_type="fixture",
                actor_id=f"source:{source_name}",
                actor_role=ActorRole.CONNECTOR,
                idempotency_key=f"fixture:artifact:{source_name}",
                retrieved_at=retrieved_at,
            )
        )
    kernel.workflow.record_adjudication(
        RecordAdjudicationRequest(
            subject_type="claim",
            subject_id="claim-before",
            decision="approve",
            reason="AI must not adjudicate",
            evidence_rejected=[],
            alternative={},
            supersedes_adjudication_id=None,
            actor_id="model:fixture",
            actor_role=ActorRole.AI_ANALYST,
            idempotency_key="fixture:rejected-adjudication",
            requested_at=datetime(2026, 8, 24, 9, 55, tzinfo=UTC),
        )
    )
    return seeded_product


@pytest.fixture
def m3_seeded_product(m2_seeded_product: SeededProduct) -> SeededProduct:
    kernel = m2_seeded_product.kernel
    sporttery_artifact_id = "sha256:" + hashlib.sha256(b"sporttery-fresh").hexdigest()
    intl_artifact_id = "sha256:" + hashlib.sha256(b"international-stale").hexdigest()
    sporttery_retrieval_id = "RET-" + hashlib.sha256(
        b"fixture:artifact:sporttery"
    ).hexdigest()[:32]
    intl_retrieval_id = "RET-" + hashlib.sha256(
        b"fixture:artifact:intl"
    ).hexdigest()[:32]

    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.market.insert_snapshot(
            SnapshotRow(
                market_snapshot_id="snapshot-early",
                match_id="match-1",
                market_definition_id="md-had",
                snapshot_kind="read_time",
                as_of="2026-08-24T08:30:00+00:00",
                fair_distribution={"home": 0.48, "draw": 0.31, "away": 0.21},
                devig_method="proportional",
                method_version="1",
                source_coverage={"sources": 2},
                freshness={},
                disagreement={},
            )
        )
        uow.evidence.insert_claim(
            ClaimRow(
                claim_id="claim-conflict",
                subject_type="match",
                subject_id="match-1",
                predicate="availability_risk",
                value={"risk": "low"},
                scope_match_id="match-1",
                valid_from="2026-08-24T09:00:00+00:00",
                valid_to=None,
                status="verified",
                extractor="fixture",
                extractor_version="1",
                created_at="2026-08-24T09:25:00+00:00",
                adjudicated_at="2026-08-24T10:20:00+00:00",
            )
        )
        for span in (
            ClaimEvidenceSpanRow(
                claim_evidence_span_id="span-before",
                claim_id="claim-before",
                artifact_id=sporttery_artifact_id,
                artifact_retrieval_id=sporttery_retrieval_id,
                quote="home player unavailable",
                locator="line:1",
            ),
            ClaimEvidenceSpanRow(
                claim_evidence_span_id="span-conflict",
                claim_id="claim-conflict",
                artifact_id=intl_artifact_id,
                artifact_retrieval_id=intl_retrieval_id,
                quote="home player available",
                locator="line:2",
            ),
        ):
            uow.evidence.insert_evidence_span(span)
        uow.connection.execute(
            insert(se.observation_sources).values(
                observation_id="obs-before",
                artifact_retrieval_id=sporttery_retrieval_id,
            )
        )
        for event in (
            (
                "cse-before-created",
                "claim-before",
                None,
                "provisional",
                "fixture:claim-before:created",
                "2026-08-24T09:20:00+00:00",
            ),
            (
                "cse-conflict-created",
                "claim-conflict",
                None,
                "provisional",
                "fixture:claim-conflict:created",
                "2026-08-24T09:25:00+00:00",
            ),
            (
                "cse-before-verified",
                "claim-before",
                "provisional",
                "verified",
                "fixture:claim-before:verified",
                "2026-08-24T10:10:00+00:00",
            ),
            (
                "cse-conflict-verified",
                "claim-conflict",
                "provisional",
                "verified",
                "fixture:claim-conflict:verified",
                "2026-08-24T10:20:00+00:00",
            ),
        ):
            uow.evidence.insert_claim_status_event(*event)
        uow.evidence.update_claim_status(
            "claim-before", "verified", "2026-08-24T10:10:00+00:00"
        )
        uow.decision.insert_bundle(
            EvidenceBundleRow(
                evidence_bundle_id="bundle-fixture",
                match_id="match-1",
                decision_session_id=None,
                frozen_at="2026-08-24T09:55:00+00:00",
                information_cutoff_at="2026-08-24T09:50:00+00:00",
                market_snapshot_id="snapshot-before",
                prior_distribution={"home": 0.5, "draw": 0.3, "away": 0.2},
                identity_resolution_version="fixture-identity-v1",
                source_coverage={"sources": 2},
                freshness={"max_age_seconds": 300},
                content_hash="fixture-bundle-hash",
            )
        )
        uow.decision.add_bundle_item(
            "bundle-fixture", "observation", observation_id="obs-before"
        )
        uow.decision.add_bundle_item(
            "bundle-fixture", "caveat_claim", claim_id="claim-before"
        )
        uow.workflow.insert_flag_instance(
            FlagInstanceRow(
                flag_instance_id="flag-fixture",
                flag_type="anchor_shield_out",
                match_id="match-1",
                direction="draw",
                strength=0.8,
                evidence_refs=[{"object_type": "claim", "object_id": "claim-before"}],
                predicted_face="draw",
                status="active",
                created_at="2026-08-24T09:40:00+00:00",
            )
        )
        uow.workflow.insert_prediction(
            PredictionRow(
                prediction_id="prediction-fixture",
                match_id="match-1",
                claim="home protection remains weak",
                falsifier="starting midfielder returns",
                status=PredictionStatus.PENDING,
                outcome=None,
                registered_at="2026-08-24T09:41:00+00:00",
                settled_at=None,
            )
        )
        uow.workflow.insert_precedent_link(
            PrecedentLinkRow(
                precedent_link_id="precedent-fixture",
                subject_type="match",
                subject_id="match-1",
                precedent_match_id="match-1",
                scope="same_structure",
                evidence_refs=[{"object_type": "claim", "object_id": "claim-before"}],
                created_at="2026-08-24T09:42:00+00:00",
            )
        )
        uow.workflow.insert_adjudication(
            AdjudicationRow(
                adjudication_id="adjudication-fixture",
                subject_type="match",
                subject_id="match-1",
                decision="hold",
                actor_id="operator:owner",
                reason="await the official lineup",
                evidence_rejected=[
                    {"object_type": "claim", "object_id": "claim-conflict"}
                ],
                alternative={"next_action": "wait"},
                created_at="2026-08-24T09:43:00+00:00",
                supersedes_adjudication_id=None,
            )
        )
    return m2_seeded_product


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


@pytest.fixture
def m2_product_services(m2_seeded_product: SeededProduct):
    from nutmeg.product.actions import ProductActionGateway
    from nutmeg.product.queries import ProductQueryService
    from nutmeg.product.repository import ProductReadRepository

    repository = ProductReadRepository(m2_seeded_product.kernel.engine)
    return ProductTestServices(
        kernel=m2_seeded_product.kernel,
        queries=ProductQueryService(repository, m2_seeded_product.kernel),
        actions=ProductActionGateway(
            m2_seeded_product.kernel,
            repository,
            clock=lambda: m2_seeded_product.clock,
        ),
        settings=m2_seeded_product.settings,
    )


@pytest.fixture
def m3_product_services(m3_seeded_product: SeededProduct):
    from nutmeg.product.actions import ProductActionGateway
    from nutmeg.product.queries import ProductQueryService
    from nutmeg.product.repository import ProductReadRepository

    repository = ProductReadRepository(m3_seeded_product.kernel.engine)
    return ProductTestServices(
        kernel=m3_seeded_product.kernel,
        queries=ProductQueryService(repository, m3_seeded_product.kernel),
        actions=ProductActionGateway(
            m3_seeded_product.kernel,
            repository,
            clock=lambda: m3_seeded_product.clock + timedelta(hours=1),
        ),
        settings=m3_seeded_product.settings,
    )
