"""单测 ``jczq_apifootball_odds`` —— 体彩盘 → API-Football 欧赔采集、对齐、降级。

全部注入假 fetcher，无网络。验证：中文→英文对齐 + 主客翻转、UTC 跨日、均赔+devig、
别名/池缺失优雅降级、merge 主备语义。
"""

from __future__ import annotations

from datetime import UTC, datetime

from nutmeg.data.fcom500 import MarketOdds
from nutmeg.domain.fixtures import Fixture, FixtureStatus
from nutmeg.domain.odds import (
    BookmakerQuote,
    MarketOddsSnapshot,
    OddsProviderSnapshotFeed,
    OutcomeOddsSnapshot,
)
from nutmeg.services.jczq_apifootball_odds import (
    _utc_date,
    collect_bold_odds_apifootball,
    load_national_team_aliases,
    merge_bold_odds,
)


def _fixture(fid: str, home: str, away: str, kickoff: str) -> Fixture:
    return Fixture(
        fixture_id=fid,
        league_code="Friendlies",
        provider_league_id=10,
        season=2026,
        kickoff_at=datetime.fromisoformat(kickoff).astimezone(UTC),
        home_team_id=None,
        away_team_id=None,
        home_team=home,
        away_team=away,
        source="api-football",
        status=FixtureStatus.SCHEDULED,
        status_short="NS",
    )


def _quotes(market_id: int, value: str, odds: list[float]) -> list[BookmakerQuote]:
    return [
        BookmakerQuote(
            bookmaker_id=i,
            bookmaker_name=f"book{i}",
            market_id=market_id,
            market_name="m",
            selection_value=value,
            decimal_odds=o,
            source="api-football",
        )
        for i, o in enumerate(odds)
    ]


def _winner_feed(
    home: list[float], draw: list[float], away: list[float]
) -> OddsProviderSnapshotFeed:
    market = MarketOddsSnapshot(
        market_key="match_winner",
        market_name="Match Winner",
        status="available",
        line=None,
        source_market_ids=[1],
        outcomes=[
            OutcomeOddsSnapshot("home", "Home", _quotes(1, "Home", home)),
            OutcomeOddsSnapshot("draw", "Draw", _quotes(1, "Draw", draw)),
            OutcomeOddsSnapshot("away", "Away", _quotes(1, "Away", away)),
        ],
    )
    return OddsProviderSnapshotFeed(
        provider="api-football",
        updated_at=None,
        bookmaker_count=max(len(home), len(draw), len(away)),
        markets={"match_winner": market},
    )


def _board(home_zh: str, away_zh: str, *, match_date: str, match_time: str) -> dict:
    return {
        "matchInfoList": [
            {
                "businessDate": "2026-06-08",
                "subMatchList": [
                    {
                        "matchStatus": "Selling",
                        "businessDate": "2026-06-08",
                        "matchNumStr": "周一201",
                        "matchDate": match_date,
                        "matchTime": match_time,
                        "homeTeamAbbName": home_zh,
                        "awayTeamAbbName": away_zh,
                    }
                ],
            }
        ]
    }


# --- UTC 跨日 -------------------------------------------------------------


def test_utc_date_late_night_rolls_back_a_day():
    # 北京 2026-06-09 02:45 → UTC 2026-06-08 18:45 → 查 06-08
    assert _utc_date("2026-06-09", "02:45:00").isoformat() == "2026-06-08"


def test_utc_date_daytime_same_day():
    # 北京 2026-06-09 10:00 → UTC 2026-06-09 02:00 → 查 06-09
    assert _utc_date("2026-06-09", "10:00:00").isoformat() == "2026-06-09"


def test_utc_date_missing_time_falls_back():
    assert _utc_date("2026-06-09", "").isoformat() == "2026-06-09"


# --- 对齐 + 转换 ----------------------------------------------------------


