"""球队损耗台账（2026-10-09 设计稿 docs/superpowers/specs/2026-10-09-team-load-ledger-design.md）。

只做取数与确定性算术：出场索引 → 每队特征 → 每场派生 → 落盘冻结。不产生判断。"""
import json
from datetime import date
from pathlib import Path

from nutmeg.decision.team_load import (
    LoadIndex,
    absences,
    build_index,
    match_row,
    merge_rows,
    write_jczq_ledger,
    write_zucai_ledger,
)

D = date(2026, 10, 9)


def _index(resolve=None) -> LoadIndex:
    return LoadIndex(resolve=resolve or (lambda name: None))


def test_features_count_rest_days_and_the_14_day_window_up_to_two_days_before():
    idx = _index()
    for day in ("2026-09-20", "2026-09-25", "2026-09-28", "2026-10-02", "2026-10-07"):
        idx.add("多特", date.fromisoformat(day))
    f = idx.features("多特", D)
    assert f["rest_days"] == 2                       # 10-07 → 10-09
    assert f["matches_14d"] == 4                     # 窗口 [09-25, 10-07]：09-20 在窗外
    assert f["long_break"] is False


def test_an_appearance_within_a_day_of_the_match_is_the_same_match_not_a_previous_one():
    # 各源对深夜场归日不一（业务日 vs 开球日），±1 天的出场就是这场本身
    idx = _index()
    idx.add("PSV", date(2026, 9, 20))
    idx.add("PSV", date(2026, 10, 8))
    idx.add("PSV", date(2026, 10, 10))
    f = idx.features("PSV", D)
    assert f["rest_days"] == 19 and f["matches_14d"] == 0 and f["long_break"] is True
    assert f["next_days"] is None


def test_next_days_looks_ahead_up_to_ten_days():
    idx = _index()
    idx.add("维京", date(2026, 10, 13))
    idx.add("维京", date(2026, 10, 25))
    assert idx.features("维京", D)["next_days"] == 4
    assert idx.features("无此队", D) == {"rest_days": None, "matches_14d": 0,
                                         "next_days": None, "long_break": False}


def test_names_resolving_to_one_team_id_share_appearances_across_sources():
    table = {"多特": "ger-bvb", "多特蒙德": "ger-bvb"}
    idx = _index(resolve=table.get)
    idx.add("多特蒙德", date(2026, 10, 2))
    assert idx.features("多特", D)["rest_days"] == 7
    assert idx.key("多特") == "ger-bvb" and idx.key("不来梅") == "name:不来梅"


def test_match_row_derives_diffs_and_flags():
    idx = _index()
    for day in ("2026-09-26", "2026-09-29", "2026-10-02", "2026-10-05"):
        idx.add("甲", date.fromisoformat(day))
    idx.add("乙", date(2026, 9, 20))
    idx.add("乙", date(2026, 10, 12))
    row = match_row(idx, key="2026-10-09-周五001", home="甲", away="乙",
                    kickoff="2026-10-09T20:00:00+08:00", captured_at="2026-10-09T12:30:00+08:00")
    assert row["home_load"]["matches_14d"] == 4 and row["away_load"]["matches_14d"] == 0
    assert row["load_diff_14"] == 4 and row["rest_diff"] == 4 - 19
    assert set(row["flags"]) == {"单边密集:home", "负荷差≥2:home", "下场≤3天:away", "长歇:away"}
    assert row["key"] == "2026-10-09-周五001" and row["captured_at"].startswith("2026-10-09T12:30")


def test_absences_come_from_the_research_rubric_only():
    rubric = {"items": {
        "F_absence_home": {"answer": "yes", "p": 0.9},
        "F_absence_away": {"answer": "no", "p": 0.3},
        "F_suspension": {"answer": "away", "p": 0.95},
        "F_rotation": {"answer": "unknown", "p": None, "abstain": True},
        "S_spine_intact": {"answer": "no", "p": 0.25},   # p＝命题（中轴完整）为真的概率
        "S_anchor_side": {"answer": "home", "p": 0.7},
    }}
    assert absences(rubric) == {"home": ["缺阵", "中轴缺"], "away": ["停赛"]}
    assert absences(None) == {"home": [], "away": []}


