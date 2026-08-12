# tests/decision/test_alias_propose.py
import json

from nutmeg.decision.alias_propose import apply_proposals, propose_for_board

# 2026-08-12 晨的真实形状:帕尔梅拉斯已入表、波特诺未入;普拉滕斯/科金博联双缺
_FIXTURES = [
    {"teams": {"home": {"name": "Palmeiras"}, "away": {"name": "Cerro Porteno"}}},
    {"teams": {"home": {"name": "Platense"}, "away": {"name": "Coquimbo Unido"}}},
    {"teams": {"home": {"name": "Palmeiras U20"}, "away": {"name": "Santos U20"}}},
]


def test_opponent_inference_single_candidate():
    """一边已解析 → 用它在当日 fixtures 里的对手作候选(采集安全失败机制的逆运算)。"""
    got = propose_for_board(
        [{"home": "帕尔梅拉斯", "away": "波特诺"}],
        resolved={"帕尔梅拉斯": "Palmeiras"},
        fixtures=_FIXTURES)
    assert got["proposals"] == [{"cn": "波特诺", "candidate_en": "Cerro Porteno",
                                 "via": "Palmeiras", "fixture": "帕尔梅拉斯 vs 波特诺"}]
    assert not got["unresolvable"]


def test_both_sides_missing_is_reported_not_guessed():
    """双边都未解析 → 无锚点,如实报出——机器不猜,这是 agent/人工的位置。"""
    got = propose_for_board(
        [{"home": "普拉滕斯", "away": "科金博联"}], resolved={}, fixtures=_FIXTURES)
    assert not got["proposals"]
    assert "双边均未解析" in got["unresolvable"][0]["reason"]


def test_ambiguous_candidates_are_not_written():
    """已解析队当日有多场(如一线队+U20 同名混入) → 歧义,只报告。"""
    fx = _FIXTURES + [{"teams": {"home": {"name": "Palmeiras"},
                                 "away": {"name": "Botafogo"}}}]
    got = propose_for_board([{"home": "帕尔梅拉斯", "away": "波特诺"}],
                            resolved={"帕尔梅拉斯": "Palmeiras"}, fixtures=fx)
    assert not got["proposals"]
    assert "候选歧义" in got["unresolvable"][0]["reason"]


def test_no_fixture_found_reported():
    got = propose_for_board([{"home": "帕尔梅拉斯", "away": "波特诺"}],
                            resolved={"帕尔梅拉斯": "Palmeiras"}, fixtures=[])
    assert "未找到" in got["unresolvable"][0]["reason"]


def test_apply_writes_only_new_keys(tmp_path):
    alias = tmp_path / "aliases.json"
    alias.write_text(json.dumps({"_comment": "x", "已有队": "Existing FC"},
                                ensure_ascii=False), "utf-8")
    lines = apply_proposals(
        [{"cn": "波特诺", "candidate_en": "Cerro Porteno", "via": "Palmeiras",
          "fixture": "f"},
         {"cn": "已有队", "candidate_en": "Other FC", "via": "X", "fixture": "f"}],
        alias_path=alias)
    table = json.loads(alias.read_text("utf-8"))
    assert table["波特诺"] == "Cerro Porteno"
    assert table["已有队"] == "Existing FC"          # 已存在不覆盖
    assert any("跳过" in ln for ln in lines)
