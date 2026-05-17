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
from nutmeg.interfaces.client_web import create_client_app
from nutmeg.observability.langsmith import build_trace_context, traced_operation
from nutmeg.process.harness import inspect_harness
from nutmeg.process.superpowers import inspect_superpowers_bridge
from nutmeg.services.analysis import AnalysisService, InsufficientEvidenceError
from nutmeg.services.client import ClientService
from nutmeg.services.evals import EvalDatasetNotFoundError, EvalService
from nutmeg.services.event_data import EventTacticalModelService
from nutmeg.services.fixtures import FixtureService
from nutmeg.services.information import FixtureInformationService, LiveInformationProvider
from nutmeg.services.jczq import (
    JczqMixedReportService,
    JczqProviderError,
    JczqSelectionError,
    SampleJczqCalculatorProvider,
    SportteryJczqCalculatorProvider,
)
from nutmeg.services.jczq_daily import (
    JczqDailyAdvisorError,
    JczqDailyAdvisorService,
    build_jczq_daily_provider,
)
from nutmeg.services.jczq_debate import (
    JczqDebateWorkspaceError,
    JczqDebateWorkspaceService,
)
from nutmeg.services.jczq_review import JczqDailyReviewService
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
from nutmeg.services.zucai_renjiu_daily import (
    ZucaiRenjiuBotWorkflow,
    ZucaiRenjiuDailyService,
    ZucaiRenjiuValidationError,
)
from nutmeg.services.zucai_odds_source import (
    ZucaiOddsSourceValidationError,
    ZucaiOddsSyncService,
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


def build_client_service() -> tuple[ClientService, Session]:
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
        ClientService(
            state_repository=SqlAlchemyClientStateRepository(session),
            default_user_id=settings.default_user_id,
            fixture_service=FixtureService(fixture_repository),
            popularity_ranker=MatchPopularityRanker(),
            value_board_service=ValueBoardService(
                fixture_repository=fixture_repository,
                snapshot_service=snapshot_service,
                odds_service=odds_service,
            ),
            prediction_repository=SqlAlchemyPredictionRepository(session),
            information_provider=FixtureInformationService(),
        ),
        session,
    )


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
    telegram_sender = None
    if settings.telegram_bot_token:
        telegram_sender = TelegramBotClient(
            token=settings.telegram_bot_token,
            base_url=settings.telegram_api_base_url,
        )
    return ZucaiWorkflowService(
        telegram_sender=telegram_sender,
        telegram_chat_ids=sorted(
            parse_telegram_allowed_chat_ids(settings.telegram_allowed_chat_ids)
        ),
        betting_repository=DuckDbBettingPlanRepository(settings),
    )


def build_zucai_scheduled_delivery_service() -> ZucaiScheduledDeliveryService:
    return ZucaiScheduledDeliveryService(workflow_service=build_zucai_workflow_service())


def build_zucai_renjiu_daily_service() -> ZucaiRenjiuDailyService:
    settings = get_settings()
    ensure_storage_paths(settings)
    telegram_sender = None
    if settings.telegram_bot_token:
        telegram_sender = TelegramBotClient(
            token=settings.telegram_bot_token,
            base_url=settings.telegram_api_base_url,
        )
    return ZucaiRenjiuDailyService(
        telegram_sender=telegram_sender,
        telegram_chat_ids=sorted(
            parse_telegram_allowed_chat_ids(settings.telegram_allowed_chat_ids)
        ),
    )


def build_zucai_source_sync_service() -> ZucaiSourceSyncService:
    return ZucaiSourceSyncService()


def build_zucai_odds_sync_service() -> ZucaiOddsSyncService:
    return ZucaiOddsSyncService()


def build_jczq_mixed_report_service(*, provider: str = "live") -> JczqMixedReportService:
    settings = get_settings()
    ensure_storage_paths(settings)
    provider_key = provider.strip().casefold()
    if provider_key == "live":
        calculator_provider = SportteryJczqCalculatorProvider()
    elif provider_key == "sample":
        calculator_provider = SampleJczqCalculatorProvider()
    else:
        raise JczqSelectionError("provider must be `live` or `sample`.")
    telegram_sender = None
    if settings.telegram_bot_token:
        telegram_sender = TelegramBotClient(
            token=settings.telegram_bot_token,
            base_url=settings.telegram_api_base_url,
        )
    return JczqMixedReportService(
        provider=calculator_provider,
        telegram_sender=telegram_sender,
        telegram_chat_ids=sorted(
            parse_telegram_allowed_chat_ids(settings.telegram_allowed_chat_ids)
        ),
    )


def build_jczq_daily_advisor_service(*, provider: str = "live") -> JczqDailyAdvisorService:
    settings = get_settings()
    ensure_storage_paths(settings)
    create_analytics_schema(settings)
    telegram_sender = None
    if settings.telegram_bot_token:
        telegram_sender = TelegramBotClient(
            token=settings.telegram_bot_token,
            base_url=settings.telegram_api_base_url,
        )
    return JczqDailyAdvisorService(
        provider=build_jczq_daily_provider(provider),
        telegram_sender=telegram_sender,
        telegram_chat_ids=sorted(
            parse_telegram_allowed_chat_ids(settings.telegram_allowed_chat_ids)
        ),
        betting_repository=DuckDbBettingPlanRepository(settings),
    )


def build_jczq_daily_review_service() -> JczqDailyReviewService:
    settings = get_settings()
    ensure_storage_paths(settings)
    create_analytics_schema(settings)
    telegram_sender = None
    if settings.telegram_bot_token:
        telegram_sender = TelegramBotClient(
            token=settings.telegram_bot_token,
            base_url=settings.telegram_api_base_url,
        )
    return JczqDailyReviewService(
        telegram_sender=telegram_sender,
        telegram_chat_ids=sorted(
            parse_telegram_allowed_chat_ids(settings.telegram_allowed_chat_ids)
        ),
        betting_repository=DuckDbBettingPlanRepository(settings),
    )


def build_jczq_debate_workspace_service() -> JczqDebateWorkspaceService:
    return JczqDebateWorkspaceService()


class JczqDailyBotWorkflow:
    def __init__(
        self,
        *,
        service: JczqDailyAdvisorService,
        output_dir: Path = Path(".nutmeg-data/jczq"),
    ) -> None:
        self._service = service
        self._output_dir = output_dir

    def run(self, *, action: str, instruction: str | None = None) -> dict[str, object]:
        try:
            if action == "revise":
                report = self._service.revise(
                    run_date="today",
                    output_dir=self._output_dir,
                    instruction=instruction or "",
                    record_final=True,
                )
            else:
                report = self._service.build_report(
                    run_date="today",
                    output_dir=self._output_dir,
                    record_final=True,
                )
        except (JczqDailyAdvisorError, JczqProviderError, JczqSelectionError) as exc:
            return {
                "status": "failed",
                "text": str(exc),
                "payload": {"status": "failed", "error": str(exc)},
                "error": str(exc),
            }
        return {
            "status": "succeeded",
            "text": self._service.render_message(report),
            "payload": report.to_dict(),
        }


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


@app.command()
def doctor(format: str = typer.Option("text", "--format", help="text or json")) -> None:
    settings = get_settings()
    ensure_storage_paths(settings)
    create_analytics_schema(settings)
    bridge = inspect_superpowers_bridge(Path.cwd())
    harness = inspect_harness(Path.cwd())
    trace_context = build_trace_context(settings, settings.default_user_id)
    session = _build_state_session()
    try:
        latest_sync = SqlAlchemySyncRunRepository(session).latest()
    finally:
        session.close()
    report = {
        "app": {
            "name": settings.app_name,
            "env": settings.app_env,
            "default_user_id": settings.default_user_id,
        },
        "storage": {
            "data_dir": str(settings.data_dir),
            "state_db_url": settings.state_db_url,
            "analytics_db_url": settings.analytics_db_url,
        },
        "providers": {
            "api_football_configured": bool(settings.api_football_key),
            "portkey_configured": bool(settings.portkey_api_key),
            "openai_configured": bool(settings.openai_api_key),
            "agent_synthesis_enabled": settings.agent_synthesis_enabled,
            "agent_synthesis_configured": bool(
                settings.agent_synthesis_enabled and settings.portkey_api_key
            ),
            "agent_synthesis_model": settings.anthropic_model,
            "bot_llm_fallback_enabled": settings.bot_llm_fallback_enabled,
            "bot_llm_fallback_configured": bool(
                settings.bot_llm_fallback_enabled and settings.openai_api_key
            ),
            "bot_llm_fallback_model": settings.bot_llm_fallback_model,
            "langsmith_enabled": trace_context.enabled,
            "langsmith_project": trace_context.project,
        },
        "workflow": bridge.to_dict(),
        "harness": harness.to_dict(),
        "latest_sync": asdict(latest_sync) if latest_sync else None,
    }
    if format == "json":
        typer.echo(json.dumps(report, indent=2, sort_keys=True, default=str))
        return

    console.print(f"[bold]Nutmeg[/bold] env={settings.app_env} user={settings.default_user_id}")
    console.print(f"state={settings.state_db_url}")
    console.print(f"analytics={settings.analytics_db_url}")
    console.print(
        "providers: "
        f"api-football={'yes' if settings.api_football_key else 'no'}, "
        f"portkey={'yes' if settings.portkey_api_key else 'no'}, "
        f"openai={'yes' if settings.openai_api_key else 'no'}, "
        f"agent-synthesis={'yes' if settings.agent_synthesis_enabled else 'no'}, "
        f"bot-fallback={'yes' if settings.bot_llm_fallback_enabled else 'no'}, "
        f"langsmith={'yes' if trace_context.enabled else 'no'}"
    )
    console.print(f"superpowers bridge verdict={bridge.verdict}")
    console.print(
        f"harness: {harness.passing_features}/{harness.total_features} feature checks passing"
    )
    if latest_sync is not None:
        console.print(
            "latest sync: "
            f"status={latest_sync.status} fixtures={latest_sync.fixtures_written} "
            f"requests={latest_sync.requests_made} scope={latest_sync.scope}"
        )


