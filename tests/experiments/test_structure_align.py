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


def _dated(face: str, day: int, p_fav: float = 0.60, **kw) -> dict:
    row = _row(face, p_fav=p_fav, **kw)
    row["date"] = f"2026-10-{day:02d}"
    return row


def test_indicator_face_maps_fav_underdog_literals_and_fields():
    row = _row("3")
    assert sa.indicator_face(row, "fav") == "3" and sa.indicator_face(row, "modal") == "3"
    assert sa.indicator_face(row, "underdog") == "0"
    assert sa.indicator_face(row, "draw") == "1" and sa.indicator_face(row, "away") == "0"
    row["research"]["upset_side"] = "away"
    assert sa.indicator_face(row, {"field": "research.upset_side"}) == "0"


def test_prescreen_strong_effect_passes_floor_and_suggests_n_min_60():
    # 选中的 40 行（priced_in=False）热门面 100% 开出 vs 市场 60%；池里另 200 行按市场开
    rows = [_dated("3", d % 28 + 1, priced=False) for d in range(40)]
    for d in range(200):
        rows.append(_dated("3" if d % 5 < 3 else "0", d % 28 + 1, priced=True))
    r = sa.prescreen_indicator(rows, {"id": "X", "face": "fav",
                                      "select": {"field": "research.hole.priced_in",
                                                 "equals": False}})
    assert r["n"] == 40 and r["pool"] == 240
    assert r["residual_pp"] > 30 and r["passes_floor"] is True
    assert r["suggested_n_min"] == 60 and r["effect_abs_pp"] >= 10


def test_prescreen_null_effect_fails_floor_and_small_hits_are_noted():
    rows = [_dated("3" if d % 5 < 3 else "0", d % 28 + 1, priced=(d % 2 == 0))
            for d in range(240)]
    spec = {"id": "Y", "face": "fav",
            "select": {"field": "research.hole.priced_in", "equals": False}}
    r = sa.prescreen_indicator(rows, spec)
    assert r["passes_floor"] is False and r["suggested_n_min"] is None
    assert r["floor_low_pp"] <= r["residual_pp"] <= r["floor_pp"]
    one = sa.prescreen_indicator(rows[:1], spec)
    assert one["n"] <= 1 and one["passes_floor"] is False and "note" in one
    assert "只做展示列" in sa.render_prescreen(r)


def test_prescreen_cli_prints_json(tmp_path: Path, capsys):
    import subprocess
    import sys

    samples = tmp_path / "s.jsonl"
    rows = [_dated("3", d % 28 + 1, priced=False) for d in range(30)]
    rows += [_dated("0", d % 28 + 1, priced=True) for d in range(60)]
    samples.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    out = tmp_path / "pre.json"
    proc = subprocess.run(
        [sys.executable, str(_PATH), "--samples", str(samples), "--json-out", str(out),
         "--indicator-json", json.dumps({"id": "Z", "face": "fav", "select": {
             "field": "research.hole.priced_in", "equals": False}})],
        capture_output=True, text=True, check=True)
    assert "回溯预筛" in proc.stdout
    assert json.loads(out.read_text(encoding="utf-8"))["id"] == "Z"
