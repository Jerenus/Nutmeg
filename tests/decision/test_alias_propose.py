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


def test_zucai_short_names_resolve_via_zgzcw_full_name_or_unique_league_prefix():
    """2026-10-08 26136：「埃因霍」「格勒诺」在种子里有画像，前提卡却报「store 无记录」。"""
    from nutmeg.decision.alias_propose import propose_zucai_aliases

    teams = [
        {"team_id": "ned-psv", "name_zh": "埃因霍温", "aliases": [], "competition_ids": ["ned"]},
        {"team_id": "fra-grenoble", "name_zh": "格勒诺布尔", "aliases": [],
         "competition_ids": ["fra2"]},
        {"team_id": "fra-guingamp", "name_zh": "甘冈", "aliases": [], "competition_ids": ["fra2"]},
        {"team_id": "eng-x", "name_zh": "格勒诺斯", "aliases": [], "competition_ids": ["eng"]},
    ]
    table = {"埃因霍温": "ned-psv", "格勒诺布尔": "fra-grenoble", "甘冈": "fra-guingamp"}
    matches = [
        {"match_no": 1, "home_team": "埃因霍", "away_team": "海伦芬", "competition": "荷甲",
         "kickoff_bj": "2026-10-10 02:00"},
        {"match_no": 2, "home_team": "甘冈", "away_team": "格勒诺", "competition": "法乙",
         "kickoff_bj": "2026-10-10 02:00"},
    ]
    kickoff = "2026-10-10 02:00:00"
    rows = [  # zgzcw 按期次顺序；两站短名不同（海伦芬 vs 赫伦芬也照样按序对齐）
        {"hostNameFull": "埃因霍温", "guestNameFull": "赫伦芬", "gameStartDate": kickoff},
        {"hostNameFull": "甘冈", "guestNameFull": "格勒诺布", "gameStartDate": kickoff},
    ]
    league = {"荷甲": "ned", "法乙": "fra2"}.get

    got = propose_zucai_aliases(matches, rows, teams, table, league)

    assert {(p["cn"], p["team_id"]) for p in got["proposals"]} == {
        ("埃因霍", "ned-psv"), ("格勒诺", "fra-grenoble")}   # 跨联赛的「格勒诺斯」不算候选
    assert [u["cn"] for u in got["unresolved"]] == ["海伦芬"]
    assert "译名不同" in got["unresolved"][0]["reason"]


def test_apply_entity_aliases_appends_once_and_keeps_seed_format(tmp_path):
    import json

    from nutmeg.decision.alias_propose import apply_entity_aliases

    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"teams": [{"team_id": "ned-psv", "aliases": ["PSV"]}]},
                               ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    proposal = {"cn": "埃因霍", "team_id": "ned-psv", "via": "zgzcw"}
    assert apply_entity_aliases([proposal, proposal], seed) == ["+ 埃因霍 → ned-psv  （zgzcw）"]
    text = seed.read_text(encoding="utf-8")
    assert json.loads(text)["teams"][0]["aliases"] == ["PSV", "埃因霍"] and text.endswith("]\n}\n")
