# tests/decision/test_alias_audit.py
from nutmeg.decision.alias_audit import audit_board, audit_day, board_matches


def _board(rows):
    return {"matchInfoList": [{"subMatchList": rows}]}


def _row(league, home, away):
    return {"leagueAbbName": league, "homeTeamAbbName": home, "awayTeamAbbName": away}


def test_board_matches_flattens_and_skips_junk():
    value = _board([_row("瑞超", "哈马比", "AIK"), {"noise": 1}])
    assert len(board_matches(value)) == 1
    assert board_matches({}) == []


def test_audit_flags_missing_odds_alias_per_match():
    """双边命中才有 fair 锚——单边缺失即整场丢锚(8/04 的真实失败形状)。

    用虚构队名而非真实缺口:真实缺口一旦补进别名表,断言就会变成"测试昨天的世界"。
    """
    report = audit_board(_board([
        _row("欧冠", "虚构甲队", "虚构乙队"),     # 双边缺失
        _row("欧冠", "荷兰", "虚构丙队"),         # 单边缺失(荷兰在国家队表里)
    ]))
    assert report["n_matches"] == 2
    missing = {r["name"] for r in report["odds_alias"]["missing_teams"]}
    assert {"虚构甲队", "虚构乙队", "虚构丙队"} == missing
    assert report["odds_alias"]["covered_matches"] == 0    # 单边缺 = 整场丢锚


def test_audit_flags_unresolved_league_entity():
    report = audit_board(_board([_row("火星联赛", "甲队", "乙队")]))
    assert [r["name"] for r in report["entity_alias"]["missing_leagues"]] == ["火星联赛"]
    assert report["entity_alias"]["missing_leagues"][0]["count"] == 1


def test_audit_day_without_snapshot_is_not_a_failure(tmp_path):
    report = audit_day("2026-08-05", tmp_path)
    assert report["n_matches"] == 0
    assert report["note"] == "无体彩快照"


