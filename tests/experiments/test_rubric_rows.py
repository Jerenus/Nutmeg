from experiments.rubric_rows import _FACTORS, factor_entries, rows_F_absence_home, rows_S_draw_mode


def _row(key, rubric, actual, fair=None, prospective=True, version="r1"):
    return {"key": key, "actual": actual, "fair": fair or {"home": .5, "draw": .3, "away": .2},
            "labels": {"rubric": rubric, "rubric_version": version},
            "provably_prospective": prospective}


def test_fact_item_rows_use_the_effect_face_set_and_explicit_no_as_control():
    yes = {"F_absence_home": {"answer": "yes", "p": .9}, "S_anchor_side": {"answer": "home"}}
    no = {"F_absence_home": {"answer": "no", "p": .2}}
    rows = rows_F_absence_home([_row("a", yes, "0"), _row("b", yes, "3"), _row("c", no, "1"),
                                _row("d", {}, "3"),
                                _row("e", {"F_absence_home": {"answer": None}}, "3")])
    assert [r["factor"] for r in rows] == [1, 1, 0]           # 弃权/没答的场不进行
    assert [r["face_hit"] for r in rows] == [1, 0, 1]         # down:home → 效应面 = 非主胜
    assert rows[0]["fair"] == .5 and rows[0]["provably_prospective"] is True


def test_draw_and_anchor_relative_items():
    draw = {"S_draw_mode": {"answer": "yes", "p": .7}}
    rows = rows_S_draw_mode([_row("a", draw, "1"), _row("b", draw, "3")])
    assert [r["face_hit"] for r in rows] == [1, 0] and rows[0]["fair"] == .3
    crash = {"S_crash_candidate": {"answer": "yes", "p": .8}}
    assert _FACTORS["rubric_S_crash_candidate"][0]([_row("a", crash, "0")]) == []   # 无锚算不出
    crash["S_anchor_side"] = {"answer": "home"}
    [r] = _FACTORS["rubric_S_crash_candidate"][0]([_row("a", crash, "0")])
    assert r["face_hit"] == 1 and r["fair"] == .5                 # down:anchor(home) → 非主胜


def test_factor_entries_cover_every_directional_item_with_zero_weight():
    entries = factor_entries()
    assert {e["factor_id"] for e in entries} == set(_FACTORS)
    assert all(e["current_weight_pp"] == 0.0 and e["layer"] == "probability" for e in entries)
    assert all(e["row_builder"].startswith("experiments.rubric_rows:rows_") for e in entries)


def test_rows_ignore_answers_from_unsupported_rubric_versions():
    yes = {"F_absence_home": {"answer": "yes", "p": .9}}
    assert rows_F_absence_home([_row("a", yes, "0", version="r0")]) == []
    assert len(rows_F_absence_home([_row("a", yes, "0")])) == 1
