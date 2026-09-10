from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nutmeg.interfaces.operator_api import RecordNoTicketCommandV2, mount_operator_api
from nutmeg.ontology.actions.models import ActionStatus
from nutmeg.product.contracts import ProductActionResponse
from nutmeg.product.operator_actions import OperatorActionService
from nutmeg.product.operator_contracts import (
    AuditDeploymentStep,
    DeploymentAuditFindingSummary,
    DeploymentCandidateSummary,
    OperatorCommandReceipt,
    OperatorLane,
)
from nutmeg.product.operator_queries import ConfirmationRequestCommandContext
from nutmeg.product.operator_tokens import (
    OperatorCommandKind,
    OperatorSnapshotTokenCodec,
    OperatorSnapshotTokenPayloadV1,
)

TASK_KEY = "zucai:26111"
NOW = datetime(2026, 9, 4, 9, tzinfo=UTC)
TOKEN_KEY = b"package-eight-deployment-api-signing-key"


class _Actions:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def _record(self, kind: str, command) -> OperatorCommandReceipt:
        self.calls.append((kind, command))
        return OperatorCommandReceipt(
            command_kind=kind,
            status="completed",
            task_key=command.task_key,
        )

    def record_no_ticket(self, command, **_authority) -> OperatorCommandReceipt:
        return self._record("record_no_ticket", command)

    def supersede_no_ticket(self, command, **_authority) -> OperatorCommandReceipt:
        return self._record("supersede_no_ticket", command)

    def create_ticket_batch(self, command, **_authority) -> OperatorCommandReceipt:
        return self._record("create_ticket_batch", command)

    def adjudicate_audit_warn(self, command, **_authority) -> OperatorCommandReceipt:
        return self._record("adjudicate_audit_warn", command)

    def approve_ticket_batch(self, command, **_authority) -> OperatorCommandReceipt:
        return self._record("approve_ticket_batch", command)

    def request_confirmation(self, command, **_authority) -> OperatorCommandReceipt:
        return self._record("request_confirmation", command)


def _client(actions: _Actions | None = None) -> tuple[TestClient, _Actions]:
    app = FastAPI()

    async def allow(_request) -> None:
        return None

    configured = actions or _Actions()
    mount_operator_api(
        app,
        require_mutation_session=allow,
        operator_actions=configured,
        actor_id="jun",
    )
    return TestClient(app), configured


def _command(kind: str, **fields: object) -> dict[str, object]:
    return {
        "schema_version": "2",
        "kind": kind,
        "expected_snapshot_token": f"opaque.{kind}.command",
        "idempotency_key": f"browser:{kind}:1",
        "task_key": TASK_KEY,
        **fields,
    }


def test_deployment_commands_route_through_the_closed_operator_gateway() -> None:
    client, actions = _client()
    documents = (
        _command(
            "record_no_ticket",
            reason_code="operator_discretion",
            reason_basis="operator_judgment",
            reason_text="Jun explicitly closed the remaining scope.",
            rule_tokens=[],
            comparison_candidate_token=None,
        ),
        _command(
            "supersede_no_ticket",
            no_ticket_revision_token="opaque.no-ticket.revision",
            reason_text="Jun explicitly reopened the still-open offer scope.",
        ),
        _command(
            "create_ticket_batch",
            candidate_selection_token="opaque.candidate.selection",
        ),
        _command(
            "adjudicate_audit_warn",
            ticket_batch_token="opaque.ticket.batch",
            findings=[
                {
                    "finding_token": "opaque.audit.warn",
                    "reason": "Jun accepts this disclosed warning.",
                    "evidence_rejected_tokens": [],
                }
            ],
        ),
        _command(
            "approve_ticket_batch",
            ticket_batch_token="opaque.ticket.batch",
        ),
        _command(
            "request_confirmation",
            ticket_artifact_token="opaque.ticket.artifact",
        ),
    )

    responses = [client.post("/api/v2/operator", json=document) for document in documents]

    assert [response.status_code for response in responses] == [200, 200, 200, 200, 200, 202]
    assert [kind for kind, _command_value in actions.calls] == [
        "record_no_ticket",
        "supersede_no_ticket",
        "create_ticket_batch",
        "adjudicate_audit_warn",
        "approve_ticket_batch",
        "request_confirmation",
    ]
    assert all(
        "actor_id" not in command.model_dump() and "actor_role" not in command.model_dump()
        for _kind, command in actions.calls
    )


