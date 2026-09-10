from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from nutmeg.interfaces.operator_api import mount_operator_api
from nutmeg.product.errors import ProductActionBlockedError
from nutmeg.product.operator_contracts import (
    AwaitResultStep,
    OperatorBlockViewV1,
    OperatorLane,
    OperatorRecoveryCode,
    OperatorRecoverySummary,
    OperatorTaskState,
    TaskProgressSummary,
    TelegramOwnerStatusV1,
)
from nutmeg.product.operator_lanes import SaleOfferSnapshot, SaleSlateSnapshot, ScopeKind
from nutmeg.product.operator_recovery import (
    OPERATOR_RECOVERY_CATALOG,
    normalize_recovery_code,
    recovery_block_for_step,
    recovery_code_for_step,
    recovery_href_for_code,
)
from nutmeg.product.operator_state import OperatorTaskFacts
from nutmeg.product.operator_workbench import OperatorWorkbenchAssembler
from tests.product.operator_v2.test_operator_pages import (
    _client as _page_client,
)
from tests.product.operator_v2.test_operator_pages import (
    _OperatorQueries as _PageQueries,
)

NOW = datetime(2026, 9, 5, 8, tzinfo=UTC)
TASK_KEY = "zucai:26116"


def _recovery_summary_payload() -> dict[str, object]:
    return {
        "code": "evidence_missing",
        "missing": "named evidence",
        "impact": "cannot freeze evidence",
        "action_label": "collect evidence",
    }


