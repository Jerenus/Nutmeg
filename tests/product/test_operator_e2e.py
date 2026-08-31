from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from nutmeg.config.settings import AppSettings
from nutmeg.interfaces.bot.telegram import TelegramBotRunner
from nutmeg.interfaces.product_api import create_product_app
from nutmeg.ontology.actions.models import ActionStatus
from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository import schema_finance as sf
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.product.actions import ProductActionGateway
from nutmeg.product.operator_actions import OperatorActionService
from nutmeg.product.operator_artifacts import ZucaiArtifactRepository
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


def _session_headers(client: TestClient) -> dict[str, str]:
    response = client.get("/api/v1/session")
    assert response.status_code == 200
    return {
        "X-CSRF-Token": response.json()["csrf_token"],
        "Origin": "http://testserver",
    }


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
    headers = _session_headers(client)

    before = operator_queries.task("jczq:2026-08-24", as_of=clock[0])
    assert before.step.kind == "await_confirmation"
    dispatch = client.post(
        "/api/v1/operator/tasks/jczq:2026-08-24/telegram-confirmation",
        headers=headers,
        json={
            "schema_version": "1",
            "expected_snapshot_token": before.mutation_token,
            "dry_run": True,
            "idempotency_key": "operator:e2e:dispatch:placed",
        },
    )
    assert dispatch.status_code == 200
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
    shadow_dispatch = client.post(
        "/api/v1/operator/tasks/jczq:2026-08-25/telegram-confirmation",
        headers=headers,
        json={
            "schema_version": "1",
            "expected_snapshot_token": shadow_before.mutation_token,
            "dry_run": True,
            "idempotency_key": "operator:e2e:dispatch:shadow",
        },
    )
    assert shadow_dispatch.status_code == 200

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