def test_deployment_commands_reject_browser_authority_ids_deadlines_and_override() -> None:
    client, actions = _client()
    invalid = (
        _command(
            "record_no_ticket",
            reason_code="operator_discretion",
            reason_basis="operator_judgment",
            reason_text="human reason",
            rule_tokens=[],
            actor_role="judge_operator",
        ),
        _command(
            "create_ticket_batch",
            candidate_selection_id="selection-raw-id",
            candidate_selection_token="opaque.selection",
        ),
        _command(
            "create_ticket_batch",
            candidate_selection_token="opaque.selection",
            deadline_at="2099-01-01T00:00:00+00:00",
        ),
        _command(
            "approve_ticket_batch",
            ticket_batch_token="opaque.ticket.batch",
            audit_error_override=True,
        ),
        _command(
            "record_ticket_audit_override",
            ticket_batch_token="opaque.ticket.batch",
        ),
        _command(
            "confirm_ticket_placement",
            ticket_artifact_token="opaque.ticket.artifact",
        ),
    )

    assert all(
        client.post("/api/v2/operator", json=document).status_code == 422
        for document in invalid
    )
    assert actions.calls == []


def test_no_ticket_has_no_default_reason_and_rule_basis_requires_rule_tokens() -> None:
    client, actions = _client()

    missing_reason = _command(
        "record_no_ticket",
        reason_basis="operator_judgment",
        reason_text="human reason",
        rule_tokens=[],
    )
    inferred_basis = _command(
        "record_no_ticket",
        reason_code="discipline_brake",
        reason_text="human reason",
        rule_tokens=["opaque.rule"],
    )
    rule_without_token = _command(
        "record_no_ticket",
        reason_code="discipline_brake",
        reason_basis="rule_derived",
        reason_text="human reason",
        rule_tokens=[],
    )

    assert client.post("/api/v2/operator", json=missing_reason).status_code == 422
    assert client.post("/api/v2/operator", json=inferred_basis).status_code == 422
    assert client.post("/api/v2/operator", json=rule_without_token).status_code == 422
    assert actions.calls == []


def _token(kind: OperatorCommandKind, *dependencies: str) -> str:
    return OperatorSnapshotTokenCodec(TOKEN_KEY).encode(
        OperatorSnapshotTokenPayloadV1(
            task_snapshot_hash="a" * 64,
            work_item_id="zucai:26111:issue:current",
            command_kind=kind,
            dependency_revision_ids=sorted(dependencies),
        )
    )


class _DeploymentQueries:
    def __init__(self, step: AuditDeploymentStep) -> None:
        self.step = step

    def task(self, task_key: str, *, as_of: datetime):
        assert task_key == TASK_KEY
        assert as_of == NOW
        return SimpleNamespace(
            selected=SimpleNamespace(
                lane=OperatorLane.ZUCAI,
                business_key="26111",
            ),
            step=self.step,
        )

    def confirmation_request_context(
        self,
        task_key: str,
        ticket_artifact_token: str,
        *,
        as_of: datetime,
    ) -> ConfirmationRequestCommandContext:
        assert task_key == TASK_KEY
        assert as_of == NOW
        assert ticket_artifact_token == self.step.ticket_artifact_token
        assert self.step.command_token is not None
        payload = OperatorSnapshotTokenCodec(TOKEN_KEY).decode(self.step.command_token)
        dependency = payload.dependency_revision_ids[0]
        return ConfirmationRequestCommandContext(
            task_key=task_key,
            task_snapshot_hash=payload.task_snapshot_hash,
            work_item_id=payload.work_item_id,
            dependency_revision_ids=tuple(payload.dependency_revision_ids),
            ticket_artifact_id=dependency.removeprefix("ticket_artifact:"),
            command_token=self.step.command_token,
            ticket_artifact_token=ticket_artifact_token,
        )

    def now(self) -> datetime:
        return NOW


class _AdjudicationGateway:
    def __init__(self) -> None:
        self.calls = []

    def execute(self, request, *, actor_id, actor_role) -> ProductActionResponse:
        self.calls.append((request, actor_id, actor_role))
        return ProductActionResponse(
            action_id="ACT-warn",
            action_type="record_adjudication",
            status="committed",
        )


