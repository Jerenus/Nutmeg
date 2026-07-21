# ruff: noqa: F401 — this package ``__init__`` is the CLI namespace hub: imports,
# factories, helpers and option singletons defined here are referenced by the
# subsystem command modules (``core``/``jczq``/``zucai``/...) via ``_cli.<name>``.
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

import io
import json
import logging
import sys
import time
from contextlib import redirect_stdout
from dataclasses import asdict
from pathlib import Path

import typer
from rich.console import Console
from sqlalchemy.orm import Session

from nutmeg.agents.llm_provider import build_bot_fallback_provider, build_synthesis_provider
from nutmeg.agents.router import classify_intent
from nutmeg.agents.workflow import LANGGRAPH_AVAILABLE, MatchAnalysisAgentWorkflow
from nutmeg.config.settings import get_settings
from nutmeg.data.api_football import ApiFootballClient, ApiFootballError
from nutmeg.data.open_meteo import OpenMeteoClient
from nutmeg.data.soccerdata_client import SoccerDataClient, SoccerDataError
from nutmeg.data.the_odds_api import TheOddsApiClient, TheOddsApiError
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
from nutmeg.observability.langsmith import build_trace_context, traced_operation
from nutmeg.ontology import build_ontology_kernel
from nutmeg.process.harness import inspect_harness
from nutmeg.process.superpowers import inspect_superpowers_bridge
from nutmeg.services.analysis import AnalysisService, InsufficientEvidenceError
from nutmeg.services.evals import EvalDatasetNotFoundError, EvalService
from nutmeg.services.event_data import EventTacticalModelService
from nutmeg.services.fixtures import FixtureService
from nutmeg.services.information import FixtureInformationService, LiveInformationProvider
from nutmeg.services.materialization import MaterializationService
from nutmeg.services.odds import OddsFixtureNotFoundError, OddsSnapshotService
from nutmeg.services.operations import DailyOperatorService
from nutmeg.services.players import PlayerProfileService
from nutmeg.services.popularity import MatchPopularityRanker, RankedFixture
from nutmeg.services.snapshot import FixtureNotFoundError, FixtureSnapshotService
from nutmeg.services.sync import FixtureSyncService
from nutmeg.services.tactics import TacticalVisualService
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
from nutmeg.storage.client_state_repository import SqlAlchemyClientStateRepository
from nutmeg.storage.fixture_repository import DuckDbFixtureRepository
from nutmeg.storage.odds_repository import (
    DuckDbOddsEventRepository,
    DuckDbOddsHistoryRepository,
    DuckDbOddsProviderHealthRepository,
)
from nutmeg.storage.prediction_repository import (
    PredictionNotFoundError,
    SqlAlchemyPredictionRepository,
)
from nutmeg.storage.reference_repository import DuckDbReferenceRepository
from nutmeg.storage.sync_run_repository import SqlAlchemySyncRunRepository

app = typer.Typer(help="Nutmeg CLI foundation")
console = Console()
LEAGUE_FILTER_OPTION = typer.Option(None, "--league")
DAYS_OPTION = typer.Option(None, "--days")
TIMEZONE_OPTION = typer.Option(None, "--timezone")
TELEGRAM_OFFSET_FILE_OPTION = typer.Option(None, "--offset-file")
TELEGRAM_NO_OFFSET_FILE_OPTION = typer.Option(False, "--no-offset-file")
TACTICAL_OUTPUT_DIR_OPTION = typer.Option(None, "--output-dir")
ALERT_PREFERENCE_OPTION = typer.Option(None, "--alert-preference")
EVENT_DATA_EVENTS_FILE_OPTION = typer.Option(None, "--events-file")
INFORMATION_SOURCES_FILE_OPTION = typer.Option(None, "--sources-file")
INFORMATION_SOURCES_CONFIG_OPTION = typer.Option(None, "--sources-config")
INFORMATION_CACHE_DIR_OPTION = typer.Option(None, "--cache-dir")
INFORMATION_LIVE_FETCH_OPTION = typer.Option(False, "--live-fetch")
INFORMATION_CACHE_TTL_OPTION = typer.Option(900, "--cache-ttl-seconds")
INFORMATION_TIMEOUT_OPTION = typer.Option(3.0, "--timeout-seconds")
INFORMATION_MAX_BYTES_OPTION = typer.Option(262_144, "--max-bytes")
CLIENT_INFORMATION_SOURCES_CONFIG_OPTION = typer.Option(None, "--information-sources-config")
CLIENT_INFORMATION_CACHE_DIR_OPTION = typer.Option(None, "--information-cache-dir")
CLIENT_INFORMATION_LIVE_FETCH_OPTION = typer.Option(False, "--live-information-fetch")
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


