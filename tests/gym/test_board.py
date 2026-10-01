import json
from pathlib import Path

import pytest

from nutmeg.gym.board import list_days, list_issues, load_jczq_board, load_zucai_issue

DAY = "2026-09-20"


def _match(code: str, *, single: int, had=("1.85", "3.40", "3.90"), hhad=None, status="Selling"):
    row = {"matchStatus": status, "businessDate": DAY, "matchNumStr": code, "matchNum": 7001,
           "matchId": 2040001 + int(code[-3:]), "matchDate": DAY, "matchTime": "19:30:00",
           "homeTeamAbbName": f"H{code[-1]}", "awayTeamAbbName": f"A{code[-1]}",
           "leagueAbbName": "英超",
           "had": {"h": had[0], "d": had[1], "a": had[2], "goalLine": ""},
           "ttg": {"s0": "6.5", "s0f": "0", "s1": "3.9", "s2": "3.3", "s3": "4.1", "s4": "6.5",
                   "s5": "12", "s6": "25", "s7": "40", "goalLine": ""},
           "crs": {"s01s00": "7.5", "s01s00f": "0", "s00s00": "9.0", "goalLine": ""},
           "poolList": [{"poolCode": "HAD", "single": single, "allUp": 1},
                        {"poolCode": "HHAD", "single": 0, "allUp": 1}]}
    if hhad:
        row["hhad"] = {"h": hhad[0], "d": hhad[1], "a": hhad[2], "goalLine": hhad[3],
                       "goalLineValue": f"{float(hhad[3]):.2f}"}
    return row


def _jczq_day(tmp_path: Path, day: str = DAY) -> Path:
    data = tmp_path / "data"
    day_dir = data / "jczq" / "daily" / day
    day_dir.mkdir(parents=True)
    doc = {"matchInfoList": [{"businessDate": day, "subMatchList": [
        _match("周六001", single=1, hhad=("5.75", "4.25", "1.39", "-1")),
        _match("周六002", single=0),
        _match("周六003", single=1, status="Closed"),
    ]}], "allUpList": {"HAD": [{"formula": "2x1"}, {"formula": "3x1"}, {"formula": "Single"}]}}
    (day_dir / "sporttery_markets.json").write_text(json.dumps(doc, ensure_ascii=False),
                                                     encoding="utf-8")
    (day_dir / "closing_odds.json").write_text(json.dumps({"周六001": {"sharp": {
        "fair_probability": {"home": 0.52, "draw": 0.26, "away": 0.22}}}}), encoding="utf-8")
    (data / "jczq" / "jc-results.json").write_text(json.dumps({day: {
        "周六001": {"match_id": "1", "ft_home": 2, "ft_away": 0},
        "周六002": {"match_id": "2", "ft_home": None, "ft_away": None}}}), encoding="utf-8")
    return data


def _zucai_issue(tmp_path: Path, issue: str = "26127") -> Path:
    data = tmp_path / "data"
    zdir = data / "zucai"
    zdir.mkdir(parents=True, exist_ok=True)
    (zdir / f"{issue}-issue.json").write_text(json.dumps({
        "issue_id": issue, "sale_deadline": "2026-09-16 17:30",
        "matches": [{"match_no": i, "home_team": f"H{i}", "away_team": f"A{i}",
                     "kickoff_bj": "2026-09-17 02:00"} for i in range(1, 15)]}), encoding="utf-8")
    (zdir / f"{issue}-odds.json").write_text(json.dumps({"issue_id": issue, "matches": [
        {"match_no": i, "home": 1.9, "draw": 3.5, "away": 4.0} for i in range(1, 15)]}),
        encoding="utf-8")
    (zdir / "official-prizes.json").write_text(json.dumps({"issues": {issue: {
        "draw_date": "2026-09-18", "results": "3 3 0 0 3 3 1 3 3 0 3 0 3 *", "void_matches": [14],
        "renjiu": {"stake_count": 50908, "stake_amount": 176.0},
        "sfc_first": {"stake_count": 401, "stake_amount": 17339.0},
        "sfc_second": {"stake_count": 9340, "stake_amount": 319.0}}}}), encoding="utf-8")
    return data