def test_warn_api_resolves_signed_findings_into_typed_adjudications() -> None:
    command_token = _token(
        OperatorCommandKind.ADJUDICATE_AUDIT_WARN,
        "finding:finding-warn-1",
        "ticket_batch_revision:batch-draft-1",
    )
    finding_token = _token(
        OperatorCommandKind.ADJUDICATE_AUDIT_WARN,
        "finding:finding-warn-1",
    )
    batch_token = _token(
        OperatorCommandKind.ADJUDICATE_AUDIT_WARN,
        "ticket_batch_revision:batch-draft-1",
    )
    step = AuditDeploymentStep(
        surface_version="2",
        task_id=TASK_KEY,
        candidate=DeploymentCandidateSummary(
            label="U864-A",
            ticket_count=1,
            stake_minor=172800,
            objective_label="P(全对)",
            objective_probability_decimal="0.279600000000",
        ),
        audit_state="warn",
        findings=[
            DeploymentAuditFindingSummary(
                severity="warn",
                label="C1 · legs",
                value="公开警告",
                finding_token=finding_token,
            )
        ],
        mode="adjudicate_audit_warn",
        command_token=command_token,
        ticket_batch_token=batch_token,
        no_ticket_command_token=_token(
            OperatorCommandKind.RECORD_NO_TICKET,
            "ticket_batch_revision:batch-draft-1",
        ),
    )
    gateway = _AdjudicationGateway()
    service = OperatorActionService(
        queries=_DeploymentQueries(step),
        action_gateway=gateway,
        snapshot_tokens=OperatorSnapshotTokenCodec(TOKEN_KEY),
        clock=lambda: NOW,
    )
    client, _actions = _client(service)

    response = client.post(
        "/api/v2/operator",
        json=_command(
            "adjudicate_audit_warn",
            expected_snapshot_token=command_token,
            ticket_batch_token=batch_token,
            findings=[
                {
                    "finding_token": finding_token,
                    "reason": "Jun explicitly accepts the disclosed warning.",
                    "evidence_rejected_tokens": [],
                }
            ],
        ),
    )

    assert response.status_code == 200, response.text
    assert response.json()["command_kind"] == "adjudicate_audit_warn"
    assert len(gateway.calls) == 1
    request, actor_id, actor_role = gateway.calls[0]
    assert actor_id == "jun"
    assert actor_role.value == "judge_operator"
    assert request.action_type == "record_adjudication"
    assert request.payload == {
        "subject_type": "ticket_audit_finding",
        "subject_id": "finding-warn-1",
        "decision": "accept_warning",
        "reason": "Jun explicitly accepts the disclosed warning.",
        "evidence_rejected": [],
        "alternative": {"no_evidence_rejected_acknowledged": True},
    }


class _ConfirmationTransport:
    def __init__(self) -> None:
        self.calls = []

    def request_confirmation(self, **fields):
        self.calls.append(fields)
        return SimpleNamespace(
            ticket_artifact_id=fields["ticket_artifact_id"],
            confirmation_id="confirmation-1",
            expires_at="2026-09-04T09:05:00+00:00",
            text="受保护票据等待 Jun 在 Telegram 确认。",
        )


class _OwnerHealth:
    def __init__(self, *, available: bool, blocking_code: str | None = None) -> None:
        self.available = available
        self.blocking_code = blocking_code
        self.calls = []

    def status(self, *, as_of):
        self.calls.append(as_of)
        return SimpleNamespace(
            available=self.available,
            blocking_code=self.blocking_code,
        )


