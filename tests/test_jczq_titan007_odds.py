"""单测 ``jczq_titan007_odds`` —— 竞彩号对齐、开球守卫、书目筛选、MarketOdds 组装。

全部注入假 fetcher，无网络。
"""

from __future__ import annotations

from datetime import datetime

import pytest

from nutmeg.data.titan007 import Titan007BoardRow, Titan007BookQuote, Titan007ParseError
from nutmeg.services.jczq_titan007_odds import (
    ALL_BOOKS,
    SHARP_BOOKS,
    collect_bold_odds_titan007,
)


def _sporttery(*rows: tuple[str, str, str, str, str]) -> dict:
    """构造 getMatchCalculatorV1 形状：(竞彩号, 主, 客, matchDate, matchTime)。"""
    return {
        "matchInfoList": [
            {
                "businessDate": "2026-09-14",
                "subMatchList": [
                    {
                        "matchNumStr": no,
                        "homeTeamAbbName": home,
                        "awayTeamAbbName": away,
                        "matchDate": date,
                        "matchTime": time,
                        "matchStatus": "Selling",
                        "businessDate": "2026-09-14",
                    }
                    for no, home, away, date, time in rows
                ],
            }
        ]
    }


def _board_row(no: str, mid: str, kickoff: str) -> Titan007BoardRow:
    return Titan007BoardRow(
        match_id=mid,
        match_no=no,
        kickoff=datetime.fromisoformat(kickoff),
        home_names=("主队",),
        away_names=("客队",),
    )


def _quote(cid: str, name: str, opening: list[float], current: list[float]):
    keys = ("home", "draw", "away")
    return Titan007BookQuote(
        company_id=cid,
        company_name=name,
        opening=dict(zip(keys, opening, strict=True)),
        current=dict(zip(keys, current, strict=True)),
        updated_at=datetime(2026, 9, 13, 23, 28),
    )


# 锐盘 3 家（恰好触到 _MIN_CONSENSUS_BOOKS）+ 2 家必排除 + 1 家噪声盘。
_QUOTES = [
    _quote("1129", "Lottery Official", [1.55, 3.65, 4.75], [1.55, 3.65, 4.75]),
    _quote("432", "HK Jockey Club", [1.55, 3.6, 4.7], [1.55, 3.6, 4.7]),
    _quote("177", "Pinnacle", [2.0, 3.4, 3.6], [1.7, 3.8, 5.0]),
    _quote("545", "Crown", [1.8, 3.6, 4.4], [1.8, 3.6, 4.4]),
    _quote("281", "Bet 365", [1.9, 3.5, 4.0], [1.75, 3.7, 4.6]),
    _quote("9999", "Rodeoslot", [9.0, 9.0, 9.0], [9.0, 9.0, 9.0]),
]


def test_aligns_by_jc_number_without_any_alias_table():
    """竞彩号是板面自带的权威键——不经任何中文→英文别名。"""
    value = _sporttery(("周一002", "国际图尔", "瓦萨", "2026-09-14", "23:00:00"))
    out = collect_bold_odds_titan007(
        value,
        run_date="2026-09-14",
        board_fetcher=lambda: [_board_row("周一002", "3085206", "2026-09-14T23:00:00")],
        odds_fetcher=lambda mid: _QUOTES,
    )
    assert set(out) == {"周一002"}
    assert "match_winner" in out["周一002"]


def test_excludes_lottery_official_from_the_international_consensus():
    """竞彩官方就是体彩盘本身；混进来会让『国际 vs 体彩』变成体彩跟自己比。"""
    value = _sporttery(("周一002", "国际图尔", "瓦萨", "2026-09-14", "23:00:00"))
    out = collect_bold_odds_titan007(
        value,
        run_date="2026-09-14",
        board_fetcher=lambda: [_board_row("周一002", "3085206", "2026-09-14T23:00:00")],
        odds_fetcher=lambda mid: _QUOTES,
        books=SHARP_BOOKS,
    )
    market = out["周一002"]["match_winner"]
    # 锐盘白名单只留 Pinnacle + Crown + Bet365；竞彩官方/香港马会/噪声盘全落选
    assert market.bookmaker_count == 3
    assert market.odds["home"] == pytest.approx(1.75, abs=1e-4)  # (1.7+1.8+1.75)/3


