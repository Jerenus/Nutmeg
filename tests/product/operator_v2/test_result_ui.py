from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nutmeg.interfaces.operator_ui import mount_operator_ui
from nutmeg.product.operator_contracts import (
    AwaitResultStep,
    OperatorLane,
    OperatorTaskResponse,
    OperatorTaskState,
    OperatorTaskSummary,
    ResultMatchSummary,
    ResultSourceSummary,
    SettlementCashEntrySummary,
    SettlementLegSummary,
    SettlementNoteSummary,
    SettlementTicketSummary,
    TaskProgressSummary,
)

NOW = datetime(2026, 9, 5, 8, tzinfo=UTC)
COMMAND_TOKEN = "opaque.result-bound-settlement-command"


def _source(label: str, state: str, result_label: str | None = None):
    return ResultSourceSummary(
        source_label=label,
        state=state,
        result_label=result_label,
        captured_at=NOW if state != "missing" else None,
    )


def _match(
    *,
    agreement: str = "agreed",
    disposition: str | None = "played_90",
    home: int | None = 2,
    away: int | None = 1,
    sources: list[ResultSourceSummary] | None = None,
):
    return ResultMatchSummary(
        official_match_no="001",
        match_label="水晶宫 - 曼彻斯特城",
        agreement_state=agreement,
        result_disposition=disposition,
        home_90=home,
        away_90=away,
        sources=sources
        or [
            _source("API-Football", "available", "2 - 1"),
            _source("官方竞彩", "available", "2 - 1"),
            _source("人工核对", "available", "2 - 1"),
        ],
    )


def _settled_ticket(*, corrected: bool = False) -> SettlementTicketSummary:
    return SettlementTicketSummary(
        ticket_number=1,
        ticket_kind_label="竞彩 2 串 1",
        settlement_state="corrected" if corrected else "settled",
        currency="CNY",
        stake_minor=400,
        paid_note_unit_count=2,
        winning_note_unit_count=1,
        void_note_unit_count=0,
        payout_minor=760,
        revision_no=2 if corrected else 1,
        corrected=corrected,
        settlement_method_label="确定性整单结算 v1",
        rounding_policy_label="竞彩逐注四舍五入 v1",
        distinct_note_count=2,
        cash_entries=(
            [
                SettlementCashEntrySummary(
                    transaction_kind="payout_reversal",
                    amount_minor=-500,
                    currency="CNY",
                    replaces_prior_payout=True,
                ),
                SettlementCashEntrySummary(
                    transaction_kind="payout",
                    amount_minor=760,
                    currency="CNY",
                    replaces_prior_payout=False,
                ),
            ]
            if corrected
            else []
        ),
        notes=[
            SettlementNoteSummary(
                note_number=1,
                structure_label="2 串 1",
                grade="won",
                unit_count=1,
                correct_leg_count=2,
                void_leg_count=0,
                prize_label=None,
                payout_minor=760,
                note_index=0,
                note_grade="won",
                winning_unit_count=1,
                void_unit_count=0,
                stake_minor=200,
                legs=[
                    SettlementLegSummary(
                        match_label="水晶宫 - 曼彻斯特城",
                        market_label="胜平负",
                        selection_label="主胜",
                        result_label="主胜",
                        grade="won",
                        leg_index=0,
                        official_match_no="001",
                        market_code="had",
                        selection_code="3",
                        result_disposition="played_90",
                        market_result_code="home",
                        leg_grade="won",
                        booked_decimal_odds="1.900000000000",
                    ),
                    SettlementLegSummary(
                        match_label="国际米兰 - 都灵",
                        market_label="总进球",
                        selection_label="2 球",
                        result_label="2 球",
                        grade="won",
                        leg_index=1,
                        official_match_no="002",
                        market_code="ttg",
                        selection_code="2",
                        result_disposition="played_90",
                        market_result_code="2",
                        leg_grade="won",
                        booked_decimal_odds="2.000000000000",
                    ),
                ],
            ),
            SettlementNoteSummary(
                note_number=2,
                structure_label="2 串 1",
                grade="lost",
                unit_count=1,
                correct_leg_count=1,
                void_leg_count=0,
                prize_label=None,
                payout_minor=0,
                note_index=1,
                note_grade="lost",
                winning_unit_count=0,
                void_unit_count=0,
                stake_minor=200,
                legs=[],
            ),
        ],
    )


class _Queries:
    def __init__(self, step: AwaitResultStep) -> None:
        selected = OperatorTaskSummary(
            task_id=step.task_id,
            lane=(
                OperatorLane.JCZQ
                if step.task_id.startswith("jczq:")
                else OperatorLane.ZUCAI
            ),
            business_key=step.task_id.partition(":")[2],
            title="竞彩 2026-09-04",
            state=OperatorTaskState.AWAIT_RESULT,
            deadline_at=NOW,
            is_actionable=step.settlement_command_token is not None,
            next_action_label="查看赛果状态",
            priority_rank=0,
        )
        self.response = OperatorTaskResponse(
            as_of=NOW,
            mutation_token="d" * 64,
            selected=selected,
            alternatives=[],
            progress=TaskProgressSummary(completed=0, total=1, label="赛果与结算"),
            step=step,
        )

    def task(self, _task_id: str, *, as_of):
        return self.response

    def worklist(self, *, as_of):
        return SimpleNamespace(selected=self.response.selected, tasks=[], as_of=as_of)


def _html(step: AwaitResultStep, *, read_only: bool = False) -> str:
    app = FastAPI()
    mount_operator_ui(
        app,
        SimpleNamespace(operator_queries=_Queries(step)),
        lambda: NOW,
        read_only=read_only,
    )
    response = TestClient(app).get(f"/tasks/{step.task_id}")
    assert response.status_code == 200
    return response.text


