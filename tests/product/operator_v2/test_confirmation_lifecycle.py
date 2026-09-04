from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from nutmeg.config.settings import AppSettings
from nutmeg.interfaces.product_api import create_product_app
from nutmeg.ontology.actions.models import ActionStatus, ActorRole, canonical_json
from nutmeg.ontology.actions.protected_ticket_actions import (
    ConfirmTicketPlacementRequest,
    ProtectedTicketActions,
)
from nutmeg.ontology.artifacts import ContentAddressedArtifactStore
from nutmeg.ontology.errors import IdempotencyConflictError
from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository import schema_finance as sf
from nutmeg.ontology.repository import schema_operator_result as sor
from nutmeg.ontology.repository import schema_tickets as st
from nutmeg.ontology.repository.operator_result import OperatorResultRepository
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel
from nutmeg.product import operator_workers
from nutmeg.product.operator_runtime import (
    OperatorRuntimeConfig,
    OperatorRuntimeScope,
    OperatorSurfaceMode,
)
from nutmeg.product.wiring import build_product_services
from nutmeg.services import telegram_ticket_confirmation as confirmation_services
from nutmeg.services.telegram_ticket_confirmation import (
    TelegramOwnerHeartbeatService,
    TelegramTicketConfirmationService,
)
from tests.ontology.operator.test_confirmation_cas import _issue
from tests.ontology.operator.test_no_ticket_actions import (
    AT,
    WORK_ITEM_ID,
    _artifact_fixture,
    _clean_candidate_audit,
)


class _NoopTelegramClient:
    def send_message(self, **_kwargs):
        return None


def _protected(fixture, tmp_path: Path) -> ProtectedTicketActions:
    return ProtectedTicketActions(
        fixture.action_service,
        ContentAddressedArtifactStore(tmp_path / "ticket-artifacts"),
        operator_decisions=fixture.actions,
        operator_candidate_auditor=_clean_candidate_audit,
    )


def _owner(fixture, *, observed_at):
    service = TelegramOwnerHeartbeatService(
        action_service=fixture.action_service,
        account_id="nutmeg",
        owner_instance_id="openclaw-primary",
        transport_label="openclaw-telegram",
        owner_mode="openclaw",
        router_version="ntc-v1",
        lease_duration=timedelta(seconds=90),
    )
    service.pulse(observed_at=observed_at)
    return service


def _confirmation(fixture, protected, *, now):
    kernel = SimpleNamespace(
        engine=fixture.engine,
        protected_tickets=protected,
    )
    return TelegramTicketConfirmationService(
        kernel=kernel,
        telegram_client=_NoopTelegramClient(),
        allowed_chat_ids={111},
        now_fn=lambda: now,
    )


