"""足彩每日流程的价值/冲突引擎接线（Phase 3c）。

从 settings 组装一个生产用 ``ZucaiValueBridge``：``ApiFootballFixtureProvider``
（真 ``ApiFootballClient``）→ 复用 JCZQ 的 ``MatchAligner`` + 别名表 + 一个
``ValueBoardService`` → 桥。CLI 的 ``zucai-renjiu-daily`` 调用
``build_zucai_value_bridge`` 并把结果交给 ``ZucaiRenjiuDailyService.build_report``。

**优雅降级是契约**。没有 API-Football key、或组装依赖图时任何报错，都返回
``None``——日报随后照常渲染，只是没有逐场冲突注解。足彩每日流程绝不能因价值引擎
缺失或配置错误而崩溃。
"""

from __future__ import annotations

import logging
from typing import Callable

from nutmeg.config.settings import AppSettings
from nutmeg.data.api_football import ApiFootballClient
from nutmeg.services.jczq_match_align import (
    ApiFootballFixtureProvider,
    MatchAligner,
    load_league_aliases,
)
from nutmeg.services.jczq_value_wiring import season_for_date
from nutmeg.services.value import ValueBoardService
from nutmeg.services.zucai_value_bridge import ZucaiValueBridge

logger = logging.getLogger(__name__)

__all__ = ["build_zucai_value_bridge"]


def build_zucai_value_bridge(
    *,
    settings: AppSettings,
    run_date: str,
    value_service_factory: Callable[[], ValueBoardService] | None = None,
) -> ZucaiValueBridge | None:
    """组装一个生产 ``ZucaiValueBridge``，或返回 ``None`` 以优雅降级。

    ``value_service_factory`` 延迟构造（DB 支撑的）``ValueBoardService``，只在
    确有 key 时才构造。API-Football key 缺失/为空——或组装过程任意一步失败——返回
    ``None``，日报降级到无冲突注解。
    """

    key = (settings.api_football_key or "").strip()
    if not key:
        logger.info(
            "NUTMEG_API_FOOTBALL_KEY 未设置 — 足彩价值桥禁用，日报将无逐场冲突注解"
        )
        return None

    if value_service_factory is None:
        logger.warning("未提供 value_service_factory — 足彩价值桥禁用")
        return None

    try:
        league_aliases = load_league_aliases()
        league_code_by_id = {
            league_id: code for code, league_id in league_aliases.items()
        }
        client = ApiFootballClient(
            base_url=settings.api_football_base_url,
            api_key=key,
        )
        fixture_provider = ApiFootballFixtureProvider(
            client=client,
            season=season_for_date(run_date),
            league_code_by_id=league_code_by_id,
        )
        aligner = MatchAligner(
            fixture_provider=fixture_provider,
            league_aliases=league_aliases,
        )
        value_service = value_service_factory()
        return ZucaiValueBridge(aligner=aligner, value_service=value_service)
    except Exception:  # noqa: BLE001 — degrade, never crash the daily flow
        logger.warning("足彩价值桥组装失败 — 降级", exc_info=True)
        return None
