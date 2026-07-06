"""fetch — 决策本体数据自取(M2 阶段一,运营自立第一件)。

新 sense 是回放已存快照;抓取现埋在退役中的 jczq-today。这里抽一条薄命令,只复用
**保留模块**的两个 fetch 基元,把当日盘口/欧赔落到 sense_day 读取的同一路径:

  - 体彩盘口 ``fetch_sporttery_value_with_fallback``(jczq_market_kernel)
    → ``<output_dir>/daily/<run_date>/sporttery_markets.json``
  - 国际欧赔 ``collect_bold_odds_apifootball``(经生产入口 ``*_live`` 装配真 client)
    → ``<output_dir>/daily/<run_date>/bold_odds.json``

落盘一律走保留模块的 ``persist_*_snapshot`` helper,确保与 ``sense_day``
(读 ``load_sporttery_snapshot`` / ``load_bold_odds_snapshot``)字节兼容。
两个 fetcher 可注入替身以便测试/replay 无网络;默认用保留模块真 fetcher。
国际欧赔失败按 jczq-today 惯例优雅降级为体彩-only,从不崩。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _default_sporttery_fetcher() -> tuple[dict, str]:
    """生产默认:体彩盘面(sporttery 主源 → 500.com 备源)。返回 ``(value, source)``。"""
    from nutmeg.services.jczq_market_kernel import (
        fetch_sporttery_value_with_fallback,
    )
    return fetch_sporttery_value_with_fallback()


def _default_euro_fetcher(value: dict, run_date: str) -> dict:
    """生产默认:API-Football 国际欧赔(``collect_bold_odds_apifootball`` 的生产入口)。

    无 ``NUTMEG_API_FOOTBALL_KEY`` 时该入口返回空 → 只落体彩快照(优雅降级)。
    """
    from nutmeg.services.jczq_apifootball_odds import (
        collect_bold_odds_apifootball_live,
    )
    return collect_bold_odds_apifootball_live(value, run_date=run_date)


def fetch_day(
    run_date: str,
    output_dir,
    *,
    sporttery_fetcher=None,
    euro_fetcher=None,
) -> str:
    """抓当日体彩盘口 + 国际欧赔,落到 sense_day 读取的同一目录。返回一行摘要。

    ``sporttery_fetcher()`` → ``(value, source)``;``euro_fetcher(value, run_date)``
    → ``{竞彩号: {market: MarketOdds}}``。二者默认用保留模块真 fetcher,测试/replay
    注入替身。国际欧赔抓取异常仅降级(不写 bold_odds),体彩快照照落。
    """
    from nutmeg.services.jczq_market_kernel import (
        persist_bold_odds_snapshot,
        persist_sporttery_snapshot,
    )

    if sporttery_fetcher is None:
        sporttery_fetcher = _default_sporttery_fetcher
    if euro_fetcher is None:
        euro_fetcher = _default_euro_fetcher

    value, source = sporttery_fetcher()
    persist_sporttery_snapshot(run_date, output_dir, value)
    n_matches = sum(
        len(day.get("subMatchList") or [])
        for day in (value.get("matchInfoList") or [])
    )

    bold_odds: dict = {}
    try:
        bold_odds = euro_fetcher(value, run_date) or {}
    except Exception:  # noqa: BLE001 — 国际 odds optional;降级体彩-only,从不崩
        logger.warning(
            "decision-fetch %s: 国际欧赔抓取失败,退体彩-only", run_date,
            exc_info=True,
        )
    if bold_odds:
        persist_bold_odds_snapshot(run_date, output_dir, bold_odds)

    return (
        f"decision-fetch {run_date}: 体彩 {n_matches} 场({source}) "
        f"+ 欧赔 {len(bold_odds)} 场"
    )