def _step(**changes: object) -> AwaitResultStep:
    values: dict[str, object] = {
        "surface_version": "2",
        "task_id": "jczq:2026-09-04",
        "title": "赛果与结算",
        "result_state": "ready",
        "result_matches": [_match()],
        "prize_state": "not_applicable",
        "settlement_state": "not_requested",
        "settlement_command_token": COMMAND_TOKEN,
    }
    values.update(changes)
    values.setdefault(
        "settlement_ready",
        values["settlement_command_token"] is not None,
    )
    return AwaitResultStep(**values)


def test_missing_and_conflicting_sources_are_explained_without_a_settlement_form() -> None:
    missing = _step(
        result_state="missing",
        result_matches=[
            _match(
                agreement="missing",
                disposition=None,
                home=None,
                away=None,
                sources=[
                    _source("API-Football", "available", "2 - 1"),
                    _source("官方竞彩", "available", "2 - 1"),
                    _source("人工核对", "missing"),
                ],
            )
        ],
        settlement_state="result_waiting",
        settlement_command_token=None,
    )
    conflict = _step(
        result_state="conflict",
        result_matches=[
            _match(
                agreement="conflict",
                disposition=None,
                home=None,
                away=None,
                sources=[
                    _source("API-Football", "available", "2 - 1"),
                    _source("官方竞彩", "available", "1 - 1"),
                    _source("人工核对", "available", "2 - 1"),
                ],
            )
        ],
        settlement_state="result_waiting",
        settlement_command_token=None,
    )

    missing_html = _html(missing)
    conflict_html = _html(conflict)

    assert "3 个来源中已到 2 个" in missing_html
    assert "人工核对" in missing_html and "尚未取得" in missing_html
    assert "三源结果不一致" in conflict_html
    assert "2 - 1" in conflict_html and "1 - 1" in conflict_html
    assert 'data-action="request-settlement"' not in missing_html
    assert 'data-action="request-settlement"' not in conflict_html


def test_ready_results_offer_one_explicit_judge_owned_settlement_request() -> None:
    html = _html(_step())

    assert "90 分钟赛果已核对" in html
    assert "水晶宫 - 曼彻斯特城" in html
    assert "2 - 1" in html
    assert 'data-action="request-settlement"' in html
    assert f'data-command-token="{COMMAND_TOKEN}"' in html
    assert "开始结算" in html
    assert "自动结算" not in html


def test_result_javascript_refreshes_and_posts_the_settlement_command() -> None:
    script = (
        Path(__file__).parents[3]
        / "nutmeg/interfaces/web/static/product/operator.js"
    ).read_text(encoding="utf-8")

    assert 'action === "request-settlement"' in script
    assert 'kind: "request_settlement"' in script
    assert "expected_snapshot_token: step.settlement_command_token" in script
    assert "result_set_revision_id" not in script
    assert "prize_table_revision_id" not in script


def test_read_only_result_page_never_exposes_a_mutation_form() -> None:
    html = _html(_step(), read_only=True)

    assert "90 分钟赛果已核对" in html
    assert "只读模式" in html
    assert 'data-action="request-settlement"' not in html


def test_settlement_view_renders_every_note_leg_payout_and_correction_label() -> None:
    html = _html(
        _step(
            settlement_state="corrected",
            settlement_command_token=None,
            currency="CNY",
            total_stake_minor=400,
            total_payout_minor=760,
            request_state="completed",
            placed_ticket_count=1,
            settled_ticket_count=1,
            tickets=[_settled_ticket(corrected=True)],
        )
    )

    for visible in (
        "结算已更正",
        "投入 ¥4.00",
        "返奖 ¥7.60",
        "第 1 票",
        "竞彩 2 串 1",
        "第 1 注",
        "命中",
        "未中",
        "水晶宫 - 曼彻斯特城",
        "胜平负",
        "主胜",
        "国际米兰 - 都灵",
        "总进球",
        "2 球",
        "结算请求已完成",
        "已结算 1 / 1 票",
        "第 2 版",
        "确定性整单结算 v1",
        "竞彩逐注四舍五入 v1",
        "撤销上次返奖 -¥5.00",
        "返奖入账 +¥7.60",
        "出票赔率",
        "1.900000000000",
    ):
        assert visible in html
    assert 'data-action="request-settlement"' not in html


def test_not_applicable_result_view_is_zero_money_and_has_no_ticket_rows() -> None:
    html = _html(
        _step(
            task_id="zucai:26116",
            result_state="not_imported",
            result_matches=[],
            prize_state="missing",
            settlement_state="not_applicable",
            settlement_command_token=None,
        )
    )

    assert "本期没有实际出票，无需结算" in html
    assert "¥" not in html
    assert "第 1 票" not in html


def test_result_surface_hides_raw_json_and_ontology_identifiers() -> None:
    html = _html(
        _step(
            settlement_state="settled",
            settlement_command_token=None,
            currency="CNY",
            total_stake_minor=400,
            total_payout_minor=760,
            tickets=[_settled_ticket()],
        )
    )

    assert "<pre" not in html
    assert "{" not in html
    assert not re.search(r"\b[0-9a-f]{64}\b", html)
    for forbidden in (
        "result_set_revision_id",
        "outcome_revision_id",
        "settlement_revision_id",
        "ticket_id",
        "action_id",
        "content_hash",
        "payload_json",
        "artifact_retrieval_id",
        'name="actor_id"',
        'name="actor_role"',
        "deterministic_system",
    ):
        assert forbidden not in html
