"""API-Football 国际 odds 采集 → jczq-today 的 ``bold_odds`` 形状。

退役背景：jczq-today 的国际欧赔原走 500.com（``fcom500.collect_bold_odds``），但
该抓取近期持续 ``market degraded``。本模块用**有配额但可靠**的 API-Football 顶替成
主源，产出与 ``collect_bold_odds`` **完全相同**的形状 ::

    {match_no: {"match_winner": MarketOdds, "over_under": MarketOdds}}

因此对 tiered 引擎是 drop-in——只换数据源槽位，不动任何选腿逻辑。

对齐：体彩竞彩盘用中文国家队名（荷兰/法国…），API-Football 用英文。本模块：

1. 把每场体彩 ``matchDate``+``matchTime``（北京时间）换算成 API-Football 归档用的
   UTC 日历日（深夜场常差一天）。
2. 用 ``jczq_national_team_aliases.json`` 把中文队名 → API-Football 英文名。
3. 在「按该 UTC 日拉取的全联赛 fixture 池」里按队对匹配（容忍主客翻转）。
4. 命中 fixture → ``/odds`` → 转成 ``MarketOdds``。

**绝不猜测**：别名缺失、或池中无配对 → 该场无信号 + 记录原因，从不模糊匹配、从不
崩（与 fcom500 的优雅降级契约一致）。API-Football 基础 ``/odds`` 不含开赛前 opening
赔率，故 ``opening_odds`` 留空、drift 信号对这些场降级为 0；conflict / dispersion /
§29 gap 照常工作。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from importlib import resources

from nutmeg.data.fcom500 import MarketOdds, _devig
from nutmeg.domain.fixtures import Fixture
from nutmeg.domain.odds import OddsProviderSnapshotFeed

logger = logging.getLogger(__name__)

__all__ = [
    "collect_bold_odds_apifootball",
    "collect_bold_odds_apifootball_live",
    "load_national_team_aliases",
    "merge_bold_odds",
]

_ALIASES_RESOURCE = "jczq_national_team_aliases.json"

# 体彩 JCZQ 标的时间是北京时间（UTC+8，中国无夏令时，固定偏移）。
_BEIJING_UTC_OFFSET_HOURS = 8

# §29 gap 比较 体彩 ttg vs 欧赔大小球——优先取主线 2.5，缺失再退 1.5/3.5。
_OVER_UNDER_LINE_PREFERENCE: tuple[tuple[str, str], ...] = (
    ("totals_2_5", "2.5"),
    ("totals_1_5", "1.5"),
    ("totals_3_5", "3.5"),
)


def _normalize(name: str) -> str:
    """空格无关 + casefold（保留重音与 &，故 Türkiye/Curaçao/Bosnia & Herzegovina
    须按 API-Football 原拼写存别名）。"""
    return "".join((name or "").split()).casefold()


def load_national_team_aliases() -> dict[str, str]:
    """中国体彩国家队中文名 → API-Football 英文名（去掉 ``_`` 注释键）。"""
    raw = json.loads(
        resources.files("nutmeg.data")
        .joinpath(_ALIASES_RESOURCE)
        .read_text(encoding="utf-8")
    )
    return {
        key: str(value)
        for key, value in raw.items()
        if not key.startswith("_") and isinstance(value, str)
    }


def _utc_date(beijing_date: str, beijing_time: str) -> date:
    """把体彩北京时间 ``matchDate``+``matchTime`` 换算成 API-Football 的 UTC 日历日。

    体彩 ``matchDate`` 是北京开球日历日；深夜场（北京 00:00-07:59）的 UTC 日是前一
    天，直接按北京日查会差一天查空。``matchTime`` 缺失/无法解析时不猜小时、保持原
    ``matchDate``（与 ``jczq_match_align`` 的 ``绝不猜测`` 约定一致）。
    """
    if not (beijing_time or "").strip():
        return date.fromisoformat(beijing_date)
    try:
        beijing = datetime.fromisoformat(f"{beijing_date}T{beijing_time.strip()}")
    except ValueError:
        return date.fromisoformat(beijing_date)
    return (beijing - timedelta(hours=_BEIJING_UTC_OFFSET_HOURS)).date()


@dataclass(slots=True, frozen=True)
class _BoardMatch:
    match_no: str
    home_zh: str
    away_zh: str
    utc_date: date


def _board_matches(value: dict, run_date: str) -> list[_BoardMatch]:
    """从 Sporttery ``getMatchCalculatorV1`` 响应抽出当日在售场次（同 bold 引擎口径）。"""
    out: list[_BoardMatch] = []
    for day in value.get("matchInfoList") or []:
        for raw in day.get("subMatchList") or []:
            if str(raw.get("matchStatus") or "").casefold() != "selling":
                continue
            business_date = str(
                raw.get("businessDate") or day.get("businessDate") or ""
            )
            if run_date and business_date and business_date != run_date:
                continue
            home_zh = str(raw.get("homeTeamAbbName") or "")
            away_zh = str(raw.get("awayTeamAbbName") or "")
            if not (home_zh and away_zh):
                continue
            kickoff_date = str(
                raw.get("matchDate") or business_date or run_date or ""
            )
            if not kickoff_date:
                continue
            out.append(
                _BoardMatch(
                    match_no=str(raw.get("matchNumStr") or ""),
                    home_zh=home_zh,
                    away_zh=away_zh,
                    utc_date=_utc_date(kickoff_date, str(raw.get("matchTime") or "")),
                )
            )
    return out


def _resolve(name_zh: str, aliases: dict[str, str]) -> str | None:
    """中文队名 → 英文名；容忍体彩的空格变体。未收录返回 ``None``（绝不猜测）。"""
    if name_zh in aliases:
        return aliases[name_zh]
    target = _normalize(name_zh)
    for zh, en in aliases.items():
        if _normalize(zh) == target:
            return en
    return None


def _find_fixture(
    pool: Iterable[Fixture], home_en: str, away_en: str
) -> tuple[Fixture, bool] | None:
    """在 fixture 池里按队对匹配；返回 ``(fixture, swapped)``，无配对返回 ``None``。

    ``swapped=True`` 表示体彩名义主队是 API-Football 的客队（体彩偶尔把客列为主）。
    """
    home_key = _normalize(home_en)
    away_key = _normalize(away_en)
    for fixture in pool:
        fx_home = _normalize(fixture.home_team)
        fx_away = _normalize(fixture.away_team)
        if fx_home == home_key and fx_away == away_key:
            return (fixture, False)
        if fx_home == away_key and fx_away == home_key:
            return (fixture, True)
    return None


def _avg(values: list[float]) -> float:
    return round(sum(values) / len(values), 4)


def _match_winner_market(
    feed: OddsProviderSnapshotFeed, swapped: bool
) -> MarketOdds | None:
    """API-Football ``match_winner`` 盘口 → ``MarketOdds``（体彩视角，按需翻转主客）。

    每个 outcome 在 ``/odds`` 里是「各家博彩一条报价」；取跨家均赔 + devig。须三路
    （home/draw/away）齐全才生成，否则视作不可用（None）。
    """
    market = feed.markets.get("match_winner")
    if market is None:
        return None
    per_book: dict[str, list[float]] = {}
    for outcome in market.outcomes:
        quotes = [
            q.decimal_odds for q in outcome.bookmaker_quotes if q.decimal_odds > 1.0
        ]
        if quotes:
            per_book[outcome.outcome_key] = quotes
    if not all(per_book.get(k) for k in ("home", "draw", "away")):
        return None
    if swapped:
        per_book = {
            "home": per_book["away"],
            "draw": per_book["draw"],
            "away": per_book["home"],
        }
    odds = {key: _avg(quotes) for key, quotes in per_book.items()}
    return MarketOdds(
        odds=odds,
        fair_probability=_devig(odds),
        independent=True,
        bookmaker_count=max(len(quotes) for quotes in per_book.values()),
        opening_odds={},  # 基础 /odds 无开赛前 opening；drift 对这些场降级为 0
        per_book_odds=per_book,
    )


def _over_under_market(feed: OddsProviderSnapshotFeed) -> MarketOdds | None:
    """API-Football 大小球盘口 → ``MarketOdds``（优先主线 2.5）。over/under 对称、无翻转。"""
    for market_key, line in _OVER_UNDER_LINE_PREFERENCE:
        market = feed.markets.get(market_key)
        if market is None:
            continue
        per_book: dict[str, list[float]] = {}
        for outcome in market.outcomes:
            quotes = [
                q.decimal_odds
                for q in outcome.bookmaker_quotes
                if q.decimal_odds > 1.0
            ]
            if quotes:
                per_book[outcome.outcome_key] = quotes
        if not (per_book.get("over") and per_book.get("under")):
            continue
        odds = {key: _avg(quotes) for key, quotes in per_book.items()}
        return MarketOdds(
            odds=odds,
            fair_probability=_devig(odds),
            independent=True,
            line=line,
            bookmaker_count=max(len(quotes) for quotes in per_book.values()),
            per_book_odds=per_book,
        )
    return None


def collect_bold_odds_apifootball(
    value: dict,
    *,
    run_date: str,
    fixture_fetcher: Callable[[date], Iterable[Fixture]],
    odds_fetcher: Callable[[str], OddsProviderSnapshotFeed],
    aliases: dict[str, str] | None = None,
) -> dict[str, dict[str, MarketOdds]]:
    """采集体彩盘各场的 API-Football 国际欧赔，键到体彩竞彩号。

    ``fixture_fetcher(utc_date)`` 返回该 UTC 日全联赛 fixture（生产包
    ``ApiFootballClient.fetch_fixtures_by_date``）；``odds_fetcher(fixture_id)``
    返回该场 ``/odds``（包 ``fetch_fixture_odds``）。两个 fetcher 注入以便测试无网络。

    返回 ``{match_no: {"match_winner": MarketOdds, "over_under": MarketOdds}}``；
    任一场对齐失败/无盘口/抓取异常仅令该场缺席——从不崩。
    """
    resolved_aliases = aliases if aliases is not None else load_national_team_aliases()
    board = _board_matches(value, run_date)
    if not board:
        return {}

    pool_by_date: dict[date, list[Fixture]] = {}

    def _pool_for(query_date: date) -> list[Fixture]:
        if query_date not in pool_by_date:
            try:
                pool_by_date[query_date] = list(fixture_fetcher(query_date))
            except Exception:  # noqa: BLE001 — degrade, never crash
                logger.warning(
                    "apifootball-odds: fixtures 抓取失败 @ %s", query_date,
                    exc_info=True,
                )
                pool_by_date[query_date] = []
        return pool_by_date[query_date]

    result: dict[str, dict[str, MarketOdds]] = {}
    for match in board:
        home_en = _resolve(match.home_zh, resolved_aliases)
        away_en = _resolve(match.away_zh, resolved_aliases)
        if home_en is None or away_en is None:
            missing = [
                zh
                for zh, en in ((match.home_zh, home_en), (match.away_zh, away_en))
                if en is None
            ]
            logger.info(
                "apifootball-odds skip %s: 国家队别名缺失 %s（补 jczq_national_team_aliases.json）",
                match.match_no, missing,
            )
            continue
        hit = _find_fixture(_pool_for(match.utc_date), home_en, away_en)
        if hit is None:
            logger.info(
                "apifootball-odds skip %s: UTC %s 池中未找到 %s vs %s",
                match.match_no, match.utc_date, home_en, away_en,
            )
            continue
        fixture, swapped = hit
        try:
            feed = odds_fetcher(fixture.fixture_id)
        except Exception:  # noqa: BLE001 — degrade, never crash
            logger.warning(
                "apifootball-odds: /odds 抓取失败 fixture=%s (%s)",
                fixture.fixture_id, match.match_no, exc_info=True,
            )
            continue
        entry: dict[str, MarketOdds] = {}
        match_winner = _match_winner_market(feed, swapped)
        if match_winner is not None:
            entry["match_winner"] = match_winner
        over_under = _over_under_market(feed)
        if over_under is not None:
            entry["over_under"] = over_under
        if entry:
            logger.info(
                "apifootball-odds %s → fixture=%s (%s vs %s, swapped=%s, markets=%s)",
                match.match_no, fixture.fixture_id, fixture.home_team,
                fixture.away_team, swapped, sorted(entry),
            )
            result[match.match_no] = entry
    return result


def merge_bold_odds(
    primary: dict[str, dict[str, MarketOdds]],
    fallback: dict[str, dict[str, MarketOdds]],
) -> dict[str, dict[str, MarketOdds]]:
    """以 ``primary`` 为准，用 ``fallback`` 补缺失的场/盘口（绝不覆盖 primary）。

    支持「API-Football 主、500.com 备」：API-Football 已覆盖的场/盘口保留；它没盖到
    的（如它无大小球的某场）由 500.com 兜底。
    """
    merged: dict[str, dict[str, MarketOdds]] = {
        match_no: dict(markets) for match_no, markets in primary.items()
    }
    for match_no, markets in fallback.items():
        slot = merged.setdefault(match_no, {})
        for market_key, odds in markets.items():
            slot.setdefault(market_key, odds)
    return merged


def collect_bold_odds_apifootball_live(
    value: dict,
    *,
    run_date: str,
    settings=None,
) -> dict[str, dict[str, MarketOdds]]:
    """生产入口：从 settings 装配真 ``ApiFootballClient`` 并采集。

    无 ``NUTMEG_API_FOOTBALL_KEY`` → 返回空（优雅降级，jczq-today 退 500.com 备源）。
    """
    from nutmeg.config.settings import get_settings
    from nutmeg.data.api_football import ApiFootballClient

    settings = settings or get_settings()
    key = (settings.api_football_key or "").strip()
    if not key:
        logger.info(
            "NUTMEG_API_FOOTBALL_KEY 未配置 — 跳过 API-Football 国际 odds，退 500.com 备源"
        )
        return {}

    client = ApiFootballClient(
        base_url=settings.api_football_base_url, api_key=key
    )
    try:
        return collect_bold_odds_apifootball(
            value,
            run_date=run_date,
            fixture_fetcher=lambda d: client.fetch_fixtures_by_date(d).fixtures,
            odds_fetcher=client.fetch_fixture_odds,
        )
    finally:
        client.close()
