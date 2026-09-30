import json
from pathlib import Path

from nutmeg.decision.betslip import BetSlip, SlipLeg, load_slips, register_slip
from nutmeg.decision.betslip_diagnosis import (
    diagnose,
    joint_death,
    narrowing,
    peers,
    prescription_for,
    shared_naked_legs,
)

FAIR_004 = {"home": 0.357, "draw": 0.270, "away": 0.373}
FAIR_005 = {"home": 0.254, "draw": 0.242, "away": 0.504}


def _jczq(slip_id, legs, day="2026-09-28", purchased=True):
    return BetSlip(slip_id=slip_id, channel="jczq", placed_at=day, legs=legs,
                   multiplier=25, combo_sizes=(len(legs),), purchased=purchased)


def _leg(key, sel, fair=None, market="had", line=None):
    return SlipLeg(key=key, market=market, line=line, selections=sel,
                   odds=tuple(2.0 for _ in sel), fair=fair)


def test_five_slips_sharing_one_naked_leg_report_the_joint_death():
    turkey = _leg("周一004", ("home",), FAIR_004)
    slips = [
        _jczq("J1", [turkey, _leg("周一005", ("home",), FAIR_005, market="hhad", line=1.0),
                     _leg("周一007", ("home",))]),
        _jczq("J2", [_leg("周一002", ("away",)), turkey]),
        _jczq("J3", [_leg("周一003", ("away",)), turkey, _leg("周一005", ("home",), FAIR_005)]),
        _jczq("J4", [turkey]),
        _jczq("J5", [turkey, _leg("周一005", ("home",), FAIR_005)]),
        _jczq("Y1", [turkey], day="2026-09-27"),           # 前一天，不算同伴
        _jczq("T1", [turkey], purchased=False),            # 试玩，不算
    ]
    new = _jczq("J5", [turkey, _leg("周一005", ("home",), FAIR_005)])
    others = peers(new, slips)
    assert {s.slip_id for s in others} == {"J1", "J2", "J3", "J4"}
    shared = shared_naked_legs(new, others)
    assert [(r["key"], r["face"], r["slip_ids"]) for r in shared] == [
        ("周一004", "3", ["J1", "J2", "J3", "J4", "J5"]),
        ("周一005", "3", ["J3", "J5"]),
    ]
    joint = joint_death(shared)
    assert joint["n_shared"] == 2 and joint["n_priced"] == 2
    assert joint["p_all_die_at_least"] == round(1 - 0.357 * 0.254, 4)
    diag = diagnose(new, others, {})
    assert "共享裸单 2 条" in diag["lines"][0] and "≥91%" in diag["lines"][0]


def test_missing_fair_is_reported_not_guessed():
    leg = _leg("周一004", ("home",))
    shared = shared_naked_legs(_jczq("A", [leg]), [_jczq("B", [leg])])
    assert shared[0]["p_face"] is None
    assert joint_death(shared) == {"n_shared": 1, "n_priced": 0, "p_all_die_at_least": None}
    assert "缺 fair 未计" in diagnose(_jczq("A", [leg]), [_jczq("B", [leg])], {})["lines"][0]


def test_double_selection_legs_are_not_naked():
    double = _leg("周一008", ("draw", "away"))
    assert shared_naked_legs(_jczq("A", [double]), [_jczq("B", [double])]) == []


def test_narrowing_against_the_prescription_counts_each_leg_once():
    faces = {"2": "0", "3": "31", "5": "3", "7": "3", "1": "10"}
    sel = {"3": ("home",), "1": ("draw",), "0": ("away",), "31": ("home", "draw"),
           "10": ("draw", "away")}
    slip = BetSlip(slip_id="R9-144", channel="renjiu", placed_at="2026-09-28", issue="26134",
                   legs=[SlipLeg(key=k, market="had", selections=sel[f]) for k, f in faces.items()],
                   faces=faces)
    prescription = {"1": "10", "2": "10", "3": "10", "5": "31", "7": "31"}
    out = narrowing(slip, prescription)
    assert out["narrower"] == ["2", "5", "7"]
    assert out["off_prescription"] == ["3"]      # 处方 10（法国/平），票买 31 → 翻面
    assert out["same"] == ["1"] and out["unprescribed"] == []
    lines = diagnose(slip, [], prescription)["lines"]
    assert any("收窄 2,5,7" in line and "翻面 3" in line for line in lines)


def test_prescription_sources_for_both_lanes(tmp_path: Path):
    zdir = tmp_path / "zucai"
    zdir.mkdir()
    (zdir / "26134-judgment-v1.json").write_text(
        json.dumps({"1": {"action": "10"}, "2": {"action": "10", "note": "x"}}), encoding="utf-8")
    day = tmp_path / "jczq" / "daily" / "2026-09-28"
    day.mkdir(parents=True)
    (day / "jczq-legs-base.json").write_text(
        json.dumps({"day": "2026-09-28", "legs": {"周一004": {"faces": "310"},
                                                  "周一005": {"faces": "30"}}}), encoding="utf-8")
    zslip = BetSlip(slip_id="Z", channel="renjiu", placed_at="2026-09-28", issue="26134", legs=[])
    assert prescription_for(zslip, tmp_path) == {"1": "10", "2": "10"}
    jslip = _jczq("J", [])
    assert prescription_for(jslip, tmp_path) == {"周一004": "310", "周一005": "30"}
    assert prescription_for(_jczq("J", [], day="2026-01-01"), tmp_path) == {}


def test_register_persists_the_diagnosis_on_the_slip(tmp_path: Path):
    turkey = _leg("周一004", ("home",), FAIR_004)
    first = _jczq("J1", [turkey])
    register_slip(tmp_path, first)
    second = _jczq("J2", [turkey, _leg("周一007", ("home",))])
    second.diagnosis = diagnose(second, peers(second, load_slips(tmp_path)), {})
    register_slip(tmp_path, second)
    stored = {s.slip_id: s for s in load_slips(tmp_path)}
    assert stored["J2"].diagnosis["shared_naked"][0]["slip_ids"] == ["J1", "J2"]
    assert stored["J1"].diagnosis == {}
