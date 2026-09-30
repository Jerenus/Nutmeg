# ruff: noqa: F401 — this package ``__init__`` is the CLI namespace hub: imports,
# factories, helpers and option singletons defined here are referenced by the
# subsystem command modules (``zucai``/``telegram``/``decision``/...) via ``_cli.<name>``.
"""Nutmeg CLI package.

``cli.py`` was split into this package, organised by subsystem, with **no**
behaviour change: every command keeps its exact name and the ``app`` Typer
object below is still the entry point (``nutmeg.interfaces.cli:app``).

This module holds the shared ``app`` object plus every module-level factory,
helper and ``typer.Option`` singleton. The subsystem modules imported at the
bottom define the ``@app.command()`` functions and reach back into this
namespace through ``import nutmeg.interfaces.cli as _cli``, so monkeypatching a
factory on the ``cli`` package is observed by the commands exactly as before.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

import typer
from rich.console import Console
from sqlalchemy.orm import Session

from nutmeg.agents.llm_provider import build_bot_fallback_provider
from nutmeg.config.settings import AppSettings, get_settings
from nutmeg.data.api_football import ApiFootballClient
from nutmeg.data.open_meteo import OpenMeteoClient
from nutmeg.data.soccerdata_client import SoccerDataClient
from nutmeg.data.the_odds_api import TheOddsApiClient
from nutmeg.data.transfermarkt import TransfermarktDataset
from nutmeg.domain.odds import OddsProvider
from nutmeg.interfaces.bot import (
    BotAdapter,
    TelegramBotClient,
    TelegramBotRunner,
    TelegramOffsetStore,
    TelegramPollingDaemon,
)
from nutmeg.notifications.wiring import build_notification_service
from nutmeg.ontology import build_ontology_kernel
from nutmeg.services.odds import OddsSnapshotService
from nutmeg.services.snapshot import FixtureSnapshotService
from nutmeg.services.value import ValueBoardService
from nutmeg.services.zucai import ZucaiValidationError, ZucaiWorkflowService
from nutmeg.services.zucai_odds_source import (
    ZucaiOddsSourceValidationError,
    ZucaiOddsSyncService,
)
from nutmeg.services.zucai_renjiu_daily import (
    ZucaiRenjiuBotWorkflow,
    ZucaiRenjiuDailyService,
    ZucaiRenjiuValidationError,
)
from nutmeg.services.zucai_schedule import (
    ZucaiScheduledDeliveryService,
    ZucaiScheduleValidationError,
)
from nutmeg.services.zucai_source import ZucaiSourceSyncService, ZucaiSourceValidationError
from nutmeg.storage.betting_plan_repository import DuckDbBettingPlanRepository
from nutmeg.storage.bootstrap import (
    build_state_engine,
    create_analytics_schema,
    create_state_schema,
    ensure_storage_paths,
)
from nutmeg.storage.fixture_repository import DuckDbFixtureRepository
from nutmeg.storage.odds_repository import (
    DuckDbOddsEventRepository,
    DuckDbOddsHistoryRepository,
    DuckDbOddsProviderHealthRepository,
)
from nutmeg.storage.reference_repository import DuckDbReferenceRepository

app = typer.Typer(help="Nutmeg CLI foundation")
console = Console()
TELEGRAM_OFFSET_FILE_OPTION = typer.Option(None, "--offset-file")
TELEGRAM_NO_OFFSET_FILE_OPTION = typer.Option(False, "--no-offset-file")
ALERT_PREFERENCE_OPTION = typer.Option(None, "--alert-preference")
ZUCAI_ISSUE_ID_OPTION = typer.Option(None, "--issue-id")
ZUCAI_ISSUE_FILE_OPTION = typer.Option(None, "--issue-file")
ZUCAI_ODDS_FILE_OPTION = typer.Option(None, "--odds-file")
ZUCAI_OVERRIDES_FILE_OPTION = typer.Option(None, "--overrides-file")
ZUCAI_OUTPUT_DIR_OPTION = typer.Option(Path(".nutmeg-data/zucai"), "--output-dir")
ZUCAI_REPORT_FILE_OPTION = typer.Option(..., "--report-file")
ZUCAI_OUTCOMES_FILE_OPTION = typer.Option(..., "--outcomes-file")
ZUCAI_REGISTRY_FILE_OPTION = typer.Option(Path(".nutmeg-data/zucai/issues.json"), "--registry-file")
ZUCAI_SCHEDULE_OUTPUT_DIR_OPTION = typer.Option(
    Path(".nutmeg-data/zucai/scheduled"), "--output-dir"
)
ZUCAI_RUN_RECORD_FILE_OPTION = typer.Option(
    Path(".nutmeg-data/zucai/scheduled-runs.json"), "--run-record-file"
)
ZUCAI_SOURCE_FILE_OPTION = typer.Option(None, "--source-file")
ZUCAI_SOURCE_URL_OPTION = typer.Option(None, "--source-url")
ZUCAI_SOURCE_LABEL_OPTION = typer.Option("Zucai schedule source", "--source-label")
CONTENT_REPORT_FILE_OPTION = typer.Option(..., "--report-file")
CONTENT_LIMIT_OPTION = typer.Option(3, "--limit")
CONTENT_OUTPUT_DIR_OPTION = typer.Option(Path(".nutmeg-data/content"), "--output-dir")
CONTENT_LLM_MODE_OPTION = typer.Option("openclaw", "--llm-mode")
CONTENT_OPENCLAW_MODEL_OPTION = typer.Option("nyu-openai-chat/gpt-5.5", "--openclaw-model")
WECHAT_OUTPUT_DIR_OPTION = typer.Option(Path(".nutmeg-data/wechat"), "--output-dir")
WECHAT_THUMB_MEDIA_ID_OPTION = typer.Option("DRY_RUN_COVER_MEDIA_ID", "--thumb-media-id")
WECHAT_AUTHOR_OPTION = typer.Option("Nutmeg", "--author")
WECHAT_SOURCE_URL_OPTION = typer.Option(None, "--source-url")
WECHAT_PACK_DIR_OPTION = typer.Option(..., "--pack-dir")
WECHAT_APP_ID_OPTION = typer.Option(None, "--app-id")
WECHAT_APP_SECRET_OPTION = typer.Option(None, "--app-secret")
DAILY_CONTENT_DATE_OPTION = typer.Option("today", "--date")
DAILY_CONTENT_PROVIDER_OPTION = typer.Option("live", "--provider")
DAILY_CONTENT_OUTPUT_DIR_OPTION = typer.Option(Path(".nutmeg-data/daily-content"), "--output-dir")
SEEDANCE_MANIFEST_OPTION = typer.Option(None, "--manifest")
SEEDANCE_RUN_DIR_OPTION = typer.Option(None, "--run-dir")
SEEDANCE_OUTPUT_DIR_OPTION = typer.Option(None, "--output-dir")
SEEDANCE_RATIO_KEY_OPTION = typer.Option("vertical", "--ratio-key")
SEEDANCE_MAX_CONCURRENCY_OPTION = typer.Option(2, "--max-concurrency")
VIDEO_MPT_RUN_DIR_OPTION = typer.Option(..., "--run-dir")
VIDEO_MPT_MATCH_ID_OPTION = typer.Option(None, "--match-id")
VIDEO_RENDER_PROPS_OPTION = typer.Option(..., "--props")
VIDEO_RENDER_OUTPUT_OPTION = typer.Option(..., "--output")
ZUCAI_ODDS_SOURCE_LABEL_OPTION = typer.Option("Zucai odds source", "--source-label")
JCZQ_OUTPUT_DIR_OPTION = typer.Option(Path(".nutmeg-data/jczq"), "--output-dir")
JCZQ_PROVIDER_OPTION = typer.Option("live", "--provider")
JCZQ_DAILY_DATE_OPTION = typer.Option("today", "--date")

logger = logging.getLogger(__name__)


def _build_state_session() -> Session:
    settings = get_settings()
    ensure_storage_paths(settings)
    engine = build_state_engine(settings)
    create_state_schema(engine)
    return Session(engine)


def build_odds_provider_client(
    settings,
    *,
    fixture_repository=None,
    event_repository=None,
) -> OddsProvider:
    """Return the configured odds-fetch client as an ``OddsProvider``.

    Selection is driven by ``settings.odds_provider`` ('api-football' |
    'the-odds-api'); both branches yield a structural ``OddsProvider`` so call
    sites depend on the protocol, not the concrete client class.
    """
    provider = settings.odds_provider.strip().casefold()
    if provider == "api-football":
        return ApiFootballClient(
            base_url=settings.api_football_base_url,
            api_key=settings.api_football_key,
        )
    if provider == "the-odds-api":
        ensure_storage_paths(settings)
        create_analytics_schema(settings)
        fixture_repository = fixture_repository or DuckDbFixtureRepository(settings)
        event_repository = event_repository or DuckDbOddsEventRepository(settings)
        return TheOddsApiClient(
            base_url=settings.the_odds_api_base_url,
            api_key=settings.the_odds_api_key,
            fixture_repository=fixture_repository,
            event_repository=event_repository,
            health_repository=DuckDbOddsProviderHealthRepository(settings),
        )
    raise ValueError(f"Unsupported odds provider `{settings.odds_provider}`.")


def build_value_board_service() -> tuple[ValueBoardService, Session]:
    settings = get_settings()
    ensure_storage_paths(settings)
    create_analytics_schema(settings)
    session = _build_state_session()
    fixture_repository = DuckDbFixtureRepository(settings)
    reference_repository = DuckDbReferenceRepository(settings)
    weather_client = OpenMeteoClient(
        geocoding_base_url=settings.open_meteo_geocoding_base_url,
        weather_base_url=settings.open_meteo_weather_base_url,
        reference_repository=reference_repository,
    )
    snapshot_service = FixtureSnapshotService(
        fixture_repository=fixture_repository,
        soccerdata_client=SoccerDataClient(database_path=settings.analytics_db_path),
        transfermarkt_dataset=TransfermarktDataset(database_path=settings.analytics_db_path),
        api_context_client=ApiFootballClient(
            base_url=settings.api_football_base_url,
            api_key=settings.api_football_key,
        ),
        reference_repository=reference_repository,
        weather_client=weather_client,
    )
    odds_client = build_odds_provider_client(
        settings,
        fixture_repository=fixture_repository,
        event_repository=DuckDbOddsEventRepository(settings),
    )
    odds_service = OddsSnapshotService(
        fixture_repository=fixture_repository,
        odds_client=odds_client,
        odds_history_repository=DuckDbOddsHistoryRepository(settings),
    )
    return (
        ValueBoardService(
            fixture_repository=fixture_repository,
            snapshot_service=snapshot_service,
            odds_service=odds_service,
        ),
        session,
    )


def build_zucai_workflow_service() -> ZucaiWorkflowService:
    settings = get_settings()
    ensure_storage_paths(settings)
    create_analytics_schema(settings)
    return ZucaiWorkflowService(
        notification_service=build_notification_service(settings=settings),
        betting_repository=DuckDbBettingPlanRepository(settings),
    )


def build_zucai_scheduled_delivery_service() -> ZucaiScheduledDeliveryService:
    return ZucaiScheduledDeliveryService(workflow_service=build_zucai_workflow_service())


def build_zucai_renjiu_daily_service() -> ZucaiRenjiuDailyService:
    settings = get_settings()
    ensure_storage_paths(settings)
    return ZucaiRenjiuDailyService(
        notification_service=build_notification_service(settings=settings),
    )


def build_zucai_source_sync_service() -> ZucaiSourceSyncService:
    return ZucaiSourceSyncService()


def build_zucai_odds_sync_service() -> ZucaiOddsSyncService:
    return ZucaiOddsSyncService()


def _build_zucai_value_bridge_for_daily(run_date: str):
    """Assemble the live value bridge for the Zucai daily report, or None.

    Wraps ``build_zucai_value_bridge`` with a ``ValueBoardService`` factory; any
    failure degrades to ``None`` so ``zucai-renjiu-daily`` always renders.
    """
    from nutmeg.services.zucai_value_wiring import build_zucai_value_bridge

    try:
        settings = get_settings()
        return build_zucai_value_bridge(
            settings=settings,
            run_date=run_date,
            value_service_factory=lambda: build_value_board_service()[0],
        )
    except Exception:  # noqa: BLE001 — degrade, never crash the daily report
        logger.warning("zucai value bridge wiring failed — degrading", exc_info=True)
        return None


def parse_telegram_allowed_chat_ids(raw_value: str | None) -> set[int]:
    if not raw_value:
        return set()
    values: set[int] = set()
    for chunk in raw_value.split(","):
        stripped = chunk.strip()
        if stripped:
            values.add(int(stripped))
    return values


def build_telegram_status_payload(settings) -> dict[str, object]:
    allowed_chat_ids = parse_telegram_allowed_chat_ids(settings.telegram_allowed_chat_ids)
    return {
        "configured": bool(settings.telegram_bot_token),
        "allowed_chat_ids_configured": bool(allowed_chat_ids),
        "allowed_chat_count": len(allowed_chat_ids),
        "api_base_url": settings.telegram_api_base_url,
        "bot_llm_fallback_enabled": settings.bot_llm_fallback_enabled,
        "bot_llm_fallback_configured": bool(
            settings.bot_llm_fallback_enabled and settings.openai_api_key
        ),
        "bot_llm_fallback_model": settings.bot_llm_fallback_model,
    }


def build_telegram_bot_runner(settings) -> TelegramBotRunner:
    if not settings.telegram_bot_token:
        raise ValueError("NUTMEG_TELEGRAM_BOT_TOKEN is not configured.")
    allowed_chat_ids = parse_telegram_allowed_chat_ids(settings.telegram_allowed_chat_ids)
    if not allowed_chat_ids:
        raise ValueError("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS is not configured.")
    client = TelegramBotClient(
        token=settings.telegram_bot_token,
        base_url=settings.telegram_api_base_url,
    )
    confirmation_handler = None
    kernel = build_ontology_kernel(AppSettings(data_dir=settings.data_dir))
    status = kernel.status()
    if (
        status.initialized
        and status.integrity_check == "ok"
        and not status.pending_migrations
    ):
        from nutmeg.services.telegram_ticket_confirmation import (
            TelegramTicketConfirmationService,
        )

        confirmation_handler = TelegramTicketConfirmationService(
            kernel=kernel,
            telegram_client=client,
            allowed_chat_ids=allowed_chat_ids,
            now_fn=lambda: datetime.now(UTC),
        )
    return TelegramBotRunner(
        client=client,
        bot_adapter=BotAdapter(
            fallback_provider=build_bot_fallback_provider(settings),
            # M2 cutover: the v1 Poisson daily advisor (jczq_daily) was retired,
            # so the bot no longer wires a jczq_workflow — BotAdapter degrades
            # `/jczq` to a "not configured" reply. The v0 match-brief analysis
            # stack (`/brief`) was retired on 2026-09-23; the adapter answers it
            # with a fixed "retired" reply. renjiu handling stays.
            renjiu_workflow=ZucaiRenjiuBotWorkflow(
                service=build_zucai_renjiu_daily_service(),
                dry_run=False,
                value_bridge_factory=_build_zucai_value_bridge_for_daily,
            ),
        ),
        allowed_chat_ids=allowed_chat_ids,
        confirmation_handler=confirmation_handler,
    )


def build_telegram_ticket_confirmation_service(
    settings,
    data_dir: Path,
    *,
    telegram_client=None,
):
    if not settings.telegram_bot_token:
        raise ValueError("NUTMEG_TELEGRAM_BOT_TOKEN is not configured.")
    allowed_chat_ids = parse_telegram_allowed_chat_ids(
        settings.telegram_allowed_chat_ids
    )
    if not allowed_chat_ids:
        raise ValueError("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS is not configured.")
    kernel = build_ontology_kernel(
        AppSettings(data_dir=Path(data_dir).expanduser().resolve())
    )
    status = kernel.status()
    if (
        not status.initialized
        or status.integrity_check != "ok"
        or status.pending_migrations
    ):
        raise ValueError("ontology must be initialized, healthy, and current")
    from nutmeg.services.telegram_ticket_confirmation import (
        TelegramTicketConfirmationService,
    )

    client = telegram_client or TelegramBotClient(
        token=settings.telegram_bot_token,
        base_url=settings.telegram_api_base_url,
    )
    return (
        TelegramTicketConfirmationService(
            kernel=kernel,
            telegram_client=client,
            allowed_chat_ids=allowed_chat_ids,
            now_fn=lambda: datetime.now(UTC),
        ),
        allowed_chat_ids,
    )


def build_telegram_polling_daemon(
    settings,
    poll_interval_seconds: float,
    offset_store: TelegramOffsetStore | None = None,
) -> TelegramPollingDaemon:
    return TelegramPollingDaemon(
        runner=build_telegram_bot_runner(settings),
        poll_interval_seconds=poll_interval_seconds,
        sleep_fn=time.sleep,
        offset_store=offset_store,
    )


def default_telegram_offset_path(settings) -> Path:
    return settings.state_dir / "telegram-bot.offset"


def telegram_daemon_summary_payload(
    summary,
    *,
    offset_persistence_enabled: bool = False,
    offset_source: str = "none",
    offset_file: Path | None = None,
) -> dict[str, object]:
    payload = {
        "polls_run": summary.polls_run,
        "updates_seen": summary.updates_seen,
        "messages_handled": summary.messages_handled,
        "messages_denied": summary.messages_denied,
        "messages_ignored": summary.messages_ignored,
        "callbacks_handled": getattr(summary, "callbacks_handled", 0),
        "shadows_marked": getattr(summary, "shadows_marked", 0),
        "next_offset": summary.next_offset,
        "stop_reason": summary.stop_reason,
        "offset_persistence_enabled": offset_persistence_enabled,
        "offset_source": offset_source,
        "offset_file": str(offset_file) if offset_file is not None else None,
    }
    return payload


PSYCHOLOGY_FIXTURE_FILE_OPTION = typer.Option(
    ..., "--fixture-file", help="JSON file with a single fixture dict"
)
PSYCHOLOGY_RULES_ONLY_OPTION = typer.Option(
    False, "--rules-only", help="Skip LLM-backed signals; only run tournament_stage"
)
INSPIRATION_DATE_OPTION = typer.Option(..., "--date", help="YYYYMMDD")
INSPIRATION_TEXT_OPTION = typer.Option(None, "--text", help="If omitted, $EDITOR is opened")


def _build_inspiration_parser():
    import os

    from nutmeg.agents.llm_provider import build_synthesis_provider
    from nutmeg.config.settings import get_settings
    from nutmeg.services.psychology.io import (
        FakeLLMCompleter,
        InspirationParser,
        PortkeyLLMCompleter,
    )

    if os.getenv("NUTMEG_PSYCHOLOGY_PARSER_FAKE_MODE") == "1":
        return InspirationParser(llm=FakeLLMCompleter(responses=[]))
    provider = build_synthesis_provider(get_settings())
    if provider is None:
        return InspirationParser(llm=FakeLLMCompleter(responses=[]))
    return InspirationParser(llm=PortkeyLLMCompleter(portkey_provider=provider))


def _normalize_date(yyyymmdd: str) -> str:
    if len(yyyymmdd) == 10 and yyyymmdd[4] == "-":
        return yyyymmdd
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"


# --- command registration ----------------------------------------------------
# Importing these subsystem modules executes their ``@app.command()`` decorators,
# registering every command on the shared ``app`` above. Done last so the package
# namespace (factories, helpers, options) is fully populated before they load.
# E402 is expected: registration must run after the namespace is built.
from nutmeg.interfaces.cli import betslip as betslip  # noqa: E402
from nutmeg.interfaces.cli import day as day  # noqa: E402
from nutmeg.interfaces.cli import decision as decision  # noqa: E402
from nutmeg.interfaces.cli import discovery as discovery  # noqa: E402
from nutmeg.interfaces.cli import judgment as judgment  # noqa: E402
from nutmeg.interfaces.cli import migration as migration  # noqa: E402
from nutmeg.interfaces.cli import notifications as notifications  # noqa: E402
from nutmeg.interfaces.cli import ontology as ontology  # noqa: E402
from nutmeg.interfaces.cli import ontology_evidence as ontology_evidence  # noqa: E402
from nutmeg.interfaces.cli import ontology_ingest as ontology_ingest  # noqa: E402
from nutmeg.interfaces.cli import plan as plan  # noqa: E402
from nutmeg.interfaces.cli import psychology as psychology  # noqa: E402
from nutmeg.interfaces.cli import reliability as reliability  # noqa: E402
from nutmeg.interfaces.cli import research as research  # noqa: E402
from nutmeg.interfaces.cli import retro as retro  # noqa: E402
from nutmeg.interfaces.cli import rsi as rsi  # noqa: E402
from nutmeg.interfaces.cli import scoreboard as scoreboard  # noqa: E402
from nutmeg.interfaces.cli import telegram as telegram  # noqa: E402
from nutmeg.interfaces.cli import workflow as workflow  # noqa: E402
from nutmeg.interfaces.cli import zucai as zucai  # noqa: E402

if __name__ == "__main__":
    app()
