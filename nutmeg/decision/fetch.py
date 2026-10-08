"""fetch — 决策本体数据自取(M2 阶段一,运营自立第一件)。

新 sense 是回放已存快照;抓取现埋在退役中的 jczq-today。这里抽一条薄命令,只复用
**保留模块**的两个 fetch 基元,把当日盘口/欧赔落到 sense_day 读取的同一路径:

  - 体彩盘口 ``fetch_sporttery_value_with_fallback``(decision.market_data)
    → ``<output_dir>/daily/<run_date>/sporttery_markets.json``
  - 国际欧赔 titan007(``collect_euro_odds_live``)
    → ``<output_dir>/daily/<run_date>/bold_odds.json``

落盘一律走保留模块的 ``persist_*_snapshot`` helper,确保与 ``sense_day``
(读 ``load_sporttery_snapshot`` / ``load_bold_odds_snapshot``)字节兼容。
两个 fetcher 可注入替身以便测试/replay 无网络;默认用保留模块真 fetcher。
国际欧赔失败按 jczq-today 惯例优雅降级为体彩-only,从不崩。
"""
from __future__ import annotations

import logging

from nutmeg.data.sporttery_board import selling_rows

logger = logging.getLogger(__name__)


def _default_sporttery_fetcher() -> tuple[dict, str]:
    """生产默认:体彩盘面(sporttery 主源 → 500.com 备源)。返回 ``(value, source)``。"""
    from nutmeg.decision.market_data import (
        fetch_sporttery_value_with_fallback,
    )
    return fetch_sporttery_value_with_fallback()


def _board_match_numbers(value: dict, run_date: str) -> list[tuple[str, str]]:
    """该业务日在售场次 ``(竞彩号, 业务日)``——判断 titan007 是否漏场的分母。

    口径必须与 ``jczq_titan007_odds._board_matches`` 一致:一份 sporttery 快照含
    **多个业务日**,不按 ``businessDate`` 过滤会把次日的场当成今天漏的,白白唤醒备源。
    """
    out: list[tuple[str, str]] = []
    for raw, business_date in selling_rows(value, run_date):
        match_no = str(raw.get("matchNumStr") or "")
        if match_no:
            out.append((match_no, business_date))
    return out


def _default_euro_fetcher(value: dict, run_date: str) -> tuple[dict, dict]:
    """生产默认：titan007 国际欧赔（唯一源）。返回 ``(bold_odds, {竞彩号: 源名})``。

    2026-09-14 换源：API-Football Free 档 8 天回放只覆盖 63/127、且卡在 ~9 场；titan007 同期
    127/127 并带初赔（证据 ``.nutmeg-data/jczq/decision/odds_backfill.md``）。API-Football 随后
    退为默认关的备源，开着时免费额度耗尽、9 月里 429 共 262 次、一场没补上；2026-10-08 删除
    （Jun：「不能正常工作就不要了」）。titan007 早上偶缺的场由 10:00 与 17:15 两次刷新补上。

    血统仍逐场带出：``MarketSnapshot.source`` 进快照 id；历史快照里的 ``apifootball`` 源保持原样。
    """
    from nutmeg.services.jczq_titan007_odds import collect_bold_odds_titan007_live

    odds = collect_bold_odds_titan007_live(value, run_date=run_date)
    missing = [no for no, _ in _board_match_numbers(value, run_date) if no not in odds]
    if missing:
        # 漏场要说话——静默退化成「丢国际锚」正是 2026-08-05 别名事故的形状。
        logger.warning(
            "decision-fetch: titan007 漏 %d 场 %s——这些场暂无国际锚（10:00 / 17:15 刷新再补）",
            len(missing), missing[:5],
        )
    return odds, {match_no: "titan007" for match_no in odds}


collect_euro_odds_live = _default_euro_fetcher
"""公开别名：生产的国际欧赔采集入口（titan007）。"""


def unpack_euro_result(result) -> tuple[dict, dict]:
    """把 euro fetcher 的返回统一成 ``(bold_odds, 血统)``。

    生产 fetcher 回元组;测试/replay 注入的替身回纯 dict——两种都收,免得为了血统
    去改每一处既有替身。纯 dict 时血统为空,调用方回落到默认源名。
    """
    if isinstance(result, tuple):
        return (result[0] or {}), (result[1] or {})
    return (result or {}), {}


def _existing_bold_odds_count(run_date: str, output_dir) -> int:
    """已落 ``bold_odds.json`` 的场数;无文件/坏文件按 0(不挡首次落盘)。"""
    import json
    from pathlib import Path

    path = Path(output_dir) / "daily" / run_date / "bold_odds.json"
    if not path.exists():
        return 0
    try:
        return len(json.loads(path.read_text(encoding="utf-8")) or {})
    except (OSError, ValueError):
        return 0


def fetch_day(
    run_date: str,
    output_dir,
    *,
    sporttery_fetcher=None,
    euro_fetcher=None,
) -> str:
    """抓当日体彩盘口 + 国际欧赔,落到 sense_day 读取的同一目录。返回一行摘要。

    ``sporttery_fetcher()`` → ``(value, source)``;``euro_fetcher(value, run_date)``
    → ``{竞彩号: {market: MarketOdds}}`` 或 ``(同前, {竞彩号: 源名})``。二者默认用
    保留模块真 fetcher,测试/replay 注入替身。国际欧赔抓取异常仅降级(不写
    bold_odds),体彩快照照落。
    """
    from nutmeg.decision.market_data import (
        persist_bold_odds_provenance,
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
    provenance: dict = {}
    try:
        bold_odds, provenance = unpack_euro_result(euro_fetcher(value, run_date))
    except Exception:  # noqa: BLE001 — 国际 odds optional;降级体彩-only,从不崩
        logger.warning(
            "decision-fetch %s: 国际欧赔抓取失败,退体彩-only", run_date,
            exc_info=True,
        )
    if bold_odds:
        previous = _existing_bold_odds_count(run_date, output_dir)
        if len(bold_odds) < previous:
            # 部分降级:本轮拿到的比上一版还少。宁可留旧快照也不覆盖——这是
            # 2026-06「WAF 降级响应覆盖完好快照」的同类死法,只是没空到触发
            # `if bold_odds` 那道门。
            logger.warning(
                "decision-fetch %s: 本轮国际欧赔 %d 场 < 已存 %d 场,拒绝覆盖快照",
                run_date, len(bold_odds), previous,
            )
        else:
            persist_bold_odds_snapshot(run_date, output_dir, bold_odds)
            if provenance:
                persist_bold_odds_provenance(run_date, output_dir, provenance)

    return (
        f"decision-fetch {run_date}: 体彩 {n_matches} 场({source}) "
        f"+ 欧赔 {len(bold_odds)} 场"
    )
