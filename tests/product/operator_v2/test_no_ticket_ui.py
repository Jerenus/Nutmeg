from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nutmeg.interfaces.operator_ui import mount_operator_ui

NOW = datetime(2026, 9, 4, 9, tzinfo=UTC)


def _task(*, audit_state: str, mode: str):
    finding = SimpleNamespace(
        severity="error" if audit_state == "error" else "warn",
        label="C1 flagged_naked_single",
        value="该结构存在一项已披露的审计问题。",
        evidence_href=None,
        finding_token="opaque.finding",
    )
    step = SimpleNamespace(
        kind="audit_deployment",
        surface_version="2",
        task_id="zucai:26111",
        candidate=SimpleNamespace(label="U864-A"),
        audit_state=audit_state,
        findings=[] if audit_state == "pass" else [finding],
        mode=mode,
        command_token=f"opaque.{mode}.command",
        candidate_selection_token="opaque.selection",
        ticket_batch_token=(None if mode == "create_ticket_batch" else "opaque.batch"),
        no_ticket_command_token="opaque.no-ticket.command",
        no_ticket_revision_token=(
            "opaque.no-ticket.revision" if mode == "supersede_no_ticket" else None
        ),
        comparison_candidate_token="opaque.candidate",
        rule_options=(
            SimpleNamespace(token="opaque.rule.k", label="k · 判断阶梯"),
        ),
    )
    return SimpleNamespace(
        mutation_token="a" * 64,
        selected=SimpleNamespace(
            task_id="zucai:26111",
            title="足彩 26111",
            next_action_label="检查审计与部署",
        ),
        alternatives=[],
        progress=SimpleNamespace(label="审计部署", completed=6, total=9),
        step=step,
    )


class _Queries:
    def __init__(self, task) -> None:
        self._task = task

    def task(self, _task_id: str, *, as_of):
        assert as_of == NOW
        return self._task


def _html(*, audit_state: str, mode: str, read_only: bool = False) -> str:
    app = FastAPI()
    mount_operator_ui(
        app,
        SimpleNamespace(operator_queries=_Queries(_task(audit_state=audit_state, mode=mode))),
        lambda: NOW,
        read_only=read_only,
    )
    return TestClient(app).get("/tasks/zucai:26111").text


def test_pass_audit_prioritizes_materialization_and_keeps_no_ticket_secondary() -> None:
    html = _html(audit_state="pass", mode="create_ticket_batch")

    assert "创建受保护票据" in html
    assert 'data-primary-command="true"' in html
    assert 'data-action="create-ticket-batch"' in html
    assert "明确不出票" in html
    assert 'data-action="record-no-ticket"' in html
    assert 'class="secondary-action no-ticket-toggle"' in html
    assert 'name="reason_code" required' in html
    assert '<option value="" selected disabled>请选择理由</option>' in html
    assert not re.search(r'<option value="(?:human_all_dice|operator_discretion)" selected', html)
    assert html.count('data-task-key="zucai:26111"') >= 2


def test_error_audit_has_external_recovery_but_no_web_override_control() -> None:
    html = _html(audit_state="error", mode="blocked")

    assert "当前 ERROR 阻止审批" in html
    assert "从技术审计取得当前批次命令" in html
    assert "decision-audit-legs" not in html
    assert "--user-override" not in html
    assert "--ticket-batch-token" not in html
    assert 'data-action="record-ticket-audit-override"' not in html
    assert 'name="audit_error_override"' not in html
    assert 'data-action="approve-ticket-batch"' not in html


def test_warn_audit_requires_explicit_warn_adjudication_before_approval() -> None:
    html = _html(audit_state="warn", mode="adjudicate_audit_warn")

    assert "逐条确认 WARN" in html
    assert 'data-action="adjudicate-audit-warn"' in html
    assert 'name="finding_token"' in html
    assert 'name="warn_reason"' in html
    assert 'data-finding-index="0"' in html
    assert 'data-action="approve-ticket-batch"' not in html


def test_recorded_no_ticket_offers_only_an_explicit_reopen_command() -> None:
    html = _html(audit_state="pass", mode="supersede_no_ticket")

    assert "本次范围已记录为不出票" in html
    assert 'data-action="supersede-no-ticket"' in html
    assert 'name="supersede_reason"' in html
    assert 'data-action="record-no-ticket"' not in html
    assert 'data-primary-command="true"' not in html


def test_deployment_page_exposes_no_json_internal_ids_or_real_tokens() -> None:
    html = _html(audit_state="pass", mode="create_ticket_batch")

    assert "<pre" not in html
    assert "{" not in html
    assert not re.search(r"\b[0-9a-f]{64}\b", html)
    for forbidden in (
        "candidate_revision_id",
        "action_id",
        "content_hash",
        "payload_json",
        "opaque.selection",
        "opaque.no-ticket.command",
        "opaque.candidate",
        'name="actor_id"',
        'name="actor_role"',
    ):
        assert forbidden not in html


def test_read_only_deployment_has_no_mutation_forms() -> None:
    html = _html(audit_state="pass", mode="create_ticket_batch", read_only=True)

    assert "只读模式" in html
    assert 'data-action="create-ticket-batch"' not in html
    assert 'data-action="record-no-ticket"' not in html


def test_deployment_javascript_refreshes_opaque_v2_tokens_before_strict_submit() -> None:
    script = (
        Path(__file__).parents[3]
        / "nutmeg"
        / "interfaces"
        / "web"
        / "static"
        / "product"
        / "operator.js"
    ).read_text(encoding="utf-8")

    task_detail_path = (
        "/api/v2/operator/tasks/${encodeURIComponent(lane)}/"
        "${encodeURIComponent(businessKey)}"
    )
    assert task_detail_path in script
    assert "taskSnapshotToken" not in script
    assert "mutation_token" not in script
    assert 'action === "create-ticket-batch"' in script
    assert 'kind: "create_ticket_batch"' in script
    assert 'action === "adjudicate-audit-warn"' in script
    assert 'kind: "adjudicate_audit_warn"' in script
    assert 'action === "approve-ticket-batch"' in script
    assert 'kind: "approve_ticket_batch"' in script
    assert 'action === "request-confirmation"' in script
    assert 'kind: "request_confirmation"' in script
    assert 'action === "record-no-ticket"' in script
    assert 'kind: "record_no_ticket"' in script
    assert 'action === "supersede-no-ticket"' in script
    assert 'kind: "supersede_no_ticket"' in script