def test_request_confirmation_api_only_opens_owner_telegram_stage_one() -> None:
    command_token = _token(
        OperatorCommandKind.REQUEST_CONFIRMATION,
        "ticket_artifact:artifact-1",
    )
    artifact_token = _token(
        OperatorCommandKind.REQUEST_CONFIRMATION,
        "ticket_artifact:artifact-1",
    )
    step = AuditDeploymentStep(
        surface_version="2",
        task_id=TASK_KEY,
        candidate=DeploymentCandidateSummary(
            label="U864-A",
            ticket_count=1,
            stake_minor=172800,
            objective_label="P(全对)",
            objective_probability_decimal="0.279600000000",
        ),
        audit_state="pass",
        findings=[],
        mode="request_confirmation",
        command_token=command_token,
        ticket_artifact_token=artifact_token,
        no_ticket_command_token=_token(
            OperatorCommandKind.RECORD_NO_TICKET,
            "ticket_artifact:artifact-1",
        ),
    )
    transport = _ConfirmationTransport()
    service = OperatorActionService(
        queries=_DeploymentQueries(step),
        action_gateway=_AdjudicationGateway(),
        telegram_confirmation=transport,
        telegram_owner_chat_id=771,
        snapshot_tokens=OperatorSnapshotTokenCodec(TOKEN_KEY),
        clock=lambda: NOW,
    )
    client, _actions = _client(service)

    response = client.post(
        "/api/v2/operator",
        json=_command(
            "request_confirmation",
            expected_snapshot_token=command_token,
            ticket_artifact_token=artifact_token,
        ),
    )

    assert response.status_code == 202, response.text
    assert response.json()["command_kind"] == "request_confirmation"
    assert transport.calls == [
        {
            "ticket_artifact_id": "artifact-1",
            "chat_id": 771,
            "dry_run": False,
            "requested_at": NOW,
        }
    ]


