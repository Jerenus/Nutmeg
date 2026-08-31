from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from nutmeg.ontology.actions.models import ActorRole
from nutmeg.product.contracts import ProductActionResponse
from nutmeg.product.errors import ProductActionBlockedError
from nutmeg.product.operator_actions import OperatorActionService
from nutmeg.product.operator_contracts import (
    AuditDeploymentStep,
    BusinessEvidenceSummary,
    ConfirmationStep,
    ConstructTicketStep,
    OperatorLane,
    OperatorTaskResponse,
    OperatorTaskState,
    OperatorTaskSummary,
    PrescriptionDeviationCommand,
    PrescriptionDifferenceSummary,
    RecordDeploymentCommand,
    RequestTelegramConfirmationCommand,
    ResolveIssueAdjudicationCommand,
    SelectTicketVersionCommand,
    TaskProgressSummary,
    TicketVersionSummary,
)

NOW = datetime(2026, 8, 28, 10, tzinfo=UTC)
TOKEN = "a" * 64


class FakeQueries:
    def __init__(self, step) -> None:
        self.step = step
        self.token = TOKEN

    def now(self) -> datetime:
        return NOW

    def task(self, task_id: str, *, as_of: datetime):
        lane = OperatorLane.JCZQ if task_id.startswith("jczq:") else OperatorLane.ZUCAI
        summary = OperatorTaskSummary(
            task_id=task_id,
            lane=lane,
            business_key=task_id.split(":", 1)[1],
            title="fixture",
            state=OperatorTaskState(self.step.kind),
            is_actionable=True,
            next_action_label="继续",
            priority_rank=0,
        )
        return OperatorTaskResponse(
            as_of=as_of,
            mutation_token=self.token,
            selected=summary,
            alternatives=[],
            progress=TaskProgressSummary(completed=0, total=1, label="fixture"),
            step=self.step,
        )


class FakeActionGateway:
    def __init__(self) -> None:
        self.requests = []

    def execute(self, request, *, actor_id, actor_role):
        self.requests.append(request)
        return ProductActionResponse(
            action_id="action-1",
            action_type=request.action_type,
            status="committed",
            committed_at=NOW.isoformat(),
        )


class FakeTelegram:
    def __init__(self) -> None:
        self.calls = []

    def request_confirmation(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            ticket_artifact_id=kwargs["ticket_artifact_id"],
            confirmation_id="confirmation-1",
            expires_at=(NOW + timedelta(minutes=5)).isoformat(),
            text="请确认已人工出票",
            callback_data="must-not-leak",
        )


def _candidate() -> TicketVersionSummary:
    return TicketVersionSummary(
        candidate_id="R432",
        label="R432",
        faces={"12": "3", "13": "31"},
        notes=2,
        cost_yuan=4,
        p_all=0.4,
        expected_broken=0.8,
        within_cap=True,
        prescription_differences=[
            PrescriptionDifferenceSummary(
                match_no=12,
                prescribed_faces="31",
                candidate_faces="3",
            ),
            PrescriptionDifferenceSummary(
                match_no=13,
                prescribed_faces="3",
                candidate_faces="31",
            ),
        ],
    )


def _service(step, *, telegram=None, owner=111) -> OperatorActionService:
    return OperatorActionService(
        queries=FakeQueries(step),
        action_gateway=FakeActionGateway(),
        telegram_confirmation=telegram,
        telegram_owner_chat_id=owner,
    )


def _judge_step():
    from nutmeg.product.operator_contracts import JudgeMatchesStep

    return JudgeMatchesStep(
        task_id="zucai:26112",
        item_key="ADJ-1",
        title="任九档位",
        prompt="选择档位",
        options=["R432", "V288"],
    )


def _construct_step():
    return ConstructTicketStep(
        task_id="zucai:26112",
        prescription={"12": "31", "13": "3"},
        candidates=[_candidate()],
    )


def _audit_step():
    return AuditDeploymentStep(
        task_id="zucai:26112",
        candidate=_candidate(),
        gate_candidate_id="R432",
        gate_candidate_cost_yuan=4,
        audit_state="pass",
        findings=[BusinessEvidenceSummary(label="部署门", value="通过")],
        deployment_state="pass",
        capital_utilization=0.01,
        median_bonus=1000,
        break_even_to_median=0.01,
        allowed_decisions=["keep", "change_structure"],
    )


def _valid_selection() -> SelectTicketVersionCommand:
    return SelectTicketVersionCommand(
        expected_snapshot_token=TOKEN,
        candidate_id="R432",
        reason="采用 R432",
        deviations=[
            PrescriptionDeviationCommand(
                match_no=12,
                rule_ids=["q-两阶段"],
                reason="丢场式减注登记",
            ),
            PrescriptionDeviationCommand(
                match_no=13,
                rule_ids=["处方优先"],
                reason="双选覆盖已命名偏离",
            ),
        ],
        idempotency_key="candidate:1",
    )


