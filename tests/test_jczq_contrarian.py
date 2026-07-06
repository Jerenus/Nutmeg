"""Tests for jczq_contrarian — spec §34 反面引擎。"""
from __future__ import annotations

from nutmeg.services.jczq_bold_combos import BoldMatch
from nutmeg.services.jczq_contrarian import (
    compute_contrarian_reads,
    render_contrarian_section,
)


def _match(no, *, home, draw, away, euro=None, h="H", a="A") -> BoldMatch:
    return BoldMatch(
        match_no=no, league="J", home=h, away=a,
        tc_odds={"home": home, "draw": draw, "away": away},
        euro_fair_prob=euro or {},
    )


# ---------------------------------------------------------------------------
# pick'em detection → fade to underdog
# ---------------------------------------------------------------------------


def test_pickem_flags_and_fades_to_underdog() -> None:
    # 鹿岛 2.11 / 神户 2.92 — 主客接近 pick'em，热门=主，反面=客胜
    reads = compute_contrarian_reads(
        [_match("201", home=2.11, draw=3.2, away=2.92, h="鹿岛", a="神户")]
    )
    assert len(reads) == 1
    r = reads[0]
    assert "pickem" in r.flags
    assert r.fade_from == "主胜"
    assert r.fade_to == "客胜"  # fade the home favourite to the away dog


def test_clear_favourite_no_contrarian() -> None:
    # 浦和 1.83 / 冈山 3.76 — 质量差大、非 pick'em、非软热带下界以上但…
    # 1.83 在软热带内 → 会触发 soft_fav。用更硬的热门验证"无反面"：
    reads = compute_contrarian_reads([_match("203", home=1.30, draw=4.5, away=8.0)])
    assert reads == []  # 硬热、主客差大 → 无 pickem/软热信号


def test_soft_favourite_alone_does_not_trigger() -> None:
    # 软热但非 pickem、无欧赔 → soft_fav 单独**不**触发（否则糊成 monochrome 噪声）。
    # 普通中等主队热门不该被无脑标反面。
    reads = compute_contrarian_reads([_match("x", home=1.80, draw=3.4, away=4.2)])
    assert reads == []


def test_soft_fav_boosts_confidence_with_pickem() -> None:
    # 软热 + pickem（主客近）→ 触发，soft_fav 抬信心（弱反→中反）
    reads = compute_contrarian_reads([_match("p", home=1.95, draw=3.3, away=2.05)])
    assert len(reads) == 1
    assert {"pickem", "soft_fav"} <= set(reads[0].flags)
    assert reads[0].confidence == "中反"  # pickem(1)+soft_fav(1)=2


# ---------------------------------------------------------------------------
# euro gap (sharp benchmark) — the strongest signal
# ---------------------------------------------------------------------------


def test_euro_inflated_favourite_is_strong_fade() -> None:
    # 体彩主 1.55(de-vig implied~0.46)；欧赔 fair 主只 0.40 → 灌水 +0.06 → euro_inflated
    # 欧赔最看好被低估的客(0.40 vs 体彩客 implied~0.34) → 反面=客胜
    reads = compute_contrarian_reads([
        _match("206", home=1.55, draw=3.5, away=2.10,
               euro={"home": 0.40, "draw": 0.22, "away": 0.40})
    ])
    assert len(reads) == 1
    r = reads[0]
    assert "euro_inflated" in r.flags
    assert r.euro_gap is not None and r.euro_gap >= 0.05
    assert r.fade_to == "客胜"
    assert r.confidence in ("强反", "中反")


def test_euro_confirms_favourite_no_fade() -> None:
    # 欧赔和体彩一致看好主（都~0.50）→ 不灌水，且非 pickem/软热 → 无反面
    reads = compute_contrarian_reads([
        _match("y", home=1.45, draw=4.0, away=6.5,
               euro={"home": 0.66, "draw": 0.20, "away": 0.14})
    ])
    assert reads == []


def test_confidence_strong_when_three_signals() -> None:
    # pickem(主客近) + soft_fav(1.90) + euro_inflated(体彩主 implied~0.40 vs 欧赔 0.34) → 强反
    reads = compute_contrarian_reads([
        _match("z", home=1.90, draw=3.4, away=2.00,
               euro={"home": 0.34, "draw": 0.24, "away": 0.42})
    ])
    assert len(reads) == 1
    assert "pickem" in reads[0].flags
    assert "euro_inflated" in reads[0].flags
    assert reads[0].confidence == "强反"


# ---------------------------------------------------------------------------
# ranking + rendering
# ---------------------------------------------------------------------------


def test_reads_sorted_strong_first() -> None:
    strong = _match("s", home=1.90, draw=3.4, away=2.00,
                    euro={"home": 0.34, "draw": 0.24, "away": 0.42})  # 强反
    weak = _match("w", home=2.30, draw=3.2, away=2.55)  # pickem only, 弱反
    reads = compute_contrarian_reads([weak, strong])
    assert len(reads) == 2
    assert reads[0].match_no == "s"  # strong first regardless of input order


def test_render_empty() -> None:
    out = render_contrarian_section([])
    assert "无明显反面机会" in out
    assert "## D" in out


def test_render_has_table_and_top_flag() -> None:
    reads = compute_contrarian_reads([
        _match("206", home=1.90, draw=3.4, away=2.00, h="川崎", a="广岛",
               euro={"home": 0.34, "draw": 0.24, "away": 0.42})
    ])
    out = render_contrarian_section(reads)
    assert "反面视角" in out
    assert "站 **客胜**" in out
    assert "🔴 今晚最锋利的反面" in out  # strong read gets headline


def test_unusable_had_skipped() -> None:
    m = BoldMatch(match_no="bad", league="J", home="H", away="A", tc_odds={})
    assert compute_contrarian_reads([m]) == []