def test_request_confirmation_blocks_when_formal_owner_heartbeat_is_missing() -> None:
    command_token = _token(
        OperatorCommandKind.REQUEST_CONFIRMATION,
        "ticket_artifact:artifact-1",
    )
    step = AuditDeploymentStep(
        surface_version="2",
        task_id=TASK_KEY,
        candidate=DeploymentCandidateSummary(
            label="U864-A",
            ticket_count=1,
            stake_minor=172800,
            objective_label="P(全对)",
            objective_probability_decimal="0.279600000000",
        ),
        audit_state="pass",
        findings=[],
        mode="request_confirmation",
        command_token=command_token,
        ticket_artifact_token=command_token,
        no_ticket_command_token=_token(
            OperatorCommandKind.RECORD_NO_TICKET,
            "ticket_artifact:artifact-1",
        ),
    )
    transport = _ConfirmationTransport()
    owner = _OwnerHealth(
        available=False,
        blocking_code="telegram_owner_missing",
    )
    service = OperatorActionService(
        queries=_DeploymentQueries(step),
        action_gateway=_AdjudicationGateway(),
        telegram_confirmation=transport,
        telegram_owner_chat_id=771,
        telegram_owner_health=owner,
        snapshot_tokens=OperatorSnapshotTokenCodec(TOKEN_KEY),
        clock=lambda: NOW,
    )
    client, _actions = _client(service)

    response = client.post(
        "/api/v2/operator",
        json=_command(
            "request_confirmation",
            expected_snapshot_token=command_token,
            ticket_artifact_token=command_token,
        ),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "telegram_owner_missing"
    assert "unavailable" in response.json()["message"]
    assert owner.calls == [NOW]
    assert transport.calls == []


class _NoTicketDecisionActions:
    def __init__(self, *, result: str = "recorded") -> None:
        self.result = result
        self.requests = []

    def record_no_ticket(self, request):
        self.requests.append(request)
        return SimpleNamespace(
            action_id="ACT-no-ticket",
            status=ActionStatus.COMMITTED,
        )

    def no_ticket_command_receipt(self, action_id: str):
        assert action_id in {"ACT-no-ticket", "ACT-supersede-no-ticket"}
        return SimpleNamespace(result=self.result)

    def supersede_no_ticket(self, request):
        self.requests.append(request)
        return SimpleNamespace(
            action_id="ACT-supersede-no-ticket",
            status=ActionStatus.COMMITTED,
        )


def _no_ticket_context_token(kind: OperatorCommandKind) -> str:
    return _token(
        kind,
        f"business_key:{TASK_KEY.removeprefix('zucai:')}",
        "lane:zucai",
        "scope_fingerprint:" + "b" * 64,
        "slate_revision:slate-26111-4",
        f"task_family:{TASK_KEY}",
    )


def test_record_no_ticket_resolves_only_signed_scope_rules_and_candidate() -> None:
    command_token = _no_ticket_context_token(OperatorCommandKind.RECORD_NO_TICKET)
    rule_token = _token(OperatorCommandKind.RECORD_NO_TICKET, "rule:k")
    candidate_token = _token(
        OperatorCommandKind.RECORD_NO_TICKET,
        "candidate:candidate-26111-u864",
    )
    decisions = _NoTicketDecisionActions()
    service = OperatorActionService(
        queries=SimpleNamespace(now=lambda: NOW),
        action_gateway=_AdjudicationGateway(),
        decision_actions=decisions,
        snapshot_tokens=OperatorSnapshotTokenCodec(TOKEN_KEY),
        clock=lambda: NOW,
    )
    client, _actions = _client(service)

    response = client.post(
        "/api/v2/operator",
        json=_command(
            "record_no_ticket",
            expected_snapshot_token=command_token,
            reason_code="operator_discretion",
            reason_basis="rule_derived",
            reason_text="Jun explicitly closed this exact remaining scope.",
            rule_tokens=[rule_token],
            comparison_candidate_token=candidate_token,
        ),
    )

    assert response.status_code == 200, response.text
    assert response.json()["command_kind"] == "record_no_ticket"
    assert len(decisions.requests) == 1
    request = decisions.requests[0]
    assert request.task_family_id == TASK_KEY
    assert request.lane == "zucai"
    assert request.business_key == "26111"
    assert request.work_item_id == "zucai:26111:issue:current"
    assert request.expected_task_snapshot_hash == "a" * 64
    assert request.expected_scope_fingerprint == "b" * 64
    assert request.rule_ids == ("k",)
    assert request.comparison_candidate_revision_id == "candidate-26111-u864"
    assert request.actor_id == "jun"
    assert request.actor_role.value == "judge_operator"
    assert request.requested_at == NOW


def test_record_no_ticket_maps_committed_snapshot_change_to_recovery_409() -> None:
    decisions = _NoTicketDecisionActions(result="task_snapshot_changed")
    service = OperatorActionService(
        queries=SimpleNamespace(now=lambda: NOW),
        action_gateway=_AdjudicationGateway(),
        decision_actions=decisions,
        snapshot_tokens=OperatorSnapshotTokenCodec(TOKEN_KEY),
        clock=lambda: NOW,
    )
    client, _actions = _client(service)
    command = RecordNoTicketCommandV2.model_validate(
        _command(
            "record_no_ticket",
            expected_snapshot_token=_no_ticket_context_token(
                OperatorCommandKind.RECORD_NO_TICKET
            ),
            reason_code="operator_discretion",
            reason_basis="operator_judgment",
            reason_text="Jun explicitly closed this exact remaining scope.",
            rule_tokens=[],
        )
    )

    response = client.post("/api/v2/operator", json=command.model_dump(mode="json"))

    assert response.status_code == 409
    assert response.json()["code"] == "task_snapshot_changed"
    assert response.json()["details"] == {"recovery_href": "/operator-next"}
    assert len(decisions.requests) == 1


def test_supersede_no_ticket_resolves_only_the_signed_current_revision() -> None:
    command_token = _no_ticket_context_token(OperatorCommandKind.SUPERSEDE_NO_TICKET)
    revision_token = _token(
        OperatorCommandKind.SUPERSEDE_NO_TICKET,
        "no_ticket_revision:no-ticket-revision-26111-1",
    )
    decisions = _NoTicketDecisionActions()
    service = OperatorActionService(
        queries=SimpleNamespace(now=lambda: NOW),
        action_gateway=_AdjudicationGateway(),
        decision_actions=decisions,
        snapshot_tokens=OperatorSnapshotTokenCodec(TOKEN_KEY),
        clock=lambda: NOW,
    )
    client, _actions = _client(service)

    response = client.post(
        "/api/v2/operator",
        json=_command(
            "supersede_no_ticket",
            expected_snapshot_token=command_token,
            no_ticket_revision_token=revision_token,
            reason_text="Jun explicitly reopens only the still-upcoming offer scope.",
        ),
    )

    assert response.status_code == 200, response.text
    assert response.json()["command_kind"] == "supersede_no_ticket"
    assert len(decisions.requests) == 1
    request = decisions.requests[0]
    assert request.no_ticket_revision_id == "no-ticket-revision-26111-1"
    assert request.expected_task_snapshot_hash == "a" * 64
    assert request.expected_scope_fingerprint == "b" * 64
    assert request.reason_text == (
        "Jun explicitly reopens only the still-upcoming offer scope."
    )
    assert request.actor_role.value == "judge_operator"