def test_aligns_and_collects_match_winner():
    value = _board("荷兰", "乌兹别克", match_date="2026-06-09", match_time="02:45:00")
    fixtures = {
        "2026-06-08": [
            _fixture("1544812", "Netherlands", "Uzbekistan", "2026-06-08T18:45:00+00:00")
        ]
    }
    feeds = {"1544812": _winner_feed([1.26, 1.24], [5.25, 5.0], [11.5, 12.0])}

    result = collect_bold_odds_apifootball(
        value,
        run_date="2026-06-08",
        fixture_fetcher=lambda d: fixtures.get(d.isoformat(), []),
        odds_fetcher=lambda fid: feeds[fid],
    )

    assert "周一201" in result
    mw = result["周一201"]["match_winner"]
    assert isinstance(mw, MarketOdds)
    assert mw.independent is True
    assert mw.odds["home"] == 1.25  # (1.26+1.24)/2
    assert mw.opening_odds == {}  # 基础 /odds 无开盘价
    # devig 概率和为 1
    assert abs(sum(mw.fair_probability.values()) - 1.0) < 1e-6
    assert mw.fair_probability["home"] > mw.fair_probability["away"]


def test_orientation_swap_preserves_sporttery_perspective():
    # 体彩名义主队=荷兰，但 API-Football 把荷兰列为客队 → 须翻转
    value = _board("荷兰", "乌兹别克", match_date="2026-06-09", match_time="02:45:00")
    fixtures = {
        "2026-06-08": [
            _fixture("X", "Uzbekistan", "Netherlands", "2026-06-08T18:45:00+00:00")
        ]
    }
    # feed 里 home=乌兹别克(=4.0)、away=荷兰(=1.3)；翻转后体彩视角 home(荷兰)应=1.3
    feeds = {"X": _winner_feed([4.0], [3.5], [1.3])}

    result = collect_bold_odds_apifootball(
        value,
        run_date="2026-06-08",
        fixture_fetcher=lambda d: fixtures.get(d.isoformat(), []),
        odds_fetcher=lambda fid: feeds[fid],
    )
    mw = result["周一201"]["match_winner"]
    assert mw.odds["home"] == 1.3
    assert mw.odds["away"] == 4.0


# --- 优雅降级 -------------------------------------------------------------


def test_missing_alias_degrades_silently():
    value = _board("火星队", "月球队", match_date="2026-06-09", match_time="02:45:00")
    result = collect_bold_odds_apifootball(
        value,
        run_date="2026-06-08",
        fixture_fetcher=lambda d: [],
        odds_fetcher=lambda fid: _winner_feed([2], [3], [4]),
    )
    assert result == {}


def test_no_fixture_in_pool_degrades_silently():
    value = _board("荷兰", "乌兹别克", match_date="2026-06-09", match_time="02:45:00")
    result = collect_bold_odds_apifootball(
        value,
        run_date="2026-06-08",
        fixture_fetcher=lambda d: [],  # 池空
        odds_fetcher=lambda fid: _winner_feed([2], [3], [4]),
    )
    assert result == {}


def test_odds_fetch_exception_degrades_silently():
    value = _board("荷兰", "乌兹别克", match_date="2026-06-09", match_time="02:45:00")
    fixtures = {
        "2026-06-08": [
            _fixture("1544812", "Netherlands", "Uzbekistan", "2026-06-08T18:45:00+00:00")
        ]
    }

    def _boom(fid):
        raise RuntimeError("429 rate limit")

    result = collect_bold_odds_apifootball(
        value,
        run_date="2026-06-08",
        fixture_fetcher=lambda d: fixtures.get(d.isoformat(), []),
        odds_fetcher=_boom,
    )
    assert result == {}


def test_incomplete_winner_market_skipped():
    # 只有 home/draw，无 away → 不可用
    value = _board("荷兰", "乌兹别克", match_date="2026-06-09", match_time="02:45:00")
    fixtures = {
        "2026-06-08": [
            _fixture("F", "Netherlands", "Uzbekistan", "2026-06-08T18:45:00+00:00")
        ]
    }
    partial = OddsProviderSnapshotFeed(
        provider="api-football",
        updated_at=None,
        bookmaker_count=1,
        markets={
            "match_winner": MarketOddsSnapshot(
                "match_winner", "Match Winner", "available", None, [1],
                [
                    OutcomeOddsSnapshot("home", "Home", _quotes(1, "Home", [1.3])),
                    OutcomeOddsSnapshot("draw", "Draw", _quotes(1, "Draw", [4.0])),
                ],
            )
        },
    )
    result = collect_bold_odds_apifootball(
        value,
        run_date="2026-06-08",
        fixture_fetcher=lambda d: fixtures.get(d.isoformat(), []),
        odds_fetcher=lambda fid: partial,
    )
    assert result == {}