def test_jczq_board_only_exposes_pre_kickoff_information(tmp_path: Path) -> None:
    data = _jczq_day(tmp_path)
    board = load_jczq_board(data, DAY)

    assert set(board.matches) == {"周六001", "周六002"}          # Closed 的场不进策略视野
    assert set(board.extra) == {"周六003"} and board.lookup("周六003").selling is False
    m = board.matches["周六001"]
    assert m.had == {"3": 1.85, "1": 3.4, "0": 3.9}
    assert m.hhad == {"line": -1.0, "3": 5.75, "1": 4.25, "0": 1.39}
    assert m.ttg["0"] == 6.5 and m.ttg["7"] == 40.0 and m.crs["s01s00"] == 7.5
    assert m.single_allowed == {"had": True, "hhad": False}
    assert board.matches["周六002"].single_allowed["had"] is False
    assert board.matches["周六002"].hhad is None and board.matches["周六002"].closing_fair is None
    assert m.closing_fair == {"home": 0.52, "draw": 0.26, "away": 0.22}
    assert m.belief_market == pytest.approx({"home": 0.4954, "draw": 0.2696, "away": 0.2350},
                                            abs=1e-3)
    assert board.results == {"周六001": {"outcome_90": "home", "goals_h": 2, "goals_a": 0}}
    assert board.allup["had"] == ["2x1", "3x1", "Single"]

    vis = board.visible()
    assert vis.results == {} and vis.extra == {} and vis.matches is board.matches


def test_board_backfills_early_kickoffs_from_the_previous_snapshot_and_keeps_next_day_rows(
    tmp_path: Path,
) -> None:
    data = _jczq_day(tmp_path)
    prev = data / "jczq" / "daily" / "2026-09-19"
    prev.mkdir()
    early = _match("周六000", single=1, had=("1.50", "4.00", "6.00"))
    early["businessDate"] = DAY
    nxt = _match("周日001", single=0, had=("2.00", "3.30", "3.60"))
    nxt["businessDate"] = "2026-09-21"
    (prev / "sporttery_markets.json").write_text(json.dumps({"matchInfoList": [
        {"businessDate": "2026-09-19", "subMatchList": [early]}]}, ensure_ascii=False),
        encoding="utf-8")
    today = json.loads((data / "jczq" / "daily" / DAY / "sporttery_markets.json")
                       .read_text(encoding="utf-8"))
    today["matchInfoList"].append({"businessDate": "2026-09-21", "subMatchList": [nxt]})
    (data / "jczq" / "daily" / DAY / "sporttery_markets.json").write_text(
        json.dumps(today, ensure_ascii=False), encoding="utf-8")
    results = json.loads((data / "jczq" / "jc-results.json").read_text(encoding="utf-8"))
    results[DAY]["周六000"] = {"match_id": "0", "ft_home": 1, "ft_away": 1, "ht_home": 0,
                              "ht_away": 1}
    results["2026-09-21"] = {"周日001": {"match_id": "9", "ft_home": 0, "ft_away": 2}}
    (data / "jczq" / "jc-results.json").write_text(json.dumps(results), encoding="utf-8")

    board = load_jczq_board(data, DAY)

    assert "周六000" not in board.matches and board.lookup("周六000").had["3"] == 1.5
    assert board.lookup("周日001").business_date == "2026-09-21"
    assert board.results["周六000"] == {"outcome_90": "draw", "goals_h": 1, "goals_a": 1,
                                       "ht_h": 0, "ht_a": 1}
    assert board.results["周日001"]["outcome_90"] == "away"
    assert "周日001" not in board.visible().extra


