import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from nutmeg.config.settings import AppSettings
from nutmeg.interfaces.bot.telegram import TelegramBotRunner
from nutmeg.interfaces.product_api import create_product_app
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.workflow_actions import (
    RecordAdjudicationRequest,
    RegisterPredictionRequest,
)
from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository import schema_finance as sf
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.product.actions import ProductActionGateway
from nutmeg.product.operator_actions import OperatorActionService
from nutmeg.product.operator_artifacts import ZucaiArtifactRepository
from nutmeg.product.operator_contracts import (
    GradePredictionCommand,
    RequestTelegramConfirmationCommand,
)
from nutmeg.product.operator_queries import OperatorQueryService
from nutmeg.product.queries import ProductQueryService
from nutmeg.product.repository import ProductReadRepository
from nutmeg.services.telegram_ticket_confirmation import (
    TelegramTicketConfirmationService,
)
from tests.ontology.test_protected_ticket_actions import (
    AT,
    _approve_request,
    _create_request,
    _created_row,
    _leg,
    _setup,
)
from tests.product.operator_fixtures import write_26112_bundle


class _TelegramClient:
    def __init__(self) -> None:
        self.updates: list[dict[str, object]] = []
        self.answers: list[tuple[str, str]] = []
        self.messages: list[tuple[int, str, object]] = []

    def get_updates(self, *, offset, timeout):
        updates, self.updates = self.updates, []
        return updates

    def answer_callback_query(self, *, callback_query_id, text):
        self.answers.append((callback_query_id, text))

    def send_message(self, *, chat_id, text, reply_markup=None):
        self.messages.append((chat_id, text, reply_markup))
        return {"ok": True, "result": {"message_id": 8}}


class _NoMessageAdapter:
    def handle_message(self, text):
        raise AssertionError(f"protected callback reached message router: {text}")


class _RecordingConfirmationService:
    def __init__(self, service: TelegramTicketConfirmationService) -> None:
        self.service = service
        self.last = None

    def request_confirmation(self, **kwargs):
        self.last = self.service.request_confirmation(**kwargs)
        return self.last

    def handle_callback(self, callback):
        return self.service.handle_callback(callback)

    def expire_due(self):
        return self.service.expire_due()


def _artifact(kernel, forecast_id: str, *, run_date: str, index: int):
    request = replace(
        _create_request(_leg(forecast_id), key=f"operator:e2e:create:{index}"),
        run_date=run_date,
    )
    created = kernel.protected_tickets.create_ticket_batch(request)
    draft = _created_row(kernel, created)
    assert draft is not None
    approved = kernel.protected_tickets.approve_ticket_batch(
        _approve_request(
            draft.ticket_batch_id,
            draft.revision_no,
            key=f"operator:e2e:approve:{index}",
        )
    )
    assert approved.status is ActionStatus.COMMITTED
    artifact_id = next(
        ref.object_id
        for ref in approved.result_refs
        if ref.object_type == "audited_ticket_artifact"
    )
    with OntologyUnitOfWork(kernel.engine) as uow:
        artifact = uow.tickets.ticket_artifact(artifact_id)
    assert artifact is not None
    return artifact


