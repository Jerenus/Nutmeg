from __future__ import annotations

import re
from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nutmeg.interfaces.operator_api import mount_operator_api
from nutmeg.interfaces.operator_ui import mount_operator_ui
from nutmeg.product.operator_contracts import (
    CandidateAuditFindingView,
    CandidateComparisonView,
    CandidateSetComparisonView,
    ConstructTicketStep,
    OperatorCommandReceipt,
    OperatorLane,
    OperatorTaskResponse,
    OperatorTaskState,
    OperatorTaskSummary,
    PrescriptionDifferenceSummary,
    TaskProgressSummary,
)

NOW = datetime(2026, 9, 4, 9, tzinfo=UTC)


class _Actions:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def request_candidate_generation(self, command, *, actor_id, actor_role):
        self.calls.append(("generate", command))
        return OperatorCommandReceipt(
            command_kind="request_candidate_generation",
            status="queued",
            task_key=command.task_key,
        )

    def select_ticket_candidate(self, command, *, actor_id, actor_role):
        self.calls.append(("select", command))
        return OperatorCommandReceipt(
            command_kind="select_candidate",
            status="completed",
            task_key=command.task_key,
        )


def _api_client(actions: _Actions) -> TestClient:
    app = FastAPI()

    async def allow(_request) -> None:
        return None

    mount_operator_api(
        app,
        require_mutation_session=allow,
        operator_actions=actions,
        actor_id="jun",
    )
    return TestClient(app)


def _command(kind: str, **extra: object) -> dict[str, object]:
    return {
        "schema_version": "2",
        "kind": kind,
        "expected_snapshot_token": "opaque.command-token",
        "idempotency_key": f"browser:{kind}:1",
        "task_key": "zucai:26111",
        **extra,
    }


def test_candidate_v2_commands_route_only_server_assigned_human_authority() -> None:
    actions = _Actions()
    client = _api_client(actions)

    generation = client.post(
        "/api/v2/operator",
        json=_command(
            "request_candidate_generation",
            market_prior_baseline_token="opaque.market-baseline",
            baseline_envelope_token="opaque.baseline-envelope",
            judgment_prescription_token="opaque.judgment-prescription",
        ),
    )
    selection = client.post(
        "/api/v2/operator",
        json=_command(
            "select_candidate",
            expected_snapshot_token="opaque.selection-command",
            candidate_token="opaque.judgment-bound-candidate",
            reason="资金帽内，采用该结构",
        ),
    )

    assert generation.status_code == 202
    assert selection.status_code == 200
    assert [kind for kind, _command_value in actions.calls] == ["generate", "select"]
    assert all("actor" not in call.model_dump() for _kind, call in actions.calls)
    generation_command = actions.calls[0][1]
    assert generation_command.market_prior_baseline_token == "opaque.market-baseline"
    assert generation_command.baseline_envelope_token == "opaque.baseline-envelope"
    assert generation_command.judgment_prescription_token == "opaque.judgment-prescription"
    selection_command = actions.calls[1][1]
    assert selection_command.expected_snapshot_token == "opaque.selection-command"
    assert selection_command.candidate_token == "opaque.judgment-bound-candidate"


def test_candidate_v2_commands_reject_extra_authority_and_incomplete_selection() -> None:
    client = _api_client(_Actions())

    assert client.post(
        "/api/v2/operator",
        json=_command(
            "request_candidate_generation",
            market_prior_baseline_token="opaque.market-baseline",
            baseline_envelope_token="opaque.baseline-envelope",
            judgment_prescription_token="opaque.judgment-prescription",
            actor_role="deterministic_system",
        ),
    ).status_code == 422
    for missing in (
        "market_prior_baseline_token",
        "baseline_envelope_token",
        "judgment_prescription_token",
    ):
        body = {
            "market_prior_baseline_token": "opaque.market-baseline",
            "baseline_envelope_token": "opaque.baseline-envelope",
            "judgment_prescription_token": "opaque.judgment-prescription",
        }
        body.pop(missing)
        assert client.post(
            "/api/v2/operator",
            json=_command("request_candidate_generation", **body),
        ).status_code == 422
    assert client.post(
        "/api/v2/operator",
        json=_command(
            "select_candidate",
            candidate_token="opaque.judgment-bound-candidate",
            reason="",
        ),
    ).status_code == 422
    assert client.post(
        "/api/v2/operator",
        json=_command("select_candidate", reason="有理由但没有候选"),
    ).status_code == 422


