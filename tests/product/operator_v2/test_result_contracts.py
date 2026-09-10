from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from nutmeg.config.settings import AppSettings, OperatorRuntimeScope, OperatorSurfaceMode
from nutmeg.interfaces.operator_api import mount_operator_api
from nutmeg.ontology.actions.models import (
    ActionOutcome,
    ActionStatus,
    ActorRole,
    ObjectRef,
)
from nutmeg.ontology.operator.result_actions import RequestSettlementRequest
from nutmeg.ontology.wiring import build_ontology_kernel
from nutmeg.product.errors import ProductActionBlockedError
from nutmeg.product.operator_actions import OperatorActionService
from nutmeg.product.operator_contracts import (
    AwaitResultStep,
    OperatorCommandReceipt,
    OperatorLane,
    ResultMatchSummary,
    ResultSourceSummary,
)
from nutmeg.product.operator_queries import OperatorQueryService
from nutmeg.product.operator_runtime import OperatorRuntimeConfig
from nutmeg.product.operator_tokens import (
    OperatorCommandKind,
    OperatorSnapshotTokenCodec,
    OperatorSnapshotTokenError,
)
from nutmeg.product.wiring import build_product_services

NOW = datetime(2026, 9, 5, 8, tzinfo=UTC)
TASK_KEY = "jczq:2026-09-04"
TOKEN_KEY = b"package-ten-result-product-token-key"


class _Actions:
    def __init__(self) -> None:
        self.calls: list[tuple[object, str, object]] = []

    def request_settlement(self, command, *, actor_id, actor_role):
        self.calls.append((command, actor_id, actor_role))
        return OperatorCommandReceipt(
            command_kind="request_settlement",
            status="queued",
            task_key=command.task_key,
        )


class _StaleActions(_Actions):
    def request_settlement(self, command, *, actor_id, actor_role):
        raise OperatorSnapshotTokenError("task_snapshot_changed")


def _client(actions: _Actions) -> TestClient:
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


def _request_document(**extra: object) -> dict[str, object]:
    return {
        "schema_version": "2",
        "kind": "request_settlement",
        "expected_snapshot_token": "opaque.result-bound-command-token",
        "idempotency_key": "browser:request-settlement:1",
        "task_key": TASK_KEY,
        **extra,
    }


def test_request_settlement_routes_only_server_assigned_judge_authority() -> None:
    actions = _Actions()
    response = _client(actions).post(
        "/api/v2/operator",
        json=_request_document(),
    )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert len(actions.calls) == 1
    command, actor_id, actor_role = actions.calls[0]
    assert command.task_key == TASK_KEY
    assert actor_id == "jun"
    assert actor_role.value == "judge_operator"
    assert "actor" not in command.model_dump()
    assert "result_set_revision_id" not in command.model_dump()


@pytest.mark.parametrize(
    "extra",
    (
        {"actor_id": "browser"},
        {"actor_role": "deterministic_system"},
        {"result_set_revision_id": "raw-result-revision"},
        {"prize_table_revision_id": "raw-prize-revision"},
        {"worker_id": "browser-worker"},
    ),
)
def test_request_settlement_rejects_browser_authority_and_result_ids(
    extra: dict[str, str],
) -> None:
    actions = _Actions()
    response = _client(actions).post(
        "/api/v2/operator",
        json=_request_document(**extra),
    )

    assert response.status_code == 422
    assert actions.calls == []


