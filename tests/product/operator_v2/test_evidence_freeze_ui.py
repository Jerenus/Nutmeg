from __future__ import annotations

import re
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nutmeg.interfaces.operator_ui import mount_operator_ui
from nutmeg.product.operator_contracts import (
    EvidenceRequirementSummary,
    MatchEvidenceChecklist,
    NoTicketControl,
    OperatorLane,
    OperatorTaskResponse,
    OperatorTaskState,
    OperatorTaskSummary,
    PrepareEvidenceStep,
    TaskProgressSummary,
)

NOW = datetime(2026, 9, 4, 9, tzinfo=UTC)
OPAQUE_TOKEN = "opaque.signed-command-token"


def _task(
    state: str,
    *,
    new_evidence: bool = False,
    match_label: str = "水晶宫 - 曼彻斯特城",
) -> OperatorTaskResponse:
    gate_state = state if state in {"complete", "missing", "stale", "conflict"} else "complete"
    freeze_state = state if state in {"queued", "linked", "failed"} else "not_requested"
    gate_complete = gate_state == "complete"
    requirement_state = {
        "missing": "missing",
        "stale": "stale",
        "conflict": "conflict",
    }.get(gate_state, "complete")
    requirements = [
        EvidenceRequirementSummary(
            requirement_id="E1",
            label="身份对齐",
            state=requirement_state,
            detail={
                "complete": "已核对",
                "missing": "尚缺数据",
                "stale": "需要刷新",
                "conflict": "需要裁决",
            }[requirement_state],
        ),
        EvidenceRequirementSummary(
            requirement_id="EC",
            label="冲突清偿",
            state="complete" if requirement_state != "conflict" else "conflict",
            detail="无未清偿冲突" if requirement_state != "conflict" else "存在冲突",
        ),
    ]
    step = PrepareEvidenceStep(
        task_id="zucai:26116",
        title="核对本期证据",
        gate_state=gate_state,
        freeze_state=freeze_state,
        complete_match_count=1 if gate_complete else 0,
        required_match_count=1,
        matches=[
            MatchEvidenceChecklist(
                official_match_no="1",
                match_label=match_label,
                complete=requirement_state == "complete",
                completed_requirement_count=sum(
                    item.state == "complete" for item in requirements
                ),
                required_requirement_count=len(requirements),
                requirements=requirements,
            )
        ],
        new_evidence_available=new_evidence,
        freeze_command_token=(
            OPAQUE_TOKEN
            if gate_complete
            and freeze_state != "queued"
            and (freeze_state not in {"linked", "failed"} or new_evidence)
            else None
        ),
        requirement_revision_token=(
            "requirement-opaque" if gate_complete else None
        ),
    )
    selected = OperatorTaskSummary(
        task_id="zucai:26116",
        lane=OperatorLane.ZUCAI,
        business_key="26116",
        title="足彩 26116",
        state=OperatorTaskState.PREPARE,
        deadline_at=NOW,
        is_actionable=True,
        next_action_label="准备证据",
        priority_rank=0,
    )
    return OperatorTaskResponse(
        as_of=NOW,
        mutation_token="a" * 64,
        selected=selected,
        alternatives=[],
        progress=TaskProgressSummary(completed=0, total=1, label="证据准备"),
        step=step,
        no_ticket=NoTicketControl(
            state="available",
            command_token="opaque.no-ticket.command",
        ),
    )


class _Queries:
    def __init__(
        self,
        state: str,
        *,
        new_evidence: bool = False,
        match_label: str = "水晶宫 - 曼彻斯特城",
    ) -> None:
        self._task = _task(
            state,
            new_evidence=new_evidence,
            match_label=match_label,
        )

    def task(self, _task_id: str, *, as_of):
        return self._task

    def worklist(self, *, as_of):
        return SimpleNamespace(
            selected=self._task.selected,
            tasks=[self._task.selected],
            as_of=as_of,
        )


