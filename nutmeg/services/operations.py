from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from nutmeg.domain.operations import (
    DailyRunSummary,
    OperationBrief,
    OperationPopularMatch,
    TelegramDispatch,
    TelegramDispatchStatus,
)
from nutmeg.services.popularity import MatchPopularityRanker


class FixtureListService(Protocol):
    def list_upcoming(self, league: str, days: int, demo: bool = False):
        ...


class DailySyncService(Protocol):
    def sync(self, league_codes, days, timezone, past_days=0):
        ...


class DailyValueBoardService(Protocol):
    def build_board(self, *, league: str, days: int, limit: int, min_edge: float):
        ...


class BriefWorkflow(Protocol):
    def run(self, *, fixture_id: str, query: str):
        ...


class TelegramSender(Protocol):
    def send_message(self, *, chat_id: int, text: str):
        ...


class DailyOperatorService:
    def __init__(
        self,
        *,
        fixture_service: FixtureListService,
        popularity_ranker: MatchPopularityRanker,
        value_board_service: DailyValueBoardService,
        sync_service: DailySyncService | None = None,
        workflow: BriefWorkflow | None = None,
        telegram_sender: TelegramSender | None = None,
        telegram_chat_ids: list[int] | None = None,
        timezone: str = 'UTC',
    ) -> None:
        self._fixture_service = fixture_service
        self._popularity_ranker = popularity_ranker
        self._value_board_service = value_board_service
        self._sync_service = sync_service
        self._workflow = workflow
        self._telegram_sender = telegram_sender
        self._telegram_chat_ids = telegram_chat_ids or []
        self._timezone = timezone

    def run(
        self,
        *,
        league: str,
        days: int,
        limit: int,
        query: str,
        dry_run: bool,
        live_sync: bool,
        briefs: bool,
        dispatch_telegram: bool,
    ) -> DailyRunSummary:
        sync_status = 'skipped'
        sync_fixtures = 0
        sync_requests = 0
        if live_sync:
            if self._sync_service is None:
                sync_status = 'config_missing'
            else:
                report = self._sync_service.sync(
                    [league],
                    days,
                    self._timezone,
                    past_days=0,
                )
                sync_status = 'succeeded'
                sync_fixtures = int(getattr(report, 'total_fixtures', 0))
                sync_requests = int(getattr(report, 'total_requests', 0))

        fixtures = self._fixture_service.list_upcoming(league, days, demo=False)
        ranked = self._popularity_ranker.rank(list(fixtures), limit=limit)
        value_board = self._value_board_service.build_board(
            league=league,
            days=days,
            limit=limit,
            min_edge=0.03,
        )
        operation_briefs = self._build_briefs(
            ranked=ranked,
            query=query,
            enabled=briefs,
        )
        message = self._render_dispatch_message(
            league=league,
            popular_matches=[
                OperationPopularMatch(
                    fixture_id=item.fixture.fixture_id,
                    rank=item.rank,
                    home_team=item.fixture.home_team,
                    away_team=item.fixture.away_team,
                    score=item.popularity.score,
                    tier=item.popularity.tier,
                )
                for item in ranked
            ],
            value_count=len(value_board.candidates),
        )
        telegram_dispatch = self._dispatch_telegram(
            enabled=dispatch_telegram,
            dry_run=dry_run,
            message=message,
        )
        return DailyRunSummary(
            league=league,
            days=days,
            generated_at=datetime.now(UTC).replace(microsecond=0),
            dry_run=dry_run,
            live_sync=live_sync,
            sync_status=sync_status,
            sync_fixtures_written=sync_fixtures,
            sync_requests_made=sync_requests,
            fixtures_considered=len(fixtures),
            popular_matches=[
                OperationPopularMatch(
                    fixture_id=item.fixture.fixture_id,
                    rank=item.rank,
                    home_team=item.fixture.home_team,
                    away_team=item.fixture.away_team,
                    score=item.popularity.score,
                    tier=item.popularity.tier,
                )
                for item in ranked
            ],
            value_candidates=value_board.candidates,
            briefs=operation_briefs,
            telegram_dispatch=telegram_dispatch,
        )

    def _build_briefs(self, *, ranked, query: str, enabled: bool) -> list[OperationBrief]:
        if not enabled:
            return [
                OperationBrief(fixture_id=item.fixture.fixture_id, status='skipped')
                for item in ranked
            ]
        if self._workflow is None:
            return [
                OperationBrief(
                    fixture_id=item.fixture.fixture_id,
                    status='failed',
                    error='brief workflow is not configured',
                )
                for item in ranked
            ]
        briefs = []
        for item in ranked:
            result = self._workflow.run(fixture_id=item.fixture.fixture_id, query=query)
            verdict = None
            confidence = None
            if getattr(result, 'analysis', None) is not None:
                verdict = result.analysis.judgment.verdict
                confidence = result.analysis.judgment.confidence
            briefs.append(
                OperationBrief(
                    fixture_id=item.fixture.fixture_id,
                    status=result.status,
                    verdict=verdict,
                    confidence=confidence,
                    error=getattr(result, 'error', None),
                )
            )
        return briefs

    def _dispatch_telegram(
        self,
        *,
        enabled: bool,
        dry_run: bool,
        message: str,
    ) -> TelegramDispatch:
        if not enabled:
            return TelegramDispatch(status=TelegramDispatchStatus.SKIPPED)
        if dry_run:
            return TelegramDispatch(
                status=TelegramDispatchStatus.DRY_RUN,
                message=message,
                chat_ids=self._telegram_chat_ids,
            )
        if self._telegram_sender is None or not self._telegram_chat_ids:
            return TelegramDispatch(
                status=TelegramDispatchStatus.CONFIG_MISSING,
                message=message,
                chat_ids=self._telegram_chat_ids,
            )
        try:
            for chat_id in self._telegram_chat_ids:
                self._telegram_sender.send_message(chat_id=chat_id, text=message)
        except Exception as exc:
            return TelegramDispatch(
                status=TelegramDispatchStatus.FAILED,
                message=message,
                chat_ids=self._telegram_chat_ids,
                error=str(exc),
            )
        return TelegramDispatch(
            status=TelegramDispatchStatus.SENT,
            message=message,
            chat_ids=self._telegram_chat_ids,
        )

    def _render_dispatch_message(
        self,
        *,
        league: str,
        popular_matches: list[OperationPopularMatch],
        value_count: int,
    ) -> str:
        lines = [
            f'Nutmeg daily run: {league}',
            f'popular matches: {len(popular_matches)}',
            f'value candidates: {value_count}',
        ]
        for item in popular_matches[:5]:
            lines.append(
                f"#{item.rank} {item.home_team} vs {item.away_team} "
                f"tier={item.tier} score={item.score}"
            )
        return '\n'.join(lines)