def build_fixture_service() -> tuple[FixtureService, Session]:
    settings = get_settings()
    ensure_storage_paths(settings)
    create_analytics_schema(settings)
    session = _build_state_session()
    repository = DuckDbFixtureRepository(settings)
    return FixtureService(repository), session


def build_sync_service() -> tuple[FixtureSyncService, Session]:
    settings = get_settings()
    ensure_storage_paths(settings)
    create_analytics_schema(settings)
    session = _build_state_session()
    fixture_repository = DuckDbFixtureRepository(settings)
    sync_run_repository = SqlAlchemySyncRunRepository(session)
    api_client = ApiFootballClient(
        base_url=settings.api_football_base_url,
        api_key=settings.api_football_key,
    )
    return FixtureSyncService(fixture_repository, sync_run_repository, api_client), session


def build_snapshot_service() -> tuple[FixtureSnapshotService, Session]:
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
    soccerdata_client = SoccerDataClient(database_path=settings.analytics_db_path)
    transfermarkt_dataset = TransfermarktDataset(database_path=settings.analytics_db_path)
    api_context_client = ApiFootballClient(
        base_url=settings.api_football_base_url,
        api_key=settings.api_football_key,
    )
    return (
        FixtureSnapshotService(
            fixture_repository=fixture_repository,
            soccerdata_client=soccerdata_client,
            transfermarkt_dataset=transfermarkt_dataset,
            api_context_client=api_context_client,
            reference_repository=reference_repository,
            weather_client=weather_client,
        ),
        session,
    )


def build_materialization_service() -> tuple[MaterializationService, Session]:
    settings = get_settings()
    ensure_storage_paths(settings)
    create_analytics_schema(settings)
    session = _build_state_session()
    return (
        MaterializationService(
            transfermarkt_dataset=TransfermarktDataset(database_path=settings.analytics_db_path),
            soccerdata_client=SoccerDataClient(database_path=settings.analytics_db_path),
        ),
        session,
    )


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


def build_odds_service() -> tuple[OddsSnapshotService, Session]:
    settings = get_settings()
    ensure_storage_paths(settings)
    create_analytics_schema(settings)
    session = _build_state_session()
    fixture_repository = DuckDbFixtureRepository(settings)
    odds_client = build_odds_provider_client(
        settings,
        fixture_repository=fixture_repository,
        event_repository=DuckDbOddsEventRepository(settings),
    )
    odds_history_repository = DuckDbOddsHistoryRepository(settings)
    return (
        OddsSnapshotService(
            fixture_repository=fixture_repository,
            odds_client=odds_client,
            odds_history_repository=odds_history_repository,
        ),
        session,
    )


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


def build_player_profile_service() -> tuple[PlayerProfileService, Session]:
    settings = get_settings()
    ensure_storage_paths(settings)
    create_analytics_schema(settings)
    session = _build_state_session()
    return (
        PlayerProfileService(
            database_path=settings.analytics_db_path,
            reference_repository=DuckDbReferenceRepository(settings),
        ),
        session,
    )


def build_eval_service() -> EvalService:
    return EvalService(dataset_dir=Path("nutmeg/evals"))


def build_prediction_repository() -> tuple[SqlAlchemyPredictionRepository, Session]:
    session = _build_state_session()
    return SqlAlchemyPredictionRepository(session), session