def _candidate(
    *,
    code: str,
    partition: str,
    rank: int | None,
    selectable: bool,
    deployable: bool,
    token: str | None,
    findings: list[CandidateAuditFindingView] | None = None,
) -> CandidateComparisonView:
    return CandidateComparisonView(
        code=code,
        partition=partition,
        rank=rank,
        selectable=selectable,
        deployable=deployable,
        candidate_token=token,
        composition={
            "singles": ["场 1 · 3"],
            "doubles": ["场 2 · 31"],
            "full_covers": ["场 3 · 310"],
            "omissions": ["场 4"],
            "pass_groups": ["任九 · 1/2/3/5/6/7/8/9/10"],
        },
        ticket_count=1,
        distinct_note_count=864,
        paid_note_unit_count=864,
        stake_minor=172800,
        capital_utilization_decimal="0.864000000000",
        objective_label="P(全对)",
        objective_probability_decimal="0.279600000000",
        expected_broken_legs_decimal="1.420000000000",
        break_even_bonus_minor=260000,
        break_even_to_official_median_decimal="1.040000000000",
        common_dead_faces=["场 5 · 平"],
        prescription_differences=[
            PrescriptionDifferenceSummary(
                match_no=5,
                prescribed_faces="31",
                candidate_faces="3",
                registered_rule_ids=["o-1球差"],
            )
        ],
        audit_findings=findings or [],
        market_difference="相对市场先验 +1.80 pp",
    )


def _step(*, request_only: bool = False, selection_completed: bool = False) -> ConstructTicketStep:
    if request_only:
        return ConstructTicketStep(
            task_id="zucai:26111",
            mode="candidate_request",
            request_generation_token="opaque.generation-command-token",
            market_prior_baseline_token="opaque.market-baseline",
            baseline_envelope_token="opaque.baseline-envelope",
            judgment_prescription_token="opaque.judgment-prescription",
        )
    return ConstructTicketStep(
        task_id="zucai:26111",
        mode="candidate_comparison",
        selection_command_token=(
            None if selection_completed else "opaque.selection-command-token"
        ),
        selection_completed=selection_completed,
        selected_candidate_code="U864-A" if selection_completed else None,
        candidate_sets=[
            CandidateSetComparisonView(
                label="判断处方候选",
                comparison_only=False,
                candidates=[
                    _candidate(
                        code="U864-A",
                        partition="eligible",
                        rank=1,
                        selectable=not selection_completed,
                        deployable=True,
                        token=(None if selection_completed else "opaque.candidate-one"),
                    ),
                    _candidate(
                        code="U864-B",
                        partition="audit_blocked",
                        rank=None,
                        selectable=not selection_completed,
                        deployable=False,
                        token=(None if selection_completed else "opaque.candidate-blocked"),
                        findings=[
                            CandidateAuditFindingView(
                                audit_kind="prescription_difference",
                                finding_code="unnamed_deviation",
                                severity="ERROR",
                                message="偏离未引用命名规则",
                                rule_id=None,
                            )
                        ],
                    ),
                    _candidate(
                        code="U1152",
                        partition="over_cap",
                        rank=None,
                        selectable=False,
                        deployable=False,
                        token=None,
                    ),
                ],
            ),
            CandidateSetComparisonView(
                label="市场条件对照",
                comparison_only=True,
                candidates=[
                    _candidate(
                        code="MARKET-864",
                        partition="eligible",
                        rank=1,
                        selectable=False,
                        deployable=False,
                        token=None,
                    )
                ],
            ),
        ],
    )