def test_merge_keeps_rows_whose_match_already_kicked_off():
    old = {"1": {"kickoff": "2026-10-09T19:00:00+08:00", "captured_at": "old"},
           "2": {"kickoff": "2026-10-09T23:00:00+08:00", "captured_at": "old"}}
    new = {"1": {"kickoff": "2026-10-09T19:00:00+08:00", "captured_at": "new"},
           "2": {"kickoff": "2026-10-09T23:00:00+08:00", "captured_at": "new"},
           "3": {"kickoff": "2026-10-10T01:00:00+08:00", "captured_at": "new"}}
    merged = merge_rows(old, new, now="2026-10-09T20:00:00+08:00")
    assert merged["1"]["captured_at"] == "old"         # 已开球：前瞻样本不许事后改
    assert merged["2"]["captured_at"] == "new" and merged["3"]["captured_at"] == "new"


def _write(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def test_build_index_reads_history_boards_and_zucai_issues(tmp_path: Path):
    data = tmp_path
    _write(data / "jczq" / "jc-history.json",
           {"2026-09-27": {"周六001": {"home": "多特蒙德", "away": "斯图加特"}}})
    _write(data / "jczq" / "daily" / "2026-10-02" / "sporttery_markets.json",
           {"value": {"matchInfoList": [{"subMatchList": [
               {"matchDate": "2026-10-02", "homeTeamAbbName": "多特",
                "homeTeamAllName": "多特蒙德", "awayTeamAbbName": "沃夫斯堡"}]}]}})
    _write(data / "zucai" / "26136-issue.json",
           {"issue_id": "26136", "matches": [
               {"match_no": 2, "home_team": "多特", "away_team": "不来梅",
                "kickoff_bj": "2026-10-10 02:30"}]})
    table = {"多特": "ger-bvb", "多特蒙德": "ger-bvb"}
    idx = build_index(data, resolve=table.get)
    f = idx.features("多特", date(2026, 10, 10))
    assert f["rest_days"] == 8 and f["matches_14d"] == 2


def test_ledgers_key_rows_like_the_corpus_and_freeze_kicked_off_rows(tmp_path: Path):
    data = tmp_path
    _write(data / "jczq" / "daily" / "2026-10-09" / "jczq-legs-base.json", {"legs": {
        "周五001": {"home_team": "甲", "away_team": "乙",
                    "kickoff_bj": "2026-10-09T20:00:00+08:00"}}})
    _write(data / "zucai" / "26136-issue.json", {"issue_id": "26136", "matches": [
        {"match_no": 3, "home_team": "丙", "away_team": "丁", "kickoff_bj": "2026-10-10 00:30"}]})
    _write(data / "zucai" / "26136-research-m3.json",
           {"rubric": {"items": {"F_absence_away": {"answer": "yes", "p": 0.95}}}})
    idx = _index()

    j = write_jczq_ledger(data, "2026-10-09", now="2026-10-09T12:30:00+08:00", index=idx)
    z = write_zucai_ledger(data, "26136", now="2026-10-09T12:30:00+08:00", index=idx)

    jdoc = json.loads(j.read_text("utf-8"))
    zdoc = json.loads(z.read_text("utf-8"))
    assert jdoc["rows"]["周五001"]["key"] == "2026-10-09-周五001"
    assert zdoc["rows"]["3"]["key"] == "26136-3"
    assert zdoc["rows"]["3"]["absences"] == {"home": [], "away": ["缺阵"]}
    assert "coverage" in jdoc and "coverage" in zdoc

    write_jczq_ledger(data, "2026-10-09", now="2026-10-09T21:00:00+08:00", index=idx)
    again = json.loads(j.read_text("utf-8"))
    assert again["rows"]["周五001"]["captured_at"] == "2026-10-09T12:30:00+08:00"


def _day_fixture(data: Path) -> None:
    _write(data / "jczq" / "daily" / "2026-10-09" / "jczq-legs-base.json", {"legs": {
        "周五001": {"home_team": "甲", "away_team": "乙",
                    "kickoff_bj": "2026-10-09T20:00:00+08:00"}}})
    _write(data / "zucai" / "26136-issue.json", {
        "issue_id": "26136", "sale_deadline": "2026-10-09 22:00", "matches": [
            {"match_no": 3, "home_team": "丙", "away_team": "丁",
             "kickoff_bj": "2026-10-10 00:30"}]})
    _write(data / "zucai" / "26136-store-ids.json", {"3": {"match_id": "m3"}})


def test_write_day_ledgers_covers_the_jczq_board_and_issues_closing_that_day(tmp_path: Path):
    from nutmeg.decision.team_load import write_day_ledgers

    _day_fixture(tmp_path)
    out = write_day_ledgers(tmp_path, "2026-10-09", now="2026-10-09T12:30:00+08:00",
                            index=_index())
    assert out["jczq"].endswith("2026-10-09/team-load.json")
    assert list(out["zucai"]) == ["26136"]
    assert out["zucai"]["26136"].endswith("26136-team-load.json")


def test_attach_hangs_frozen_ledger_rows_on_corpus_rows_by_key(tmp_path: Path):
    from nutmeg.decision.team_load import attach_ledgers

    _write(tmp_path / "jczq" / "daily" / "2026-10-06" / "team-load.json", {"rows": {
        "周二012": {"key": "2026-10-06-周二012", "captured_at": "2026-10-06T12:30:00+08:00",
                    "kickoff": "2026-10-06T20:00:00+08:00", "load_diff_14": 2}}})
    _write(tmp_path / "zucai" / "26135-team-load.json", {"rows": {
        "14": {"key": "26135-14", "captured_at": "2026-10-07T03:00:00+08:00",
               "kickoff": "2026-10-07T02:45:00+08:00", "load_diff_14": 0}}})
    rows = [{"src": "jczq", "key": "2026-10-06-周二012"},
            {"src": "zucai", "key": "26135-14"},
            {"src": "kernel", "key": "k-1"}]
    assert attach_ledgers(rows, tmp_path) == 1
    assert rows[0]["team_load"]["load_diff_14"] == 2
    assert "team_load" not in rows[1]          # 开球后才冻结：不是前瞻样本
    assert "team_load" not in rows[2]


def test_brief_cell_marks_implausible_rest_days_as_a_coverage_gap():
    """赛季中休 >30 天多半是没上板的场次缺失（26136：德乙、法乙、北欧 42–56 天），不能当真。"""
    from nutmeg.decision.team_load import brief_cell

    row = {"home_load": {"rest_days": 42, "matches_14d": 0, "next_days": None,
                         "long_break": True},
           "away_load": {"rest_days": None, "matches_14d": 0, "next_days": None,
                         "long_break": False},
           "flags": ["长歇:home"], "absences": {"home": [], "away": []}}
    assert brief_cell(row) == "休42?/? 14天0/0 ⏸主"


def test_ledger_rows_carry_the_kernel_match_id_for_duty_fulfilment(tmp_path: Path):
    from nutmeg.decision.team_load import jczq_ledger_rows, zucai_ledger_rows

    _day_fixture(tmp_path)
    legs_path = tmp_path / "jczq" / "daily" / "2026-10-09" / "jczq-legs-base.json"
    legs = json.loads(legs_path.read_text("utf-8"))
    legs["legs"]["周五001"]["match_id"] = "M-1"
    legs_path.write_text(json.dumps(legs, ensure_ascii=False), encoding="utf-8")
    now = "2026-10-09T12:30:00+08:00"
    assert jczq_ledger_rows(tmp_path, "2026-10-09", now=now, index=_index())["周五001"][
        "match_id"] == "M-1"
    assert zucai_ledger_rows(tmp_path, "26136", now=now, index=_index())["3"]["match_id"] == "m3"


def test_schedule_store_counts_fixtures_that_never_reached_the_board(tmp_path):
    """2026-10-24：API-Football 日程落盘后，没上竞彩板的场也算出场（修波鸿 56 天假长歇）。"""
    from types import SimpleNamespace

    from nutmeg.decision.team_load import store_fixtures

    fx = [SimpleNamespace(home_team="VfL Bochum", away_team="SC Paderborn 07", status="finished",
                          league_code="2. Bundesliga"),
          SimpleNamespace(home_team="X", away_team="Y", status="postponed", league_code="L")]
    path = store_fixtures(tmp_path, date(2026, 10, 17), fx)
    rows = json.loads(path.read_text("utf-8"))
    assert [r["home"] for r in rows] == ["VfL Bochum"]            # 延期不算出场
    (tmp_path / "jczq").mkdir()
    idx = build_index(tmp_path, resolve=lambda n: {"VfL Bochum": "ger-vfl-bochum"}.get(n))
    f = idx.features("VfL Bochum", date(2026, 10, 24))
    assert f["rest_days"] == 7 and f["matches_14d"] == 1