def _update(*, callback_data: str, ingress_at, **changes):
    values = {
        "account_id": "nutmeg",
        "owner_instance_id": "openclaw-primary",
        "callback_query_id": "callback-1",
        "sender_id": "222",
        "chat_id": "111",
        "message_id": "7",
        "authorized": True,
        "namespace": "ntc",
        "callback_data": callback_data,
        "server_ingress_at": ingress_at,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _callback_counts(engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            "terminal": int(
                connection.scalar(
                    select(func.count()).select_from(
                        st.operator_artifact_terminal_receipts
                    )
                )
                or 0
            ),
            "attestation": int(
                connection.scalar(
                    select(func.count()).select_from(
                        sor.operator_telegram_callback_attestations
                    )
                )
                or 0
            ),
            "ticket": int(
                connection.scalar(select(func.count()).select_from(sf.tickets)) or 0
            ),
            "cash": int(
                connection.scalar(
                    select(func.count()).select_from(sf.cash_transactions)
                )
                or 0
            ),
            "placement": int(
                connection.scalar(
                    select(func.count()).select_from(st.ticket_placements)
                )
                or 0
            ),
        }


def _replay_workspace(tmp_path: Path, variable: str) -> tuple[Path, Path]:
    configured = os.environ.get(variable)
    root = (tmp_path if configured is None else Path(configured)).resolve()
    workspace = root / "data" / "ontology"
    workspace.mkdir(parents=True, exist_ok=True)
    return root, workspace


def test_isolated_callback_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, workspace = _replay_workspace(tmp_path, "NUTMEG_P9_REPLAY_ROOT")
    base_time = datetime.now(UTC) - timedelta(minutes=1)
    from tests.ontology.operator import test_candidate_actions as candidate_module
    from tests.ontology.operator import test_confirmation_cas as confirmation_module
    from tests.ontology.operator import test_judgment_actions as judgment_module
    from tests.ontology.operator import test_no_ticket_actions as no_ticket_module

    monkeypatch.setattr(judgment_module, "AT", base_time)
    monkeypatch.setattr(candidate_module, "AT", base_time)
    monkeypatch.setattr(no_ticket_module, "AT", base_time)
    monkeypatch.setattr(confirmation_module, "AT", base_time)

    fixture = _artifact_fixture(workspace, at=base_time)
    protected = _protected(fixture, workspace)
    issued = _issue(protected, fixture, key="confirmation:public-replay:issue")
    assert issued.nonce is not None

    project_root = Path(__file__).resolve().parents[3]
    plugin_path = (
        project_root
        / "integrations"
        / "openclaw"
        / "nutmeg-ticket-confirmation"
        / "index.js"
    )
    node_program = r"""
import { pathToFileURL } from "node:url";

let raw = "";
for await (const chunk of process.stdin) raw += chunk;
const input = JSON.parse(raw);
const module = await import(pathToFileURL(process.argv.at(-1)).href);
const registrations = { handlers: [], services: [] };
const plugin = module.createNutmegTicketConfirmationPlugin();
plugin.register({
  registrationMode: "full",
  pluginConfig: input.pluginConfig,
  registerInteractiveHandler(value) { registrations.handlers.push(value); },
  registerService(value) { registrations.services.push(value); },
});
const responses = { replies: [], edits: [] };
await registrations.services[0].start({ logger: { warn() {} } });
const result = await registrations.handlers[0].handler({
  accountId: "nutmeg",
  callbackId: "public-callback-1",
  senderId: "222",
  auth: { isAuthorizedSender: true },
  callback: { data: input.callbackData, chatId: 111, messageId: 7 },
  respond: {
    async reply(value) { responses.replies.push(value); },
    async editMessage(value) { responses.edits.push(value); },
  },
});
await registrations.services[0].stop();
process.stdout.write(JSON.stringify({ result, responses }));
"""
    document = {
        "pluginConfig": {
            "projectRoot": str(project_root),
            "accountId": "nutmeg",
            "ownerInstanceId": "openclaw-primary",
            "allowedChatIds": ["111"],
            "allowedSenderIds": ["222"],
            "heartbeatIntervalSeconds": 30,
            "leaseSeconds": 90,
        },
        "callbackData": f"ntc:{issued.nonce}",
    }
    environment = os.environ.copy()
    environment.update(
        {
            "NUTMEG_DATA_DIR": str(root / "data"),
            "NUTMEG_PRODUCTION_DATA_DIR": str(root / "production"),
            "NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS": "111",
        }
    )
    completed = subprocess.run(  # noqa: S603 - fixed executable and local fixture
        ["node", "--input-type=module", "-e", node_program, str(plugin_path)],
        cwd=project_root,
        env=environment,
        input=json.dumps(document),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    public = json.loads(completed.stdout)
    assert public == {
        "result": {"handled": True},
        "responses": {
            "replies": [],
            "edits": [{"text": "Placement recorded.", "buttons": []}],
        },
    }
    assert _callback_counts(fixture.engine) == {
        "terminal": 1,
        "attestation": 1,
        "ticket": 1,
        "cash": 1,
        "placement": 1,
    }


def test_isolated_timeout_replay(tmp_path: Path) -> None:
    root, workspace = _replay_workspace(tmp_path, "NUTMEG_P9_REPLAY_ROOT")
    fixture = _artifact_fixture(workspace)
    protected = _protected(fixture, workspace)
    _issue(protected, fixture, key="confirmation:timeout-replay:issue")
    worker = operator_workers.ConfirmationDeadlineWorker(
        action_service=fixture.action_service,
        protected_tickets=protected,
        worker_id="operator-confirmation-deadline",
    )
    supervisor = operator_workers.OperatorInfrastructureWorkers(
        confirmation_deadlines=worker,
        data_dir=root / "data",
        clock=lambda: fixture.cutoff,
        poll_interval_seconds=60,
    )
    settings = AppSettings(
        _env_file=None,
        data_dir=root / "data",
        production_data_dir=(root / "production").resolve(),
    )
    runtime = OperatorRuntimeConfig(
        surface_mode=OperatorSurfaceMode.ACTIVE,
        runtime_scope=OperatorRuntimeScope.ISOLATED_CANDIDATE,
        data_dir=(root / "data").resolve(),
        production_data_dir=(root / "production").resolve(),
        running_commit="isolated-p9-replay",
    )
    unavailable = SimpleNamespace()
    services = SimpleNamespace(
        settings=settings,
        runtime=runtime,
        infrastructure_workers=supervisor,
        queries=unavailable,
        actions=unavailable,
        operator_queries=unavailable,
        operator_actions=unavailable,
        copilot=None,
        tickets=unavailable,
        confirmation_transport_kind="simulated",
    )

    with TestClient(
        create_product_app(
            services,
            session_secret="isolated-p9-session",
            csrf_secret="isolated-p9-csrf",
            clock=lambda: fixture.cutoff,
            runtime_config=runtime,
        )
    ):
        pass

    with OntologyUnitOfWork(fixture.engine) as uow:
        terminal = uow.tickets.artifact_terminal_receipt(fixture.artifact_id)
    assert terminal is not None
    assert terminal.terminal_kind == "shadow"
    assert terminal.terminal_reason == "deadline_unconfirmed"
    assert _callback_counts(fixture.engine) == {
        "terminal": 1,
        "attestation": 0,
        "ticket": 0,
        "cash": 0,
        "placement": 0,
    }


def test_active_product_services_register_package9_consumers(tmp_path: Path) -> None:
    data_dir = (tmp_path / "isolated").resolve()
    production_dir = (tmp_path / "production").resolve()
    settings = AppSettings(
        _env_file=None,
        data_dir=data_dir,
        production_data_dir=production_dir,
        operator_surface_mode="active",
        operator_runtime_scope="isolated_candidate",
        operator_token_signing_key="isolated-p9-signing-key-32-bytes-min",
    )
    kernel = build_ontology_kernel(settings)
    kernel.initialize()
    runtime = OperatorRuntimeConfig(
        surface_mode=OperatorSurfaceMode.ACTIVE,
        runtime_scope=OperatorRuntimeScope.ISOLATED_CANDIDATE,
        data_dir=data_dir,
        production_data_dir=production_dir,
        running_commit="isolated-p9-replay",
    )

    services = build_product_services(settings, runtime_config=runtime)

    assert isinstance(
        services.infrastructure_workers,
        operator_workers.OperatorInfrastructureWorkers,
    )
    assert services.infrastructure_workers.worker_names == (
        "EvidenceFreezeRequestWorker",
        "MarketBaselineWorker",
        "CandidateGenerationWorker",
        "ConfirmationDeadlineWorker",
    )


def test_market_baseline_worker_resolves_work_item_without_existing_baseline(
    tmp_path: Path,
) -> None:
    from nutmeg.product.wiring import _operator_work_item_id
    from tests.ontology.operator.test_judgment_actions import (
        AT as JUDGMENT_AT,
    )
    from tests.ontology.operator.test_judgment_actions import (
        _fixture as judgment_fixture,
    )

    fixture = judgment_fixture(tmp_path)
    worker = operator_workers.MarketBaselineWorker(
        action_service=fixture.action_service,
        decision_actions=fixture.decision_actions,
        worker_id="operator-market-baseline",
        lease_duration=timedelta(minutes=5),
        work_item_id_resolver=lambda revision_id: _operator_work_item_id(
            fixture.engine,
            revision_id,
        ),
    )

    completed = worker.run_once(limit=1, as_of=JUDGMENT_AT + timedelta(seconds=2))

    scope_material = {
        "families": ["offer-family-1"],
        "revisions": ["offer-revision-1"],
    }
    scope_key = hashlib.sha256(
        canonical_json(scope_material).encode("utf-8")
    ).hexdigest()[:16]
    expected = f"jczq:2026-09-04:{'c' * 64}:sale_wave:{scope_key}"
    assert len(completed) == 1
    with OntologyUnitOfWork(fixture.engine) as uow:
        baseline = uow.operator_decision.market_prior_baseline_revision(
            completed[0].result_refs[0].object_id
        )
    assert baseline is not None
    assert baseline.work_item_id == expected


def test_official_cancellation_import_terminalizes_open_challenge_atomically(
    tmp_path: Path,
) -> None:
    from sqlalchemy import insert

    from nutmeg.ontology.operator.sale_actions import (
        ImportOfficialSaleSlateRequest,
        OfficialSaleSlateManifestV1,
        SaleActions,
        official_sale_parser_receipt_hash,
    )

    fixture = _artifact_fixture(tmp_path)
    protected = _protected(fixture, tmp_path)
    _issue(protected, fixture, key="confirmation:official-cancel:issue")
    published = AT + timedelta(minutes=4)
    retrieved = AT + timedelta(minutes=5)
    manifest = OfficialSaleSlateManifestV1.model_validate(
        {
            "schema_version": "official-sale-slate-v1",
            "lane": "jczq",
            "business_key": "2026-09-04",
            "published_at": published,
            "retrieved_at": retrieved,
            "official_source_artifact_retrieval_id": "retrieval-correction",
            "supersedes_slate_revision_id": "slate-1",
            "offers": [
                {
                    "canonical_match_id": "match-1",
                    "official_match_no": "001",
                    "market_definition_ids": ["md-had"],
                    "sale_opens_at": AT - timedelta(hours=1),
                    "sale_deadline_at": fixture.cutoff,
                    "status": "cancelled",
                }
            ],
        }
    )
    content_hash = official_sale_parser_receipt_hash(
        lane="jczq",
        business_key="2026-09-04",
        published_at=published,
        offers=manifest.offers,
    )
    with fixture.engine.begin() as connection:
        connection.execute(
            insert(schema.source_runs).values(
                source_run_id="run-correction",
                source_name="sporttery",
                source_type="official_schedule",
                started_at=retrieved.isoformat(),
                finished_at=retrieved.isoformat(),
                status="succeeded",
            )
        )
        connection.execute(
            insert(schema.source_artifacts).values(
                artifact_id="artifact-correction",
                first_recorded_at=retrieved.isoformat(),
                content_type="application/json",
                storage_path="sha256/correction",
                byte_size=2,
                content_hash=content_hash,
            )
        )
        connection.execute(
            insert(schema.artifact_retrievals).values(
                artifact_retrieval_id="retrieval-correction",
                artifact_id="artifact-correction",
                source_run_id="run-correction",
                source_name="sporttery",
                source_type="official_sale_schedule",
                reported_content_type="application/json",
                canonical_url="https://www.sporttery.cn/correction.json",
                requested_url="https://www.sporttery.cn/correction.json",
                published_at=published.isoformat(),
                retrieved_at=retrieved.isoformat(),
                status="stored",
            )
        )
    actions = SaleActions(
        fixture.action_service,
        operator_decisions=fixture.actions,
    )

    imported = actions.import_official_sale_slate(
        ImportOfficialSaleSlateRequest(
            manifest=manifest,
            actor_id="system:official-sale",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key="confirmation:official-cancel:import",
            requested_at=retrieved,
        )
    )

    assert imported.outcome.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(fixture.engine) as uow:
        terminal = uow.tickets.artifact_terminal_receipt(fixture.artifact_id)
        facts = uow.operator_result.review_eligibility_facts_for_work_item(
            WORK_ITEM_ID
        )
    assert terminal is not None
    assert terminal.terminal_kind == "shadow"
    assert terminal.terminal_reason == "official_offer_cancelled"
    assert terminal.action_id == imported.outcome.action_id
    assert len(facts) == 1
    assert facts[0].action_id == imported.outcome.action_id


@pytest.mark.parametrize("deadline_due", (False, True))
def test_official_deadline_shortening_respects_the_new_cutoff(
    tmp_path: Path,
    deadline_due: bool,
) -> None:
    from sqlalchemy import insert

    from nutmeg.ontology.operator.sale_actions import (
        ImportOfficialSaleSlateRequest,
        OfficialSaleSlateManifestV1,
        SaleActions,
        official_sale_parser_receipt_hash,
    )

    fixture = _artifact_fixture(tmp_path)
    protected = _protected(fixture, tmp_path)
    issued = _issue(protected, fixture, key="confirmation:future-shortening:issue")
    shortened_cutoff = fixture.cutoff - timedelta(minutes=30)
    retrieved = shortened_cutoff if deadline_due else AT + timedelta(minutes=5)
    published = retrieved - timedelta(minutes=1)
    manifest = OfficialSaleSlateManifestV1.model_validate(
        {
            "schema_version": "official-sale-slate-v1",
            "lane": "jczq",
            "business_key": "2026-09-04",
            "published_at": published,
            "retrieved_at": retrieved,
            "official_source_artifact_retrieval_id": "retrieval-future-shortening",
            "supersedes_slate_revision_id": "slate-1",
            "offers": [
                {
                    "canonical_match_id": "match-1",
                    "official_match_no": "001",
                    "market_definition_ids": ["md-had"],
                    "sale_opens_at": AT - timedelta(hours=1),
                    "sale_deadline_at": shortened_cutoff,
                    "status": "on_sale",
                }
            ],
        }
    )
    content_hash = official_sale_parser_receipt_hash(
        lane="jczq",
        business_key="2026-09-04",
        published_at=published,
        offers=manifest.offers,
    )
    with fixture.engine.begin() as connection:
        connection.execute(
            insert(schema.source_runs).values(
                source_run_id="run-future-shortening",
                source_name="sporttery",
                source_type="official_schedule",
                started_at=retrieved.isoformat(),
                finished_at=retrieved.isoformat(),
                status="succeeded",
            )
        )
        connection.execute(
            insert(schema.source_artifacts).values(
                artifact_id="artifact-future-shortening",
                first_recorded_at=retrieved.isoformat(),
                content_type="application/json",
                storage_path="sha256/future-shortening",
                byte_size=2,
                content_hash=content_hash,
            )
        )
        connection.execute(
            insert(schema.artifact_retrievals).values(
                artifact_retrieval_id="retrieval-future-shortening",
                artifact_id="artifact-future-shortening",
                source_run_id="run-future-shortening",
                source_name="sporttery",
                source_type="official_sale_schedule",
                reported_content_type="application/json",
                canonical_url="https://www.sporttery.cn/future-shortening.json",
                requested_url="https://www.sporttery.cn/future-shortening.json",
                published_at=published.isoformat(),
                retrieved_at=retrieved.isoformat(),
                status="stored",
            )
        )

    imported = SaleActions(
        fixture.action_service,
        operator_decisions=fixture.actions,
    ).import_official_sale_slate(
        ImportOfficialSaleSlateRequest(
            manifest=manifest,
            actor_id="system:official-sale",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key="confirmation:future-shortening:import",
            requested_at=retrieved,
        )
    )

    assert imported.outcome.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(fixture.engine) as uow:
        terminal = uow.tickets.artifact_terminal_receipt(fixture.artifact_id)
        head = uow.tickets.confirmation_challenge_head(fixture.artifact_id)
        current_offer = uow.operator_sale.current_offer_by_family("offer-family-1")
        facts = uow.operator_result.review_eligibility_facts_for_work_item(
            WORK_ITEM_ID
        )
    assert current_offer is not None
    assert current_offer.sale_deadline_at == shortened_cutoff.isoformat()
    if not deadline_due:
        assert terminal is None
        assert head is not None
        assert head.challenge_revision_id == issued.confirmation_id
        assert facts == ()
    else:
        assert terminal is not None
        assert terminal.terminal_kind == "shadow"
        assert terminal.terminal_reason == "official_deadline_shortened"
        assert terminal.action_id == imported.outcome.action_id
        assert head is None
        assert len(facts) == 1
        assert facts[0].action_id == imported.outcome.action_id


def test_official_offer_removal_terminalizes_bound_artifact_as_cancelled(
    tmp_path: Path,
) -> None:
    from sqlalchemy import insert, text

    from nutmeg.ontology.operator.sale_actions import (
        ImportOfficialSaleSlateRequest,
        OfficialSaleSlateManifestV1,
        SaleActions,
        official_sale_parser_receipt_hash,
    )

    fixture = _artifact_fixture(tmp_path)
    protected = _protected(fixture, tmp_path)
    _issue(protected, fixture, key="confirmation:offer-removal:issue")
    with fixture.engine.begin() as connection:
        connection.execute(text("INSERT INTO matches (match_id) VALUES ('match-2')"))
        connection.execute(
            text(
                "INSERT INTO official_offer_families "
                "(official_offer_family_id, lane, business_key, official_match_no, "
                "match_id, created_at) VALUES "
                "('offer-family-2', 'jczq', '2026-09-04', '002', 'match-2', :at)"
            ),
            {"at": AT.isoformat()},
        )
        connection.execute(
            text(
                "INSERT INTO official_offer_revisions "
                "(official_offer_revision_id, official_offer_family_id, slate_revision_id, "
                "match_id, official_match_no, market_definition_ids_json, sale_opens_at, "
                "sale_deadline_at, status) VALUES "
                "('offer-revision-2', 'offer-family-2', 'slate-1', 'match-2', '002', "
                "'[\"md-had\"]', :opens, :deadline, 'on_sale')"
            ),
            {
                "opens": (AT - timedelta(hours=1)).isoformat(),
                "deadline": fixture.cutoff.isoformat(),
            },
        )

    published = AT + timedelta(minutes=4)
    retrieved = AT + timedelta(minutes=5)
    manifest = OfficialSaleSlateManifestV1.model_validate(
        {
            "schema_version": "official-sale-slate-v1",
            "lane": "jczq",
            "business_key": "2026-09-04",
            "published_at": published,
            "retrieved_at": retrieved,
            "official_source_artifact_retrieval_id": "retrieval-offer-removal",
            "supersedes_slate_revision_id": "slate-1",
            "offers": [
                {
                    "canonical_match_id": "match-2",
                    "official_match_no": "002",
                    "market_definition_ids": ["md-had"],
                    "sale_opens_at": AT - timedelta(hours=1),
                    "sale_deadline_at": fixture.cutoff,
                    "status": "on_sale",
                }
            ],
        }
    )
    content_hash = official_sale_parser_receipt_hash(
        lane="jczq",
        business_key="2026-09-04",
        published_at=published,
        offers=manifest.offers,
    )
    with fixture.engine.begin() as connection:
        connection.execute(
            insert(schema.source_runs).values(
                source_run_id="run-offer-removal",
                source_name="sporttery",
                source_type="official_schedule",
                started_at=retrieved.isoformat(),
                finished_at=retrieved.isoformat(),
                status="succeeded",
            )
        )
        connection.execute(
            insert(schema.source_artifacts).values(
                artifact_id="artifact-offer-removal",
                first_recorded_at=retrieved.isoformat(),
                content_type="application/json",
                storage_path="sha256/offer-removal",
                byte_size=2,
                content_hash=content_hash,
            )
        )
        connection.execute(
            insert(schema.artifact_retrievals).values(
                artifact_retrieval_id="retrieval-offer-removal",
                artifact_id="artifact-offer-removal",
                source_run_id="run-offer-removal",
                source_name="sporttery",
                source_type="official_sale_schedule",
                reported_content_type="application/json",
                canonical_url="https://www.sporttery.cn/offer-removal.json",
                requested_url="https://www.sporttery.cn/offer-removal.json",
                published_at=published.isoformat(),
                retrieved_at=retrieved.isoformat(),
                status="stored",
            )
        )

    imported = SaleActions(
        fixture.action_service,
        operator_decisions=fixture.actions,
    ).import_official_sale_slate(
        ImportOfficialSaleSlateRequest(
            manifest=manifest,
            actor_id="system:official-sale",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key="confirmation:offer-removal:import",
            requested_at=retrieved,
        )
    )

    assert imported.outcome.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(fixture.engine) as uow:
        terminal = uow.tickets.artifact_terminal_receipt(fixture.artifact_id)
        head = uow.tickets.confirmation_challenge_head(fixture.artifact_id)
    assert terminal is not None
    assert terminal.terminal_kind == "shadow"
    assert terminal.terminal_reason == "official_offer_cancelled"
    assert head is None


def test_attested_openclaw_callback_atomically_places_and_replays(tmp_path: Path) -> None:
    fixture = _artifact_fixture(tmp_path)
    protected = _protected(fixture, tmp_path)
    issued = _issue(protected, fixture, key="confirmation:lifecycle:issue")
    assert issued.nonce is not None
    ingress = AT + timedelta(minutes=3)
    owner = _owner(fixture, observed_at=ingress - timedelta(seconds=30))
    confirmation = _confirmation(fixture, protected, now=ingress)
    update = _update(callback_data=f"ntc:{issued.nonce}", ingress_at=ingress)

    first = confirmation_services.ingest_openclaw_telegram_update(
        update,
        trusted_account_id="nutmeg",
        owner_instance_id="openclaw-primary",
        bridge_received_at=ingress + timedelta(seconds=1),
        heartbeat_service=owner,
        confirmation_service=confirmation,
    )
    replay = confirmation_services.ingest_openclaw_telegram_update(
        update,
        trusted_account_id="nutmeg",
        owner_instance_id="openclaw-primary",
        bridge_received_at=ingress + timedelta(seconds=1),
        heartbeat_service=owner,
        confirmation_service=confirmation,
    )

    assert first.message == replay.message == "Placement recorded."
    assert _callback_counts(fixture.engine) == {
        "terminal": 1,
        "attestation": 1,
        "ticket": 1,
        "cash": 1,
        "placement": 1,
    }
    with OntologyUnitOfWork(fixture.engine) as uow:
        attestation = uow.operator_result.telegram_callback_attestation(
            account_id="nutmeg",
            callback_query_id="callback-1",
        )
        placement = uow.tickets.placement_for_artifact(fixture.artifact_id)
        heartbeat = uow.operator_result.telegram_owner_heartbeat(
            account_id="nutmeg",
            owner_instance_id="openclaw-primary",
        )
        actions = uow.connection.execute(
            select(schema.actions.c.action_type, schema.actions.c.payload_json)
            .where(schema.actions.c.action_type == "confirm_ticket_placement")
        ).all()
    assert attestation is not None
    assert placement is not None
    assert heartbeat is not None
    assert heartbeat.heartbeat_sequence == 2
    assert attestation.action_id == placement.action_id
    assert attestation.source_artifact_id == placement.receipt_artifact_id
    assert attestation.source_artifact_retrieval_id == placement.receipt_retrieval_id
    assert len(actions) == 1
    assert issued.nonce not in actions[0].payload_json


def test_operator_artifact_rejects_non_attested_direct_placement(tmp_path: Path) -> None:
    fixture = _artifact_fixture(tmp_path)
    protected = _protected(fixture, tmp_path)
    issued = _issue(protected, fixture, key="confirmation:lifecycle:direct:issue")
    assert issued.confirmation_id is not None
    assert issued.nonce is not None
    with OntologyUnitOfWork(fixture.engine) as uow:
        artifact = uow.tickets.ticket_artifact(fixture.artifact_id)
    assert artifact is not None

    with pytest.raises(ValueError, match="attested OpenClaw callback"):
        protected.confirm_ticket_placement(
            ConfirmTicketPlacementRequest(
                ticket_artifact_id=fixture.artifact_id,
                confirmation_id=issued.confirmation_id,
                nonce=issued.nonce,
                ticket_hash=artifact.ticket_hash,
                amount=artifact.amount,
                currency=artifact.currency,
                channel=artifact.channel,
                placement_mode="manual",
                external_reference="manual:forbidden",
                receipt_content=b"manual",
                receipt_content_type="text/plain",
                actor_id="jun",
                actor_role=ActorRole.JUDGE_OPERATOR,
                idempotency_key="confirmation:lifecycle:direct:confirm",
                requested_at=AT + timedelta(minutes=3),
            )
        )


def test_same_callback_id_with_changed_attestation_is_an_idempotency_conflict(
    tmp_path: Path,
) -> None:
    fixture = _artifact_fixture(tmp_path)
    protected = _protected(fixture, tmp_path)
    issued = _issue(protected, fixture, key="confirmation:lifecycle:conflict:issue")
    assert issued.nonce is not None
    ingress = AT + timedelta(minutes=3)
    owner = _owner(fixture, observed_at=ingress - timedelta(seconds=30))
    confirmation = _confirmation(fixture, protected, now=ingress)
    kwargs = {
        "trusted_account_id": "nutmeg",
        "owner_instance_id": "openclaw-primary",
        "bridge_received_at": ingress + timedelta(seconds=1),
        "heartbeat_service": owner,
        "confirmation_service": confirmation,
    }

    confirmation_services.ingest_openclaw_telegram_update(
        _update(callback_data=f"ntc:{issued.nonce}", ingress_at=ingress),
        **kwargs,
    )
    with pytest.raises(IdempotencyConflictError):
        confirmation_services.ingest_openclaw_telegram_update(
            _update(
                callback_data=f"ntc:{issued.nonce}",
                ingress_at=ingress,
                sender_id="different-sender",
            ),
            **kwargs,
        )

    assert _callback_counts(fixture.engine)["attestation"] == 1


def test_plugin_ingress_before_cutoff_wins_when_bridge_finishes_after_cutoff(
    tmp_path: Path,
) -> None:
    fixture = _artifact_fixture(tmp_path)
    protected = _protected(fixture, tmp_path)
    issued = _issue(protected, fixture, key="confirmation:lifecycle:cutoff:issue")
    assert issued.nonce is not None
    ingress = fixture.cutoff - timedelta(microseconds=1)
    owner = _owner(fixture, observed_at=ingress - timedelta(seconds=30))
    confirmation = _confirmation(fixture, protected, now=fixture.cutoff + timedelta(seconds=1))

    confirmation_services.ingest_openclaw_telegram_update(
        _update(callback_data=f"ntc:{issued.nonce}", ingress_at=ingress),
        trusted_account_id="nutmeg",
        owner_instance_id="openclaw-primary",
        bridge_received_at=fixture.cutoff + timedelta(seconds=1),
        heartbeat_service=owner,
        confirmation_service=confirmation,
    )

    with OntologyUnitOfWork(fixture.engine) as uow:
        terminal = uow.tickets.artifact_terminal_receipt(fixture.artifact_id)
    assert terminal is not None
    assert terminal.terminal_kind == "placed"
    assert terminal.terminal_at == ingress.isoformat()


def test_attestation_failure_rolls_back_terminal_and_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _artifact_fixture(tmp_path)
    protected = _protected(fixture, tmp_path)
    issued = _issue(protected, fixture, key="confirmation:lifecycle:rollback:issue")
    assert issued.nonce is not None
    ingress = AT + timedelta(minutes=3)
    owner = _owner(fixture, observed_at=ingress - timedelta(seconds=30))
    confirmation = _confirmation(fixture, protected, now=ingress)

    def fail_attestation(*_args, **_kwargs):
        raise RuntimeError("injected attestation failure")

    monkeypatch.setattr(
        OperatorResultRepository,
        "insert_telegram_callback_attestation",
        fail_attestation,
    )
    with pytest.raises(RuntimeError, match="injected attestation failure"):
        confirmation_services.ingest_openclaw_telegram_update(
            _update(callback_data=f"ntc:{issued.nonce}", ingress_at=ingress),
            trusted_account_id="nutmeg",
            owner_instance_id="openclaw-primary",
            bridge_received_at=ingress + timedelta(seconds=1),
            heartbeat_service=owner,
            confirmation_service=confirmation,
        )

    assert _callback_counts(fixture.engine) == {
        "terminal": 0,
        "attestation": 0,
        "ticket": 0,
        "cash": 0,
        "placement": 0,
    }
    with OntologyUnitOfWork(fixture.engine) as uow:
        assert uow.tickets.confirmation_challenge_head(fixture.artifact_id) is not None


@pytest.mark.parametrize(
    ("issue_challenge", "expected_reason"),
    (
        (False, "confirmation_not_requested"),
        (True, "deadline_unconfirmed"),
    ),
)
def test_deadline_worker_shadows_due_artifacts_and_writes_review_eligibility(
    tmp_path: Path,
    issue_challenge: bool,
    expected_reason: str,
) -> None:
    fixture = _artifact_fixture(tmp_path)
    protected = _protected(fixture, tmp_path)
    if issue_challenge:
        _issue(protected, fixture, key="confirmation:lifecycle:deadline:issue")
    worker = operator_workers.ConfirmationDeadlineWorker(
        action_service=fixture.action_service,
        protected_tickets=protected,
        worker_id="operator-confirmation-deadline",
    )

    outcomes = worker.run_once(limit=10, as_of=fixture.cutoff)
    replay = worker.run_once(limit=10, as_of=fixture.cutoff + timedelta(seconds=1))

    assert len(outcomes) == 1
    assert outcomes[0].status is ActionStatus.COMMITTED
    assert replay == ()
    with OntologyUnitOfWork(fixture.engine) as uow:
        terminal = uow.tickets.artifact_terminal_receipt(fixture.artifact_id)
        facts = uow.operator_result.review_eligibility_facts_for_work_item(
            WORK_ITEM_ID
        )
    assert terminal is not None
    assert terminal.terminal_reason == expected_reason
    assert len(facts) == 1
    assert facts[0].artifact_terminal_receipt_id == (
        terminal.artifact_terminal_receipt_id
    )
    assert _callback_counts(fixture.engine)["ticket"] == 0