def test_populates_opening_odds_the_signal_apifootball_could_never_give():
    value = _sporttery(("周一002", "国际图尔", "瓦萨", "2026-09-14", "23:00:00"))
    out = collect_bold_odds_titan007(
        value,
        run_date="2026-09-14",
        board_fetcher=lambda: [_board_row("周一002", "3085206", "2026-09-14T23:00:00")],
        odds_fetcher=lambda mid: _QUOTES,
        books=SHARP_BOOKS,
    )
    market = out["周一002"]["match_winner"]
    assert market.opening_odds["home"] == pytest.approx(1.9, abs=1e-4)  # (2.0+1.8+1.9)/3
    assert market.opening_odds != market.odds  # drift 不再恒为 0


def test_all_books_mode_keeps_the_noise_but_still_drops_the_excluded():
    value = _sporttery(("周一002", "国际图尔", "瓦萨", "2026-09-14", "23:00:00"))
    out = collect_bold_odds_titan007(
        value,
        run_date="2026-09-14",
        board_fetcher=lambda: [_board_row("周一002", "3085206", "2026-09-14T23:00:00")],
        odds_fetcher=lambda mid: _QUOTES,
        books=ALL_BOOKS,
    )
    # 6 家里排除竞彩官方 + 香港马会，剩 Pinnacle/Crown/Bet365/Rodeoslot
    assert out["周一002"]["match_winner"].bookmaker_count == 4


def test_kickoff_mismatch_skips_the_match():
    """竞彩号每周复用；开球时间不符 = 对到了别的一期，宁可丢场不可错配。"""
    value = _sporttery(("周一002", "国际图尔", "瓦萨", "2026-09-14", "23:00:00"))
    out = collect_bold_odds_titan007(
        value,
        run_date="2026-09-14",
        board_fetcher=lambda: [_board_row("周一002", "3085206", "2026-09-07T23:00:00")],
        odds_fetcher=lambda mid: _QUOTES,
    )
    assert out == {}


def test_match_absent_from_titan_board_degrades_silently():
    value = _sporttery(("周一002", "国际图尔", "瓦萨", "2026-09-14", "23:00:00"))
    out = collect_bold_odds_titan007(
        value,
        run_date="2026-09-14",
        board_fetcher=lambda: [],
        odds_fetcher=lambda mid: _QUOTES,
    )
    assert out == {}


def test_per_match_odds_failure_degrades_only_that_match():
    value = _sporttery(
        ("周一002", "国际图尔", "瓦萨", "2026-09-14", "23:00:00"),
        ("周一003", "科莫", "帕尔马", "2026-09-15", "00:30:00"),
    )

    def flaky(match_id: str):
        if match_id == "3085206":
            raise Titan007ParseError("degraded")
        return _QUOTES

    out = collect_bold_odds_titan007(
        value,
        run_date="2026-09-14",
        board_fetcher=lambda: [
            _board_row("周一002", "3085206", "2026-09-14T23:00:00"),
            _board_row("周一003", "2993786", "2026-09-15T00:30:00"),
        ],
        odds_fetcher=flaky,
    )
    assert set(out) == {"周一003"}


def test_board_fetch_failure_returns_empty_never_raises():
    """板面抓不到 → 空 dict，由 fetch_day 决定不落盘（不覆盖完好快照）。"""

    def boom():
        raise Titan007ParseError("WAF")

    out = collect_bold_odds_titan007(
        _sporttery(("周一002", "国际图尔", "瓦萨", "2026-09-14", "23:00:00")),
        run_date="2026-09-14",
        board_fetcher=boom,
        odds_fetcher=lambda mid: _QUOTES,
    )
    assert out == {}


def test_fair_probability_sums_to_one():
    value = _sporttery(("周一002", "国际图尔", "瓦萨", "2026-09-14", "23:00:00"))
    out = collect_bold_odds_titan007(
        value,
        run_date="2026-09-14",
        board_fetcher=lambda: [_board_row("周一002", "3085206", "2026-09-14T23:00:00")],
        odds_fetcher=lambda mid: _QUOTES,
        books=SHARP_BOOKS,
    )
    fair = out["周一002"]["match_winner"].fair_probability
    assert sum(fair.values()) == pytest.approx(1.0, abs=1e-6)
    assert out["周一002"]["match_winner"].independent is True