def test_resolve_issue_adjudication_writes_named_typed_action() -> None:
    service = _service(_judge_step())
    result = service.resolve_issue_adjudication(
        "zucai:26112",
        ResolveIssueAdjudicationCommand(
            expected_snapshot_token=TOKEN,
            adjudication_key="ADJ-1",
            decision="override",
            reason="Jun selected the disclosed exception",
            selected_option="R432",
            evidence_rejected=[{"object_type": "claim", "object_id": "claim-1"}],
            idempotency_key="ui:26112:ADJ-1",
        ),
        actor_id="owner",
        actor_role=ActorRole.JUDGE_OPERATOR,
    )

    assert result.status == "committed"
    request = service.action_gateway.requests[-1]
    assert request.action_type == "record_adjudication"
    assert request.payload["subject_type"] == "issue"
    assert request.payload["subject_id"] == "26112"
    assert request.payload["alternative"] == {
        "rx_adjudication_id": "ADJ-1",
        "selected_option": "R432",
    }


def test_select_candidate_records_named_rules() -> None:
    service = _service(_construct_step())
    service.select_ticket_version(
        "zucai:26112",
        _valid_selection(),
        actor_id="owner",
        actor_role=ActorRole.JUDGE_OPERATOR,
    )
    alternative = service.action_gateway.requests[-1].payload["alternative"]
    assert alternative == {
        "candidate_id": "R432",
        "deviation_registry": [
            {
                "match_no": 12,
                "rule_ids": ["q-两阶段"],
                "reason": "丢场式减注登记",
            },
            {
                "match_no": 13,
                "rule_ids": ["处方优先"],
                "reason": "双选覆盖已命名偏离",
            },
        ],
    }


def test_candidate_selection_requires_registration_for_every_actual_diff() -> None:
    service = _service(_construct_step())
    command = _valid_selection().model_copy(
        update={"deviations": _valid_selection().deviations[:1]}
    )
    with pytest.raises(ProductActionBlockedError, match="13.*偏离登记"):
        service.select_ticket_version(
            "zucai:26112",
            command,
            actor_id="owner",
            actor_role=ActorRole.JUDGE_OPERATOR,
        )


def test_stale_snapshot_token_writes_no_action() -> None:
    service = _service(_construct_step())
    stale = _valid_selection().model_copy(update={"expected_snapshot_token": "f" * 64})
    with pytest.raises(ProductActionBlockedError, match="form was opened"):
        service.select_ticket_version(
            "zucai:26112",
            stale,
            actor_id="owner",
            actor_role=ActorRole.JUDGE_OPERATOR,
        )
    assert service.action_gateway.requests == []


@pytest.mark.parametrize("role", [ActorRole.AI_ANALYST, ActorRole.DETERMINISTIC_SYSTEM])
def test_non_judge_roles_cannot_mutate_operator_task(role) -> None:
    service = _service(_construct_step())
    with pytest.raises(ProductActionBlockedError, match="judge_operator"):
        service.select_ticket_version(
            "zucai:26112",
            _valid_selection(),
            actor_id="not-owner",
            actor_role=role,
        )


def test_empty_position_is_rejected_when_gate_does_not_offer_it() -> None:
    service = _service(_audit_step())
    with pytest.raises(ProductActionBlockedError, match="not allowed by current gate"):
        service.record_deployment(
            "zucai:26112",
            RecordDeploymentCommand(
                expected_snapshot_token=TOKEN,
                candidate_id="R432",
                decision="empty_position",
                reason="generic caution is not enough",
                idempotency_key="ui:26112:deployment",
            ),
            actor_id="owner",
            actor_role=ActorRole.JUDGE_OPERATOR,
        )


def test_telegram_uses_bound_artifact_and_configured_owner() -> None:
    telegram = FakeTelegram()
    service = _service(
        ConfirmationStep(
            task_id="jczq:2026-08-28",
            ticket_artifact_id="tat-1",
            amount=100,
            currency="CNY",
            deadline_at=NOW + timedelta(hours=2),
            confirmation_state="not_issued",
        ),
        telegram=telegram,
    )
    result = service.request_telegram_confirmation(
        "jczq:2026-08-28",
        RequestTelegramConfirmationCommand(
            expected_snapshot_token=TOKEN,
            idempotency_key="telegram:1",
            dry_run=True,
        ),
        actor_id="owner",
        actor_role=ActorRole.JUDGE_OPERATOR,
    )

    assert telegram.calls[-1] == {
        "ticket_artifact_id": "tat-1",
        "chat_id": 111,
        "dry_run": True,
        "requested_at": NOW,
    }
    assert result.dispatch_state == "dry_run"
    assert "callback" not in result.model_dump_json()


@pytest.mark.parametrize("field", ["actor_id", "actor_role", "chat_id", "amount", "hash"])
def test_commands_reject_server_owned_fields(field: str) -> None:
    payload = _valid_selection().model_dump(mode="json")
    payload[field] = "spoofed"
    with pytest.raises(ValidationError):
        SelectTicketVersionCommand.model_validate(payload)
