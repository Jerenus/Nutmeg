import pytest

from nutmeg.decision.crowd_source import parse_zgzcw
from nutmeg.decision.crowd_trigger import evaluate, facts, fires, validate
from tests.decision.crowd_fixtures import zg_doc

BOARD = parse_zgzcw(zg_doc())


def test_validate_accepts_nested_and_rejects_unknowns():
    validate({"all": [{"field": "face", "op": "==", "v": "1"},
                      {"not": {"field": "league_group", "op": "in", "v": ["national"]}}]})
    with pytest.raises(ValueError, match="未知字段"):
        validate({"field": "gap", "op": ">=", "v": 1})
    with pytest.raises(ValueError):
        validate({"field": "face", "op": "~", "v": "1"})
    with pytest.raises(ValueError, match="列表"):
        validate({"field": "league", "op": "in", "v": "英超"})
    with pytest.raises(ValueError, match="嵌套"):
        validate({"all": [{"any": [{"not": {"field": "face", "op": "==", "v": "1"}}]}]})


def test_facts_units_are_percent_and_board_hot_count():
    f = facts(BOARD[6], "3", BOARD)          # 1.30 的主胜
    assert f["p_face"] > 65 and f["is_fav"] is True and f["fav_face"] == "3"
    assert f["board_hot_count"] == sum(1 for m in BOARD if max(m.p.values()) >= 0.65)
    assert f["league_group"] == "top5"


def test_evaluate_and_fires():
    draw = {"field": "face", "op": "==", "v": "1"}
    assert fires(draw, BOARD) == [(m.no, "1") for m in BOARD]
    hot_home = {"all": [{"field": "face", "op": "==", "v": "3"},
                        {"field": "p_face", "op": ">=", "v": 65}]}
    assert {no for no, _ in fires(hot_home, BOARD)} == {m.no for m in BOARD if m.p["3"] >= 0.65}
    assert evaluate({"not": draw}, facts(BOARD[0], "0", BOARD)) is True


def test_attention_fields_are_facts_and_a_missing_value_never_fires():
    """Polymarket 关注度（2026-10-09）：pm_volume_k / pm_rank；没上 Polymarket＝空，叶子为假。"""
    from nutmeg.decision.crowd_source import CrowdMatch
    from nutmeg.decision.crowd_trigger import evaluate, facts, validate

    listed = CrowdMatch(no=2, league="德甲", home="多特", away="不来梅",
                        p={"3": 0.70, "1": 0.17, "0": 0.13}, pm_volume_k=80.3, pm_rank=1)
    unlisted = CrowdMatch(no=5, league="西甲", home="马拉加", away="西班人",
                          p={"3": 0.35, "1": 0.30, "0": 0.35})
    trig = {"all": [{"field": "is_fav", "op": "==", "v": True},
                    {"field": "pm_rank", "op": "<=", "v": 3}]}
    validate(trig)
    board = [listed, unlisted]
    assert facts(listed, "3", board)["pm_volume_k"] == 80.3
    assert evaluate(trig, facts(listed, "3", board)) is True
    assert evaluate(trig, facts(unlisted, "0", board)) is False
    assert evaluate({"field": "pm_rank", "op": "not_in", "v": [1]}, facts(unlisted, "0", board)) \
        is False