def test_operator_confirmation_books_one_and_timeout_explains_shadow(
    tmp_path: Path,
) -> None:
    kernel, forecast_id = _setup(tmp_path)
    placed_artifact = _artifact(
        kernel, forecast_id, run_date="2026-08-24", index=1
    )
    shadow_artifact = _artifact(
        kernel, forecast_id, run_date="2026-08-25", index=2
    )
    clock = [AT]
    telegram_client = _TelegramClient()
    confirmation = _RecordingConfirmationService(
        TelegramTicketConfirmationService(
            kernel=kernel,
            telegram_client=telegram_client,
            allowed_chat_ids={111},
            now_fn=lambda: clock[0],
        )
    )
    settings = AppSettings(data_dir=tmp_path / "data", default_user_id="owner")
    repository = ProductReadRepository(kernel.engine)
    product_queries = ProductQueryService(repository, kernel)
    operator_queries = OperatorQueryService(
        repository=repository,
        product_queries=product_queries,
        artifacts=ZucaiArtifactRepository(tmp_path / "empty-zucai"),
        official_history_provider=lambda: [],
        clock=lambda: clock[0],
    )
    actions = ProductActionGateway(kernel, repository, clock=lambda: clock[0])
    operator_actions = OperatorActionService(
        queries=operator_queries,
        action_gateway=actions,
        telegram_confirmation=confirmation,
        telegram_owner_chat_id=111,
    )
    services = SimpleNamespace(
        kernel=kernel,
        queries=product_queries,
        actions=actions,
        settings=settings,
        operator_queries=operator_queries,
        operator_actions=operator_actions,
        copilot=None,
        tickets=SimpleNamespace(),
    )
    client = TestClient(
        create_product_app(
            services,
            session_secret="operator-e2e-session",
            csrf_secret="operator-e2e-csrf",
            clock=lambda: clock[0],
        )
    )
    before = operator_queries.task("jczq:2026-08-24", as_of=clock[0])
    assert before.step.kind == "await_confirmation"
    dispatch = operator_actions.request_telegram_confirmation(
        "jczq:2026-08-24",
        RequestTelegramConfirmationCommand(
            expected_snapshot_token=before.mutation_token,
            dry_run=True,
            idempotency_key="operator:e2e:dispatch:placed",
        ),
        actor_id="owner",
        actor_role=ActorRole.JUDGE_OPERATOR,
    )
    assert dispatch.dispatch_state == "dry_run"
    assert confirmation.last is not None

    runner = TelegramBotRunner(
        client=telegram_client,
        bot_adapter=_NoMessageAdapter(),
        allowed_chat_ids={111},
        confirmation_handler=confirmation,
    )
    clock[0] = AT + timedelta(minutes=1)
    telegram_client.updates = [{
        "update_id": 1,
        "callback_query": {
            "id": "operator-cb-placed",
            "data": confirmation.last.callback_data,
            "message": {"message_id": 8, "chat": {"id": 111}},
        },
    }]
    callback = runner.poll_once(offset=1, timeout=0)
    after = operator_queries.task("jczq:2026-08-24", as_of=clock[0])

    assert callback.callbacks_handled == 1
    assert after.step.kind == "await_result"

    shadow_before = operator_queries.task("jczq:2026-08-25", as_of=clock[0])
    shadow_dispatch = operator_actions.request_telegram_confirmation(
        "jczq:2026-08-25",
        RequestTelegramConfirmationCommand(
            expected_snapshot_token=shadow_before.mutation_token,
            dry_run=True,
            idempotency_key="operator:e2e:dispatch:shadow",
        ),
        actor_id="owner",
        actor_role=ActorRole.JUDGE_OPERATOR,
    )
    assert shadow_dispatch.dispatch_state == "dry_run"

    clock[0] = AT + timedelta(hours=2, minutes=1)
    timeout = runner.poll_once(offset=2, timeout=0)
    shadow_after = operator_queries.task("jczq:2026-08-25", as_of=clock[0])
    shadow_page = client.get("/tasks/jczq:2026-08-25")

    assert timeout.shadows_marked == 1
    assert shadow_after.selected.state == "complete"
    assert "未确认，按未出票处理" in shadow_page.text
    assert "没有入账" in shadow_page.text

    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.finance.count_tickets() == 1
        assert uow.tickets.count_placements() == 1
        assert uow.finance.ledger_balance("acct-jczq") == -placed_artifact.amount
        assert uow.tickets.shadow_for_artifact(
            shadow_artifact.ticket_artifact_id
        ) is not None
        assert uow.connection.execute(
            select(func.count()).select_from(sf.cash_transactions)
        ).scalar_one() == 1
        confirm_role = uow.connection.execute(
            select(schema.actions.c.actor_role).where(
                schema.actions.c.action_type == "confirm_ticket_placement"
            )
        ).scalar_one()
    assert confirm_role == "judge_operator"