@pytest.mark.parametrize(
    ("contract", "payload"),
    (
        (
            OperatorBlockViewV1,
            {
                "code": "totally_unstable",
                "message": "unknown",
                "repair_owner": "nobody",
                "recovery_link": "/operator-next",
            },
        ),
        (
            OperatorRecoverySummary,
            {**_recovery_summary_payload(), "code": "totally_unstable"},
        ),
        (
            TelegramOwnerStatusV1,
            {
                "owner_mode": "unavailable",
                "configured": False,
                "heartbeat_state": "unavailable",
                "confirmation_available": False,
                "blocking_code": "totally_unstable",
                "recovery_label": "repair owner",
            },
        ),
    ),
)
def test_every_public_recovery_contract_rejects_unknown_codes(
    contract: type,
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        contract.model_validate(payload)


def test_recovery_catalog_covers_the_closed_contract_enum() -> None:
    assert set(OPERATOR_RECOVERY_CATALOG) == set(OperatorRecoveryCode)


def _requirement(requirement_id: str, state: str) -> SimpleNamespace:
    return SimpleNamespace(requirement_id=requirement_id, state=state)


def _prepare_step(requirement_id: str, gate_state: str) -> SimpleNamespace:
    return SimpleNamespace(
        kind="prepare_evidence",
        gate_state=gate_state,
        matches=[SimpleNamespace(requirements=[_requirement(requirement_id, gate_state)])],
    )


@pytest.mark.parametrize(
    ("step", "expected"),
    (
        (_prepare_step("E1", "missing"), "identity_unresolved"),
        (_prepare_step("E2", "missing"), "evidence_missing"),
        (_prepare_step("E2", "stale"), "evidence_stale"),
        (_prepare_step("EC", "conflict"), "evidence_conflict"),
        (SimpleNamespace(kind="audit_deployment", audit_state="error"), "audit_error"),
        (
            SimpleNamespace(kind="await_confirmation", confirmation_state="expired"),
            "confirmation_expired",
        ),
        (
            SimpleNamespace(
                kind="await_result",
                result_state="not_imported",
                settlement_state="result_waiting",
                blocking_codes=["result_not_ready"],
            ),
            "result_source_missing",
        ),
        (
            SimpleNamespace(
                kind="await_result",
                result_state="postponed",
                settlement_state="result_waiting",
                blocking_codes=["result_not_ready"],
            ),
            "result_pending",
        ),
        (
            SimpleNamespace(
                kind="await_result",
                result_state="conflict",
                settlement_state="result_waiting",
                blocking_codes=["result_not_ready"],
            ),
            "result_source_conflict",
        ),
        (
            SimpleNamespace(
                kind="await_result",
                result_state="ready",
                settlement_state="integrity_blocked",
                blocking_codes=["placement_integrity_blocked"],
            ),
            "placement_ledger_integrity",
        ),
        (
            SimpleNamespace(kind="review", scoreboard_projection_state="stale"),
            None,
        ),
        (
            SimpleNamespace(kind="review", scoreboard_projection_state="unavailable"),
            None,
        ),
    ),
)
def test_step_states_map_to_stable_recovery_codes(
    step: SimpleNamespace,
    expected: str | None,
) -> None:
    assert recovery_code_for_step(step) == expected


def test_recovery_block_uses_catalog_copy_and_explicit_task_link() -> None:
    step = _prepare_step("E2", "stale")
    retry_at = NOW + timedelta(minutes=30)

    block = recovery_block_for_step(
        step,
        recovery_link="/operator-next/zucai/26116",
        reevaluate_at=retry_at,
    )

    assert block is not None
    definition = OPERATOR_RECOVERY_CATALOG[OperatorRecoveryCode.EVIDENCE_STALE]
    assert block.code is OperatorRecoveryCode.EVIDENCE_STALE
    assert block.message == definition.message
    assert block.repair_owner == definition.repair_owner
    assert block.reevaluate_at == retry_at
    assert block.recovery_link == "/operator-next/zucai/26116"


def test_blocked_result_stage_remains_visible_in_today_with_public_recovery_code() -> None:
    deadline = NOW - timedelta(hours=1)
    facts = OperatorTaskFacts(
        lane=OperatorLane.ZUCAI,
        business_key="26116",
        deadline_at=deadline,
        waiting_until=None,
        source_error_code=None,
        has_issue=True,
        has_prep=True,
        unresolved_adjudications=0,
        candidate_count=1,
        selected_candidate_id="selected",
        audit_recorded=True,
        deployment_decision="keep",
        ticket_artifact_id="protected-artifact",
        confirmation_state="consumed",
        placement_state="placed",
        result_available=False,
        pending_review_items=0,
    )
    built = SimpleNamespace(
        facts=facts,
        progress=TaskProgressSummary(completed=0, total=1, label="等待赛果"),
        step=AwaitResultStep(
            surface_version="2",
            task_id=TASK_KEY,
            title="赛果与结算",
            expected_at=deadline,
            result_state="missing",
            prize_state="not_applicable",
            settlement_state="result_waiting",
            placed_ticket_count=1,
            blocking_codes=["result_not_ready"],
        ),
        mutation_token="a" * 64,
        work_item_identity="ticket-scope",
        scope_kind=ScopeKind.TICKET,
        projected_state=OperatorTaskState.AWAIT_RESULT,
        deployment_outcome=None,
        scope_label="已出票票据",
    )
    slate = SaleSlateSnapshot(
        lane=OperatorLane.ZUCAI,
        business_key="26116",
        slate_revision_id="slate-26116",
        content_hash="slate-content",
        offers=(
            SaleOfferSnapshot(
                official_offer_family_id="offer-family-1",
                official_offer_revision_id="offer-revision-1",
                match_id="match-1",
                official_match_no="001",
                market_definition_ids=("md-had",),
                sale_opens_at=NOW - timedelta(days=1),
                sale_deadline_at=deadline,
                source_status="sale_closed",
            ),
        ),
        source_official=True,
        revision_no=1,
        published_at=NOW - timedelta(days=1),
        retrieved_at=NOW - timedelta(hours=2),
    )
    assembler = OperatorWorkbenchAssembler(
        slates=(slate,),
        built_tasks=(built,),
        match_lookup=lambda _match_id, _as_of: SimpleNamespace(
            home_team="主队",
            away_team="客队",
            competition="测试联赛",
            scheduled_at=deadline,
        ),
    )

    today = assembler.today(as_of=NOW)

    assert len(today.entries) == 1
    assert today.entries[0].blocking_reason is not None
    assert today.entries[0].blocking_reason.code == "result_source_missing"
    assert today.entries[0].next_action.enabled is False
    assert today.entries[0].next_action.action_label == "补齐正式赛果来源"


def test_review_remains_enterable_when_scoreboard_projection_is_unavailable() -> None:
    deadline = NOW - timedelta(hours=1)
    facts = OperatorTaskFacts(
        lane=OperatorLane.ZUCAI,
        business_key="26116",
        deadline_at=deadline,
        waiting_until=None,
        source_error_code=None,
        has_issue=True,
        has_prep=True,
        unresolved_adjudications=0,
        candidate_count=1,
        selected_candidate_id="selected",
        audit_recorded=True,
        deployment_decision="keep",
        ticket_artifact_id="protected-artifact",
        confirmation_state="consumed",
        placement_state="placed",
        result_available=True,
        pending_review_items=1,
    )
    built = SimpleNamespace(
        facts=facts,
        progress=TaskProgressSummary(completed=0, total=1, label="复盘"),
        step=SimpleNamespace(
            kind="review",
            scoreboard_projection_state="unavailable",
        ),
        mutation_token="b" * 64,
        work_item_identity="review-scope",
        scope_kind=ScopeKind.REVIEW,
        projected_state=OperatorTaskState.REVIEW,
        deployment_outcome=None,
        scope_label="赛后复盘",
    )
    slate = SaleSlateSnapshot(
        lane=OperatorLane.ZUCAI,
        business_key="26116",
        slate_revision_id="slate-26116",
        content_hash="slate-content",
        offers=(
            SaleOfferSnapshot(
                official_offer_family_id="offer-family-1",
                official_offer_revision_id="offer-revision-1",
                match_id="match-1",
                official_match_no="001",
                market_definition_ids=("md-had",),
                sale_opens_at=NOW - timedelta(days=1),
                sale_deadline_at=deadline,
                source_status="sale_closed",
            ),
        ),
        source_official=True,
        revision_no=1,
        published_at=NOW - timedelta(days=1),
        retrieved_at=NOW - timedelta(hours=2),
    )
    assembler = OperatorWorkbenchAssembler(
        slates=(slate,),
        built_tasks=(built,),
        match_lookup=lambda _match_id, _as_of: SimpleNamespace(
            home_team="主队",
            away_team="客队",
            competition="测试联赛",
            scheduled_at=deadline,
        ),
    )

    today = assembler.today(as_of=NOW)

    assert len(today.entries) == 1
    assert today.entries[0].blocking_reason is None
    assert today.entries[0].next_action.enabled is True
    assert today.entries[0].next_action.action_label == "继续复盘"


@pytest.mark.parametrize(
    ("code", "task_key", "expected"),
    (
        ("evidence_missing", TASK_KEY, "/operator-next/zucai/26116"),
        ("projection_stale", TASK_KEY, "/operator-next/zucai/26116"),
        ("telegram_update_owner_conflict", TASK_KEY, "/operator-next/maintenance"),
        ("diagnostic_unavailable", None, "/operator-next/maintenance"),
        ("task_snapshot_changed", TASK_KEY, "/operator-next"),
    ),
)
def test_recovery_href_is_deterministic_and_never_accepts_a_raw_path(
    code: str,
    task_key: str | None,
    expected: str,
) -> None:
    assert recovery_href_for_code(code, task_key=task_key) == expected


def test_default_action_blocked_code_is_normalized_to_the_closed_fallback() -> None:
    assert normalize_recovery_code("action_blocked") is OperatorRecoveryCode.OPERATOR_TASK_BLOCKED


class _BlockedActions:
    def __init__(self, code: str) -> None:
        self.code = code

    def request_settlement(self, _command, *, actor_id, actor_role):
        del actor_id, actor_role
        raise ProductActionBlockedError("deterministic block", code=self.code)


def _blocked_api_client(code: str) -> TestClient:
    app = FastAPI()

    async def allow(_request) -> None:
        return None

    mount_operator_api(
        app,
        require_mutation_session=allow,
        operator_actions=_BlockedActions(code),
        actor_id="jun",
    )
    return TestClient(app)


@pytest.mark.parametrize(
    ("source_code", "public_code", "href"),
    (
        ("projection_stale", "projection_stale", "/operator-next/zucai/26116"),
        (
            "telegram_update_owner_conflict",
            "telegram_update_owner_conflict",
            "/operator-next/maintenance",
        ),
        ("action_blocked", "operator_task_blocked", "/operator-next/zucai/26116"),
    ),
)
def test_blocked_operator_api_returns_stable_code_and_recovery_href(
    source_code: str,
    public_code: str,
    href: str,
) -> None:
    response = _blocked_api_client(source_code).post(
        "/api/v2/operator",
        json={
            "schema_version": "2",
            "kind": "request_settlement",
            "expected_snapshot_token": "opaque-command-token",
            "idempotency_key": f"recovery:{source_code}",
            "task_key": TASK_KEY,
        },
    )

    assert response.status_code == 409
    assert response.json()["code"] == public_code
    assert response.json()["details"] == {"recovery_href": href}


class _RecoveryPageQueries(_PageQueries):
    def __init__(self) -> None:
        super().__init__()
        work_item = self.current.work_items[0]
        blocked_action = work_item.next_action.model_copy(update={"enabled": False})
        blocked_item = work_item.model_copy(
            update={
                "blocking_reason": OperatorBlockViewV1(
                    code="evidence_stale",
                    message="证据已超过允许时效。",
                    repair_owner="外部采集",
                    reevaluate_at=NOW + timedelta(minutes=30),
                    recovery_link="/operator-next/zucai/26116",
                ),
                "next_action": blocked_action,
            }
        )
        self.current = self.current.model_copy(update={"work_items": [blocked_item]})


def test_work_item_recovery_panel_exposes_code_owner_time_and_link(tmp_path: Path) -> None:
    response = _page_client(
        tmp_path,
        mode="active",
        operator_queries=_RecoveryPageQueries(),
    ).get("/operator-next/zucai/26116/sale-wave-opaque0001")

    assert response.status_code == 200
    assert "evidence_stale" in response.text
    assert "外部采集" in response.text
    assert "09-05 08:30" in response.text
    assert 'href="/operator-next/zucai/26116"' in response.text