def build_daily_operator_service() -> tuple[DailyOperatorService, Session]:
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
    analysis_service = AnalysisService(
        snapshot_service=snapshot_service,
        odds_service=odds_service,
    )
    telegram_sender = None
    telegram_chat_ids: list[int] = []
    if settings.telegram_bot_token:
        telegram_sender = TelegramBotClient(
            token=settings.telegram_bot_token,
            base_url=settings.telegram_api_base_url,
        )
        telegram_chat_ids = sorted(
            parse_telegram_allowed_chat_ids(settings.telegram_allowed_chat_ids)
        )
    return (
        DailyOperatorService(
            fixture_service=FixtureService(fixture_repository),
            popularity_ranker=MatchPopularityRanker(),
            value_board_service=ValueBoardService(
                fixture_repository=fixture_repository,
                snapshot_service=snapshot_service,
                odds_service=odds_service,
            ),
            sync_service=FixtureSyncService(
                fixture_repository,
                SqlAlchemySyncRunRepository(session),
                ApiFootballClient(
                    base_url=settings.api_football_base_url,
                    api_key=settings.api_football_key,
                ),
            ),
            workflow=MatchAnalysisAgentWorkflow(
                analysis_service=analysis_service,
                synthesis_provider=build_synthesis_provider(settings),
            ),
            telegram_sender=telegram_sender,
            telegram_chat_ids=telegram_chat_ids,
            timezone=settings.sync_timezone,
        ),
        session,
    )


def build_tactical_visual_service() -> tuple[TacticalVisualService, Session]:
    snapshot_service, session = build_snapshot_service()
    return TacticalVisualService(snapshot_service=snapshot_service), session


def build_event_tactical_model_service() -> EventTacticalModelService:
    return EventTacticalModelService()


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


def build_fixture_information_service() -> FixtureInformationService:
    return FixtureInformationService()


def build_live_fixture_information_service(
    *,
    manifest_path: Path,
    cache_dir: Path | None = None,
    live_fetch: bool = False,
    cache_ttl_seconds: int = 900,
    timeout_seconds: float = 3.0,
    max_bytes: int = 262_144,
) -> FixtureInformationService:
    resolved_cache_dir = cache_dir or Path(".nutmeg-data") / "information-cache"
    return FixtureInformationService(
        provider=LiveInformationProvider(
            manifest_path=manifest_path,
            cache_dir=resolved_cache_dir,
            live_fetch=live_fetch,
            default_cache_ttl_seconds=cache_ttl_seconds,
            default_timeout_seconds=timeout_seconds,
            default_max_bytes=max_bytes,
        )
    )


def build_analysis_service() -> tuple[AnalysisService, Session | None]:
    snapshot_service, session = build_snapshot_service()
    odds_service, _ = build_odds_service()
    return AnalysisService(snapshot_service=snapshot_service, odds_service=odds_service), session


def build_agent_workflow() -> tuple[MatchAnalysisAgentWorkflow, Session | None]:
    settings = get_settings()
    analysis_service, session = build_analysis_service()
    return (
        MatchAnalysisAgentWorkflow(
            analysis_service=analysis_service,
            synthesis_provider=build_synthesis_provider(settings),
        ),
        session,
    )


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


def _provider_health_payload(settings, odds_provider: str) -> dict[str, object] | None:
    if odds_provider != "the-odds-api":
        return None
    create_analytics_schema(settings)
    latest = DuckDbOddsProviderHealthRepository(settings).get_latest(odds_provider)
    if latest is None:
        return None
    return {
        "cache_hits": latest.cache_hits,
        "cache_misses": latest.cache_misses,
        "reconcile_attempts": latest.reconcile_attempts,
        "reconcile_failures": latest.reconcile_failures,
        "stale_refresh_attempts": latest.stale_refresh_attempts,
        "stale_refresh_successes": latest.stale_refresh_successes,
        "last_event_id": latest.last_event_id,
        "last_error": latest.last_error,
        "updated_at": latest.updated_at.isoformat() if latest.updated_at else None,
    }


