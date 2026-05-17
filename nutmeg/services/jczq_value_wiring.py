"""Live wiring for the value/conflict engine in the daily JCZQ brief.

Phase 3 piece 2. Assembles a production ``JczqValueBridge`` from settings:
``ApiFootballFixtureProvider`` (real ``ApiFootballClient``) → ``MatchAligner``
+ a ``ValueBoardService`` → bridge. The CLI calls ``build_jczq_value_bridge``
and hands the result to ``build_brief``.

**Graceful degradation is the contract.** No API-Football key, or any error
constructing the dependency graph, yields ``None`` — the brief then renders
its 赔率冲突点 placeholder. The daily flow must never crash on a missing or
misconfigured value engine.
"""

from __future__ import annotations

import logging
from typing import Callable

from nutmeg.config.catalog import league_code_by_api_football_id
from nutmeg.config.settings import AppSettings
from nutmeg.data.api_football import ApiFootballClient
from nutmeg.services.jczq_match_align import (
    ApiFootballFixtureProvider,
    MatchAligner,
    load_league_aliases,
)
from nutmeg.services.jczq_value_bridge import JczqValueBridge
from nutmeg.services.value import ValueBoardService

logger = logging.getLogger(__name__)

__all__ = ["build_jczq_value_bridge", "season_for_date"]


def season_for_date(run_date: str) -> int:
    """Map a JCZQ run date to an API-Football season year.

    European-league seasons span two calendar years; API-Football labels a
    season by its starting year. A fixture from July onward belongs to the
    season starting that year; a January–June fixture belongs to the season
    that started the previous year.
    """

    year, month, _day = (int(part) for part in run_date.split("-"))
    return year if month >= 7 else year - 1


def build_jczq_value_bridge(
    *,
    settings: AppSettings,
    run_date: str,
    value_service_factory: Callable[[], ValueBoardService] | None = None,
) -> JczqValueBridge | None:
    """Assemble a live ``JczqValueBridge``, or ``None`` for graceful degradation.

    ``value_service_factory`` defers the (DB-backed) ``ValueBoardService``
    construction so it is only built when a key is actually present; the CLI
    passes ``build_value_board_service``-style factory. When the API-Football
    key is missing/blank — or anything in the assembly fails — ``None`` is
    returned and the brief degrades to its placeholder.
    """

    key = (settings.api_football_key or "").strip()
    if not key:
        logger.info(
            "NUTMEG_API_FOOTBALL_KEY not set — value bridge disabled, "
            "brief will render the 赔率冲突点 placeholder"
        )
        return None

    if value_service_factory is None:
        logger.warning("no value_service_factory supplied — value bridge disabled")
        return None

    try:
        league_aliases = load_league_aliases()
        client = ApiFootballClient(
            base_url=settings.api_football_base_url,
            api_key=key,
        )
        fixture_provider = ApiFootballFixtureProvider(
            client=client,
            season=season_for_date(run_date),
            # 用目录正式 code（epl/serie-a/...）标注 fixture，使模型 snapshot 的
            # get_league() 能解析；用中文联赛名会触发 'Unknown league code'。
            league_code_by_id=league_code_by_api_football_id(),
        )
        aligner = MatchAligner(
            fixture_provider=fixture_provider,
            league_aliases=league_aliases,
        )
        value_service = value_service_factory()
        return JczqValueBridge(aligner=aligner, value_service=value_service)
    except Exception:  # noqa: BLE001 — degrade, never crash the daily flow
        logger.warning("value bridge assembly failed — degrading", exc_info=True)
        return None
