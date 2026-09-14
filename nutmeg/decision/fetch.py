"""fetch — 决策本体数据自取(M2 阶段一,运营自立第一件)。

新 sense 是回放已存快照;抓取现埋在退役中的 jczq-today。这里抽一条薄命令,只复用
**保留模块**的两个 fetch 基元,把当日盘口/欧赔落到 sense_day 读取的同一路径:

  - 体彩盘口 ``fetch_sporttery_value_with_fallback``(decision.market_data)
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
    from nutmeg.decision.market_data import (
        fetch_sporttery_value_with_fallback,
    )
    return fetch_sporttery_value_with_fallback()


def _default_euro_fetcher(value: dict, run_date: str) -> tuple[dict, dict]:
    """生产默认:titan007 国际欧赔主源,API-Football 补缺。

    2026-09-14 换源。API-Football Free 档 100 次/天,8 天回放实测覆盖
    63/127(50%),且不管板面多大都卡在 ~9 场;titan007 免费无配额、同期
    127/127(100%),并带初赔(API-Football 基础 ``/odds`` 结构性没有,故 drift
    信号在旧源上恒为 0)。证据见 ``.nutmeg-data/jczq/decision/odds_backfill.md``。

    API-Football 退为备源,补 titan007 本阶段不出的 ``over_under`` 盘口(亚盘/大小球
    住在另外两个 AES 加密端点,属后续阶段)。``merge_bold_odds`` 的语义正是
    primary 优先、fallback 只补缺,绝不覆盖。两源都空 → 只落体彩快照(优雅降级,
    与换源前行为一致)。

    返回 ``(bold_odds, {竞彩号: 源名})``。血统必须单独带出来:合并后单看 bold_odds
    无从知道某场的 ``match_winner`` 是哪个源给的,而 ``MarketSnapshot.source`` 既进
    快照 id、又是 ``anchor``/``day_regime`` 的优先级键——整批贴一个源名等于给判断层
    喂错血统。``merge_bold_odds`` 是 primary 优先,所以 primary 里有的场就是 titan007 的。
    """
    from nutmeg.services.jczq_apifootball_odds import (
        collect_bold_odds_apifootball_live,
        merge_bold_odds,
    )
    from nutmeg.services.jczq_titan007_odds import (
        collect_bold_odds_titan007_live,
    )

    primary = collect_bold_odds_titan007_live(value, run_date=run_date)
    try:
        fallback = collect_bold_odds_apifootball_live(value, run_date=run_date)
    except Exception:  # noqa: BLE001 — 备源失败不拖累主源
        logger.warning(
            "decision-fetch: API-Football 备源失败,仅用 titan007", exc_info=True
        )
        fallback = {}
    merged = merge_bold_odds(primary, fallback)
    provenance = {
        match_no: ("titan007" if match_no in primary else "apifootball")
        for match_no in merged
    }
    return merged, provenance


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


# ---------------------------------------------------------------------------
# 传统足彩(胜负彩/任九)数据自取 — 复用保留的 zucai_source/zucai_odds_source 同步服务
# (M2 决策:这两模块归运营保留,阶段三不删)。落 <issue>-issue.json + <issue>-odds*.json
# 到 sense_zucai 的 _default_loader 读取的同一 zucai_dir,字节兼容。
# ---------------------------------------------------------------------------


def _default_zucai_sync():
    """生产默认:传统足彩赛程同步服务(写 <issue>-issue.json)。"""
    from nutmeg.services.zucai_source import ZucaiSourceSyncService
    return ZucaiSourceSyncService()


def _default_zucai_odds_sync():
    """生产默认:传统足彩赔率同步服务(写 <issue>-odds*.json)。"""
    from nutmeg.services.zucai_odds_source import ZucaiOddsSyncService
    return ZucaiOddsSyncService()


def fetch_zucai(
    issue: str,
    zucai_dir,
    *,
    sync=None,
    odds_sync=None,
    registry_file=None,
    slot: str = "afternoon",
    live_fetch: bool = False,
    schedule_source_url: str | None = None,
    schedule_source_file=None,
    odds_source_url: str | None = None,
    odds_source_file=None,
    run_date: str | None = None,
    captured_at: str | None = None,
) -> str:
    """抓一期传统足彩赛程 + 赔率,落到 sense_zucai 读取的同一目录。返回一行摘要。

    ``sync``/``odds_sync`` 默认用保留模块真同步服务(``ZucaiSourceSyncService`` /
    ``ZucaiOddsSyncService``),测试注入替身不打网。二者各需一个 source(file 或
    url+live_fetch);赛程与赔率来自不同源,故分开配置。落盘:
    ``<zucai_dir>/<issue>-issue.json`` + ``<zucai_dir>/<issue>-odds*.json``
    (slot=afternoon→``-odds.json``,revision→``-odds-revision.json``)。

    赛程(主)失败按同步服务自身校验抛出;赔率(次)失败仅降级(不写赔率、不崩),
    与 decision-fetch 国际欧赔降级同一哲学——单缺赔率不该拖垮整条日循环。
    """
    from pathlib import Path

    if sync is None:
        sync = _default_zucai_sync()
    if odds_sync is None:
        odds_sync = _default_zucai_odds_sync()
    if registry_file is None:
        registry_file = Path(zucai_dir) / "issues.json"

    sched_result = sync.sync(
        source_file=schedule_source_file,
        source_url=schedule_source_url,
        live_fetch=live_fetch,
        run_date=run_date,
        output_dir=zucai_dir,
        registry_file=registry_file,
    )
    n_issues = getattr(sched_result, "parsed_count", 0)

    n_odds = 0
    try:
        odds_result = odds_sync.sync(
            source_file=odds_source_file,
            source_url=odds_source_url,
            live_fetch=live_fetch,
            issue_id=issue,
            slot=slot,
            captured_at=captured_at,
            output_dir=zucai_dir,
            registry_file=registry_file,
        )
        n_odds = getattr(odds_result, "parsed_count", 0)
    except Exception:  # noqa: BLE001 — 赔率槽 optional;降级不崩(同 decision-fetch 欧赔)
        logger.warning(
            "decision-fetch-zucai %s: 赔率同步失败(slot=%s),仅落赛程", issue, slot,
            exc_info=True,
        )

    return (
        f"decision-fetch-zucai {issue}: 期表 {n_issues} 期 "
        f"+ 赔率 {n_odds} 行(slot={slot})"
    )
