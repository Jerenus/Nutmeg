# tests/decision/test_read_builder.py
"""判读 → Read/legs 桥：只做转录与词典校验，不推断任何一场该买什么。"""
import pytest

from nutmeg.decision.legs_audit import audit_legs, legs_from_dict
from nutmeg.decision.read_builder import JudgmentError, build, format_warnings

FAIR = {"1": {"home": 0.605, "draw": 0.220, "away": 0.174},
        "2": {"home": 0.412, "draw": 0.266, "away": 0.321}}
IDS = {"1": {"match_id": "match-a", "snapshot_id": "snap-a", "name": "西汉姆-雷克斯"},
       "2": {"match_id": "match-b", "snapshot_id": "snap-b", "name": "柏林联-沙尔克"}}


def _judgment(**over):
    base = {
        "1": {"action": "31", "confidence": 3, "anchor_integrity": "fail",
              "directional_flags": ["anchor_shield_out"],
              "team_tags": {"home": ["pivot_absent"], "away": ["new_cb_pairing"]},
              "tracking_tags": ["midfield_pivot_absent"], "note": "跟市场"},
        "2": {"action": "310", "confidence": 2, "anchor_integrity": "fail",
              "crash_markers": ["opening_new_coach_debut"], "note": "C9 全包"},
    }
    for k, v in over.items():
        base.setdefault(k, {}).update(v) if k in base else base.update({k: v})
    return base


def test_build_emits_reads_and_legs_that_audit_cleanly():
    r = build(_judgment(), issue="26122", store_ids=IDS, fair=FAIR,
              made_at="2026-09-11T11:10:00+08:00")
    assert [x["read_id"] for x in r.reads] == [
        "R-claude-zucai-26122-01-had", "R-claude-zucai-26122-02-had"]
    assert r.reads[0]["belief"] == r.reads[0]["prior"]      # 零偏移=跟市场
    legs = legs_from_dict(r.legs)
    assert legs[0].directional_flags == (("anchor_shield_out", "1"),)
    assert ("home", "pivot_absent") in legs[0].team_tags
    audit_legs(legs)           # 生成的结构必须能直接过审计器，不抛异常


def test_dropped_match_keeps_read_but_leaves_legs():
    """丢整场仍要落 Read（判读留痕），但不进票面——26122 丢了 5 场，判读没丢。"""
    j = _judgment()
    j["2"]["action"] = "drop"
    r = build(j, issue="26122", store_ids=IDS, fair=FAIR, made_at="t")
    assert len(r.reads) == 2
    assert set(r.legs["legs"]) == {"1"}


def test_missing_fair_raises_instead_of_defaulting():
    """禁嘴算：缺 fair 必须抛错，不能补一个默认分布。"""
    with pytest.raises(JudgmentError) as exc:
        build(_judgment(), issue="26122", store_ids=IDS, fair={"1": FAIR["1"]},
              made_at="t")
    assert "缺 fair" in str(exc.value)


def test_missing_store_ids_raises():
    with pytest.raises(JudgmentError):
        build(_judgment(), issue="26122", store_ids={"1": IDS["1"]}, fair=FAIR,
              made_at="t")


def test_bad_confidence_raises():
    j = _judgment()
    j["1"]["confidence"] = 0
    with pytest.raises(JudgmentError):
        build(j, issue="26122", store_ids=IDS, fair=FAIR, made_at="t")


def test_off_lexicon_names_warn_but_do_not_block():
    """词典外的旗/标签只警告不阻断——阻断会让任何笔误堵死整条判读链。"""
    j = _judgment()
    j["1"]["directional_flags"] = ["away_side_draw_utility"]
    j["1"]["tracking_tags"] = ["hot_streak"]
    r = build(j, issue="26122", store_ids=IDS, fair=FAIR, made_at="t")
    assert any("away_side_draw_utility" in w for w in r.warnings)
    assert any("hot_streak" in w for w in r.warnings)
    assert "2 条词典" in format_warnings(r)


def test_belief_offset_is_flagged_for_evidence_review():
    """belief≠prior 必须提示——净偏移 ≥5pp 要有官宣/确证锚（C8）。"""
    j = _judgment()
    j["1"]["belief"] = {"home": 0.55, "draw": 0.25, "away": 0.20}
    r = build(j, issue="26122", store_ids=IDS, fair=FAIR, made_at="t")
    assert any("belief≠prior" in w for w in r.warnings)
