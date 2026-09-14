# tests/decision/test_zucai_prep.py
from nutmeg.decision.zucai_prep import (
    align_to_sporttery,
    board_dates,
    diff_prep,
    heartbeat_line,
    render_brief,
    screens,
)


def _zm(no, home, away, comp="荷甲", date="2026-08-09"):
    return {"match_no": no, "home_team": home, "away_team": away,
            "competition": comp, "match_date": date}


def _board(rows):
    return {"matchInfoList": [{"subMatchList": rows}]}


def _row(num, home, away):
    return {"matchNum": num, "homeTeamAllName": home, "awayTeamAllName": away}


def test_alignment_uses_alias_table_for_name_variants():
    """足彩写"埃因霍温"、体彩写"PSV埃因霍温",别名表把两者映到同一英文名。

    纯前缀规则在这里会漏(前者是后者的**后缀**),而漏掉 = 静默丢 ttg 形状约束。
    """
    resolve = {"埃因霍温": "PSV Eindhoven", "PSV埃因霍温": "PSV Eindhoven",
               "福图纳": "Fortuna Sittard", "福图纳锡塔德": "Fortuna Sittard"}.get
    got = align_to_sporttery([_zm(6, "埃因霍温", "福图纳")],
                             _board([_row(6018, "PSV埃因霍温", "福图纳锡塔德")]),
                             resolve=resolve)
    assert got["mapping"] == {6: "6018"}
    assert not got["unmatched"]


def test_alignment_reports_matches_absent_from_the_board():
    """有些场次是真的不在竞彩板上(英联赛杯)。那是事实,但必须显式列出来——
    静默降级正是 8/04 整板丢锚而无人知的形状。"""
    got = align_to_sporttery([_zm(3, "德比郡", "林肯城", comp="英联赛杯")],
                             _board([]), resolve=lambda _n: None)
    assert got["mapping"] == {}
    assert got["unmatched"][0]["competition"] == "英联赛杯"


def test_alignment_flags_ambiguity_instead_of_guessing():
    resolve = {"甲队": "A", "乙队": "B"}.get
    got = align_to_sporttery([_zm(1, "甲队", "乙队")],
                             _board([_row(1, "甲队", "乙队"), _row(2, "甲队", "乙队")]),
                             resolve=resolve)
    assert got["mapping"] == {} and got["ambiguous"][0]["candidates"] == ["1", "2"]


def test_board_dates_span_neighbouring_business_days():
    """深夜场的体彩业务日会落在前一天,只读 run_date 那一份会漏。"""
    dates = board_dates("2026-08-09", [_zm(1, "a", "b", date="2026-08-10")])
    assert {"2026-08-08", "2026-08-09", "2026-08-10", "2026-08-11"} <= set(dates)


def _rec(no, home, draw, away, name=None, ttg=True):
    return {"name": name or f"m{no}", "fair_had": {"home": home, "draw": draw, "away": away},
            "ttg_anchor": ttg}


def test_screens_are_candidate_pools_not_conclusions():
    recs = {"1": _rec(1, 0.86, 0.10, 0.04, "强锚"),
            "2": _rec(2, 0.40, 0.28, 0.32, "抛硬币"),
            "3": {"name": "丢锚", "fair_had": None}}
    got = screens(recs)
    assert [s["name"] for s in got["strong_anchors"]] == ["强锚"]
    assert [s["name"] for s in got["coinflip"]] == ["抛硬币"]
    assert [m["name"] for m in got["missing_euro_anchor"]] == ["丢锚"]
    # 平局面值降序:抛硬币场的平比强锚场肥
    assert got["fattest_draws"][0]["name"] == "抛硬币"


def test_diff_reports_only_moves_above_threshold():
    base = {"records": {"1": _rec(1, 0.50, 0.25, 0.25), "2": _rec(2, 0.40, 0.30, 0.30)},
            "slot": "afternoon", "captured_at": "t0"}
    later = {"records": {"1": _rec(1, 0.53, 0.24, 0.23), "2": _rec(2, 0.402, 0.299, 0.299)},
             "slot": "revision", "captured_at": "t1", "issue": "26103"}
    got = diff_prep(base, later)
    assert got["n_moved"] == 1
    assert got["moves"][0]["match_no"] == 1
    assert got["moves"][0]["delta_pp"]["home"] == 3.0


def test_heartbeat_speaks_on_a_no_issue_day():
    """无期日也要发——这正是 7/21 静默死亡三周没被发现的原因。"""
    line = heartbeat_line(None, "今日无期。下一期 26103 截止 2026-08-11 22:00")
    assert "26103" in line and "今日无期" in line