def _client(
    state: str,
    *,
    read_only: bool = False,
    new_evidence: bool = False,
    match_label: str = "水晶宫 - 曼彻斯特城",
) -> TestClient:
    app = FastAPI()
    services = SimpleNamespace(
        operator_queries=_Queries(
            state,
            new_evidence=new_evidence,
            match_label=match_label,
        )
    )
    mount_operator_ui(
        app,
        services,
        lambda: NOW,
        read_only=read_only,
    )
    return TestClient(app)


@pytest.mark.parametrize(
    ("state", "visible"),
    [
        ("complete", "证据已齐，可以冻结"),
        ("missing", "尚缺数据"),
        ("stale", "需要刷新"),
        ("conflict", "需要裁决"),
        ("queued", "冻结请求已排队"),
        ("linked", "证据版本已冻结"),
    ],
)
def test_evidence_states_render_as_business_checklists(state: str, visible: str) -> None:
    response = _client(state).get("/tasks/zucai:26116")

    assert response.status_code == 200
    assert 'data-step-kind="prepare_evidence"' in response.text
    assert visible in response.text
    assert "水晶宫 - 曼彻斯特城" in response.text
    assert "身份对齐" in response.text


def test_freeze_is_the_only_primary_control_and_only_when_gate_is_complete() -> None:
    complete = _client("complete").get("/tasks/zucai:26116").text

    assert 'data-action="freeze-evidence"' in complete
    assert complete.count('class="primary-action"') == 1
    assert OPAQUE_TOKEN in complete
    for state in ("missing", "stale", "conflict", "queued", "linked", "failed"):
        html = _client(state).get("/tasks/zucai:26116").text
        assert 'data-action="freeze-evidence"' not in html
        assert 'class="primary-action"' not in html


def test_prepare_evidence_keeps_no_ticket_as_an_unselected_secondary_action() -> None:
    html = _client("missing").get("/tasks/zucai:26116").text

    assert "明确不出票" in html
    assert 'data-action="record-no-ticket"' in html
    assert 'class="secondary-action no-ticket-toggle"' in html
    assert '<option value="" selected disabled>请选择理由</option>' in html
    assert not re.search(
        r'<option value="(?:human_all_dice|operator_discretion)" selected',
        html,
    )
    assert "opaque.no-ticket.command" not in html


def test_linked_bundle_with_new_evidence_offers_explicit_refreeze() -> None:
    html = _client("linked", new_evidence=True).get("/tasks/zucai:26116").text

    assert "证据版本已冻结" in html
    assert "有新证据可用" in html
    assert 'data-action="freeze-evidence"' in html
    assert "重新冻结" in html


def test_failed_request_only_offers_refreeze_after_dependencies_change() -> None:
    unchanged = _client("failed").get("/tasks/zucai:26116").text
    changed = _client("failed", new_evidence=True).get("/tasks/zucai:26116").text

    assert 'data-action="freeze-evidence"' not in unchanged
    assert 'data-action="freeze-evidence"' in changed


def test_queued_state_refreshes_and_untrusted_labels_are_escaped() -> None:
    queued = _client("queued").get("/tasks/zucai:26116").text
    escaped = _client(
        "complete",
        match_label='<script>alert("evidence")</script>',
    ).get("/tasks/zucai:26116").text

    assert 'data-auto-refresh="waiting"' in queued
    assert "<script>alert" not in escaped
    assert "&lt;script&gt;alert" in escaped


def test_read_only_and_normal_pages_hide_internal_evidence_material() -> None:
    for html in (
        _client("complete").get("/tasks/zucai:26116").text,
        _client("complete", read_only=True).get("/tasks/zucai:26116").text,
    ):
        assert "<pre" not in html
        assert "{" not in html
        assert not re.search(r"\b[0-9a-f]{64}\b", html)
        for forbidden in (
            "action_id",
            "bundle_id",
            "content_hash",
            "schema_version",
            "dependency_fingerprint",
            "Traceback",
        ):
            assert forbidden not in html
    read_only = _client("complete", read_only=True).get("/tasks/zucai:26116").text
    assert 'data-action="freeze-evidence"' not in read_only