def test_zucai_issue_devigs_raw_odds_and_carries_prizes(tmp_path: Path) -> None:
    data = _zucai_issue(tmp_path)
    issue = load_zucai_issue(data, "26127")

    assert len(issue.matches) == 14
    assert abs(sum(issue.matches["1"].fair.values()) - 1) < 1e-9
    assert issue.matches["1"].fair["home"] == pytest.approx(0.4956, abs=1e-3)
    assert issue.results == "3 3 0 0 3 3 1 3 3 0 3 0 3 *" and issue.void == {14}
    assert issue.prizes["renjiu"]["stake_amount"] == 176.0
    vis = issue.visible()
    assert vis.prizes is None and vis.results is None and vis.void == set()


def test_list_days_and_issues_skip_incomplete(tmp_path: Path) -> None:
    data = _jczq_day(tmp_path)
    (data / "jczq" / "daily" / "2026-09-21").mkdir()
    (data / "jczq" / "daily" / "2026-09-21" / "sporttery_markets.json").write_text("{}",
                                                                                  encoding="utf-8")
    _zucai_issue(tmp_path)
    (data / "zucai" / "26128-issue.json").write_text("{}", encoding="utf-8")   # 无 odds/奖金

    assert list_days(data) == [DAY]                      # 09-21 无赛果
    assert list_issues(data) == ["26127"]
    with pytest.raises(FileNotFoundError):
        load_jczq_board(data, "2026-09-22")


def test_board_marks_registered_void_matches(tmp_path: Path) -> None:
    data = _jczq_day(tmp_path)
    (data / "jczq" / "void-matches.json").write_text(json.dumps({DAY: ["周六002"]}),
                                                     encoding="utf-8")
    board = load_jczq_board(data, DAY)
    assert board.results["周六002"] == {"void": True}
    assert board.results["周六001"]["outcome_90"] == "home"      # 有赛果的不受影响


def _history_data(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    (data / "jczq" / "daily" / "2025-12-14").mkdir(parents=True)
    (data / "jczq" / "jc-history.json").write_text(json.dumps({"2025-12-14": {
        "周日001": {"match_id": "1", "ft_home": 2, "ft_away": 0, "ht_home": 1, "ht_away": 0,
                  "line": "-1", "home": "A", "away": "B",
                  "sp": {"had": {"outcome": "胜", "odds": 1.45},
                         "hhad": {"outcome": "平", "line": -1.0, "odds": 3.1}}},
        "周日002": {"match_id": "2", "ft_home": 0, "ft_away": 0, "home": "C", "away": "D",
                  "sp": None},
        "周日003": {"match_id": "3", "ft_home": 1, "ft_away": 0, "home": "E", "away": "F",
                  "sp": {"had": {"outcome": "胜", "odds": 1.3}}}}}), encoding="utf-8")
    (data / "jczq" / "daily" / "2025-12-14" / "closing_odds.json").write_text(json.dumps({
        "周日001": {"sharp": {"fair_probability": {"home": 0.74, "draw": 0.16, "away": 0.10}}},
        "周日003": {"sharp": {"fair_probability": {"home": 0.80, "draw": 0.12, "away": 0.08}}}}),
        encoding="utf-8")
    return data


def test_history_board_uses_closing_as_belief_and_sp_for_settlement(tmp_path: Path) -> None:
    data = _history_data(tmp_path)
    with pytest.raises(FileNotFoundError):
        load_jczq_board(data, "2025-12-14")                      # 没有快照、未允许历史板
    board = load_jczq_board(data, "2025-12-14", allow_history=True)

    assert board.source == "history_sp" and set(board.matches) == {"周日001", "周日003"}
    assert "周日002" in board.extra and board.lookup("周日002").selling is False   # 没卖胜平负
    m = board.matches["周日001"]
    assert m.had == {} and m.belief_any == {"home": 0.74, "draw": 0.16, "away": 0.10}
    assert m.sp["had"] == {"outcome": "胜", "odds": 1.45}
    assert board.extra["周日002"].belief_any is None              # 无终盘
    assert board.results["周日001"] == {"outcome_90": "home", "goals_h": 2, "goals_a": 0,
                                       "ht_h": 1, "ht_a": 0}
    assert list_days(data) == [] and list_days(data, include_history=True) == ["2025-12-14"]
