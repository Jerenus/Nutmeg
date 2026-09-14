"""单测市场微结构 —— titan007 带来的、旧源结构性拿不到的判据原料。

API-Football 基础 ``/odds`` 无初赔、也不给逐家报价，故 drift / 离散度 / 返还率位移
三项在旧源上要么恒为 0、要么根本算不出。换源后这些量才第一次可得。

本模块只算**可观测量**，不判好坏——好坏是判断层的事，且要走 Factor 生死流程。
"""

from __future__ import annotations

import pytest

from nutmeg.data.fcom500 import MarketOdds
from nutmeg.decision.microstructure import market_microstructure


def _mo(**kw) -> MarketOdds:
    odds = kw.pop("odds", {"home": 2.0, "draw": 3.4, "away": 4.0})
    base = dict(
        odds=odds,
        fair_probability={},
        independent=True,
    )
    base.update(kw)
    return MarketOdds(**base)


def test_no_opening_odds_yields_no_drift_keys():
    """旧源(API-Football)没有初赔——不能伪造成 drift=0，那会把『没测量』说成『没移动』。"""
    micro = market_microstructure(_mo())
    assert "drift_pp" not in micro
    assert "payout_open" in micro or "payout_current" in micro


def test_drift_is_the_opening_to_current_fair_move():
    micro = market_microstructure(
        _mo(
            odds={"home": 1.70, "draw": 3.80, "away": 5.00},
            opening_odds={"home": 2.07, "draw": 3.37, "away": 3.54},
        )
    )
    # 初赔 fair home = (1/2.07)/(1/2.07+1/3.37+1/3.54) = .45476
    # 即时 fair home = (1/1.70)/(1/1.70+1/3.80+1/5.00) = .55948
    assert micro["drift_home_pp"] == pytest.approx(10.47, abs=0.01)
    assert micro["drift_draw_pp"] == pytest.approx(-2.90, abs=0.01)
    assert micro["drift_away_pp"] == pytest.approx(-7.57, abs=0.01)
    # drift_pp 取**绝对值最大**的那一路，并保留符号
    assert micro["drift_pp"] == pytest.approx(10.47, abs=0.01)


def test_payout_measures_the_vig_on_both_ends():
    micro = market_microstructure(
        _mo(
            odds={"home": 1.70, "draw": 3.80, "away": 5.00},
            opening_odds={"home": 2.07, "draw": 3.37, "away": 3.54},
        )
    )
    assert micro["payout_current"] == pytest.approx(95.11, abs=0.01)
    assert micro["payout_open"] == pytest.approx(94.13, abs=0.01)
    # 返还率上升 = 抽水收窄 = 庄家更笃定
    assert micro["payout_delta_pp"] == pytest.approx(0.98, abs=0.01)


def test_dispersion_measures_cross_book_disagreement_on_the_favourite():
    micro = market_microstructure(
        _mo(
            odds={"home": 1.75, "draw": 3.70, "away": 4.67},
            per_book_odds={
                "home": [1.70, 1.75, 1.80],
                "draw": [3.80, 3.70, 3.60],
                "away": [5.00, 4.60, 4.40],
            },
        )
    )
    assert micro["books"] == 3
    assert micro["dispersion_pp"] > 0


def test_dispersion_is_skipped_when_book_lists_do_not_align():
    """API-Football 的 per_book_odds 各路家数可以不等 —— 那时逐家 fair 无从对齐。

    宁可不出这个量，也不能拿错位的家凑一个假离散度。
    """
    micro = market_microstructure(
        _mo(
            per_book_odds={"home": [1.7, 1.8], "draw": [3.8], "away": [5.0, 4.6]},
            bookmaker_count=2,
        )
    )
    assert "dispersion_pp" not in micro
    assert micro["books"] == 2   # 家数仍来自 bookmaker_count，只是不敢算离散度


def test_empty_market_yields_empty_micro():
    assert market_microstructure(MarketOdds(odds={}, fair_probability={}, independent=True)) == {}
    assert market_microstructure(None) == {}