def test_grading_advances_one_review_item_at_a_time(tmp_path: Path) -> None:
    kernel, forecast_id = _setup(tmp_path)
    artifact = _artifact(kernel, forecast_id, run_date="2026-08-24", index=1)
    telegram_client = _TelegramClient()
    confirmation = TelegramTicketConfirmationService(
        kernel=kernel,
        telegram_client=telegram_client,
        allowed_chat_ids={111},
        now_fn=lambda: AT,
    )
    prepared = confirmation.request_confirmation(
        ticket_artifact_id=artifact.ticket_artifact_id,
        chat_id=111,
        dry_run=True,
        requested_at=AT,
    )
    confirmation.handle_callback({
        "id": "operator-review-placement",
        "data": prepared.callback_data,
        "message": {"message_id": 8, "chat": {"id": 111}},
    })

    artifact_root = write_26112_bundle(tmp_path / "zucai")
    rx_path = artifact_root / "26112-rx.json"
    rx = json.loads(rx_path.read_text("utf-8"))
    rx["outcomes"] = {
        "settled_at": "2026-08-29T10:00:00+08:00",
        "source": "official 90-minute results",
        "draw_result": "fixture",
        "position": "placed",
        "prescription_score": "fixture",
        "ticket_counterfactuals": "fixture",
        "predictions": {},
        "adjudication_outcomes": {},
        "key_lessons": "not operator copy",
    }
    rx_path.write_text(json.dumps(rx, ensure_ascii=False), "utf-8")

    prediction_ids = []
    for index, (claim, falsifier) in enumerate((
        ("至少一场平", "全无平局"),
        ("主队至少赢一场", "主队全不胜"),
    )):
        registered = kernel.workflow.register_prediction(
            RegisterPredictionRequest(
                match_id=None,
                subject_type="issue",
                subject_id="26112",
                claim=claim,
                falsifier=falsifier,
                actor_id="operator:owner",
                actor_role=ActorRole.JUDGE_OPERATOR,
                idempotency_key=f"operator:e2e:prediction:{index}",
                requested_at=AT + timedelta(seconds=index + 1),
            )
        )
        assert registered.status is ActionStatus.COMMITTED
        prediction_ids.append(registered.result_refs[0].object_id)

    alternatives = (
        {"rx_adjudication_id": "ADJ-1", "selected_option": "R432"},
        {"candidate_id": "R432", "deviation_registry": []},
        {
            "deployment_decision": "keep",
            "ticket_artifact_id": artifact.ticket_artifact_id,
        },
    )
    for index, alternative in enumerate(alternatives):
        outcome = kernel.workflow.record_adjudication(
            RecordAdjudicationRequest(
                subject_type="issue",
                subject_id="26112",
                decision="operator_workbench",
                reason="test fixture transition",
                evidence_rejected=[],
                alternative=alternative,
                supersedes_adjudication_id=None,
                actor_id="operator:owner",
                actor_role=ActorRole.JUDGE_OPERATOR,
                idempotency_key=f"operator:e2e:adjudication:{index}",
                requested_at=AT + timedelta(minutes=index + 1),
            )
        )
        assert outcome.status is ActionStatus.COMMITTED

    clock = AT + timedelta(minutes=5)
    repository = ProductReadRepository(kernel.engine)
    product_queries = ProductQueryService(repository, kernel)
    queries = OperatorQueryService(
        repository=repository,
        product_queries=product_queries,
        artifacts=ZucaiArtifactRepository(artifact_root),
        official_history_provider=lambda: [],
        clock=lambda: clock,
    )
    service = OperatorActionService(
        queries=queries,
        action_gateway=ProductActionGateway(kernel, repository, clock=lambda: clock),
    )

    first = queries.task("zucai:26112", as_of=clock)
    assert first.step.kind == "review"
    assert first.step.current_item.item_id == prediction_ids[0]
    result = service.grade_prediction(
        "zucai:26112",
        GradePredictionCommand(
            expected_snapshot_token=first.mutation_token,
            prediction_id=prediction_ids[0],
            outcome="hit",
            reason="official result satisfies the claim",
            idempotency_key="operator:e2e:grade:1",
        ),
        actor_id="owner",
        actor_role=ActorRole.JUDGE_OPERATOR,
    )
    assert result.status == "committed"

    second = queries.task("zucai:26112", as_of=clock)
    assert second.step.current_item.item_id == prediction_ids[1]
    service.grade_prediction(
        "zucai:26112",
        GradePredictionCommand(
            expected_snapshot_token=second.mutation_token,
            prediction_id=prediction_ids[1],
            outcome="miss",
            reason="official result falsifies the claim",
            idempotency_key="operator:e2e:grade:2",
        ),
        actor_id="owner",
        actor_role=ActorRole.JUDGE_OPERATOR,
    )

    final = queries.task("zucai:26112", as_of=clock)
    assert final.selected.state == "complete"
