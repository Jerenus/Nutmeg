"""spec §29.1 — A 档 gap-guard「欧赔同认热门」豁免 (v2.5, 2026-05-29 落地).

Root cause (5/28): the §17.1 anchor gap-guard dropped 4/5 home favourites
(001/003/004/005) because 体彩 implied − 欧赔 fair ≥ 0.08 on every short price —
structural margin, not a public-invented mirage. All four dropped favourites
won straight up, yet A/B/D produced no ticket on the friendliest chalk day.
§29.1 exempts a favourite when the European market also rates it a clear
favourite (fair ≥ EURO_CONFIRM_FAVOURITE_PROB) and the 体彩 premium is not
absurd (gap < EURO_CONFIRM_MAX_GAP).
"""
from __future__ import annotations

from nutmeg.services.jczq_bold_combos import BoldMatch, PoolSignals
from nutmeg.services.jczq_tiered import (
    DEFAULT_TIER_A,
    EURO_CONFIRM_FAVOURITE_PROB,
    EURO_CONFIRM_MAX_GAP,
    PlanContext,
    _favourite_had_leg,
    pick_anchor_tier,
)


def _match(
    match_no: str,
    *,
    had: dict[str, float],
    euro_fair: dict[str, float] | None = None,
    hhad: dict[str, float] | None = None,
    hhad_line: float = -1.0,
) -> BoldMatch:
    return BoldMatch(
        match_no=match_no,
        home="主",
        away="客",
        league="联赛",
        tc_odds=had,
        euro_fair_prob=euro_fair or {},
        hhad_odds=hhad or {},
        hhad_line=hhad_line,
        ttg_odds={},
        crs_odds={},
    )


def _ctx() -> PlanContext:
    return PlanContext(pool_signals=PoolSignals())


def test_constants_sane():
    # threshold = 欧赔认热门概率门槛；ceiling = 体彩溢价上限
    assert 0.5 <= EURO_CONFIRM_FAVOURITE_PROB <= 0.6
    assert 0.15 <= EURO_CONFIRM_MAX_GAP <= 0.25


def test_gap_guard_keeps_sharp_confirmed_favourite():
    """5/28 周四001: had 1.51 (implied .662) vs 欧赔 fair .57 → gap .092 ≥ .08
    触发 gap-guard，但欧赔同认热门(.57≥.55) 且溢价不离谱(.092<.20) → 保留。"""
    m = _match("001", had={"home": 1.51, "draw": 3.48, "away": 5.6},
               euro_fair={"home": 0.570, "draw": 0.246, "away": 0.184})
    result = _favourite_had_leg(m)
    assert result is not None, "sharp-confirmed favourite must survive gap-guard"
    leg, _ = result
    assert leg.pick_label == "胜" and abs(leg.tc_odds - 1.51) < 1e-6


def test_gap_guard_still_drops_public_invented_favourite():
    """中赔热门 had 1.80 (implied .556) vs 欧赔 fair .45 → gap .106 ≥ .08，
    且欧赔不认热门(.45<.55) → 仍丢（体彩凭空造热门）。"""
    m = _match("X", had={"home": 1.80, "draw": 3.30, "away": 4.20},
               euro_fair={"home": 0.45, "draw": 0.30, "away": 0.25})
    assert _favourite_had_leg(m) is None


def test_gap_guard_drops_absurd_premium_even_if_sharp_favourite():
    """had 1.30 (implied .769) vs 欧赔 fair .55 → gap .219 ≥ .20 上限 →
    即便欧赔也认热门，体彩溢价过大仍视为陷阱，丢。"""
    m = _match("Y", had={"home": 1.30, "draw": 4.50, "away": 9.0},
               euro_fair={"home": 0.55, "draw": 0.25, "away": 0.20})
    assert _favourite_had_leg(m) is None


def test_gap_guard_unaffected_when_no_euro_snapshot():
    """无欧赔快照 (fair 缺失) → gap-guard 整体跳过，腿保留（与 §17.1 一致）。"""
    m = _match("Z", had={"home": 1.51, "draw": 3.48, "away": 5.6}, euro_fair={})
    assert _favourite_had_leg(m) is not None


def test_chalk_day_anchor_fires_with_sharp_confirmed_favourites():
    """5/28 满盘热门日：三场真热门经 §29.1 豁免后 A 档组 3 串主胜 @≈4.82。
    赛果 001 1:0 / 003 2:0 / 002 2:0 全主胜 — 修复前 A=None。"""
    matches = [
        _match("001", had={"home": 1.51, "draw": 3.48, "away": 5.6},
               euro_fair={"home": 0.570, "draw": 0.246, "away": 0.184},
               hhad={"home": 2.8, "draw": 3.2, "away": 2.18}),
        _match("003", had={"home": 1.52, "draw": 3.45, "away": 5.5},
               euro_fair={"home": 0.572, "draw": 0.259, "away": 0.169},
               hhad={"home": 2.95, "draw": 2.98, "away": 2.2}),
        _match("002", had={"home": 2.10, "draw": 2.77, "away": 3.42},
               euro_fair={"home": 0.399, "draw": 0.309, "away": 0.293},
               hhad={"home": 5.05, "draw": 3.4, "away": 1.57}),
    ]
    tier = pick_anchor_tier(DEFAULT_TIER_A, [], frozenset(), _ctx(), matches)
    assert tier is not None, "A must fire on a sharp-confirmed chalk day"
    picks = {tl.leg.match_no: (tl.leg.market, tl.leg.pick_label) for tl in tier.legs}
    assert len(picks) == 3
    assert all(mkt == "had" and lbl == "胜" for mkt, lbl in picks.values())
    assert 2.5 <= tier.total_odds <= 5.5
