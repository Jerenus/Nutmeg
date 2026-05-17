"""JCZQ ↔ API-Football 比赛对齐。

体彩竞彩足球（JCZQ）每日系统用中国体彩的 ``周六NNN`` 编号 + 中文队名标识比赛；
价值引擎（``ValueBoardService``）用 API-Football 的 ``fixture_id`` 标识。两套系统
互不相通，本模块是桥梁：

    JCZQ 比赛（周六NNN + 中文主客 + 日期 + 联赛）
        │  联赛别名 → API-Football league_id
        │  /fixtures?league=&date=  → 当日该联赛全部 fixture
        │  球队别名 → API-Football 英文队名 → 在 fixture 列表里配对
        ▼
    API-Football fixture_id

设计原则：
- **绝不猜测**。联赛或球队任一别名缺失 → 该场无信号 + 记录原因，不做模糊匹配。
- 测试用 fixture 注入（``FixtureProvider`` 协议），生产用真网；本模块自身不发网络请求。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from importlib import resources
from typing import Protocol

from nutmeg.domain.fixtures import Fixture
from nutmeg.domain.jczq_daily import JczqDailyMatch

logger = logging.getLogger(__name__)

_LEAGUE_ALIASES_RESOURCE = "jczq_league_aliases.json"
_TEAM_ALIASES_RESOURCE = "jczq_team_aliases.json"


def _strip_comment(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if not key.startswith("_")}


def load_league_aliases() -> dict[str, int]:
    """中国体彩联赛缩写 → API-Football league_id。"""
    raw = json.loads(
        resources.files("nutmeg.data")
        .joinpath(_LEAGUE_ALIASES_RESOURCE)
        .read_text(encoding="utf-8")
    )
    return {key: int(value) for key, value in _strip_comment(raw).items()}


def load_team_aliases() -> dict[str, dict[str, str]]:
    """{联赛: {中文队名: API-Football 英文队名}}。"""
    raw = json.loads(
        resources.files("nutmeg.data")
        .joinpath(_TEAM_ALIASES_RESOURCE)
        .read_text(encoding="utf-8")
    )
    return {
        league: dict(teams)
        for league, teams in _strip_comment(raw).items()
        if isinstance(teams, dict)
    }


def _normalize(name: str) -> str:
    return "".join((name or "").split()).casefold()


# 体彩 JCZQ 标的时间是北京时间（UTC+8，中国无夏令时，固定偏移）。
_BEIJING_UTC_OFFSET_HOURS = 8


def _utc_query_date(match_date: str, match_time: str) -> str:
    """把 JCZQ 的北京时间 ``match_date``+``match_time`` 换算成 API-Football 归档用的
    UTC 日历日。

    API-Football 按 UTC 给 fixture 归档；体彩"周日"票里有大量北京 00:00-07:59 开球
    的深夜场，其 UTC 日历日是前一天——直接按北京 ``match_date`` 查会差一天、查空。
    ``match_time`` 缺失或无法解析时退回原 ``match_date``。
    """
    try:
        beijing = datetime.fromisoformat(f"{match_date}T{(match_time or '').strip()}")
    except ValueError:
        return match_date
    return (beijing - timedelta(hours=_BEIJING_UTC_OFFSET_HOURS)).date().isoformat()


@dataclass(slots=True, frozen=True)
class MatchAlignment:
    """一个 JCZQ 比赛的对齐结果。

    ``matched`` 为 ``False`` 时 ``fixture_id``/``fixture`` 为 ``None``，``reason``
    说明为何无信号（联赛未收录 / 球队未收录 / 当日无 fixture）。
    """

    match_no: str
    league: str
    home_team: str
    away_team: str
    matched: bool
    fixture_id: str | None = None
    fixture: Fixture | None = None
    orientation_swapped: bool = False
    reason: str | None = None


class FixtureProvider(Protocol):
    """按 (league_id, date) 返回 API-Football fixture 列表。

    生产实现包一个真 ``ApiFootballClient`` 调用；测试注入假实现，无网络。
    """

    def fixtures_for(self, *, league_id: int, date: str) -> list[Fixture]: ...


class MatchAligner:
    def __init__(
        self,
        *,
        fixture_provider: FixtureProvider,
        league_aliases: dict[str, int] | None = None,
        team_aliases: dict[str, dict[str, str]] | None = None,
    ) -> None:
        self._fixture_provider = fixture_provider
        self._league_aliases = league_aliases or load_league_aliases()
        self._team_aliases = team_aliases or load_team_aliases()
        # (league_id, date) → fixtures，同一天同联赛只查一次。
        self._fixture_cache: dict[tuple[int, str], list[Fixture]] = {}

    def align_day(self, matches: list[JczqDailyMatch]) -> list[MatchAlignment]:
        """对齐一整天的 JCZQ 比赛，每场一个结果（顺序与输入一致）。"""
        return [self.align(match) for match in matches]

    def align(self, match: JczqDailyMatch) -> MatchAlignment:
        league_id = self._league_aliases.get(match.league)
        if league_id is None:
            reason = f"联赛 '{match.league}' 未收录于 jczq_league_aliases.json"
            logger.info("align skip %s: %s", match.match_no, reason)
            return self._unmatched(match, reason)

        team_table = self._team_aliases.get(match.league, {})
        home_en = self._lookup_team(team_table, match.home_team)
        away_en = self._lookup_team(team_table, match.away_team)
        missing = [
            zh
            for zh, en in ((match.home_team, home_en), (match.away_team, away_en))
            if en is None
        ]
        if missing:
            reason = (
                f"球队 {missing} 未收录于 jczq_team_aliases.json['{match.league}']"
            )
            logger.info("align skip %s: %s", match.match_no, reason)
            return self._unmatched(match, reason)

        # match_time 是可选的鸭子类型字段（JczqDailyMatch 有；足彩 _AlignableMatch
        # 适配器无开球时间）——缺失时 _utc_query_date 自动退回原 match_date。
        query_date = _utc_query_date(
            match.match_date, getattr(match, "match_time", "")
        )
        fixtures = self._fixtures_for(league_id, query_date)
        if not fixtures:
            reason = (
                f"API-Football 当日（{query_date} UTC）联赛 {league_id} 无 fixture"
            )
            logger.info("align skip %s: %s", match.match_no, reason)
            return self._unmatched(match, reason)

        assert home_en is not None and away_en is not None
        hit = self._find_fixture(fixtures, home_en, away_en)
        if hit is None:
            reason = (
                f"当日 fixture 列表里未找到 {home_en} vs {away_en} 的配对"
            )
            logger.info("align skip %s: %s", match.match_no, reason)
            return self._unmatched(match, reason)

        fixture, swapped = hit
        logger.info(
            "align %s → fixture_id=%s (%s vs %s, swapped=%s)",
            match.match_no,
            fixture.fixture_id,
            fixture.home_team,
            fixture.away_team,
            swapped,
        )
        return MatchAlignment(
            match_no=match.match_no,
            league=match.league,
            home_team=match.home_team,
            away_team=match.away_team,
            matched=True,
            fixture_id=fixture.fixture_id,
            fixture=fixture,
            orientation_swapped=swapped,
            reason=None,
        )

    def _lookup_team(
        self, team_table: dict[str, str], chinese_name: str
    ) -> str | None:
        if chinese_name in team_table:
            return team_table[chinese_name]
        # 容忍体彩队名的空格变体。
        normalized = _normalize(chinese_name)
        for zh, en in team_table.items():
            if _normalize(zh) == normalized:
                return en
        return None

    def _fixtures_for(self, league_id: int, date: str) -> list[Fixture]:
        cache_key = (league_id, date)
        if cache_key not in self._fixture_cache:
            self._fixture_cache[cache_key] = list(
                self._fixture_provider.fixtures_for(league_id=league_id, date=date)
            )
        return self._fixture_cache[cache_key]

    def _find_fixture(
        self, fixtures: list[Fixture], home_en: str, away_en: str
    ) -> tuple[Fixture, bool] | None:
        home_key = _normalize(home_en)
        away_key = _normalize(away_en)
        for fixture in fixtures:
            fx_home = _normalize(fixture.home_team)
            fx_away = _normalize(fixture.away_team)
            if fx_home == home_key and fx_away == away_key:
                return (fixture, False)
            if fx_home == away_key and fx_away == home_key:
                # 体彩偶尔把名义客队列为主队；按队对匹配并标记朝向翻转。
                return (fixture, True)
        return None

    def _unmatched(self, match: JczqDailyMatch, reason: str) -> MatchAlignment:
        return MatchAlignment(
            match_no=match.match_no,
            league=match.league,
            home_team=match.home_team,
            away_team=match.away_team,
            matched=False,
            reason=reason,
        )


class ApiFootballFixtureProvider:
    """生产 ``FixtureProvider``：包 ``ApiFootballClient.fetch_upcoming_fixtures``。

    用 ``date`` 作为单日 ``from``/``to`` 窗口查询某联赛当天 fixture。``league_code``
    由别名表反查（仅作 ``Fixture.league_code`` 标签用，可缺省）。生产专用——测试
    应注入假 ``FixtureProvider``，本类不在测试中实例化以避免真网络。
    """

    def __init__(
        self,
        *,
        client,
        season: int,
        league_code_by_id: dict[int, str] | None = None,
        timezone: str = "UTC",
    ) -> None:
        self._client = client
        self._season = season
        self._league_code_by_id = league_code_by_id or {}
        self._timezone = timezone

    def fixtures_for(self, *, league_id: int, date: str) -> list[Fixture]:
        from datetime import date as _date

        day = _date.fromisoformat(date)
        batch = self._client.fetch_upcoming_fixtures(
            league_code=self._league_code_by_id.get(league_id, str(league_id)),
            league_id=league_id,
            season=self._season,
            date_from=day,
            date_to=day,
            timezone=self._timezone,
        )
        return list(batch.fixtures)
