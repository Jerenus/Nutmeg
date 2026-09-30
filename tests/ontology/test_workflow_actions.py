from datetime import UTC, datetime
from pathlib import Path

import pytest

from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.actions.workflow_actions import (
    CreateAgentProposalRequest,
    RecordAdjudicationRequest,
    RegisterPredictionRequest,
    ResolveAgentProposalRequest,
    WorkflowActions,
)
from nutmeg.ontology.errors import OptimisticConcurrencyError
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.evidence import ObservationRow
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.workflow.models import PredictionStatus, ProposalStatus

AT = datetime(2026, 8, 24, 10, tzinfo=UTC)


def _setup(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.identity.insert_match_minimal("match-1")
        uow.identity.insert_match_minimal("match-precedent")
        uow.identity.insert_match_minimal("match-other")
        for observation_id, match_id, recorded_at in (
            ("obs-1", "match-1", "2026-08-24T09:30:00+00:00"),
            ("obs-future", "match-1", "2026-08-24T10:01:00+00:00"),
            ("obs-other", "match-other", "2026-08-24T09:30:00+00:00"),
        ):
            uow.evidence.insert_observation(
                ObservationRow(
                    observation_id=observation_id,
                    observation_type="availability",
                    subject_type="match",
                    subject_id=match_id,
                    scope_match_id=match_id,
                    value={"available": observation_id == "obs-1"},
                    schema_version="1",
                    valid_from="2026-08-24T09:00:00+00:00",
                    valid_to=None,
                    observed_at=recorded_at,
                    recorded_at=recorded_at,
                    verification_method="official",
                    quality={"grade": "A"},
                )
            )
    service = ActionService(lambda: OntologyUnitOfWork(engine))
    return WorkflowActions(service), engine


def _proposal(
    *,
    role: ActorRole = ActorRole.AI_ANALYST,
    key: str = "proposal:create:1",
    citation_refs: list[dict[str, str]] | None = None,
    operator_prompt: str = "Investigate the verified availability evidence.",
) -> CreateAgentProposalRequest:
    return CreateAgentProposalRequest(
        subject_type="match",
        subject_id="match-1",
        proposal_type="forecast",
        payload={"belief": {"home": 0.52, "draw": 0.28, "away": 0.2}},
        citation_refs=(
            [{"object_type": "observation", "object_id": "obs-1"}]
            if citation_refs is None
            else citation_refs
        ),
        information_cutoff_at=AT.isoformat(),
        operator_prompt=operator_prompt,
        model_name="analyst-agent",
        model_version="2026-08-24",
        actor_id="model:analyst",
        actor_role=role,
        idempotency_key=key,
        requested_at=AT,
    )


def _resolve(
    proposal_id: str,
    *,
    expected_version: int = 1,
    key: str = "proposal:resolve:1",
) -> ResolveAgentProposalRequest:
    return ResolveAgentProposalRequest(
        agent_proposal_id=proposal_id,
        resolution=ProposalStatus.APPROVED,
        expected_version=expected_version,
        actor_id="operator:owner",
        actor_role=ActorRole.JUDGE_OPERATOR,
        idempotency_key=key,
        requested_at=AT,
    )


def test_ai_proposal_is_not_an_adjudication(tmp_path: Path) -> None:
    workflow, engine = _setup(tmp_path)

    proposal = workflow.create_agent_proposal(_proposal())

    assert proposal.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        row = uow.workflow.get_agent_proposal(proposal.result_refs[0].object_id)
        assert row.status is ProposalStatus.PENDING
        assert row.information_cutoff_at == AT.isoformat()
        assert row.operator_prompt == "Investigate the verified availability evidence."
        assert uow.workflow.count_adjudications() == 0


@pytest.mark.parametrize(
    ("label", "citation_refs"),
    (
        ("empty", []),
        ("future", [{"object_type": "observation", "object_id": "obs-future"}]),
        ("foreign", [{"object_type": "observation", "object_id": "obs-other"}]),
        ("missing", [{"object_type": "observation", "object_id": "obs-missing"}]),
        ("unsupported", [{"object_type": "action", "object_id": "action-1"}]),
        (
            "duplicate",
            [
                {"object_type": "observation", "object_id": "obs-1"},
                {"object_type": "observation", "object_id": "obs-1"},
            ],
        ),
    ),
)
def test_proposal_rejects_invalid_citations(
    tmp_path: Path,
    label: str,
    citation_refs: list[dict[str, str]],
) -> None:
    workflow, _engine = _setup(tmp_path)

    with pytest.raises(ValueError, match="citation"):
        workflow.create_agent_proposal(
            _proposal(key=f"proposal:invalid:{label}", citation_refs=citation_refs)
        )


def test_judge_cannot_create_ai_proposal(tmp_path: Path) -> None:
    workflow, _engine = _setup(tmp_path)

    outcome = workflow.create_agent_proposal(
        _proposal(role=ActorRole.JUDGE_OPERATOR, key="proposal:judge:denied")
    )

    assert outcome.status is ActionStatus.REJECTED


def test_proposal_requires_operator_prompt(tmp_path: Path) -> None:
    workflow, _engine = _setup(tmp_path)

    with pytest.raises(ValueError, match="operator_prompt"):
        workflow.create_agent_proposal(
            _proposal(key="proposal:blank-prompt", operator_prompt=" ")
        )


def test_ai_cannot_record_operator_adjudication(tmp_path: Path) -> None:
    workflow, _engine = _setup(tmp_path)
    request = RecordAdjudicationRequest(
        subject_type="claim",
        subject_id="claim-1",
        decision="approve",
        reason="unsupported by verified evidence",
        evidence_rejected=[{"object_type": "claim", "object_id": "claim-2"}],
        alternative={"decision": "hold"},
        supersedes_adjudication_id=None,
        actor_id="model:analyst",
        actor_role=ActorRole.AI_ANALYST,
        idempotency_key="adjudication:denied",
        requested_at=AT,
    )

    outcome = workflow.record_adjudication(request)

    assert outcome.status is ActionStatus.REJECTED


def test_operator_records_adjudication_with_rejected_evidence(tmp_path: Path) -> None:
    workflow, engine = _setup(tmp_path)
    request = RecordAdjudicationRequest(
        subject_type="claim",
        subject_id="claim-1",
        decision="reject",
        reason="source is superseded",
        evidence_rejected=[{"object_type": "claim", "object_id": "claim-2"}],
        alternative={"use": "claim-3"},
        supersedes_adjudication_id=None,
        actor_id="operator:owner",
        actor_role=ActorRole.JUDGE_OPERATOR,
        idempotency_key="adjudication:1",
        requested_at=AT,
    )

    outcome = workflow.record_adjudication(request)

    assert outcome.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        row = uow.workflow.get_adjudication(outcome.result_refs[0].object_id)
        assert row.reason == "source is superseded"
        assert row.evidence_rejected == [
            {"object_id": "claim-2", "object_type": "claim"}
        ]
        assert row.alternative == {"use": "claim-3"}


def test_operator_resolves_proposal_without_mutating_payload(tmp_path: Path) -> None:
    workflow, engine = _setup(tmp_path)
    created = workflow.create_agent_proposal(_proposal())
    proposal_id = created.result_refs[0].object_id

    resolved = workflow.resolve_agent_proposal(_resolve(proposal_id))

    assert resolved.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        row = uow.workflow.get_agent_proposal(proposal_id)
        assert row.status is ProposalStatus.APPROVED
        assert row.version == 2
        assert row.payload == {
            "belief": {"home": 0.52, "draw": 0.28, "away": 0.2}
        }


def test_proposal_resolution_revalidates_stored_citations(tmp_path: Path) -> None:
    workflow, engine = _setup(tmp_path)
    created = workflow.create_agent_proposal(_proposal())
    proposal_id = created.result_refs[0].object_id
    with OntologyUnitOfWork(engine) as uow:
        uow.connection.exec_driver_sql(
            "DELETE FROM observations WHERE observation_id = 'obs-1'"
        )

    with pytest.raises(ValueError, match="citation"):
        workflow.resolve_agent_proposal(_resolve(proposal_id))

    with OntologyUnitOfWork(engine) as uow:
        assert uow.workflow.get_agent_proposal(proposal_id).status is ProposalStatus.PENDING


def test_stale_proposal_resolution_is_rejected(tmp_path: Path) -> None:
    workflow, _engine = _setup(tmp_path)
    created = workflow.create_agent_proposal(_proposal())
    proposal_id = created.result_refs[0].object_id
    workflow.resolve_agent_proposal(_resolve(proposal_id))

    with pytest.raises(OptimisticConcurrencyError):
        workflow.resolve_agent_proposal(
            _resolve(proposal_id, expected_version=1, key="proposal:resolve:stale")
        )


def test_prediction_is_typed_and_governed(tmp_path: Path) -> None:
    """flag/precedent 入账 2026-10-01 随内核瘦身退役（记分牌是唯一事实源）；预测登记仍是活路径。"""
    workflow, engine = _setup(tmp_path)

    prediction = workflow.register_prediction(
        RegisterPredictionRequest(
            match_id="match-1",
            subject_type="match",
            subject_id="match-1",
            claim="away price shortens before close",
            falsifier="away price stays flat or lengthens",
            actor_id="model:analyst",
            actor_role=ActorRole.AI_ANALYST,
            idempotency_key="prediction:1",
            requested_at=AT,
        )
    )

    assert prediction.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        prediction_row = uow.workflow.get_prediction(prediction.result_refs[0].object_id)
        assert prediction_row.status is PredictionStatus.PENDING
        assert prediction_row.outcome is None