def test_request_settlement_returns_the_closed_stale_task_error() -> None:
    response = _client(_StaleActions()).post(
        "/api/v2/operator",
        json=_request_document(),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "task_snapshot_changed"
    assert response.json()["details"] == {"recovery_href": "/operator-next"}


def _sources(state: str = "available") -> list[ResultSourceSummary]:
    return [
        ResultSourceSummary(source_label=label, state=state)
        for label in ("API-Football", "官方竞彩", "人工核对")
    ]


def test_result_match_contract_enforces_normalized_score_shape() -> None:
    played = ResultMatchSummary(
        official_match_no="001",
        match_label="水晶宫 - 曼彻斯特城",
        agreement_state="agreed",
        result_disposition="played_90",
        home_90=1,
        away_90=0,
        sources=_sources(),
    )

    assert played.score_label == "1 - 0"
    with pytest.raises(ValidationError):
        ResultMatchSummary(
            official_match_no="001",
            match_label="水晶宫 - 曼彻斯特城",
            agreement_state="agreed",
            result_disposition="postponed",
            home_90=1,
            away_90=0,
            sources=_sources(),
        )
    with pytest.raises(ValidationError):
        ResultMatchSummary(
            official_match_no="001",
            match_label="水晶宫 - 曼彻斯特城",
            agreement_state="conflict",
            result_disposition="played_90",
            home_90=1,
            away_90=0,
            sources=_sources(),
        )


def test_not_applicable_settlement_contract_forbids_money_and_tickets() -> None:
    step = AwaitResultStep(
        surface_version="2",
        task_id="zucai:26116",
        title="赛果与结算",
        result_state="not_imported",
        prize_state="missing",
        settlement_state="not_applicable",
    )

    assert step.total_stake_minor == 0
    assert step.total_payout_minor == 0
    assert step.currency is None
    assert step.tickets == []
    with pytest.raises(ValidationError):
        AwaitResultStep(
            surface_version="2",
            task_id="zucai:26116",
            title="赛果与结算",
            result_state="ready",
            prize_state="ready",
            settlement_state="not_applicable",
            currency="CNY",
            total_stake_minor=200,
        )


def test_result_contracts_forbid_unexpected_payload_fields() -> None:
    with pytest.raises(ValidationError):
        ResultSourceSummary(
            source_label="官方竞彩",
            state="available",
            artifact_retrieval_id="must-not-cross-product-boundary",
        )


class _ResultRows:
    def __init__(self, result, *, request=None, run=None) -> None:
        self.result = result
        self.request = request
        self.run = run

    def current_result_set(self, *, lane: str, business_key: str):
        assert lane == "jczq"
        assert business_key == "2026-09-04"
        return self.result

    def result_matches_for_set(self, _revision_id: str):
        return (
            SimpleNamespace(
                match_result_revision_id="match-result-1",
                official_match_no="001",
                match_id="match-1",
                normalized_disposition="played_90",
                normalized_home_90=2,
                normalized_away_90=1,
                agreement_state="agreed",
            ),
            SimpleNamespace(
                match_result_revision_id="match-result-2",
                official_match_no="002",
                match_id="match-2",
                normalized_disposition="official_void",
                normalized_home_90=None,
                normalized_away_90=None,
                agreement_state="agreed",
            ),
        )

    def result_source_receipts_for_set(self, _revision_id: str):
        rows = []
        for match_number in (1, 2):
            for source_index, source_kind in enumerate(
                ("api_football", "sporttery_game90", "okooo_manual")
            ):
                rows.append(
                    SimpleNamespace(
                        match_result_revision_id=f"match-result-{match_number}",
                        source_index=source_index,
                        source_kind=source_kind,
                        receipt_state="available",
                        source_disposition=(
                            "played_90" if match_number == 1 else "official_void"
                        ),
                        home_90=2 if match_number == 1 else None,
                        away_90=1 if match_number == 1 else None,
                        captured_at=NOW.isoformat(),
                        invalid_code=None,
                    )
                )
        return tuple(rows)

    def outcomes_for_result_set(self, _revision_id: str):
        revision_no = getattr(self.result, "revision_no", 1)
        return tuple(
            SimpleNamespace(match_id=f"match-{number}", revision_no=revision_no)
            for number in (1, 2)
        )

    def placed_ticket_ids_for_work_item(self, _work_item_id: str):
        return ("ticket-1",)

    def settlement_request_for_result(self, _revision_id: str):
        return self.request

    def task_settlement_run_for_request(self, _request_id: str):
        return self.run


class _TicketRows:
    def __init__(self, terminal_kind: str) -> None:
        self.terminal_kind = terminal_kind

    def artifact_work_item_links_for_work_item(self, _work_item_id: str):
        return (SimpleNamespace(ticket_artifact_id="artifact-1"),)

    def artifact_terminal_receipt(self, _artifact_id: str):
        return SimpleNamespace(terminal_kind=self.terminal_kind)


class _Uow:
    def __init__(
        self,
        result,
        *,
        terminal_kind: str = "placed",
        request=None,
        run=None,
        worker_state: str = "queued",
    ) -> None:
        self.operator_result = _ResultRows(result, request=request, run=run)
        self.tickets = _TicketRows(terminal_kind)
        self.operator_decision = SimpleNamespace(
            worker_job_for_source=lambda **_kwargs: SimpleNamespace(state=worker_state)
        )

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class _ContextQueries(OperatorQueryService):
    @staticmethod
    def _decision_lineage(_uow, task_key, _as_of, *, require_envelope):
        assert task_key == TASK_KEY
        assert require_envelope is True
        return SimpleNamespace(
            task_key=TASK_KEY,
            task_snapshot_hash="a" * 64,
            work_item_id="jczq:2026-09-04:work-item",
            slate_revision_id="slate-current",
        )


def _context_queries(result) -> OperatorQueryService:
    return _ContextQueries(
        repository=SimpleNamespace(),
        product_queries=SimpleNamespace(),
        official_history_provider=lambda: [],
        clock=lambda: NOW,
        unit_of_work_factory=lambda: _Uow(result),
        snapshot_tokens=OperatorSnapshotTokenCodec(TOKEN_KEY),
    )


def _result_row(**changes: object):
    values = {
        "result_set_revision_id": "result-current",
        "task_family_id": TASK_KEY,
        "work_item_id": "jczq:2026-09-04:work-item",
        "task_snapshot_hash": "a" * 64,
        "slate_revision_id": "slate-current",
        "lane": "jczq",
        "business_key": "2026-09-04",
        "match_count": 2,
        "outcome_count": 2,
        "zucai_prize_table_revision_id": None,
        "revision_no": 1,
        "result_cutoff_at": NOW.isoformat(),
    }
    values.update(changes)
    return SimpleNamespace(**values)


def test_settlement_context_binds_the_exact_ready_result_without_scoreboard_state() -> None:
    context = _context_queries(_result_row()).settlement_request_context(
        TASK_KEY,
        as_of=NOW,
    )

    assert context.task_snapshot_hash == "a" * 64
    assert context.work_item_id == "jczq:2026-09-04:work-item"
    assert context.result_set_revision_id == "result-current"
    assert context.prize_table_revision_id is None
    assert context.dependency_revision_ids == (
        "result_set_revision:result-current",
        "slate_revision:slate-current",
    )
    payload = OperatorSnapshotTokenCodec(TOKEN_KEY).decode(context.command_token)
    assert payload.command_kind is OperatorCommandKind.REQUEST_SETTLEMENT
    assert payload.dependency_revision_ids == list(context.dependency_revision_ids)


class _ResultActions:
    def __init__(self) -> None:
        self.requests: list[RequestSettlementRequest] = []

    def request_settlement(self, request: RequestSettlementRequest) -> ActionOutcome:
        self.requests.append(request)
        return ActionOutcome(
            action_id="action-request-settlement",
            action_type="request_settlement",
            status=ActionStatus.COMMITTED,
            result_refs=(
                ObjectRef("operator_settlement_request", "settlement-request-1"),
            ),
        )


def test_operator_action_service_requests_settlement_from_server_lineage() -> None:
    queries = _context_queries(_result_row())
    context = queries.settlement_request_context(TASK_KEY, as_of=NOW)
    result_actions = _ResultActions()
    service = OperatorActionService(
        queries=queries,
        action_gateway=SimpleNamespace(),
        result_actions=result_actions,
        snapshot_tokens=OperatorSnapshotTokenCodec(TOKEN_KEY),
        clock=lambda: NOW,
    )
    command = SimpleNamespace(
        task_key=TASK_KEY,
        expected_snapshot_token=context.command_token,
        idempotency_key="browser:request-settlement:real-service",
    )

    receipt = service.request_settlement(
        command,
        actor_id="jun",
        actor_role=ActorRole.JUDGE_OPERATOR,
    )

    assert receipt.command_kind == "request_settlement"
    assert receipt.status == "queued"
    assert receipt.task_key == TASK_KEY
    assert result_actions.requests == [
        RequestSettlementRequest(
            result_set_revision_id="result-current",
            expected_task_snapshot_hash="a" * 64,
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="browser:request-settlement:real-service",
            requested_at=NOW,
        )
    ]


def test_active_application_wires_the_result_action_boundary(tmp_path: Path) -> None:
    data_dir = (tmp_path / "candidate").resolve()
    production_dir = (tmp_path / "production").resolve()
    settings = AppSettings(
        _env_file=None,
        data_dir=data_dir,
        production_data_dir=production_dir,
        operator_runtime_scope=OperatorRuntimeScope.ISOLATED_CANDIDATE,
        operator_surface_mode=OperatorSurfaceMode.ACTIVE,
        operator_token_signing_key="package-ten-product-wiring-key-32-bytes",
    )
    runtime = OperatorRuntimeConfig(
        surface_mode=OperatorSurfaceMode.ACTIVE,
        runtime_scope=OperatorRuntimeScope.ISOLATED_CANDIDATE,
        data_dir=data_dir,
        production_data_dir=production_dir,
        running_commit="a" * 40,
    )
    build_ontology_kernel(settings).initialize()

    services = build_product_services(settings, runtime_config=runtime)

    assert services.operator_actions is not None
    assert services.operator_actions._result_actions is services.kernel.result_actions


@pytest.mark.parametrize(
    "changes",
    (
        {"outcome_count": 1},
        {"work_item_id": "another-work-item"},
        {"task_snapshot_hash": "b" * 64},
        {"slate_revision_id": "stale-slate"},
    ),
)
def test_settlement_context_rejects_incomplete_or_stale_result_lineage(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ProductActionBlockedError):
        _context_queries(_result_row(**changes)).settlement_request_context(
            TASK_KEY,
            as_of=NOW,
        )


def test_formal_result_projection_uses_business_labels_and_signed_command() -> None:
    service = _context_queries(_result_row())
    service._repository = SimpleNamespace(
        match=lambda match_id, _as_of: {
            "home_team": "水晶宫" if match_id == "match-1" else "国际米兰",
            "away_team": "曼彻斯特城" if match_id == "match-1" else "都灵",
        }
    )
    lineage = _ContextQueries._decision_lineage(
        None,
        TASK_KEY,
        NOW,
        require_envelope=True,
    )

    built = service._formal_result_stage(
        _Uow(_result_row()),
        lineage,
        OperatorLane.JCZQ,
        "2026-09-04",
        NOW,
        NOW,
    )

    assert built is not None
    assert isinstance(built.step, AwaitResultStep)
    assert built.step.surface_version == "2"
    assert built.step.result_state == "ready"
    assert [item.match_label for item in built.step.result_matches] == [
        "水晶宫 - 曼彻斯特城",
        "国际米兰 - 都灵",
    ]
    assert built.step.result_matches[1].result_disposition == "official_void"
    assert [item.outcome_state for item in built.step.result_matches] == [
        "committed",
        "committed",
    ]
    assert built.step.request_state == "not_requested"
    assert built.step.placed_ticket_count == 1
    assert built.step.settled_ticket_count == 0
    assert built.step.blocking_codes == []
    assert built.step.settlement_ready is True
    assert built.step.settlement_command_token is not None
    assert built.summary.state.value == "await_result"


def test_formal_result_projection_hides_command_while_request_is_queued() -> None:
    service = _context_queries(_result_row())
    service._repository = SimpleNamespace(match=lambda _match_id, _as_of: None)
    lineage = _ContextQueries._decision_lineage(
        None,
        TASK_KEY,
        NOW,
        require_envelope=True,
    )

    built = service._formal_result_stage(
        _Uow(
            _result_row(),
            request=SimpleNamespace(settlement_request_id="settlement-request-1"),
        ),
        lineage,
        OperatorLane.JCZQ,
        "2026-09-04",
        NOW,
        NOW,
    )

    assert built is not None
    assert built.step.settlement_state == "queued"
    assert built.step.request_state == "queued"
    assert built.step.placed_ticket_count == 1
    assert built.step.settled_ticket_count == 0
    assert built.step.last_run is None
    assert built.step.settlement_ready is False
    assert built.step.settlement_command_token is None


def test_zero_placement_projection_is_explicitly_not_applicable() -> None:
    service = _context_queries(None)
    lineage = _ContextQueries._decision_lineage(
        None,
        TASK_KEY,
        NOW,
        require_envelope=True,
    )

    built = service._formal_result_stage(
        _Uow(None, terminal_kind="shadow"),
        lineage,
        OperatorLane.JCZQ,
        "2026-09-04",
        NOW,
        NOW,
    )

    assert built is not None
    assert built.step.settlement_state == "not_applicable"
    assert built.step.tickets == []
    assert built.summary.state.value == "complete"


def test_settlement_projection_loads_leg_grades_once_per_ticket_revision() -> None:
    class _SettlementRows:
        def __init__(self) -> None:
            self.leg_grade_reads = 0

        @staticmethod
        def ticket_settlement_revision(_revision_id: str):
            return SimpleNamespace(
                settlement_revision_id="settlement-1",
                ticket_id="ticket-1",
                settlement_state="settled",
                currency="CNY",
                stake_minor=400,
                paid_note_unit_count=2,
                winning_note_unit_count=2,
                void_note_unit_count=0,
                gross_payout_minor=760,
                revision_no=1,
                method_version="operator-task-settlement-v1",
                rounding_policy_version="cn_sporttery_jczq_v1",
                distinct_note_count=2,
            )

        @staticmethod
        def ticket_notes(_ticket_id: str):
            return tuple(
                SimpleNamespace(
                    ticket_note_id=f"note-{index}",
                    note_index=index - 1,
                    ticket_kind="jczq_pass",
                    structure_code="1x1",
                    group_code=None,
                    stake_minor=200,
                )
                for index in (1, 2)
            )

        @staticmethod
        def ticket_note_settlements(_revision_id: str):
            return tuple(
                SimpleNamespace(
                    ticket_note_id=f"note-{index}",
                    note_grade="won",
                    unit_count=1,
                    correct_leg_count=1,
                    void_leg_count=0,
                    prize_tier_code=None,
                    payout_minor=380,
                    winning_unit_count=1,
                    void_unit_count=0,
                )
                for index in (1, 2)
            )

        def ticket_note_leg_settlements(self, _revision_id: str):
            self.leg_grade_reads += 1
            return tuple(
                SimpleNamespace(
                    ticket_note_leg_id=f"leg-{index}",
                    market_result_code="home",
                    result_disposition="played_90",
                    leg_grade="won",
                )
                for index in (1, 2)
            )

        @staticmethod
        def ticket_note_legs(ticket_note_id: str):
            index = ticket_note_id.partition("-")[2]
            return (
                SimpleNamespace(
                    ticket_note_leg_id=f"leg-{index}",
                    match_id=f"match-{index}",
                    market_definition_id="md-had",
                    selection_code="3",
                    leg_index=0,
                    booked_decimal_odds="1.900000000000",
                    settlement_parameter_decimal=None,
                ),
            )

        @staticmethod
        def settlement_cash_links(_revision_id: str):
            return ()

    rows = _SettlementRows()
    uow = SimpleNamespace(
        operator_result=rows,
        finance=SimpleNamespace(
            ticket=lambda _ticket_id: SimpleNamespace(ticket_kind="jczq_pass")
        ),
        market=SimpleNamespace(market_kind=lambda _market_id: "had"),
    )
    service = _context_queries(_result_row())
    service._repository = SimpleNamespace(match=lambda _match_id, _as_of: None)

    tickets = service._settlement_ticket_views(
        uow,
        SimpleNamespace(ticket_settlement_revision_ids=("settlement-1",)),
        result_rows=(
            SimpleNamespace(match_id="match-1", official_match_no="001"),
            SimpleNamespace(match_id="match-2", official_match_no="002"),
        ),
        cutoff=NOW,
    )

    assert len(tickets[0].notes) == 2
    assert rows.leg_grade_reads == 1