def build_agent_status_payload(settings) -> dict[str, object]:
    odds_provider = settings.odds_provider.strip().casefold()
    odds_configured = (
        bool(settings.api_football_key)
        if odds_provider == "api-football"
        else bool(settings.the_odds_api_key)
        if odds_provider == "the-odds-api"
        else False
    )
    return {
        "agent": {
            "executor": "langgraph" if LANGGRAPH_AVAILABLE else "deterministic",
            "langgraph_available": LANGGRAPH_AVAILABLE,
        },
        "synthesis": {
            "enabled": settings.agent_synthesis_enabled,
            "configured": bool(settings.agent_synthesis_enabled and settings.portkey_api_key),
            "provider": "portkey",
            "model": settings.anthropic_model,
        },
        "bot_fallback": {
            "enabled": settings.bot_llm_fallback_enabled,
            "configured": bool(settings.bot_llm_fallback_enabled and settings.openai_api_key),
            "provider": "openai",
            "model": settings.bot_llm_fallback_model,
        },
        "odds_provider": {
            "name": odds_provider,
            "configured": odds_configured,
            "health_metrics_available": odds_provider == "the-odds-api",
            "health": _provider_health_payload(settings, odds_provider),
        },
    }


def build_today_briefs_payload(
    *,
    league: str,
    days: int,
    limit: int,
    demo: bool,
    briefs: bool,
    query: str,
    fixtures,
    workflow=None,
    sort: str = "kickoff",
) -> dict[str, object]:
    selected = _select_fixture_candidates(fixtures=list(fixtures), limit=limit, sort=sort)
    items: list[dict[str, object]] = []
    for fixture, ranked_fixture in selected:
        item = _fixture_candidate_payload(fixture, query=query, ranked_fixture=ranked_fixture)
        if briefs and workflow is not None:
            try:
                result = workflow.run(fixture_id=fixture.fixture_id, query=query)
                item["brief"] = build_match_brief_payload(result)
            except Exception as exc:
                item["brief"] = {
                    "fixture_id": fixture.fixture_id,
                    "query": query,
                    "status": "failed",
                    "sections": {},
                    "error": str(exc),
                }
        items.append(item)

    empty_reason = None
    if not items:
        empty_reason = "No local fixtures available. Run fixtures-sync or use --demo."
    return {
        "league": league,
        "days": days,
        "limit": limit,
        "demo": demo,
        "briefs_requested": briefs,
        "query": query,
        "sort": sort,
        "items": items,
        "empty_reason": empty_reason,
    }


def build_popular_matches_payload(
    *,
    league: str,
    days: int,
    limit: int,
    demo: bool,
    query: str,
    fixtures,
) -> dict[str, object]:
    ranked = MatchPopularityRanker().rank(list(fixtures), limit=limit)
    items = [
        _fixture_candidate_payload(
            ranked_fixture.fixture,
            query=query,
            ranked_fixture=ranked_fixture,
        )
        for ranked_fixture in ranked
    ]
    empty_reason = None
    if not items:
        empty_reason = "No local fixtures available. Run fixtures-sync or use --demo."
    return {
        "league": league,
        "days": days,
        "limit": limit,
        "demo": demo,
        "query": query,
        "sort": "popularity",
        "items": items,
        "empty_reason": empty_reason,
    }


def _select_fixture_candidates(
    *,
    fixtures,
    limit: int,
    sort: str,
) -> list[tuple[object, RankedFixture | None]]:
    if sort == "kickoff":
        return [(fixture, None) for fixture in fixtures[:limit]]
    if sort == "popularity":
        return [
            (ranked_fixture.fixture, ranked_fixture)
            for ranked_fixture in MatchPopularityRanker().rank(fixtures, limit=limit)
        ]
    raise ValueError("sort must be `kickoff` or `popularity`.")


