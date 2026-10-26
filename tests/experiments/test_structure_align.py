"""§1d 结构对准脚本：逐场落到最深一层 n≥n_min 的格，只展示不改默认动作。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_PATH = Path(__file__).resolve().parents[2] / "experiments" / "structure_align.py"
_SPEC = importlib.util.spec_from_file_location("structure_align", _PATH)
sa = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sa)


def _row(face: str, p_fav: float = 0.60, rel: str = "fav", priced: bool = True,
         label: str = "real", unit: str = "spine") -> dict:
    return {
        "result": {"face": face},
        "belief": {"market": {"3": p_fav, "1": 0.25, "0": round(0.75 - p_fav, 2)}},
        "research": {"prospective": True, "upset_label": label,
                     "hole": {"rel": rel, "priced_in": priced, "unit": unit}},
        "derived": {"fav": "3", "p_fav": p_fav, "band": sa.band_of(p_fav),
                    "hole_rel": rel, "hole_priced": priced, "hole_unit": unit},
    }


def _leg(p_home: float = 0.60, side: str = "home", unit: str = "spine",
         strength: str = "real", priced: bool = True) -> dict:
    return {
        "name": "甲-乙",
        "prior": {"home": p_home, "draw": 0.25, "away": round(0.75 - p_home, 2)},
        "_hole": {"side": side, "unit": unit, "priced_in": priced},
        "strength_balance": {"underdog_path": {"side": "away", "strength": strength}},
    }


def test_locates_deepest_layer_with_enough_samples():
    rows = [_row("3")] * 15 + [_row("0")] * 5                 # 五维格 n=20
    rows += [_row("3", unit="attack")] * 30                   # 同档同洞位同价态同标签，不同单位
    grid = sa.build_grid(rows)
    key, market, fav = sa.leg_cell(_leg())
    assert key == ("b57–64", "fav", "价内", "real", "球员")
    layer, depth, _, c = sa.locate(grid, key, n_min=20)
    assert depth == 5 and c["n"] == 20 and c["fav"] == 15


def test_falls_back_to_shallower_layer_when_thin():
    rows = [_row("3")] * 5 + [_row("1", unit="attack")] * 20  # 五维格只有 5，四维格 25
    grid = sa.build_grid(rows)
    key, _, _ = sa.leg_cell(_leg())
    layer, depth, _, c = sa.locate(grid, key, n_min=20)
    assert depth == 4 and c["n"] == 25


def test_render_flags_only_cells_off_by_ten_points():
    rows = [_row("3")] * 16 + [_row("0")] * 4                 # 80% 开热门 vs 市场 60% → +20pp
    grid = sa.build_grid(rows)
    md = sa.render([("1", _leg())], grid, n_min=20, title="t")
    assert "+20pp" in md and "|差|≥10pp" in md
    thin = sa.render([("1", _leg())], sa.build_grid(rows[:5]), n_min=20, title="t")
    assert "无一层 n≥20" in thin and "无一格改默认动作" in thin


def test_prospective_filter_and_market_requirement(tmp_path: Path):
    good = _row("3")
    bad = {**_row("3"), "research": {**_row("3")["research"], "prospective": None}}
    p = tmp_path / "s.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in (good, bad)) + "\n", encoding="utf-8")
    assert len(sa.load_samples(p)) == 1
