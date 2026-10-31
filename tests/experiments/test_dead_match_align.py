"""§1e 近期死亡场同构对位：死＝票形被开出排除面/单死；近 N 期同格逐场列出；票形死亡率对照市场 P。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[2] / "experiments" / "dead_match_align.py"
_SPEC = importlib.util.spec_from_file_location("dead_match_align", _PATH)
dm = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(dm)


def _row(issue: str, no: int, face: str | None, *, p_fav: float = 0.52, structure: str = "double",
         stance: str = "3", cover: str | None = "1", ai: str = "fail", rel: str = "fav") -> dict:
    return {
        "home": f"甲{no}", "away": f"乙{no}", "zucai": {"issue": issue, "no": no},
        "result": {"face": face} if face else None,
        "belief": {"market": {"3": p_fav, "1": 0.25, "0": round(0.75 - p_fav, 2)}},
        "research": {"prospective": True, "anchor_integrity": ai, "upset_label": "real",
                     "stance_structure": structure, "stance_face": stance, "stance_cover": cover,
                     "hole": {"rel": rel, "priced_in": True, "unit": "defense"}},
        "derived": {"fav": "3", "p_fav": p_fav, "band": "C45–56", "hole_rel": rel,
                    "hole_priced": True, "hole_unit": "defense"},
    }


def test_death_is_excluded_face_or_single_miss_not_fav_miss():
    assert dm.death(_row("26149", 3, "0")) == "排除面开"          # 31 开 0
    assert dm.death(_row("26149", 4, "1")) is None               # 31 开 1：翻车但票活
    assert dm.death(_row("26148", 3, "0", structure="single", cover=None)) == "单死"
    assert dm.death(_row("26152", 6, None)) is None              # 无赛果
    assert dm.outcome_mark(_row("26149", 4, "1")) == "✗"
    assert dm.outcome_mark(_row("26149", 5, "3")) == "✓"


def test_ticket_form_names_excluded_face_relative_to_fav():
    assert dm.ticket_form(_row("x", 1, "3", cover="1"))[0] == "双·排非热门胜"
    assert dm.ticket_form(_row("x", 1, "3", cover="0"))[0] == "双·排平"
    assert dm.ticket_form(_row("x", 1, "3", stance="1", cover="0"))[0] == "双·排热门"
    assert dm.ticket_form(_row("x", 1, "3", structure="single", cover=None))[0] == "单"


def test_recent_window_and_render_list_same_cell_matches():
    rows = [_row("26145", 13, "3"), _row("26149", 3, "0"), _row("26150", 7, "1", cover="0"),
            _row("26150", 2, "1"), _row("26151", 1, None), _row("26152", 6, None),
            _row("26152", 9, None, ai="pass")]
    window = dm.recent_issues(rows, "26152", 2)
    assert window == ["26149", "26150"]            # 26151 无赛果不计入；26145 在窗外
    recent = [r for r in rows if r["zucai"]["issue"] in window]
    md = dm.render("26152", rows[-2:], recent, [r for r in rows if r.get("result")], window)
    assert "☠ 26149-3" in md and "☠ 26150-7" in md and "✗ 26150-2" in md
    assert "26145-13" not in md
    assert "近期无同格" in md                        # 场 9（锚方 pass）退层后仍无同格
    assert "双·排平 | 1 / 1（100%）" in md