def _fixture_candidate_payload(
    fixture,
    *,
    query: str,
    ranked_fixture: RankedFixture | None,
) -> dict[str, object]:
    item: dict[str, object] = {
        "fixture": asdict(fixture),
        "fixture_id": fixture.fixture_id,
        "league": fixture.league_code,
        "kickoff_at": fixture.kickoff_at.isoformat(),
        "home_team": fixture.home_team,
        "away_team": fixture.away_team,
        "venue": fixture.venue,
        "status": fixture.status.value,
        "suggested_bot_message": f"/brief {fixture.fixture_id} {query}",
    }
    if ranked_fixture is not None:
        item["rank"] = ranked_fixture.rank
        item["popularity"] = {
            "score": ranked_fixture.popularity.score,
            "tier": ranked_fixture.popularity.tier,
            "reasons": list(ranked_fixture.popularity.reasons),
        }
    return item


def build_match_brief_payload(result) -> dict[str, object]:
    analysis = result.analysis
    if result.status != "succeeded" or analysis is None:
        return {
            "fixture_id": result.fixture_id,
            "query": result.query,
            "status": result.status,
            "fixture": None,
            "judgment": None,
            "evidence": None,
            "agent": {
                "executor": result.executor,
                "nodes": result.nodes,
            },
            "generated_synthesis": result.generated_synthesis,
            "sections": {},
            "error": result.error or "Match brief could not be generated.",
        }

    evidence = analysis.evidence
    sections = {
        "core_reasons": analysis.judgment.core_reasons,
        "snapshot_summary": evidence.snapshot_summary,
        "tactical_evidence": evidence.tactical_summary,
        "market_evidence": [*evidence.odds_summary, *evidence.market_shape_summary],
        "caveats": evidence.caveats,
    }
    return {
        "fixture_id": result.fixture_id,
        "query": result.query,
        "status": result.status,
        "fixture": asdict(analysis.fixture),
        "judgment": asdict(analysis.judgment),
        "evidence": asdict(evidence),
        "intent": analysis.intent.value,
        "conflict_state": analysis.conflict_state,
        "generated_at": analysis.generated_at.isoformat(),
        "agent": {
            "executor": result.executor,
            "nodes": result.nodes,
        },
        "generated_synthesis": result.generated_synthesis,
        "sections": sections,
        "error": result.error,
    }


def _print_brief_list(title: str, items: list[str]) -> None:
    if not items:
        return
    console.print(f"{title}:")
    for item in items:
        console.print(f" - {item}")


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
    workflow, _session = build_agent_workflow()
    return TelegramBotRunner(
        client=TelegramBotClient(
            token=settings.telegram_bot_token,
            base_url=settings.telegram_api_base_url,
        ),
        bot_adapter=BotAdapter(
            workflow=workflow,
            payload_builder=build_match_brief_payload,
            fallback_provider=build_bot_fallback_provider(settings),
            # M2 cutover: the v1 Poisson daily advisor (jczq_daily) was retired,
            # so the bot no longer wires a jczq_workflow — BotAdapter degrades
            # `/jczq` to a "not configured" reply. renjiu handling stays.
            renjiu_workflow=ZucaiRenjiuBotWorkflow(
                service=build_zucai_renjiu_daily_service(),
                dry_run=False,
                value_bridge_factory=_build_zucai_value_bridge_for_daily,
            ),
        ),
        allowed_chat_ids=allowed_chat_ids,
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
from nutmeg.interfaces.cli import core as core  # noqa: E402
from nutmeg.interfaces.cli import decision as decision  # noqa: E402
from nutmeg.interfaces.cli import migration as migration  # noqa: E402
from nutmeg.interfaces.cli import notifications as notifications  # noqa: E402
from nutmeg.interfaces.cli import odds as odds  # noqa: E402
from nutmeg.interfaces.cli import ontology as ontology  # noqa: E402
from nutmeg.interfaces.cli import ontology_evidence as ontology_evidence  # noqa: E402
from nutmeg.interfaces.cli import ontology_ingest as ontology_ingest  # noqa: E402
from nutmeg.interfaces.cli import operations as operations  # noqa: E402
from nutmeg.interfaces.cli import psychology as psychology  # noqa: E402
from nutmeg.interfaces.cli import telegram as telegram  # noqa: E402
from nutmeg.interfaces.cli import zucai as zucai  # noqa: E402

if __name__ == "__main__":
    app()