def test_brief_leaves_the_judgment_table_empty():
    """备料只出事实与确定性算术;旗/共振/动作/选面必须是空表而不是预填结论。"""
    prep = {"issue": "26103", "slot": "afternoon", "captured_at": "t",
            "run_date": "2026-08-11", "n_matches": 1,
            "alignment": {"unmatched": [], "ambiguous": []},
            "records": {"1": {**_rec(1, 0.5, 0.25, 0.25, "甲-乙"), "league": "荷甲",
                              "kickoff_bj": "08-11 20:30", "over25": 0.55,
                              "top_scores": [["1:1", 0.12]], "hhad_line": "-1",
                              "sporttery_had_date": "2026-08-11"}},
            "screens": screens({"1": _rec(1, 0.5, 0.25, 0.25, "甲-乙")}),
            "judgment": None}
    md = render_brief(prep)
    assert "## 判读(待主循环填写)" in md
    assert "| 1 |  |  |  |  |  |" in md          # 空行,不是预填
    assert "候选池,不是结论" in md


# --- titan007 国际欧赔并入备料(只补充,不替换 500.com 基线)-----------------------

def _prep_dirs(tmp_path, *, intl: dict | None = None):
    """最小可跑的 zucai/output 目录。返回 PrepInputs。"""
    import json

    from nutmeg.decision.zucai_prep import PrepInputs

    zdir = tmp_path / "zucai"
    zdir.mkdir(parents=True)
    (zdir / "26125-issue.json").write_text(json.dumps({
        "issue_id": "26125",
        "matches": [{"match_no": 1, "competition": "意甲", "home_team": "都灵",
                     "away_team": "罗马", "kickoff_bj": "2026-09-15 00:30",
                     "match_date": "2026-09-15"}],
    }, ensure_ascii=False), encoding="utf-8")
    (zdir / "26125-odds.json").write_text(json.dumps({
        "issue_id": "26125",
        "matches": [{"match_no": 1, "home": 6.0, "draw": 4.3, "away": 1.64}],
    }, ensure_ascii=False), encoding="utf-8")
    if intl is not None:
        (zdir / "26125-odds-intl.json").write_text(
            json.dumps(intl, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "jczq"
    (out / "daily" / "2026-09-14").mkdir(parents=True)
    return PrepInputs(issue="26125", run_date="2026-09-14", slot="afternoon",
                      zucai_dir=zdir, output_dir=out)


_INTL = {
    "issue_id": "26125",
    "matches": [{
        "match_no": 1,
        "fair": {"home": 0.162, "draw": 0.226, "away": 0.612},
        "odds": {"home": 5.9, "draw": 4.2, "away": 1.62},
        "opening_odds": {"home": 5.2, "draw": 4.0, "away": 1.70},
        "books": 15,
        "micro": {"drift_pp": 6.92, "dispersion_pp": 0.95, "payout_delta_pp": 0.61},
        "jczq_match_no": "周一004",
        "titan007_match_id": "2993793",
    }],
}


def test_prep_attaches_international_odds_when_present(tmp_path):
    from nutmeg.decision.zucai_prep import build_prep

    prep = build_prep(_prep_dirs(tmp_path, intl=_INTL))
    rec = prep["records"]["1"]
    assert rec["intl"]["books"] == 15
    assert rec["intl"]["jczq_match_no"] == "周一004"
    assert rec["intl"]["micro"]["drift_pp"] == 6.92


def test_prep_keeps_the_500com_baseline_as_the_fair_anchor(tmp_path):
    """国际欧赔是补充,不是替换。

    直接把 fair_had 换成 titan007 会静默改变足彩判读层的输入分布——那属判据变更,
    须先有证据再由用户裁定,与竞彩换源走同一条规矩。
    """
    from nutmeg.decision.zucai_prep import build_prep

    with_intl = build_prep(_prep_dirs(tmp_path / "a", intl=_INTL))
    without = build_prep(_prep_dirs(tmp_path / "b"))
    assert with_intl["records"]["1"]["fair_had"] == without["records"]["1"]["fair_had"]
    assert without["records"]["1"]["intl"] is None


def test_prep_runs_unchanged_when_the_intl_file_is_absent(tmp_path):
    from nutmeg.decision.zucai_prep import build_prep

    prep = build_prep(_prep_dirs(tmp_path))
    assert prep["records"]["1"]["intl"] is None


def test_brief_shows_the_international_consensus_and_its_drift(tmp_path):
    from nutmeg.decision.zucai_prep import build_prep, render_brief

    brief = render_brief(build_prep(_prep_dirs(tmp_path, intl=_INTL)))
    assert "国际欧赔" in brief
    assert "周一004" in brief          # 对齐来源可追
    assert "6.92" in brief             # drift 可见