@app.command()
def fixtures(
    league: str = typer.Option("epl", "--league"),
    next_days: int = typer.Option(7, "--next"),
    demo: bool = typer.Option(False, "--demo", help="use in-memory demo fixtures"),
) -> None:
    settings = get_settings()
    fixture_service, session = build_fixture_service()
    try:
        with traced_operation(
            settings,
            operation_name="cli.fixtures.list",
            user_id=settings.default_user_id,
            tags=["fixtures", "list"],
            metadata={"league": league, "days": next_days, "demo": demo},
        ):
            fixtures = fixture_service.list_upcoming(league, next_days, demo=demo)
    finally:
        session.close()

    if not fixtures:
        console.print(
            "No fixtures available yet. Run `nutmeg fixtures-sync` or `nutmeg seed-demo`."
        )
        raise typer.Exit(code=0)

    console.print(f"Upcoming fixtures: {league}")
    for fixture in fixtures:
        console.print(
            " | ".join(
                [
                    fixture.fixture_id,
                    fixture.kickoff_at.isoformat(),
                    f"{fixture.home_team} vs {fixture.away_team}",
                    fixture.status_short,
                    fixture.venue or "-",
                ]
            )
        )


@app.command("fixtures-sync")
def fixtures_sync(
    league: list[str] | None = LEAGUE_FILTER_OPTION,
    days: int | None = DAYS_OPTION,
    timezone: str | None = TIMEZONE_OPTION,
    past_days: int = typer.Option(0, "--past-days"),
) -> None:
    settings = get_settings()
    requested_days = days or settings.default_sync_days
    requested_timezone = timezone or settings.sync_timezone
    sync_service, session = build_sync_service()
    try:
        with traced_operation(
            settings,
            operation_name="cli.fixtures.sync",
            user_id=settings.default_user_id,
            tags=["fixtures", "sync"],
            metadata={
                "league_codes": league or ["all"],
                "days": requested_days,
                "past_days": past_days,
                "timezone": requested_timezone,
            },
        ):
            report = sync_service.sync(
                league_codes=league,
                days=requested_days,
                past_days=past_days,
                timezone=requested_timezone,
            )
            session.commit()
    except ApiFootballError as exc:
        session.commit()
        console.print(f"API-Football sync failed: {exc}")
        raise typer.Exit(code=2) from exc
    except Exception:
        session.commit()
        raise
    finally:
        session.close()

    console.print(
        f"Synced {report.total_fixtures} fixtures across {len(report.leagues)} competition(s)."
    )
    for summary in report.leagues:
        console.print(
            " - ".join(
                [
                    summary.league_code,
                    f"season={summary.season}",
                    f"fixtures={summary.fixtures_written}",
                    f"requests={summary.requests_made}",
                ]
            )
        )


@app.command("seed-demo")
def seed_demo(league: str = typer.Option("epl", "--league")) -> None:
    settings = get_settings()
    fixture_service, session = build_fixture_service()
    try:
        with traced_operation(
            settings,
            operation_name="cli.fixtures.seed_demo",
            user_id=settings.default_user_id,
            tags=["fixtures", "demo"],
            metadata={"league": league},
        ):
            fixtures = fixture_service.seed_demo(league)
            session.commit()
    finally:
        session.close()
    console.print(f"Seeded {len(fixtures)} fixtures for {league}.")


@app.command("reference-refresh")
def reference_refresh(
    league: str = typer.Option("epl", "--league"),
    season: int = typer.Option(..., "--season"),
) -> None:
    settings = get_settings()
    materialization_service, session = build_materialization_service()
    try:
        with traced_operation(
            settings,
            operation_name="cli.reference.refresh",
            user_id=settings.default_user_id,
            tags=["reference", "materialization"],
            metadata={"league": league, "season": season},
        ):
            result = materialization_service.refresh_snapshot_support_data(league, season)
            if session is not None:
                session.commit()
    finally:
        if session is not None:
            session.close()
    console.print(
        f"{result.league_code} season={result.season} "
        f"transfermarkt_rows={result.transfermarkt_rows} "
        f"soccerdata_rows={result.soccerdata_rows}"
    )


