# tests/decision/test_alias_audit.py
from nutmeg.decision.alias_audit import (
    audit_board,
    audit_day,
    audit_history,
    board_matches,
    format_audit,
    format_history,
)


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


def test_audit_clean_board_has_no_gaps():
    """已收录的国家队盘面 = 零缺口(别名表本身的正样本)。"""
    report = audit_board(_board([_row("瑞超", "荷兰", "巴西")]))
    assert report["odds_alias"]["missing_teams"] == []
    assert report["odds_alias"]["covered_matches"] == 1
    assert "无缺口" in format_audit("2026-08-05", report)


def test_format_audit_names_the_fix_path():
    report = audit_board(_board([_row("火星联赛", "无名甲", "无名乙")]))
    text = format_audit("2026-08-05", report)
    assert "jczq_club_team_aliases.json" in text          # 采集侧修法
    assert "decision-entities-sync" in text               # 实体侧修法
    assert "无名甲" in text


def test_audit_day_without_snapshot_is_not_a_failure(tmp_path):
    report = audit_day("2026-08-05", tmp_path)
    assert report["n_matches"] == 0
    assert report["note"] == "无体彩快照"


def test_audit_history_aggregates_across_days(tmp_path):
    """--history 是"加完别名后"的验收口径:按联赛给出仍在丢锚的场次。"""
    import json
    days = {
        "2026-08-01": [_row("瑞超", "荷兰", "巴西")],                  # 双边命中
        "2026-08-02": [_row("火星联赛", "虚构甲", "虚构乙"),           # 双边缺
                       _row("瑞超", "荷兰", "虚构丙")],                # 单边缺
    }
    for day, rows in days.items():
        d = tmp_path / "daily" / day
        d.mkdir(parents=True)
        (d / "sporttery_markets.json").write_text(
            json.dumps(_board(rows), ensure_ascii=False), encoding="utf-8")
    report = audit_history(tmp_path)
    assert report["n_days"] == 2 and report["n_matches"] == 3
    assert report["covered_matches"] == 1
    assert report["by_league"]["火星联赛"] == {"n": 1, "covered": 0}
    assert report["by_league"]["瑞超"] == {"n": 2, "covered": 1}
    assert report["missing_teams"]["虚构甲"] == 1
    text = format_history(report)
    assert "33.3%" in text and "火星联赛: 1/1" in text


def test_audit_history_on_empty_dir_is_clean(tmp_path):
    report = audit_history(tmp_path)
    assert report["n_matches"] == 0 and report["by_league"] == {}
    assert "全覆盖" in format_history(report)