class _Queries:
    def __init__(self, step: ConstructTicketStep) -> None:
        selected = OperatorTaskSummary(
            task_id="zucai:26111",
            lane=OperatorLane.ZUCAI,
            business_key="26111",
            title="足彩 26111",
            state=OperatorTaskState.CONSTRUCT_TICKET,
            deadline_at=NOW,
            is_actionable=True,
            next_action_label="比较候选票",
            priority_rank=0,
        )
        self.response = OperatorTaskResponse(
            as_of=NOW,
            mutation_token="d" * 64,
            selected=selected,
            alternatives=[],
            progress=TaskProgressSummary(completed=0, total=1, label="候选比较"),
            step=step,
        )

    def task(self, _task_id: str, *, as_of):
        return self.response

    def worklist(self, *, as_of):
        return SimpleNamespace(selected=self.response.selected, tasks=[], as_of=as_of)


def _ui_client(step: ConstructTicketStep, *, read_only: bool = False) -> TestClient:
    app = FastAPI()
    mount_operator_ui(
        app,
        SimpleNamespace(operator_queries=_Queries(step)),
        lambda: NOW,
        read_only=read_only,
    )
    return TestClient(app)


def test_candidate_request_is_an_explicit_operator_action() -> None:
    html = _ui_client(_step(request_only=True)).get("/tasks/zucai:26111").text

    assert "生成完整候选集" in html
    assert 'data-action="request-candidate-generation"' in html
    assert "opaque.generation-command-token" in html
    assert "opaque.market-baseline" in html
    assert "opaque.baseline-envelope" in html
    assert "opaque.judgment-prescription" in html
    assert "自动选择" not in html


def test_comparison_renders_every_partition_and_never_preselects() -> None:
    html = _ui_client(_step()).get("/tasks/zucai:26111").text

    for visible in (
        "判断处方候选",
        "市场条件对照",
        "仅比较，不可出票",
        "可选择",
        "审计阻断",
        "可建草稿，审批仍阻断",
        "超过资金帽",
        "单选",
        "场 1 · 3",
        "双选",
        "场 2 · 31",
        "全包",
        "场 3 · 310",
        "遗漏",
        "场 4",
        "任九 · 1/2/3/5/6/7/8/9/10",
        "付费注数",
        "864",
        "回本金额",
        "¥2,600.00",
        "官方中位倍数",
        "1.0400×",
        "27.9600%",
        "¥1,728.00",
        "86.40%",
        "1.4200",
        "场 5 · 平",
        "o-1球差",
        "偏离未引用命名规则",
        "相对市场先验 +1.80 pp",
    ):
        assert visible in html
    assert html.count('type="radio"') == 2
    assert "checked" not in html
    assert 'data-action="select-ticket-candidate"' in html
    assert 'data-command-token="opaque.selection-command-token"' in html
    assert "推荐" not in html


def test_comparison_hides_json_and_internal_identifiers() -> None:
    html = _ui_client(_step()).get("/tasks/zucai:26111").text

    assert "<pre" not in html
    assert "{" not in html
    assert not re.search(r"\b[0-9a-f]{64}\b", html)
    for forbidden in (
        "candidate_revision_id",
        "candidate_set_revision_id",
        "action_id",
        "content_hash",
        "payload_json",
        'name="actor_id"',
        'name="actor_role"',
    ):
        assert forbidden not in html


def test_read_only_comparison_contains_no_selection_form() -> None:
    html = _ui_client(_step(), read_only=True).get("/tasks/zucai:26111").text

    assert "U864-A" in html
    assert "只读模式" in html
    assert 'data-action="select-ticket-candidate"' not in html


def test_completed_selection_keeps_comparison_visible_without_a_repeat_form() -> None:
    html = _ui_client(_step(selection_completed=True)).get("/tasks/zucai:26111").text

    assert "U864-A" in html
    assert "已选择 U864-A，等待部署审计" in html
    assert 'data-action="select-ticket-candidate"' not in html


def test_candidate_contract_keeps_selection_and_deployment_distinct() -> None:
    blocked = _candidate(
        code="BLOCKED-DRAFT",
        partition="audit_blocked",
        rank=None,
        selectable=True,
        deployable=False,
        token="opaque.blocked-draft",
    )

    assert blocked.selectable is True
    assert blocked.deployable is False
    assert blocked.candidate_token == "opaque.blocked-draft"