@app.command("fixture-snapshot")
def fixture_snapshot(
    fixture_id: str = typer.Option(..., "--fixture-id"),
    recent_matches: int = typer.Option(5, "--recent-matches"),
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    settings = get_settings()
    snapshot_service, session = build_snapshot_service()
    captured_stdout = io.StringIO()
    root_logger = logging.getLogger("root")
    original_root_level = root_logger.level
    suppress_root_info = format == "json" and (
        original_root_level == logging.NOTSET or original_root_level < logging.WARNING
    )
    try:
        if suppress_root_info:
            root_logger.setLevel(logging.WARNING)
        with redirect_stdout(captured_stdout):
            with traced_operation(
                settings,
                operation_name="cli.fixtures.snapshot",
                user_id=settings.default_user_id,
                tags=["fixtures", "snapshot"],
                metadata={
                    "fixture_id": fixture_id,
                    "recent_matches": recent_matches,
                    "format": format,
                },
            ):
                snapshot = snapshot_service.build_snapshot(
                    fixture_id,
                    recent_matches=recent_matches,
                )
    except (FixtureNotFoundError, SoccerDataError) as exc:
        console.print(str(exc))
        raise typer.Exit(code=2) from exc
    finally:
        if suppress_root_info:
            root_logger.setLevel(original_root_level)
        session.close()

    noisy_stdout = captured_stdout.getvalue()
    if noisy_stdout:
        print(noisy_stdout, file=sys.stderr, end="")

    payload = asdict(snapshot)
    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    console.print(
        f"{snapshot.fixture.fixture_id} | {snapshot.fixture.kickoff_at.isoformat()} | "
        f"{snapshot.fixture.home_team} vs {snapshot.fixture.away_team}"
    )
    if snapshot.environment is not None:
        weather_summary = "weather=n/a"
        if snapshot.environment.weather is not None:
            weather_summary = (
                f"weather={snapshot.environment.weather.temperature_c}C "
                f"precip={snapshot.environment.weather.precipitation_probability} "
                f"wind={snapshot.environment.weather.wind_speed_kph}"
            )
        travel_summary = "travel=n/a"
        if snapshot.environment.away_travel is not None:
            travel_summary = (
                f"travel={snapshot.environment.away_travel.distance_km}km "
                f"({snapshot.environment.away_travel.bucket})"
            )
        kickoff_local = (
            snapshot.environment.kickoff_local_time.isoformat()
            if snapshot.environment.kickoff_local_time is not None
            else "n/a"
        )
        console.print(
            "environment "
            f"venue={snapshot.environment.venue_name or '-'} "
            f"referee={snapshot.environment.referee or '-'} "
            f"kickoff_local={kickoff_local} "
            f"{weather_summary} {travel_summary}"
        )
    for side, team in [("home", snapshot.home), ("away", snapshot.away)]:
        console.print(f"{side}: {team.canonical_name}")
        if team.season_metrics is not None:
            shots = (
                f"{team.season_metrics.shots:.1f}"
                if team.season_metrics.shots is not None
                else "n/a"
            )
            shots_on_target = (
                f"{team.season_metrics.shots_on_target:.1f}"
                if team.season_metrics.shots_on_target is not None
                else "n/a"
            )
            goals = (
                f"{team.season_metrics.goals:.1f}"
                if team.season_metrics.goals is not None
                else "n/a"
            )
            xg = f"{team.season_metrics.xg:.1f}" if team.season_metrics.xg is not None else "n/a"
            console.print(f"  season shots={shots} sot={shots_on_target} goals={goals} xg={xg}")
        if team.recent_form is not None:
            console.print(
                f"  recent W-D-L={team.recent_form.wins}-{team.recent_form.draws}-"
                f"{team.recent_form.losses} points={team.recent_form.points} "
                f"xg={team.recent_form.xg_for:.1f}/{team.recent_form.xg_against:.1f}"
            )
        if team.shot_summary is not None:
            console.print(
                f"  shots count={team.shot_summary.shots} goals={team.shot_summary.goals} "
                f"open_play={team.shot_summary.open_play_shots} "
                f"xg={team.shot_summary.total_xg:.2f}"
            )
        if team.market_value is not None:
            console.print(
                f"  market value={team.market_value.total_market_value_eur} "
                f"source={team.market_value.source}"
            )
        if team.injuries:
            injury_summary = ", ".join(
                f"{injury.player_name} ({injury.reason or injury.status})"
                for injury in team.injuries
            )
            console.print("  injuries=" + injury_summary)
        if team.lineup is not None:
            console.print(
                f"  lineup status={team.lineup.status} formation={team.lineup.formation or '-'} "
                f"players={', '.join(player.player_name for player in team.lineup.players[:11])}"
            )
        if team.availability is not None:
            console.print(
                "  availability "
                f"injuries={len(team.availability.injuries)} "
                f"suspensions={len(team.availability.suspensions)} "
                f"returning={len(team.availability.returning_players)} "
                f"summary={team.availability.expected_absences_summary or '-'}"
            )
            if team.availability.bench_depth is not None:
                console.print(
                    "  bench depth "
                    f"label={team.availability.bench_depth.label} "
                    f"available={team.availability.bench_depth.available_players} "
                    f"value={team.availability.bench_depth.bench_market_value_eur}"
                )
    if snapshot.matchup is not None:
        h2h_matches = (
            snapshot.matchup.head_to_head.matches if snapshot.matchup.head_to_head else "n/a"
        )
        home_trend = "n/a"
        if snapshot.matchup.home_trend is not None:
            home_trend = (
                f"{snapshot.matchup.home_trend.goals_for_per_match:.2f}/"
                f"{snapshot.matchup.home_trend.xg_for_per_match:.2f}"
            )
        away_trend = "n/a"
        if snapshot.matchup.away_trend is not None:
            away_trend = (
                f"{snapshot.matchup.away_trend.goals_for_per_match:.2f}/"
                f"{snapshot.matchup.away_trend.xg_for_per_match:.2f}"
            )
        console.print(f"matchup h2h={h2h_matches} home_trend={home_trend} away_trend={away_trend}")
    console.print(f"deferred: {', '.join(snapshot.deferred_sections)}")


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


@app.command("odds-snapshot")
def odds_snapshot(
    fixture_id: str = typer.Option(..., "--fixture-id"),
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    settings = get_settings()
    odds_service, session = build_odds_service()
    try:
        with traced_operation(
            settings,
            operation_name="cli.odds.snapshot",
            user_id=settings.default_user_id,
            tags=["odds", "snapshot"],
            metadata={"fixture_id": fixture_id, "format": format},
        ):
            snapshot = odds_service.build_snapshot(fixture_id)
    except (OddsFixtureNotFoundError, ApiFootballError, TheOddsApiError, ValueError) as exc:
        console.print(str(exc))
        raise typer.Exit(code=2) from exc
    finally:
        session.close()

    payload = asdict(snapshot)
    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    updated_at = snapshot.provider.updated_at.isoformat() if snapshot.provider.updated_at else "n/a"
    console.print(
        f"{snapshot.fixture.fixture_id} | {snapshot.fixture.kickoff_at.isoformat()} | "
        f"{snapshot.fixture.home_team} vs {snapshot.fixture.away_team}"
    )
    console.print(
        "provider "
        f"name={snapshot.provider.name} "
        f"updated={updated_at} "
        f"bookmakers={snapshot.provider.bookmaker_count}"
    )
    for market_key, market in snapshot.markets.items():
        line = f" line={market.line}" if market.line is not None else ""
        console.print(
            f"{market_key} status={market.status}{line} source_ids={market.source_market_ids}"
        )
        for outcome in market.outcomes:
            fair_probability = (
                f"{outcome.fair_probability:.4f}" if outcome.fair_probability is not None else "n/a"
            )
            fair_price = f"{outcome.fair_odds:.3f}" if outcome.fair_odds is not None else "n/a"
            console.print(
                f"  {outcome.outcome_key} best={outcome.best_odds} "
                f"avg={outcome.average_odds} fair_prob={fair_probability} "
                f"fair_odds={fair_price} books={outcome.bookmaker_count}"
            )
        if snapshot.history and market_key in snapshot.history:
            history = snapshot.history[market_key]
            if history.points:
                console.print(
                    f"  history points={len(history.points)} "
                    f"movement={history.movement or 'n/a'} "
                    f"span={history.movement_span if history.movement_span is not None else 'n/a'} "
                    f"drift={history.drift_vs_current or {}}"
                )


@app.command("value-board")
def value_board(
    league: str = typer.Option("epl", "--league"),
    days: int = typer.Option(3, "--days"),
    limit: int = typer.Option(10, "--limit"),
    min_edge: float = typer.Option(0.03, "--min-edge"),
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    service, session = build_value_board_service()
    try:
        board = service.build_board(
            league=league,
            days=days,
            limit=limit,
            min_edge=min_edge,
        )
    except (ApiFootballError, TheOddsApiError, ValueError) as exc:
        console.print(str(exc))
        raise typer.Exit(code=2) from exc
    finally:
        session.close()

    payload = asdict(board)
    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    console.print(
        f"Value board: league={board.league} days={board.days} "
        f"candidates={len(board.candidates)} skipped={len(board.skipped)}"
    )
    if not board.candidates:
        console.print("No positive model-vs-market edges found.")
    for candidate in board.candidates:
        console.print(
            " | ".join(
                [
                    candidate.fixture_id,
                    candidate.kickoff_at.isoformat(),
                    f"{candidate.home_team} vs {candidate.away_team}",
                    candidate.outcome_key,
                    f"edge={candidate.edge:.1%}",
                    f"model={candidate.model_probability:.1%}",
                    f"market={candidate.market_probability:.1%}",
                    f"best={candidate.best_odds:.3f}",
                    f"kelly25={candidate.quarter_kelly_fraction:.2%}",
                    f"rating={candidate.rating}",
                ]
            )
        )
    if board.skipped:
        console.print("Skipped fixtures:")
        for skipped in board.skipped[:5]:
            console.print(f" - {skipped.fixture_id}: {skipped.reason}")


@app.command("player-profile")
def player_profile(
    player: str = typer.Option(..., "--player"),
    team: str = typer.Option(..., "--team"),
    league: str = typer.Option("epl", "--league"),
    season: int | None = typer.Option(None, "--season"),
    similar_limit: int = typer.Option(5, "--similar-limit"),
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    service, session = build_player_profile_service()
    try:
        profile = service.build_profile(
            league=league,
            season=season,
            team=team,
            player=player,
            similar_limit=similar_limit,
        )
    finally:
        session.close()

    payload = asdict(profile)
    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    identity_name = profile.identity.canonical_name if profile.identity else player
    console.print(
        f"Player profile: {identity_name} | team={profile.query_team} "
        f"league={profile.league} season={profile.season}"
    )
    if profile.market:
        market_value = (
            profile.market.market_value_eur
            if profile.market.market_value_eur is not None
            else "n/a"
        )
        console.print(
            f"market position={profile.market.position or 'n/a'} "
            f"value={market_value} "
            f"source={profile.market.source}"
        )
    if profile.season_metrics:
        metrics = profile.season_metrics
        console.print(
            f"season minutes={metrics.minutes} goals90={metrics.goals_per90} "
            f"assists90={metrics.assists_per90} xg90={metrics.xg_per90} "
            f"xa90={metrics.xa_per90}"
        )
    if profile.availability:
        console.print(
            f"availability status={profile.availability.status} "
            f"reason={profile.availability.reason or 'n/a'} "
            f"return={profile.availability.expected_return or 'n/a'}"
        )
    if profile.similar_players:
        console.print("similar players:")
        for item in profile.similar_players:
            console.print(
                f" - {item.player_name} | {item.team_name} | score={item.similarity_score:.3f}"
            )
    if profile.unavailable_sections:
        console.print(f"unavailable: {', '.join(profile.unavailable_sections)}")


@app.command("eval-run")
def eval_run(
    dataset: str = typer.Option("starter", "--dataset"),
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    service = build_eval_service()
    try:
        result = service.run_dataset(dataset)
    except EvalDatasetNotFoundError as exc:
        console.print(str(exc))
        raise typer.Exit(code=2) from exc

    payload = asdict(result)
    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    console.print(
        f"eval dataset={result.dataset} total={result.total_cases} "
        f"passed={result.passed_cases} failed={result.failed_cases}"
    )
    for item in result.results:
        status = "PASS" if item.passed else "FAIL"
        missing = f" missing={item.missing_keywords}" if item.missing_keywords else ""
        console.print(f" - {item.case_id} [{item.category}] {status}{missing}")


@app.command("prediction-record")
def prediction_record(
    fixture_id: str = typer.Option(..., "--fixture-id"),
    league: str = typer.Option("epl", "--league"),
    home_team: str = typer.Option(..., "--home-team"),
    away_team: str = typer.Option(..., "--away-team"),
    home_probability: float = typer.Option(..., "--home-probability"),
    draw_probability: float = typer.Option(..., "--draw-probability"),
    away_probability: float = typer.Option(..., "--away-probability"),
    picked_outcome: str = typer.Option(..., "--pick", help="home, draw, or away"),
    notes: str | None = typer.Option(None, "--notes"),
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    settings = get_settings()
    repository, session = build_prediction_repository()
    try:
        prediction_id = repository.record_prediction(
            user_id=settings.default_user_id,
            fixture_id=fixture_id,
            league=league,
            home_team=home_team,
            away_team=away_team,
            probabilities={
                "home": home_probability,
                "draw": draw_probability,
                "away": away_probability,
            },
            picked_outcome=picked_outcome,
            notes=notes,
        )
    except ValueError as exc:
        console.print(str(exc))
        raise typer.Exit(code=2) from exc
    finally:
        session.close()

    payload = {"prediction_id": prediction_id, "status": "recorded"}
    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    console.print(f"Recorded prediction id={prediction_id}")


@app.command("prediction-outcome")
def prediction_outcome(
    prediction_id: int = typer.Option(..., "--prediction-id"),
    actual_outcome: str = typer.Option(..., "--actual", help="home, draw, or away"),
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    repository, session = build_prediction_repository()
    try:
        repository.record_outcome(
            prediction_id=prediction_id,
            actual_outcome=actual_outcome,
        )
    except (PredictionNotFoundError, ValueError) as exc:
        console.print(str(exc))
        raise typer.Exit(code=2) from exc
    finally:
        session.close()

    payload = {
        "prediction_id": prediction_id,
        "actual_outcome": actual_outcome,
        "status": "resolved",
    }
    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    console.print(f"Recorded outcome id={prediction_id} actual={actual_outcome}")


@app.command("prediction-review")
def prediction_review(
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    settings = get_settings()
    repository, session = build_prediction_repository()
    try:
        summary = repository.review(user_id=settings.default_user_id)
    finally:
        session.close()

    payload = asdict(summary)
    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    brier = summary.average_brier_score if summary.average_brier_score is not None else "n/a"
    accuracy = summary.pick_accuracy if summary.pick_accuracy is not None else "n/a"
    console.print(
        f"prediction review total={summary.total_predictions} "
        f"resolved={summary.resolved_predictions} "
        f"brier={brier} "
        f"accuracy={accuracy}"
    )


@app.command("daily-run")
def daily_run(
    league: str = typer.Option("epl", "--league"),
    days: int = typer.Option(3, "--days"),
    limit: int = typer.Option(5, "--limit"),
    query: str = typer.Option("Give me the pre-match operator brief.", "--query"),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
    live_sync: bool = typer.Option(False, "--live-sync"),
    briefs: bool = typer.Option(False, "--briefs"),
    dispatch_telegram: bool = typer.Option(False, "--dispatch-telegram"),
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    service, session = build_daily_operator_service()
    try:
        summary = service.run(
            league=league,
            days=days,
            limit=limit,
            query=query,
            dry_run=dry_run,
            live_sync=live_sync,
            briefs=briefs,
            dispatch_telegram=dispatch_telegram,
        )
        session.commit()
    except Exception:
        session.commit()
        raise
    finally:
        session.close()

    payload = asdict(summary)
    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    console.print(
        f"daily-run league={summary.league} days={summary.days} "
        f"dry_run={summary.dry_run} live_sync={summary.live_sync}"
    )
    console.print(
        f"sync status={summary.sync_status} "
        f"fixtures={summary.sync_fixtures_written} requests={summary.sync_requests_made}"
    )
    console.print(
        f"fixtures considered={summary.fixtures_considered} "
        f"popular={len(summary.popular_matches)} value={len(summary.value_candidates)}"
    )
    console.print(f"telegram dispatch={summary.telegram_dispatch.status.value}")
    for item in summary.popular_matches:
        console.print(
            f" - #{item.rank} {item.home_team} vs {item.away_team} "
            f"tier={item.tier} score={item.score}"
        )


@app.command("zucai-report")
def zucai_report(
    issue_id: str | None = ZUCAI_ISSUE_ID_OPTION,
    issue_file: Path | None = ZUCAI_ISSUE_FILE_OPTION,
    odds_file: Path | None = ZUCAI_ODDS_FILE_OPTION,
    overrides_file: Path | None = ZUCAI_OVERRIDES_FILE_OPTION,
    output_dir: Path = ZUCAI_OUTPUT_DIR_OPTION,
    pdf: bool = typer.Option(False, "--pdf"),
    record_final: bool = typer.Option(True, "--record-final/--no-record-final"),
    dispatch_telegram: bool = typer.Option(False, "--dispatch-telegram"),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    service = build_zucai_workflow_service()
    try:
        report = service.build_report(
            issue_id=issue_id,
            issue_file=issue_file,
            odds_file=odds_file,
            overrides_file=overrides_file,
            output_dir=output_dir,
            render_pdf=pdf or dispatch_telegram,
            dispatch_telegram=dispatch_telegram,
            dry_run=dry_run,
            record_final=record_final,
        )
    except ZucaiValidationError as exc:
        console.print(str(exc))
        raise typer.Exit(code=2) from exc

    payload = report.to_dict()
    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    console.print(
        f"zucai issue={report.issue.issue_id} matches={len(report.recommendations)} "
        f"plans={len(report.plans)} warnings={len(report.warnings)}"
    )
    console.print(f"markdown={report.artifacts.markdown_path}")
    if report.artifacts.pdf_path:
        console.print(f"pdf={report.artifacts.pdf_path}")
    console.print(f"dispatch={report.dispatch.status}")
    for recommendation in report.recommendations:
        console.print(
            f"{recommendation.match_no}. pick={recommendation.pick} "
            f"risk={recommendation.risk_tier} confidence={recommendation.confidence:.2f}"
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


@app.command("zucai-renjiu-daily")
def zucai_renjiu_daily(
    run_date: str = typer.Option("today", "--date"),
    issue_id: str | None = ZUCAI_ISSUE_ID_OPTION,
    issue_file: Path | None = ZUCAI_ISSUE_FILE_OPTION,
    odds_file: Path | None = ZUCAI_ODDS_FILE_OPTION,
    output_dir: Path = ZUCAI_OUTPUT_DIR_OPTION,
    pdf: bool = typer.Option(False, "--pdf"),
    dispatch_telegram: bool = typer.Option(False, "--dispatch-telegram"),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    service = build_zucai_renjiu_daily_service()
    value_bridge = _build_zucai_value_bridge_for_daily(run_date)
    try:
        report = service.build_report(
            run_date=run_date,
            issue_id=issue_id,
            issue_file=issue_file,
            odds_file=odds_file,
            output_dir=output_dir,
            render_pdf=pdf or dispatch_telegram,
            dispatch_telegram=dispatch_telegram,
            dry_run=dry_run,
            value_bridge=value_bridge,
        )
    except ZucaiRenjiuValidationError as exc:
        console.print(str(exc))
        raise typer.Exit(code=2) from exc

    payload = report.to_dict()
    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    recommended = next(
        ticket for ticket in report.tickets if ticket.ticket_id == report.recommended_ticket_id
    )
    console.print(
        f"zucai-renjiu-daily issue={report.issue_id} recommended={recommended.name} "
        f"cost={recommended.cost_yuan} dispatch={report.dispatch.status}"
    )
    console.print(f"markdown={report.artifacts.markdown_path}")
    if report.artifacts.pdf_path:
        console.print(f"pdf={report.artifacts.pdf_path}")
    for ticket in report.tickets:
        console.print(f" - {ticket.name}: {ticket.code} ({ticket.stake_count}注/{ticket.cost_yuan}元)")


@app.command("zucai-auto-run")
def zucai_auto_run(
    run_date: str = typer.Option("today", "--date"),
    slot: str = typer.Option(..., "--slot"),
    registry_file: Path = ZUCAI_REGISTRY_FILE_OPTION,
    output_dir: Path = ZUCAI_SCHEDULE_OUTPUT_DIR_OPTION,
    run_record_file: Path = ZUCAI_RUN_RECORD_FILE_OPTION,
    dispatch_telegram: bool = typer.Option(False, "--dispatch-telegram"),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
    force: bool = typer.Option(False, "--force"),
    quiet: bool = typer.Option(False, "--quiet"),
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    service = build_zucai_scheduled_delivery_service()
    try:
        result = service.run(
            run_date=run_date,
            slot=slot,
            registry_file=registry_file,
            output_dir=output_dir,
            run_record_file=run_record_file,
            dispatch_telegram=dispatch_telegram,
            dry_run=dry_run,
            force=force,
        )
    except ZucaiScheduleValidationError as exc:
        console.print(str(exc))
        raise typer.Exit(code=2) from exc

    payload = result.to_dict()
    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    if quiet and result.status == "skipped_no_issue":
        return
    console.print(
        f"zucai-auto-run date={result.run_date} slot={result.slot} "
        f"status={result.status} issue={result.issue_id or '-'}"
    )
    if result.skipped_reason:
        console.print(f"reason={result.skipped_reason}")
    if result.artifacts.pdf_path:
        console.print(f"pdf={result.artifacts.pdf_path}")
    console.print(f"dispatch={result.dispatch.status}")
    for warning in result.warnings:
        console.print(f"warning: {warning}")


@app.command("zucai-source-sync")
def zucai_source_sync(
    source_file: Path | None = ZUCAI_SOURCE_FILE_OPTION,
    source_url: str | None = ZUCAI_SOURCE_URL_OPTION,
    live_fetch: bool = typer.Option(False, "--live-fetch"),
    run_date: str = typer.Option("today", "--date"),
    source_label: str = ZUCAI_SOURCE_LABEL_OPTION,
    output_dir: Path = ZUCAI_OUTPUT_DIR_OPTION,
    registry_file: Path = ZUCAI_REGISTRY_FILE_OPTION,
    timeout_seconds: float = typer.Option(5.0, "--timeout-seconds"),
    max_bytes: int = typer.Option(524_288, "--max-bytes"),
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    service = build_zucai_source_sync_service()
    try:
        result = service.sync(
            source_file=source_file,
            source_url=source_url,
            live_fetch=live_fetch,
            run_date=run_date,
            output_dir=output_dir,
            registry_file=registry_file,
            source_label=source_label,
            timeout_seconds=timeout_seconds,
            max_bytes=max_bytes,
        )
    except ZucaiSourceValidationError as exc:
        console.print(str(exc))
        raise typer.Exit(code=2) from exc

    payload = result.to_dict()
    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    console.print(
        f"zucai-source-sync parsed={result.parsed_count} "
        f"active={','.join(result.active_issue_ids) or '-'}"
    )
    console.print(f"registry={result.registry_path}")
    for issue_id, path in result.written_issue_paths.items():
        console.print(f" - {issue_id}: {path}")
    for warning in result.warnings:
        console.print(f"warning: {warning}")


@app.command("zucai-odds-sync")
def zucai_odds_sync(
    source_file: Path | None = ZUCAI_SOURCE_FILE_OPTION,
    source_url: str | None = ZUCAI_SOURCE_URL_OPTION,
    live_fetch: bool = typer.Option(False, "--live-fetch"),
    issue_id: str | None = ZUCAI_ISSUE_ID_OPTION,
    slot: str = typer.Option(..., "--slot"),
    captured_at: str | None = typer.Option(None, "--captured-at"),
    source_label: str = ZUCAI_ODDS_SOURCE_LABEL_OPTION,
    output_dir: Path = ZUCAI_OUTPUT_DIR_OPTION,
    registry_file: Path = ZUCAI_REGISTRY_FILE_OPTION,
    timeout_seconds: float = typer.Option(5.0, "--timeout-seconds"),
    max_bytes: int = typer.Option(524_288, "--max-bytes"),
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    service = build_zucai_odds_sync_service()
    try:
        result = service.sync(
            source_file=source_file,
            source_url=source_url,
            live_fetch=live_fetch,
            issue_id=issue_id,
            slot=slot,
            captured_at=captured_at,
            output_dir=output_dir,
            registry_file=registry_file,
            source_label=source_label,
            timeout_seconds=timeout_seconds,
            max_bytes=max_bytes,
        )
    except ZucaiOddsSourceValidationError as exc:
        console.print(str(exc))
        raise typer.Exit(code=2) from exc

    payload = result.to_dict()
    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    console.print(
        f"zucai-odds-sync issue={result.issue_id} slot={result.slot} rows={result.parsed_count}"
    )
    console.print(f"odds={result.odds_path}")
    console.print(f"registry={result.registry_path}")
    for warning in result.warnings:
        console.print(f"warning: {warning}")


@app.command("zucai-grade")
def zucai_grade(
    report_file: Path = ZUCAI_REPORT_FILE_OPTION,
    outcomes_file: Path = ZUCAI_OUTCOMES_FILE_OPTION,
    record_db: bool = typer.Option(True, "--record-db/--no-record-db"),
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    service = build_zucai_workflow_service()
    try:
        grade = service.grade_report(
            report_file=report_file,
            outcomes_file=outcomes_file,
            record_db=record_db,
        )
    except ZucaiValidationError as exc:
        console.print(str(exc))
        raise typer.Exit(code=2) from exc

    payload = grade.to_dict()
    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    console.print(
        f"zucai-grade issue={grade.issue_id} "
        f"matches={len(grade.match_results)} plans={len(grade.plan_results)}"
    )
    for plan in grade.plan_results:
        console.print(
            f" - {plan.name}: hit={plan.hit_count}/{plan.selected_count} "
            f"covered={'yes' if plan.covered else 'no'}"
        )
    for warning in grade.warnings:
        console.print(f" warning: {warning}")


@app.command("jczq-mixed-report")
def jczq_mixed_report(
    provider: str = JCZQ_PROVIDER_OPTION,
    output_dir: Path = JCZQ_OUTPUT_DIR_OPTION,
    pdf: bool = typer.Option(False, "--pdf"),
    dispatch_telegram: bool = typer.Option(False, "--dispatch-telegram"),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    try:
        service = build_jczq_mixed_report_service(provider=provider)
        report = service.build_report(
            output_dir=output_dir,
            render_pdf=pdf or dispatch_telegram,
            dispatch_telegram=dispatch_telegram,
            dry_run=dry_run,
        )
    except (JczqProviderError, JczqSelectionError) as exc:
        console.print(str(exc))
        raise typer.Exit(code=2) from exc

    payload = report.to_dict()
    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    console.print(
        f"jczq-mixed-report combos={len(report.combinations)} "
        f"official_update={report.official_last_update}"
    )
    console.print(f"markdown={report.artifacts.markdown_path}")
    if report.artifacts.pdf_path:
        console.print(f"pdf={report.artifacts.pdf_path}")
    console.print(f"dispatch={report.dispatch.status}")
    for combo in report.combinations:
        console.print(
            f" - {combo.name}: odds={combo.total_odds:.2f} 2元={combo.two_yuan_return:.2f}"
        )


@app.command("jczq-daily-advisor")
def jczq_daily_advisor(
    provider: str = JCZQ_PROVIDER_OPTION,
    run_date: str = JCZQ_DAILY_DATE_OPTION,
    output_dir: Path = JCZQ_OUTPUT_DIR_OPTION,
    revision_text: str | None = typer.Option(None, "--revision-text"),
    record_final: bool = typer.Option(True, "--record-final/--no-record-final"),
    dispatch_telegram: bool = typer.Option(False, "--dispatch-telegram"),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    try:
        service = build_jczq_daily_advisor_service(provider=provider)
        if revision_text:
            report = service.revise(
                run_date=run_date,
                output_dir=output_dir,
                instruction=revision_text,
                dispatch_telegram=dispatch_telegram,
                dry_run=dry_run,
                record_final=record_final,
            )
        else:
            report = service.build_report(
                run_date=run_date,
                output_dir=output_dir,
                dispatch_telegram=dispatch_telegram,
                dry_run=dry_run,
                record_final=record_final,
            )
    except (JczqDailyAdvisorError, JczqProviderError, JczqSelectionError) as exc:
        console.print(str(exc))
        raise typer.Exit(code=2) from exc

    payload = report.to_dict()
    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    console.print(service.render_message(report))


@app.command("jczq-daily-review")
def jczq_daily_review(
    run_date: str = typer.Option("yesterday", "--date"),
    output_dir: Path = JCZQ_OUTPUT_DIR_OPTION,
    dispatch_telegram: bool = typer.Option(False, "--dispatch-telegram"),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    service = build_jczq_daily_review_service()
    report = service.build_review(
        run_date=run_date,
        output_dir=output_dir,
        dispatch_telegram=dispatch_telegram,
        dry_run=dry_run,
    )

    if format == "json":
        typer.echo(json.dumps(report, indent=2, sort_keys=True, default=str))
        return

    console.print(str(report.get("message") or ""))


@app.command("jczq-debate-init")
def jczq_debate_init(
    run_date: str = typer.Option("today", "--date"),
    output_dir: Path = JCZQ_OUTPUT_DIR_OPTION,
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    service = build_jczq_debate_workspace_service()
    try:
        result = service.initialize_workspace(run_date=run_date, output_dir=output_dir)
    except JczqDebateWorkspaceError as exc:
        console.print(str(exc))
        raise typer.Exit(code=2) from exc

    if format == "json":
        typer.echo(json.dumps(result, indent=2, sort_keys=True, default=str))
        return
    console.print(f"jczq-debate-init date={result['run_date']}")
    console.print(f"debate_dir={result['debate_dir']}")
    for path in result.get("artifacts", {}).values():
        console.print(f"- {path}")


@app.command("jczq-debate-compare")
def jczq_debate_compare(
    run_date: str = typer.Option("today", "--date"),
    output_dir: Path = JCZQ_OUTPUT_DIR_OPTION,
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    service = build_jczq_debate_workspace_service()
    result = service.compare_workspace(run_date=run_date, output_dir=output_dir)

    if format == "json":
        typer.echo(json.dumps(result, indent=2, sort_keys=True, default=str))
        return
    console.print(f"jczq-debate-compare date={result['run_date']}")
    console.print(f"consensus={len(result['consensus_legs'])}")
    console.print(f"conflicts={', '.join(result['conflict_matches']) or '-'}")
    console.print(f"disagreements={result['artifacts']['disagreements_path']}")


@app.command("jczq-debate-finalize")
def jczq_debate_finalize(
    run_date: str = typer.Option("today", "--date"),
    output_dir: Path = JCZQ_OUTPUT_DIR_OPTION,
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    service = build_jczq_debate_workspace_service()
    result = service.finalize_workspace(run_date=run_date, output_dir=output_dir)

    if format == "json":
        typer.echo(json.dumps(result, indent=2, sort_keys=True, default=str))
        return
    console.print(f"jczq-debate-finalize date={result['run_date']}")
    console.print(f"final_plan={result['final_plan_path']}")


def _build_jczq_value_bridge_for_brief(brief_date: str):
    """Assemble the live value bridge for the daily brief, or None.

    Wraps ``build_jczq_value_bridge`` with a ``ValueBoardService`` factory; any
    failure degrades to ``None`` so ``jczq-daily-brief`` always renders.
    """
    from nutmeg.services.jczq_value_wiring import build_jczq_value_bridge

    try:
        settings = get_settings()
        return build_jczq_value_bridge(
            settings=settings,
            run_date=brief_date,
            value_service_factory=lambda: build_value_board_service()[0],
        )
    except Exception:  # noqa: BLE001 — degrade, never crash the brief
        logger.warning("value bridge wiring failed — degrading", exc_info=True)
        return None


@app.command("jczq-daily-brief")
def jczq_daily_brief(
    run_date: str | None = typer.Option(None, "--date", help="目标日期 YYYY-MM-DD，默认今天 live"),
    replay_date: str | None = typer.Option(None, "--replay", help="从已存 context.json 回放"),
    output_dir: Path = JCZQ_OUTPUT_DIR_OPTION,
    write: Path | None = typer.Option(None, "--write", help="写入文件（默认 stdout）"),
) -> None:
    from nutmeg.services.jczq_brief import build_brief, today_iso, write_or_print_brief
    from nutmeg.services.jczq_conflict_bridge import record_conflict_signals

    # Wire the value/conflict engine: align the day's JCZQ matches to
    # API-Football, run ValueBoardService, render the real 赔率冲突点 section.
    # No key / API down / empty alignment → bridge is None → placeholder.
    brief_date = replay_date or run_date or today_iso()
    value_bridge = _build_jczq_value_bridge_for_brief(brief_date)

    try:
        markdown = build_brief(
            run_date=run_date,
            replay_date=replay_date,
            output_dir=output_dir,
            service_builder=build_jczq_daily_advisor_service,
            value_bridge=value_bridge,
        )
    except FileNotFoundError as exc:
        console.print(str(exc))
        raise typer.Exit(code=2) from exc

    # Self-validation loop: persist the day's conflict signals so next-day
    # jczq-daily-review grades them and the stake ladder accrues a track record.
    if value_bridge is not None:
        try:
            recorded = record_conflict_signals(
                value_bridge=value_bridge,
                run_date=brief_date,
                output_dir=output_dir,
            )
            if recorded:
                console.print(f"recorded {recorded} conflict signal(s)", style="dim")
        except Exception:  # noqa: BLE001 — store failure must not break the brief
            logger.warning("conflict-signal recording failed", exc_info=True)

    write_or_print_brief(markdown, write)


@app.command("jczq-second-leg")
def jczq_second_leg(
    run_date: str = typer.Option(..., "--date", help="目标日期 YYYY-MM-DD"),
    output_dir: Path = JCZQ_OUTPUT_DIR_OPTION,
    solo: str | None = typer.Option(
        None,
        "--solo",
        help="单核腿 '<match_no> <pool> <pick>'，例如 '周三003 crs 0:0'",
    ),
    auto: bool = typer.Option(False, "--auto", help="从 final-plan.json 自动读取单核腿"),
    top: int = typer.Option(8, "--top", help="输出前 N 个候选"),
) -> None:
    from nutmeg.services.jczq_second_leg import parse_solo, suggest_second_legs

    if not auto and not solo:
        console.print("必须提供 --solo 或 --auto")
        raise typer.Exit(code=2)

    try:
        solo_tuple = parse_solo(solo) if (solo and not auto) else None
        rendered = suggest_second_legs(
            run_date=run_date,
            output_dir=output_dir,
            solo=solo_tuple,
            auto=auto,
            top=top,
        )
    except (FileNotFoundError, ValueError) as exc:
        console.print(str(exc))
        raise typer.Exit(code=2) from exc

    typer.echo(rendered)


@app.command("jczq-final-plan-pdf")
def jczq_final_plan_pdf(
    run_date: str = typer.Option("today", "--date", help="目标日期 YYYY-MM-DD 或 today"),
    output_dir: Path = JCZQ_OUTPUT_DIR_OPTION,
    dispatch: bool = typer.Option(False, "--dispatch", help="渲染后通过 Telegram bot 推送"),
    telegram_token: str | None = typer.Option(
        None, "--telegram-token", help="覆盖 NUTMEG_TELEGRAM_BOT_TOKEN"
    ),
    telegram_chat_ids: str | None = typer.Option(
        None,
        "--telegram-chat-ids",
        help="覆盖 NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS，逗号分隔",
    ),
) -> None:
    from datetime import date as _date_cls

    from nutmeg.services.jczq_final_plan_pdf import render_and_dispatch

    resolved_date = _date_cls.today().isoformat() if run_date == "today" else run_date
    chat_ids = (
        [int(x.strip()) for x in telegram_chat_ids.split(",") if x.strip()]
        if telegram_chat_ids
        else None
    )

    try:
        result = render_and_dispatch(
            run_date=resolved_date,
            output_dir=output_dir,
            dispatch=dispatch,
            telegram_token=telegram_token,
            telegram_chat_ids=chat_ids,
        )
    except (FileNotFoundError, RuntimeError) as exc:
        console.print(str(exc))
        raise typer.Exit(code=2) from exc

    console.print(f"Wrote PDF: {result.pdf_path} ({result.pdf_bytes} bytes)")
    if result.skipped_dispatch_reason:
        console.print(f"(skipped dispatch: {result.skipped_dispatch_reason})")
        return
    for chat_id in result.dispatched_chat_ids:
        console.print(f"Dispatched PDF to chat_id={chat_id}")


@app.command("jczq-replay")
def jczq_replay(
    run_date: str = typer.Option("2026-05-03", "--date", help="回放的目标日期"),
    input_dir: Path = JCZQ_OUTPUT_DIR_OPTION,
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    from nutmeg.services.jczq_replay import replay_with_new_generator

    try:
        result = replay_with_new_generator(run_date=run_date, input_dir=input_dir)
    except FileNotFoundError as exc:
        console.print(str(exc))
        raise typer.Exit(code=2) from exc

    if format == "json":
        typer.echo(
            json.dumps(
                {
                    "run_date": result.run_date,
                    "match_count": result.match_count,
                    "legs": [
                        {
                            "plan": r.plan,
                            "match_no": r.match_no,
                            "pool": r.pool,
                            "pick": r.pick,
                            "odds": r.odds,
                            "actual": r.actual,
                            "hit": r.hit,
                        }
                        for r in result.leg_rows
                    ],
                },
                indent=2,
                sort_keys=True,
                default=str,
            )
        )
        return

    typer.echo(result.rendered_text)


@app.command("tactical-visuals")
def tactical_visuals(
    fixture_id: str = typer.Option(..., "--fixture-id"),
    output_dir: Path | None = TACTICAL_OUTPUT_DIR_OPTION,
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    service, session = build_tactical_visual_service()
    try:
        pack = service.build_pack(fixture_id, output_dir=output_dir)
    except (FixtureNotFoundError, ApiFootballError, SoccerDataError, ValueError) as exc:
        console.print(str(exc))
        raise typer.Exit(code=2) from exc
    finally:
        session.close()

    payload = asdict(pack)
    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    console.print(
        f"tactical visuals fixture={pack.fixture.fixture_id} "
        f"artifacts={len(pack.artifacts)} unavailable={pack.unavailable_sections}"
    )
    for artifact in pack.artifacts:
        path = f" path={artifact.path}" if artifact.path else ""
        console.print(f" - {artifact.name} status={artifact.status} source={artifact.source}{path}")
    for insight in pack.insights:
        console.print(f" insight: {insight}")


@app.command("event-tactical-models")
def event_tactical_models(
    fixture_id: str = typer.Option(..., "--fixture-id"),
    events_file: Path | None = EVENT_DATA_EVENTS_FILE_OPTION,
    output_dir: Path | None = TACTICAL_OUTPUT_DIR_OPTION,
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    service = build_event_tactical_model_service()
    report = service.build_report(
        fixture_id=fixture_id,
        events_file=events_file,
        output_dir=output_dir,
    )
    payload = report.to_dict()
    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    quality = payload["quality"]
    console.print(
        f"event tactical models fixture={payload['fixture_id']} "
        f"status={quality['status']} events={quality['event_count']}"
    )
    console.print(
        "models: "
        f"{payload['pass_network']['model_label']}, "
        f"{payload['spatial_value']['model_label']}, "
        f"{payload['player_contributions']['model_label']}"
    )
    if payload["unavailable_sections"]:
        console.print(f"unavailable={payload['unavailable_sections']}")
    for artifact in payload["artifacts"]:
        path = f" path={artifact['file_path']}" if artifact.get("file_path") else ""
        console.print(f" - {artifact['title']} kind={artifact['kind']}{path}")
    for warning in payload["warnings"]:
        console.print(f" warning: {warning}")


@app.command("fixture-information")
def fixture_information(
    fixture_id: str = typer.Option(..., "--fixture-id"),
    home_team: str | None = typer.Option(None, "--home-team"),
    away_team: str | None = typer.Option(None, "--away-team"),
    sources_file: Path | None = INFORMATION_SOURCES_FILE_OPTION,
    sources_config: Path | None = INFORMATION_SOURCES_CONFIG_OPTION,
    cache_dir: Path | None = INFORMATION_CACHE_DIR_OPTION,
    live_fetch: bool = INFORMATION_LIVE_FETCH_OPTION,
    cache_ttl_seconds: int = INFORMATION_CACHE_TTL_OPTION,
    timeout_seconds: float = INFORMATION_TIMEOUT_OPTION,
    max_bytes: int = INFORMATION_MAX_BYTES_OPTION,
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    service = (
        build_live_fixture_information_service(
            manifest_path=sources_config,
            cache_dir=cache_dir,
            live_fetch=live_fetch,
            cache_ttl_seconds=cache_ttl_seconds,
            timeout_seconds=timeout_seconds,
            max_bytes=max_bytes,
        )
        if sources_config is not None
        else build_fixture_information_service()
    )
    digest = service.build_digest(
        fixture_id=fixture_id,
        home_team=home_team,
        away_team=away_team,
        sources_file=None if sources_config is not None else sources_file,
    )
    payload = digest.to_dict()
    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    console.print(
        f"fixture information fixture={payload['fixture_id']} "
        f"status={payload['status']} sources={payload['source_count']}"
    )
    console.print(str(payload["summary"]))
    for item in payload["items"]:
        console.print(
            " | ".join(
                [
                    str(item["reliability"]),
                    str(item["source_name"]),
                    str(item["title"]),
                    str(item.get("url") or "-"),
                ]
            )
        )
    for warning in payload["warnings"]:
        console.print(f" warning: {warning}")


@app.command("analyze-match")
def analyze_match(
    fixture_id: str = typer.Option(..., "--fixture-id"),
    query: str = typer.Option(..., "--query"),
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    settings = get_settings()
    analysis_service, session = build_analysis_service()
    try:
        with traced_operation(
            settings,
            operation_name="cli.analysis.match",
            user_id=settings.default_user_id,
            tags=["analysis", "match"],
            metadata={"fixture_id": fixture_id, "query": query, "format": format},
        ):
            result = analysis_service.analyze_match(fixture_id, query=query)
    except (
        InsufficientEvidenceError,
        FixtureNotFoundError,
        OddsFixtureNotFoundError,
        ApiFootballError,
        TheOddsApiError,
        ValueError,
    ) as exc:
        console.print(str(exc))
        raise typer.Exit(code=2) from exc
    finally:
        if session is not None:
            session.close()

    payload = asdict(result)
    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    console.print(
        f"{result.fixture.fixture_id} | "
        f"{result.fixture.home_team} vs {result.fixture.away_team} | "
        f"intent={result.intent.value}"
    )
    console.print(f"Judgment: {result.judgment.verdict}")
    console.print("Core reasons:")
    for reason in result.judgment.core_reasons:
        console.print(f" - {reason}")
    if result.evidence.tactical_summary:
        console.print("Tactical evidence:")
        for item in result.evidence.tactical_summary:
            console.print(f" - {item}")
    if result.evidence.odds_summary:
        console.print("Market evidence:")
        for item in result.evidence.odds_summary:
            console.print(f" - {item}")
    if result.evidence.market_shape_summary:
        console.print("Market shape:")
        for item in result.evidence.market_shape_summary:
            console.print(f" - {item}")
    if result.evidence.caveats:
        console.print("Caveats:")
        for item in result.evidence.caveats:
            console.print(f" - {item}")
    console.print(f"Conflict state: {result.conflict_state}")
    console.print(f"Counterargument: {result.judgment.counterargument}")
    console.print(f"Confidence: {result.judgment.confidence}")


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


@app.command("today-briefs")
def today_briefs(
    league: str = typer.Option("epl", "--league"),
    days: int = typer.Option(1, "--days"),
    limit: int = typer.Option(5, "--limit"),
    demo: bool = typer.Option(False, "--demo"),
    briefs: bool = typer.Option(False, "--briefs"),
    query: str = typer.Option("Give me the pre-match operator brief.", "--query"),
    sort: str = typer.Option("kickoff", "--sort", help="kickoff or popularity"),
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    fixture_service, fixture_session = build_fixture_service()
    workflow = None
    workflow_session = None
    try:
        fixtures = fixture_service.list_upcoming(league, days, demo=demo)
        if briefs:
            workflow, workflow_session = build_agent_workflow()
        payload = build_today_briefs_payload(
            league=league,
            days=days,
            limit=limit,
            demo=demo,
            briefs=briefs,
            query=query,
            fixtures=fixtures,
            workflow=workflow,
            sort=sort,
        )
    except ValueError as exc:
        if format == "json":
            typer.echo(json.dumps({"status": "failed", "error": str(exc)}, indent=2))
        else:
            console.print(str(exc))
        raise typer.Exit(code=2) from exc
    finally:
        fixture_session.close()
        if workflow_session is not None:
            workflow_session.close()

    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    console.print(f"Today brief candidates: {league}")
    if not payload["items"]:
        console.print(payload["empty_reason"])
        return
    for item in payload["items"]:
        columns = [
            str(item["fixture_id"]),
            str(item["kickoff_at"]),
            f"{item['home_team']} vs {item['away_team']}",
            str(item.get("venue") or "-"),
            str(item["suggested_bot_message"]),
        ]
        if item.get("popularity"):
            columns.insert(0, f"#{item['rank']} score={item['popularity']['score']}")
        console.print(" | ".join(columns))
        brief = item.get("brief")
        if isinstance(brief, dict):
            judgment = brief.get("judgment") or {}
            if brief.get("status") == "succeeded":
                console.print(
                    f"  brief: {judgment.get('verdict')} confidence={judgment.get('confidence')}"
                )
            else:
                console.print(f"  brief failed: {brief.get('error')}")


@app.command("popular-matches")
def popular_matches(
    league: str = typer.Option("epl", "--league"),
    days: int = typer.Option(1, "--days"),
    limit: int = typer.Option(5, "--limit"),
    demo: bool = typer.Option(False, "--demo"),
    query: str = typer.Option("Give me the pre-match operator brief.", "--query"),
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    fixture_service, fixture_session = build_fixture_service()
    try:
        fixtures = fixture_service.list_upcoming(league, days, demo=demo)
        payload = build_popular_matches_payload(
            league=league,
            days=days,
            limit=limit,
            demo=demo,
            query=query,
            fixtures=fixtures,
        )
    finally:
        fixture_session.close()

    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    console.print(f"Popular matches: {league}")
    if not payload["items"]:
        console.print(payload["empty_reason"])
        return
    for item in payload["items"]:
        popularity = item["popularity"]
        console.print(
            " | ".join(
                [
                    f"#{item['rank']}",
                    f"score={popularity['score']}",
                    f"tier={popularity['tier']}",
                    str(item["fixture_id"]),
                    str(item["kickoff_at"]),
                    f"{item['home_team']} vs {item['away_team']}",
                    "; ".join(popularity["reasons"]),
                    str(item["suggested_bot_message"]),
                ]
            )
        )


@app.command("agent-status")
def agent_status(format: str = typer.Option("text", "--format", help="text or json")) -> None:
    settings = get_settings()
    payload = build_agent_status_payload(settings)
    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    agent = payload["agent"]
    synthesis = payload["synthesis"]
    odds_provider = payload["odds_provider"]
    bot_fallback = payload["bot_fallback"]
    console.print(
        f"agent executor={agent['executor']} "
        f"langgraph={'yes' if agent['langgraph_available'] else 'no'}"
    )
    console.print(
        f"synthesis enabled={'yes' if synthesis['enabled'] else 'no'} "
        f"configured={'yes' if synthesis['configured'] else 'no'} "
        f"model={synthesis['model']}"
    )
    console.print(
        f"odds provider={odds_provider['name']} "
        f"configured={'yes' if odds_provider['configured'] else 'no'} "
        f"health-metrics={'yes' if odds_provider['health_metrics_available'] else 'no'}"
    )
    console.print(
        f"bot fallback enabled={'yes' if bot_fallback['enabled'] else 'no'} "
        f"configured={'yes' if bot_fallback['configured'] else 'no'} "
        f"model={bot_fallback['model']}"
    )


@app.command("client-status")
def client_status(
    user_id: str | None = typer.Option(None, "--user-id"),
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    service, session = build_client_service()
    try:
        payload = service.status(user_id=user_id)
    finally:
        if session is not None:
            session.close()

    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    console.print(
        f"client status user={payload['user_id']} "
        f"health={payload['health']['health']} "
        f"plan={payload['entitlements']['plan']}"
    )


@app.command("client-feed")
def client_feed(
    league: str = typer.Option("epl", "--league"),
    days: int = typer.Option(3, "--days"),
    limit: int = typer.Option(5, "--limit"),
    user_id: str | None = typer.Option(None, "--user-id"),
    demo: bool = typer.Option(False, "--demo"),
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    service, session = build_client_service()
    try:
        payload = service.daily_feed(
            user_id=user_id,
            league=league,
            days=days,
            limit=limit,
            demo=demo,
        )
    finally:
        if session is not None:
            session.close()

    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    console.print(
        f"Client feed: league={payload['league']} opportunities={len(payload['opportunities'])}"
    )
    for item in payload["opportunities"]:
        console.print(
            " | ".join(
                [
                    f"#{item['rank']}",
                    str(item["fixture_id"]),
                    f"{item['home_team']} vs {item['away_team']}",
                    f"actionability={item['actionability']}",
                    f"freshness={item['freshness']['health']}",
                    f"next={item['suggested_action']}",
                ]
            )
        )


@app.command("client-match")
def client_match(
    fixture_id: str = typer.Option(..., "--fixture-id"),
    user_id: str | None = typer.Option(None, "--user-id"),
    information_sources_config: Path | None = CLIENT_INFORMATION_SOURCES_CONFIG_OPTION,
    information_cache_dir: Path | None = CLIENT_INFORMATION_CACHE_DIR_OPTION,
    live_information_fetch: bool = CLIENT_INFORMATION_LIVE_FETCH_OPTION,
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    service, session = build_client_service()
    if information_sources_config is not None:
        service.set_information_provider(
            build_live_fixture_information_service(
                manifest_path=information_sources_config,
                cache_dir=information_cache_dir,
                live_fetch=live_information_fetch,
            )
        )
    try:
        payload = service.match_workspace(user_id=user_id, fixture_id=fixture_id)
    finally:
        if session is not None:
            session.close()

    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    judgment = payload.get("judgment") or {}
    console.print(
        f"Client match: {payload['fixture_id']} "
        f"actionability={payload['actionability']} "
        f"confidence={judgment.get('confidence')}"
    )
    console.print(str(judgment.get("verdict") or "No verdict"))


@app.command("client-question")
def client_question(
    fixture_id: str = typer.Option(..., "--fixture-id"),
    question: str = typer.Option(..., "--question"),
    user_id: str | None = typer.Option(None, "--user-id"),
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    service, session = build_client_service()
    try:
        payload = service.answer_question(
            user_id=user_id,
            fixture_id=fixture_id,
            question=question,
        )
    finally:
        if session is not None:
            session.close()

    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    console.print(payload["answer"])


@app.command("client-watchlist")
def client_watchlist(
    target_type: str = typer.Option("fixture", "--target-type"),
    target_id: str = typer.Option(..., "--target-id"),
    alert_preference: list[str] | None = ALERT_PREFERENCE_OPTION,
    user_id: str | None = typer.Option(None, "--user-id"),
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    service, session = build_client_service()
    resolved_user_id = user_id or getattr(service, "default_user_id", "owner")
    try:
        payload = service.save_watchlist_item(
            user_id=resolved_user_id,
            target_type=target_type,
            target_id=target_id,
            alert_preferences=alert_preference or [],
        )
    finally:
        if session is not None:
            session.close()

    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    console.print(
        f"Watchlist saved: {payload['target_type']}={payload['target_id']} "
        f"alerts={','.join(payload['alert_preferences']) or '-'}"
    )


@app.command("client-alerts")
def client_alerts(
    user_id: str | None = typer.Option(None, "--user-id"),
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    service, session = build_client_service()
    resolved_user_id = user_id or getattr(service, "default_user_id", "owner")
    try:
        payload = service.alerts(user_id=resolved_user_id)
    finally:
        if session is not None:
            session.close()

    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    console.print(f"Client alerts: {len(payload['alerts'])}")
    for alert in payload["alerts"]:
        console.print(
            " | ".join(
                [
                    str(alert.get("alert_id")),
                    str(alert.get("fixture_id")),
                    str(alert.get("change_type")),
                    str(alert.get("severity")),
                    str(alert.get("after_summary")),
                ]
            )
        )


@app.command("client-prediction-record")
def client_prediction_record(
    fixture_id: str = typer.Option(..., "--fixture-id"),
    pick: str = typer.Option(..., "--pick"),
    source_audit_id: str | None = typer.Option(None, "--source-audit-id"),
    client_notes: str | None = typer.Option(None, "--client-notes"),
    user_id: str | None = typer.Option(None, "--user-id"),
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    service, session = build_client_service()
    resolved_user_id = user_id or getattr(service, "default_user_id", "owner")
    try:
        payload = service.record_prediction(
            user_id=resolved_user_id,
            fixture_id=fixture_id,
            pick=pick,
            source_audit_id=source_audit_id,
            client_notes=client_notes,
        )
    finally:
        if session is not None:
            session.close()

    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    console.print(
        f"Client prediction recorded: id={payload['prediction_id']} "
        f"fixture={payload['fixture_id']} pick={payload['pick']}"
    )


@app.command("client-web")
def client_web(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8765, "--port"),
) -> None:
    import uvicorn

    service, _session = build_client_service()
    uvicorn.run(create_client_app(service=service), host=host, port=port)


@app.command("jczq-web")
def jczq_web(
    output_dir: Path = JCZQ_OUTPUT_DIR_OPTION,
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8765, "--port"),
) -> None:
    import uvicorn

    from nutmeg.interfaces.jczq_web import create_jczq_web_app
    from nutmeg.services.jczq_web import JczqWebCockpitService
    from nutmeg.storage.jczq_web_repository import JczqWebRepository

    repository = JczqWebRepository(Path(output_dir) / "jczq-web.sqlite3")
    repository.initialize()
    service = JczqWebCockpitService(output_dir=output_dir, repository=repository)
    uvicorn.run(create_jczq_web_app(service=service), host=host, port=port)


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


@app.command("match-brief")
def match_brief(
    fixture_id: str = typer.Option(..., "--fixture-id"),
    query: str = typer.Option(..., "--query"),
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    settings = get_settings()
    workflow, session = build_agent_workflow()
    try:
        with traced_operation(
            settings,
            operation_name="cli.operator.match_brief",
            user_id=settings.default_user_id,
            tags=["operator", "brief", "match"],
            metadata={"fixture_id": fixture_id, "query": query, "format": format},
        ):
            result = workflow.run(fixture_id=fixture_id, query=query)
    finally:
        if session is not None:
            session.close()

    payload = build_match_brief_payload(result)
    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        if result.status == "failed":
            raise typer.Exit(code=2)
        return

    if result.status == "failed":
        console.print(payload["error"])
        raise typer.Exit(code=2)

    analysis = result.analysis
    if analysis is None:
        console.print("Match brief could not be generated.")
        raise typer.Exit(code=2)

    console.print(f"Match Brief: {analysis.fixture.home_team} vs {analysis.fixture.away_team}")
    console.print(f"Fixture: {analysis.fixture.fixture_id}")
    console.print(f"Query: {result.query}")
    console.print(f"Verdict: {analysis.judgment.verdict}")
    console.print(f"Confidence: {analysis.judgment.confidence}")
    console.print(f"Conflict: {analysis.conflict_state}")
    console.print(f"Counterargument: {analysis.judgment.counterargument}")
    _print_brief_list("Core reasons", analysis.judgment.core_reasons)
    _print_brief_list("Snapshot context", analysis.evidence.snapshot_summary)
    _print_brief_list("Tactical evidence", analysis.evidence.tactical_summary)
    _print_brief_list(
        "Market evidence",
        [*analysis.evidence.odds_summary, *analysis.evidence.market_shape_summary],
    )
    _print_brief_list("Caveats", analysis.evidence.caveats)
    if result.generated_synthesis:
        console.print("Generated synthesis:")
        console.print(result.generated_synthesis)
    console.print(f"Agent: {result.executor} | nodes={' -> '.join(result.nodes)}")


@app.command("agent-analyze-match")
def agent_analyze_match(
    fixture_id: str = typer.Option(..., "--fixture-id"),
    query: str = typer.Option(..., "--query"),
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    settings = get_settings()
    workflow, session = build_agent_workflow()
    try:
        with traced_operation(
            settings,
            operation_name="cli.agent.analysis.match",
            user_id=settings.default_user_id,
            tags=["agent", "analysis", "match"],
            metadata={"fixture_id": fixture_id, "query": query, "format": format},
        ):
            result = workflow.run(fixture_id=fixture_id, query=query)
    finally:
        if session is not None:
            session.close()

    payload = asdict(result)
    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        if result.status == "failed":
            raise typer.Exit(code=2)
        return

    console.print(f"Agent status: {result.status}")
    console.print(f"Agent nodes: {' -> '.join(result.nodes)}")
    if result.analysis is not None:
        console.print(f"Judgment: {result.analysis.judgment.verdict}")
        console.print(f"Confidence: {result.analysis.judgment.confidence}")
    if result.generated_synthesis:
        console.print("Generated synthesis:")
        console.print(result.generated_synthesis)
    if result.error:
        console.print(result.error)
        raise typer.Exit(code=2)


@app.command("bot-dry-run")
def bot_dry_run(
    message: str = typer.Option(..., "--message"),
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    settings = get_settings()
    workflow, session = build_agent_workflow()
    try:
        adapter = BotAdapter(
            workflow=workflow,
            payload_builder=build_match_brief_payload,
            fallback_provider=build_bot_fallback_provider(settings),
            jczq_workflow=JczqDailyBotWorkflow(
                service=build_jczq_daily_advisor_service(provider="live")
            ),
            renjiu_workflow=ZucaiRenjiuBotWorkflow(
                service=build_zucai_renjiu_daily_service(),
                dry_run=True,
                value_bridge_factory=_build_zucai_value_bridge_for_daily,
            ),
        )
        response = adapter.handle_message(message)
    finally:
        if session is not None:
            session.close()

    if format == "json":
        typer.echo(json.dumps(asdict(response), indent=2, sort_keys=True, default=str))
        if response.status == "failed":
            raise typer.Exit(code=2)
        return

    console.print(response.text)
    if response.status == "failed":
        raise typer.Exit(code=2)


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
            jczq_workflow=JczqDailyBotWorkflow(
                service=build_jczq_daily_advisor_service(provider="live")
            ),
            renjiu_workflow=ZucaiRenjiuBotWorkflow(
                service=build_zucai_renjiu_daily_service(),
                dry_run=False,
                value_bridge_factory=_build_zucai_value_bridge_for_daily,
            ),
        ),
        allowed_chat_ids=allowed_chat_ids,
    )


@app.command("telegram-bot-status")
def telegram_bot_status(
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    settings = get_settings()
    payload = build_telegram_status_payload(settings)
    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    console.print(
        f"telegram configured={'yes' if payload['configured'] else 'no'} "
        f"allowlist={'yes' if payload['allowed_chat_ids_configured'] else 'no'} "
        f"allowed-chats={payload['allowed_chat_count']}"
    )


@app.command("telegram-bot-poll-once")
def telegram_bot_poll_once(
    offset: int | None = typer.Option(None, "--offset"),
    timeout: int = typer.Option(10, "--timeout"),
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    settings = get_settings()
    try:
        runner = build_telegram_bot_runner(settings)
        summary = runner.poll_once(offset=offset, timeout=timeout)
    except ValueError as exc:
        payload = {"status": "failed", "error": str(exc)}
        if format == "json":
            typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        else:
            console.print(str(exc))
        raise typer.Exit(code=2) from exc

    payload = {
        "updates_seen": summary.updates_seen,
        "messages_handled": summary.messages_handled,
        "messages_denied": summary.messages_denied,
        "messages_ignored": summary.messages_ignored,
        "next_offset": summary.next_offset,
    }
    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    console.print(
        f"updates={summary.updates_seen} handled={summary.messages_handled} "
        f"denied={summary.messages_denied} ignored={summary.messages_ignored} "
        f"next_offset={summary.next_offset}"
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


@app.command("telegram-bot-run")
def telegram_bot_run(
    offset: int | None = typer.Option(None, "--offset"),
    timeout: int = typer.Option(10, "--timeout"),
    poll_interval: float = typer.Option(2.0, "--poll-interval"),
    max_polls: int | None = typer.Option(None, "--max-polls"),
    offset_file: Path | None = TELEGRAM_OFFSET_FILE_OPTION,
    no_offset_file: bool = TELEGRAM_NO_OFFSET_FILE_OPTION,
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    settings = get_settings()
    offset_store = None
    resolved_offset_file = None
    offset_source = "explicit" if offset is not None else "none"
    if not no_offset_file:
        resolved_offset_file = offset_file or default_telegram_offset_path(settings)
        offset_store = TelegramOffsetStore(resolved_offset_file)
        if offset is None:
            stored_offset = offset_store.read()
            if stored_offset is not None:
                offset = stored_offset
                offset_source = "store"
            else:
                offset_source = "telegram"
    try:
        daemon = build_telegram_polling_daemon(
            settings,
            poll_interval_seconds=poll_interval,
            offset_store=offset_store,
        )
        summary = daemon.run(offset=offset, timeout=timeout, max_polls=max_polls)
    except ValueError as exc:
        payload = {"status": "failed", "error": str(exc)}
        if format == "json":
            typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        else:
            console.print(str(exc))
        raise typer.Exit(code=2) from exc

    payload = telegram_daemon_summary_payload(
        summary,
        offset_persistence_enabled=offset_store is not None,
        offset_source=offset_source,
        offset_file=resolved_offset_file,
    )
    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    console.print(
        f"polls={summary.polls_run} updates={summary.updates_seen} "
        f"handled={summary.messages_handled} denied={summary.messages_denied} "
        f"ignored={summary.messages_ignored} next_offset={summary.next_offset} "
        f"stop={summary.stop_reason} offset_source={offset_source} "
        f"offset_file={resolved_offset_file}"
    )


@app.command("classify-query")
def classify_query(query: str) -> None:
    console.print(classify_intent(query).value)


if __name__ == "__main__":
    app()


PSYCHOLOGY_FIXTURE_FILE_OPTION = typer.Option(
    ..., "--fixture-file", help="JSON file with a single fixture dict"
)
PSYCHOLOGY_RULES_ONLY_OPTION = typer.Option(
    False, "--rules-only", help="Skip LLM-backed signals; only run tournament_stage"
)
INSPIRATION_DATE_OPTION = typer.Option(..., "--date", help="YYYYMMDD")
INSPIRATION_TEXT_OPTION = typer.Option(None, "--text", help="If omitted, $EDITOR is opened")


@app.command(name="psychology-inspect")
def psychology_inspect_cmd(
    fixture_file: Path = PSYCHOLOGY_FIXTURE_FILE_OPTION,
    rules_only: bool = PSYCHOLOGY_RULES_ONLY_OPTION,
) -> None:
    """Dump SignalReadings for a single fixture from each enabled provider."""
    from nutmeg.services.psychology.engine import (
        PsychologyEngine,
        SignalContext,
        TournamentStageSignal,
    )

    fixture = json.loads(fixture_file.read_text(encoding="utf-8"))
    fixture_id = str(fixture.get("id"))
    providers: list = [TournamentStageSignal()]
    if not rules_only:
        pass
    engine = PsychologyEngine(providers=providers)
    [verdict] = engine.evaluate(
        ctx=SignalContext(date="manual", fixtures=[fixture], snapshots={}, odds={}),
        data_picks={fixture_id: {}},
    )
    payload = {
        "fixture_id": fixture_id,
        "lean_direction": verdict.lean_direction,
        "conviction": verdict.conviction,
        "market_views": {
            market: {"outcome": view.outcome, "conviction": view.conviction}
            for market, view in verdict.market_views.items()
        },
        "readings": [
            {
                "provider": r.provider,
                "market": r.market,
                "outcome_view": r.outcome_view,
                "conviction": r.conviction,
                "evidence": r.evidence,
                "abstain_reason": r.abstain_reason,
            }
            for r in verdict.contributing_readings
        ],
    }
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


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


@app.command(name="inspiration-write")
def inspiration_write_cmd(
    date: str = INSPIRATION_DATE_OPTION,
    text: str | None = INSPIRATION_TEXT_OPTION,
) -> None:
    import os
    from datetime import datetime, timezone

    from nutmeg.services.psychology.io import InspirationStore

    base = Path(os.environ.get("NUTMEG_INSPIRATION_DIR", ".nutmeg-data/inspiration"))
    iso = _normalize_date(date)
    if text is None:
        editor = os.environ.get("EDITOR", "nano")
        tmpfile = base / iso / "raw.md"
        tmpfile.parent.mkdir(parents=True, exist_ok=True)
        if not tmpfile.exists():
            tmpfile.write_text("", encoding="utf-8")
        os.system(f"{editor} {tmpfile!s}")
        text = tmpfile.read_text(encoding="utf-8")
    store = InspirationStore(base_dir=base)
    store.write_raw(date=iso, text=text)
    note = _build_inspiration_parser().parse(text, date=iso)
    store.write_parsed(
        date=iso,
        tags=note.parsed_tags,
        raw_text=note.raw_text,
        parse_method=note.parse_method,
        timestamp=datetime.now(tz=timezone.utc).isoformat(),
    )
    typer.echo(f"saved {iso} via {note.parse_method}")


@app.command(name="inspiration-show")
def inspiration_show_cmd(date: str = typer.Argument(..., help="YYYYMMDD")) -> None:
    import os

    from nutmeg.services.psychology.io import InspirationStore

    base = Path(os.environ.get("NUTMEG_INSPIRATION_DIR", ".nutmeg-data/inspiration"))
    iso = _normalize_date(date)
    note = InspirationStore(base_dir=base).read(date=iso)
    if note is None:
        typer.echo(f"no inspiration recorded for {iso}")
        raise typer.Exit(code=1)
    typer.echo(
        json.dumps(
            {
                "date": note.date,
                "raw_text": note.raw_text,
                "parsed_tags": {
                    "lean": note.parsed_tags.lean,
                    "conviction": note.parsed_tags.conviction,
                    "focus": note.parsed_tags.focus,
                    "force_psychology": note.parsed_tags.force_psychology,
                    "force_data": note.parsed_tags.force_data,
                },
                "parse_method": note.parse_method,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
