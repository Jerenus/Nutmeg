"""Tests for jczq_opportunity — spec §35 机会雷达底座."""
from __future__ import annotations

from nutmeg.services.jczq_bold_combos import BoldMatch
from nutmeg.services.jczq_opportunity import (
    Opportunity,
    contrarian_lens,
    drift_lens,
    render_opportunity_radar,
    scan_opportunities,
    totals_lens,
)


def _match(no, *, tc, euro=None, opening=None, ttg=None, ou=None, ou_line=0.0,
           h="H", a="A") -> BoldMatch:
    return BoldMatch(
        match_no=no, league="J", home=h, away=a, tc_odds=tc,
        euro_odds=euro or {}, euro_opening=opening or {},
        ttg_odds=ttg or {}, ou_odds=ou or {}, ou_line=ou_line,
    )


# 体彩 ttg 偏小球（P(over@2.5)≈0.41）
_TTG_LOW = {"total_0": 7.0, "total_1": 3.5, "total_2": 3.0,
            "total_3": 3.8, "total_4": 6.0, "total_5": 11.0}


# ---------------------------------------------------------------------------
# 反面透镜（适配 §34）
# ---------------------------------------------------------------------------


def test_contrarian_lens_wraps_pickem() -> None:
    ops = contrarian_lens([_match("201", tc={"home": 2.11, "draw": 3.2, "away": 2.92},
                                  h="鹿岛", a="神户")])
    assert len(ops) == 1
    assert ops[0].lens == "反面"
    assert ops[0].pick == "客胜"
    assert ops[0].confidence in ("强", "中", "弱")


# ---------------------------------------------------------------------------
# 异动透镜（steam + lag）
# ---------------------------------------------------------------------------


def test_drift_lens_flags_steam_toward_side() -> None:
    # 欧赔开盘 客 2.50→现在 2.00：客 implied 0.40→0.50 移动 +0.10 steam
    m = _match("x",
               tc={"home": 2.2, "draw": 3.3, "away": 2.6},
               opening={"home": 2.2, "draw": 3.4, "away": 2.50},
               euro={"home": 2.6, "draw": 3.6, "away": 2.00})
    ops = drift_lens([m])
    assert len(ops) == 1
    assert ops[0].lens == "异动"
    assert ops[0].pick == "客胜"  # money moved toward away


def test_drift_lens_lag_boosts_confidence() -> None:
    # 欧赔大幅朝客移动 + 体彩客 implied 明显低于欧赔 → 价值窗口 → 强
    m = _match("x",
               tc={"home": 1.9, "draw": 3.3, "away": 3.4},   # 体彩仍把客当冷门
               opening={"home": 1.8, "draw": 3.5, "away": 4.2},
               euro={"home": 2.5, "draw": 3.6, "away": 2.05})  # 欧赔已把客拉成准热门
    ops = drift_lens([m])
    assert len(ops) == 1
    assert ops[0].confidence == "强"
    assert "价值窗口" in ops[0].reason


def test_drift_lens_no_movement_no_signal() -> None:
    m = _match("x",
               tc={"home": 1.9, "draw": 3.3, "away": 3.9},
               opening={"home": 2.0, "draw": 3.4, "away": 3.7},
               euro={"home": 2.0, "draw": 3.4, "away": 3.7})  # opening==live → 无异动
    assert drift_lens([m]) == []


def test_drift_lens_no_euro_degrades() -> None:
    m = _match("x", tc={"home": 1.9, "draw": 3.3, "away": 3.9})  # 无欧赔
    assert drift_lens([m]) == []


# ---------------------------------------------------------------------------
# scan + render
# ---------------------------------------------------------------------------


def test_totals_lens_flags_over_value() -> None:
    # 体彩偏小球(over≈0.41) + 欧赔偏大球(over≈0.55) → 价值在大球、强
    m = _match("t", tc={"home": 2.0, "draw": 3.3, "away": 3.5},
               ttg=_TTG_LOW, ou={"over": 1.70, "under": 2.10}, ou_line=2.5)
    ops = totals_lens([m])
    assert len(ops) == 1
    assert ops[0].lens == "大小球"
    assert ops[0].pick == "大球"
    assert ops[0].confidence == "强"


def test_totals_lens_flags_under_value() -> None:
    # 体彩 over≈0.41 + 欧赔强压小球(over≈0.32) → 价值在小球
    m = _match("t", tc={"home": 2.0, "draw": 3.3, "away": 3.5},
               ttg=_TTG_LOW, ou={"over": 3.00, "under": 1.40}, ou_line=2.5)
    ops = totals_lens([m])
    assert len(ops) == 1
    assert ops[0].pick == "小球"


def test_totals_lens_agreement_no_signal() -> None:
    # 欧赔 over≈0.41 ≈ 体彩 → 无错价
    m = _match("t", tc={"home": 2.0, "draw": 3.3, "away": 3.5},
               ttg=_TTG_LOW, ou={"over": 2.30, "under": 1.62}, ou_line=2.5)
    assert totals_lens([m]) == []


def test_totals_lens_no_ou_degrades() -> None:
    m = _match("t", tc={"home": 2.0, "draw": 3.3, "away": 3.5}, ttg=_TTG_LOW)
    assert totals_lens([m]) == []


def test_scan_groups_by_lens() -> None:
    by_lens = scan_opportunities([
        _match("201", tc={"home": 2.11, "draw": 3.2, "away": 2.92})
    ])
    assert set(by_lens.keys()) == {"反面", "异动", "大小球"}
    assert len(by_lens["反面"]) == 1


def test_render_empty_radar() -> None:
    out = render_opportunity_radar({"反面": [], "异动": []})
    assert "雷达无信号" in out
    assert "## D" in out


def test_render_radar_has_lens_subsections() -> None:
    by_lens = scan_opportunities([
        _match("201", tc={"home": 2.11, "draw": 3.2, "away": 2.92}, h="鹿岛", a="神户")
    ])
    out = render_opportunity_radar(by_lens)
    assert "机会雷达" in out
    assert "### 反面" in out


def test_render_resonance_when_two_lenses_agree() -> None:
    # 反面(home 热门+pickem→站客) + 异动(欧赔朝客 steam) 都指客胜 → 共振
    m = _match("206",
               tc={"home": 2.00, "draw": 3.3, "away": 2.10},  # home 热门、pickem → 反面站客
               opening={"home": 1.85, "draw": 3.4, "away": 2.60},
               euro={"home": 2.30, "draw": 3.5, "away": 2.00},  # 欧赔朝客移动
               h="川崎", a="广岛")
    by_lens = scan_opportunities([m])
    out = render_opportunity_radar(by_lens)
    assert "🔆 多视角共振" in out


def test_lens_is_pluggable_registry() -> None:
    # 底座契约：LENSES 是 (名, 函数) 列表，加透镜=追加一行
    from nutmeg.services.jczq_opportunity import LENSES
    names = [n for n, _ in LENSES]
    assert {"反面", "异动", "大小球"} <= set(names)
    assert all(callable(fn) for _, fn in LENSES)