# --- merge 主备 -----------------------------------------------------------


def _mo(home: float) -> MarketOdds:
    odds = {"home": home, "draw": 3.4, "away": 3.0}
    return MarketOdds(odds=odds, fair_probability={}, independent=True)


def test_merge_prefers_primary_fills_fallback():
    primary = {"周一201": {"match_winner": _mo(1.25)}}
    fallback = {
        "周一201": {"match_winner": _mo(9.99), "over_under": _mo(1.9)},
        "周一203": {"match_winner": _mo(2.1)},
    }
    merged = merge_bold_odds(primary, fallback)
    # primary 的 match_winner 不被覆盖
    assert merged["周一201"]["match_winner"].odds["home"] == 1.25
    # fallback 补上 primary 缺失的 over_under
    assert merged["周一201"]["over_under"].odds["home"] == 1.9
    # fallback 补上 primary 没有的整场
    assert merged["周一203"]["match_winner"].odds["home"] == 2.1


def test_merge_empty_primary_returns_fallback():
    fallback = {"周一201": {"match_winner": _mo(2.0)}}
    assert merge_bold_odds({}, fallback) == fallback


# --- 别名表 ----------------------------------------------------------------


def test_alias_table_covers_todays_board_and_strips_comment():
    aliases = load_national_team_aliases()
    assert "_comment" not in aliases
    for zh, en in (
        ("荷兰", "Netherlands"),
        ("乌兹别克", "Uzbekistan"),
        ("法国", "France"),
        ("北爱尔兰", "Northern Ireland"),
        ("秘鲁", "Peru"),
        ("西班牙", "Spain"),
    ):
        assert aliases[zh] == en


# --- 俱乐部别名（欧战资格赛/联赛）------------------------------------------


def test_resolves_club_alias_and_collects():
    # 俱乐部赛(欧罗巴)：体彩中文俱乐部名 → API-Football 英文名 → 采集。
    # 默认(不显式传 aliases)即应覆盖俱乐部，证明国家队+俱乐部合并生效。
    value = _board("伏伊伏丁", "费伦茨", match_date="2026-06-09", match_time="02:45:00")
    fixtures = {
        "2026-06-08": [
            _fixture("F1", "Vojvodina", "Ferencvarosi TC", "2026-06-08T18:45:00+00:00")
        ]
    }
    feeds = {"F1": _winner_feed([3.1], [3.3], [2.0])}

    result = collect_bold_odds_apifootball(
        value,
        run_date="2026-06-08",
        fixture_fetcher=lambda d: fixtures.get(d.isoformat(), []),
        odds_fetcher=lambda fid: feeds[fid],
    )

    assert "周一201" in result
    assert result["周一201"]["match_winner"].odds["away"] == 2.0


def test_load_club_team_aliases_strips_comment_and_covers_board():
    from nutmeg.services.jczq_apifootball_odds import load_club_team_aliases

    aliases = load_club_team_aliases()
    assert "_comment" not in aliases
    for zh, en in (
        ("伏伊伏丁", "Vojvodina"),
        ("费伦茨", "Ferencvarosi TC"),
        ("索陆军", "CSKA Sofia"),
        ("德里城", "Derry City"),
        ("斯海杜克", "HNK Hajduk Split"),
        ("日利纳", "Žilina"),
    ):
        assert aliases[zh] == en


def test_load_team_aliases_merges_national_and_club():
    from nutmeg.services.jczq_apifootball_odds import load_team_aliases

    merged = load_team_aliases()
    assert "_comment" not in merged
    assert merged["法国"] == "France"  # 国家队
    assert merged["索陆军"] == "CSKA Sofia"  # 俱乐部
