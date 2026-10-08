# tests/decision/test_zucai_prep.py
import json
from datetime import datetime

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


def test_alignment_prefers_explicit_channel_map_over_team_names():
    """跨泳道身份已有显式映射时，不再让队名别名决定是否丢锚。"""
    got = align_to_sporttery(
        [_zm(4, "富勒姆", "曼联")],
        _board([_row(7020, "富勒姆", "曼彻斯特联")]),
        resolve=lambda _n: None,
        explicit_mapping={4: "7020"},
    )
    assert got["mapping"] == {4: "7020"}
    assert got["unmatched"] == []


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


def test_prep_uses_explicit_cross_channel_identity_before_team_names(tmp_path):
    import json

    from nutmeg.decision.zucai_prep import build_prep

    inputs = _prep_dirs(tmp_path)
    inputs.zucai_dir.joinpath("26125-channel-map.json").write_text(
        json.dumps({"jczq-match-1": 1}), encoding="utf-8"
    )
    daily = inputs.output_dir / "daily" / inputs.run_date
    daily.joinpath("jczq-legs-base.json").write_text(
        json.dumps({"legs": {"周日020": {"match_id": "jczq-match-1"}}}),
        encoding="utf-8",
    )
    daily.joinpath("sporttery_markets.json").write_text(
        json.dumps(_board([{**_row(7020, "完全不同", "仍然不同"),
                            "matchNumStr": "周日020"}])),
        encoding="utf-8",
    )

    prep = build_prep(inputs)

    assert prep["records"]["1"]["sporttery_match_num"] == "7020"
    assert prep["alignment"] == {"unmatched": [], "ambiguous": []}


def test_brief_shows_the_international_consensus_and_its_drift(tmp_path):
    from nutmeg.decision.zucai_prep import build_prep, render_brief

    brief = render_brief(build_prep(_prep_dirs(tmp_path, intl=_INTL)))
    assert "国际欧赔" in brief
    assert "周一004" in brief          # 对齐来源可追
    assert "6.92" in brief             # drift 可见


def test_blend_fair_is_equal_weight_and_renormalised():
    """两源等权混合 prior。

    证据（2026-09-15，n=264 双源可比样本）：500.com 去水均值 Brier 0.5485、
    titan007 锐盘当前 0.5433；**50/50 等权混合 BSS +0.57%，CI[+0.01,+1.15]，
    CI 下界 > 0**，而纯 titan007(+0.95%) 的 CI[-0.16,+2.06] 含 0。
    机制 = 集成平均降方差（两源误差部分抵消）。
    """
    from nutmeg.decision.zucai_prep import blend_fair

    a = {"home": 0.50, "draw": 0.30, "away": 0.20}
    b = {"home": 0.60, "draw": 0.25, "away": 0.15}
    out = blend_fair(a, b)

    assert out == {"home": 0.55, "draw": 0.275, "away": 0.175}
    assert abs(sum(out.values()) - 1.0) < 1e-9


def test_blend_fair_needs_both_sources():
    """任一源缺失就不混合——宁可用单源，不许拿半份数据冒充混合。"""
    from nutmeg.decision.zucai_prep import blend_fair

    a = {"home": 0.5, "draw": 0.3, "away": 0.2}
    assert blend_fair(a, None) is None
    assert blend_fair(None, a) is None
    assert blend_fair(a, {"home": 0.5}) is None


def test_prep_record_carries_blend_and_keeps_baseline(tmp_path):
    """记录里同时留 fair_had(500.com 基线) 与 fair_blend，**不覆盖基线**。"""
    from nutmeg.decision.zucai_prep import attach_blend

    rec = {"fair_had": {"home": 0.50, "draw": 0.30, "away": 0.20},
           "intl": {"fair": {"home": 0.60, "draw": 0.25, "away": 0.15}}}
    attach_blend(rec)

    assert rec["fair_had"] == {"home": 0.50, "draw": 0.30, "away": 0.20}
    assert rec["fair_blend"] == {"home": 0.55, "draw": 0.275, "away": 0.175}
    assert rec["fair_source"] == "blend_500_titan007_5050"


def test_prep_record_without_intl_has_no_blend(tmp_path):
    from nutmeg.decision.zucai_prep import attach_blend

    rec = {"fair_had": {"home": 0.5, "draw": 0.3, "away": 0.2}, "intl": None}
    attach_blend(rec)

    assert rec["fair_blend"] is None
    assert rec["fair_source"] == "c500_only"


def test_blend_refuses_when_sources_contradict():
    """两源严重分歧 = 大概率对齐错了，**拒绝混合**而不是取平均。

    2026-09-15 实测：26125 场1 的 500.com 给主胜 84.7%、titan007 给客胜 89.2%
    （titan007 侧对齐到了「中国女足-中国香港女足」）。等权平均得到
    44.3/8.8/46.9 —— 看起来完全正常的垃圾。静默平均两个互相矛盾的源，
    正是「假数据比没数据更危险」的那一类。
    """
    from nutmeg.decision.zucai_prep import blend_fair

    a = {"home": 0.847, "draw": 0.106, "away": 0.047}
    b = {"home": 0.038, "draw": 0.071, "away": 0.892}
    assert blend_fair(a, b) is None, "互相矛盾的两源不得混合"


def test_blend_tolerates_ordinary_disagreement():
    """常规分歧（同一模态面、幅度温和）仍然混合——闸不能把正常样本也挡掉。"""
    from nutmeg.decision.zucai_prep import blend_fair

    a = {"home": 0.50, "draw": 0.28, "away": 0.22}
    b = {"home": 0.58, "draw": 0.25, "away": 0.17}
    out = blend_fair(a, b)
    assert out is not None
    assert abs(out["home"] - 0.54) < 1e-6


def test_attach_blend_marks_the_contradiction(tmp_path):
    from nutmeg.decision.zucai_prep import attach_blend

    rec = {"fair_had": {"home": 0.847, "draw": 0.106, "away": 0.047},
           "intl": {"fair": {"home": 0.038, "draw": 0.071, "away": 0.892}}}
    attach_blend(rec)

    assert rec["fair_blend"] is None
    assert rec["fair_source"] == "c500_only"
    assert rec["blend_blocked"] == "source_contradiction"


# ── Telegram 推送与实际功能同步（2026-09-14 用户反馈「一直推送无效信息」）──────
#
# 实测 49 条历史推送（zucai.prep + prep-revision 全部日志）：
#   · 🌙「今日无期」心跳 **20/49 = 41%** —— 纯噪音，且新装 morning agent 后
#     无期日从 2 条变 3 条
#   · 「判读待主循环」**29/29** —— 常量字符串，零信息
#   · 「强锚候选 N」29/29 —— 就是 top1≥70 的计数，闭环已证是**价格重述**
#   · 「位移超门槛 N」15 条 —— 而闭环实测**晚盘不优于早盘 BSS -0.07%
#     CI[-0.42,+0.28]**，RUNBOOK B8 早把 18:30 降为事实核对
# 而真正救命的「分歧闸拦截」从未进过推送：26125 场1 两源 84.7 vs 89.5，
# 静默平均得到 44/9/47 的垃圾——**那才是当天唯一需要人知道的事**。


def _prep(**over):
    base = {
        "issue": "26125", "slot": "afternoon", "run_date": "2026-09-14",
        "captured_at": "2026-09-14T14:00:00", "n_matches": 14,
        "alignment": {"unmatched": [], "ambiguous": []},
        "screens": {"strong_anchors": [], "coinflip": [], "missing_euro_anchor": []},
        "records": {},
    }
    base.update(over)
    return base


def test_message_drops_the_constant_and_the_price_restatement():
    from nutmeg.decision.zucai_prep import prep_message

    prep = _prep(screens={"strong_anchors": [{"match_no": 1}, {"match_no": 2}],
                          "coinflip": [], "missing_euro_anchor": []})
    body = prep_message(prep, moved=None)
    assert "判读待主循环" not in body      # 常量,29/29 出现,零信息
    assert "强锚候选" not in body          # 价格重述,闭环已证伪


def test_message_surfaces_the_blend_gate_block():
    """分歧闸拦截必须上推——26125 场1 就是靠它没拿到 44/9/47 的垃圾。"""
    from nutmeg.decision.zucai_prep import prep_message

    prep = _prep(records={
        "1": {"blend_blocked": "source_contradiction", "fair_source": "c500_only"},
        "2": {"fair_source": "blend_500_titan007_5050"},
    })
    body = prep_message(prep, moved=None)
    assert "分歧闸" in body and "场1" in body


def test_message_drops_static_alignment_and_routine_coverage():
    """2026-10-05：「体彩未对齐 N 场」「混合 prior 覆盖 n/m」是板面的静态统计（假期竞彩板空时
    13/14 未对齐是预期），对人没有可操作的内容，Jun 点名为无用资讯——不进推送，备料 md 里照写。"""
    from nutmeg.decision.zucai_prep import prep_message

    prep = _prep(alignment={"unmatched": [{"match_no": 3}, {"match_no": 4}], "ambiguous": []},
                 records={"1": {"fair_blend": {"home": 0.5}}})
    body = prep_message(prep, moved=None)
    assert "未对齐" not in body and "覆盖" not in body


def test_message_names_the_moved_matches():
    """位移推送要说是哪几场、往哪动——只说「位移超门槛 2 条」得再去翻文件。"""
    from nutmeg.decision.zucai_prep import prep_message

    moves = [{"match_no": 4, "name": "冰岛-乌克兰", "delta_pp": {"home": -6.2, "draw": 4.1,
                                                              "away": 2.1}}]
    body = prep_message(_prep(slot="revision"), moved=1, moves=moves)
    assert "场4 冰岛-乌克兰" in body and "主-6.2" in body and "平+4.1" in body


def test_message_calls_out_missing_international_collection():
    from nutmeg.decision.zucai_prep import prep_message

    prep = _prep(
        intl_status="not_collected",
        records={"1": {"fair_had": {"home": 0.5, "draw": 0.3, "away": 0.2}}},
    )
    body = prep_message(prep, moved=None)
    assert "混合 prior 未采集" in body
    assert "混合 prior 覆盖 0/1" not in body


def test_message_calls_out_failed_international_collection():
    from nutmeg.decision.zucai_prep import prep_message

    prep = _prep(intl_status="fetch_failed", records={"1": {}})
    body = prep_message(prep, moved=None)
    assert "混合 prior 采集失败" in body
    assert "混合 prior 覆盖 0/1" not in body


def test_no_issue_day_is_silent():
    """41% 的噪音来源：无期日不再推送。"""
    from nutmeg.decision.zucai_prep import no_issue_message

    assert no_issue_message(stale_days=0) is None
    assert no_issue_message(stale_days=6) is None


def test_long_silence_still_alerts():
    """静默失败必须仍可见——7/21 那次死了三周没人发现。"""
    from nutmeg.decision.zucai_prep import NO_ISSUE_ALERT_DAYS, no_issue_message

    body = no_issue_message(stale_days=NO_ISSUE_ALERT_DAYS)
    assert body is not None and "7" in body


def test_revision_slot_is_silent_without_real_change():
    """RUNBOOK B8 已把 18:30 降为事实核对；无异动就别响。"""
    from nutmeg.decision.zucai_prep import should_push

    quiet = _prep(slot="revision")
    assert should_push(quiet, slot="revision", moved=0, base_prep=_prep()) is False
    assert should_push(quiet, slot="revision", moved=3) is True
    # 分歧闸状态本身就是异动
    blocked = _prep(slot="revision", records={"1": {"blend_blocked": "x"}})
    assert should_push(blocked, slot="revision", moved=0) is True
    # ⛔未对齐是板面**静态属性**，14:00 已报过——不得把 18:30 再叫醒一次。
    # （26125 有 8 场未对齐，若算异动则 revision 永远会响，等于没做过滤。）
    static = _prep(slot="revision",
                   alignment={"unmatched": [{"match_no": i} for i in range(8)],
                              "ambiguous": []})
    assert should_push(static, slot="revision", moved=0) is False


def test_morning_and_afternoon_also_speak_only_on_real_change():
    """2026-10-05：判读的起点已是 12:00 当日报告与机器初稿（10-01 定位），11:00/14:00 的
    例行统计不再推。三档同一条规则：位移超门槛或分歧闸状态变化才响。"""
    from nutmeg.decision.zucai_prep import should_push

    assert should_push(_prep(slot="morning"), slot="morning", moved=None) is False
    assert should_push(_prep(), slot="afternoon", moved=0, base_prep=_prep(slot="morning")) is False
    assert should_push(_prep(), slot="afternoon", moved=2) is True
    blocked = _prep(slot="morning", records={"1": {"blend_blocked": "x"}})
    assert should_push(blocked, slot="morning", moved=None) is True


def test_run_prep_is_silent_on_a_no_issue_day(tmp_path):
    """端到端：无期日跑一趟，日志照写、Telegram 一条不发。"""
    from nutmeg.decision.zucai_gate import InsaleIssue
    from nutmeg.decision.zucai_prep import run_zucai_prep

    sent = []

    def _spy(kind, key, fingerprint, text, **_kwargs):
        sent.append(text)

    def _gate(**_kw):
        return (InsaleIssue(issue="26130", deadline=datetime(2026, 9, 20, 22, 0)),
                "今日无期。下一期 26130 截止 2026-09-20 22:00(6 天后)")

    result = run_zucai_prep(
        run_date="2026-09-14", slot="afternoon",
        zucai_dir=tmp_path, output_dir=tmp_path, live_fetch=False,
        dispatch=True, gate_fetcher=None, notification_service=_spy,
        gate_fn=_gate,
    )
    assert result.status == "no_issue"
    assert "今日无期" in result.summary        # 日志照写
    assert sent == []                          # Telegram 静默


def test_run_prep_treats_a_closed_issue_page_as_no_issue(tmp_path):
    """10-06 误报：上一期已截止、下一期未开售时，备料应静默记「今日无期」并退出 0，
    不是「探测失败」（后者 exit 1 并推送）。"""
    from nutmeg.decision.zucai_prep import run_zucai_prep

    closed = ('<li class="chked" data-expect="26135" ><i class="ico-chk"></i>当前第26135期</li>'
              '<span>&nbsp;&nbsp;10-05 22:00&nbsp;&nbsp;官方售彩已截止</span>')
    sent = []

    def _spy(kind, key, fingerprint, text, **_kwargs):
        sent.append(text)

    result = run_zucai_prep(
        run_date="2026-10-06", slot="morning",
        zucai_dir=tmp_path, output_dir=tmp_path, live_fetch=False,
        dispatch=True, gate_fetcher=lambda _u: closed, notification_service=_spy,
    )
    assert result.status == "no_issue" and result.succeeded
    assert "今日无期" in result.summary and "探测失败" not in result.summary
    assert sent == []


def test_live_prep_collects_international_prior_before_building(tmp_path, monkeypatch):
    import json

    from nutmeg.decision.zucai_prep import run_zucai_prep

    inputs = _prep_dirs(tmp_path)
    monkeypatch.setattr(
        "nutmeg.decision.zucai_insale.fetch_and_write",
        lambda *_args, **_kwargs: {"issue": "26125"},
    )

    result = run_zucai_prep(
        run_date=inputs.run_date,
        slot="afternoon",
        issue="26125",
        zucai_dir=inputs.zucai_dir,
        output_dir=inputs.output_dir,
        live_fetch=True,
        intl_fetcher=lambda _doc: {1: _INTL["matches"][0]},
    )

    intl = json.loads(
        inputs.zucai_dir.joinpath("26125-odds-intl.json").read_text("utf-8")
    )
    prep = json.loads(result.prep_path.read_text("utf-8"))
    assert len(intl["matches"]) == 1
    assert prep["intl_status"] == "available"
    assert prep["records"]["1"]["fair_blend"] is not None


def test_run_prep_still_alerts_after_long_silence(tmp_path):
    from nutmeg.decision.zucai_gate import InsaleIssue
    from nutmeg.decision.zucai_prep import (
        NO_ISSUE_ALERT_DAYS,
        run_zucai_prep,
        touch_liveness,
    )

    sent = []

    def _spy(kind, key, fingerprint, text, **_kwargs):
        sent.append(text)

    touch_liveness(tmp_path, run_date="2026-09-01", status="prepared")  # 13 天前

    def _gate(**_kw):
        return (InsaleIssue(issue="26130", deadline=datetime(2026, 9, 20, 22, 0)), "今日无期")

    run_zucai_prep(run_date="2026-09-14", slot="afternoon", zucai_dir=tmp_path,
                   output_dir=tmp_path, live_fetch=False, dispatch=True,
                   notification_service=_spy, gate_fn=_gate)
    assert len(sent) == 1
    assert str(NO_ISSUE_ALERT_DAYS) in sent[0]

def test_revision_does_not_repeat_an_unchanged_blend_gate():
    """闸的**状态变化**才是新消息；一直拦着同一场不是（14:00 已报过）。"""
    from nutmeg.decision.zucai_prep import should_push

    blocked = _prep(slot="revision", records={"1": {"blend_blocked": "x"}})
    same = _prep(slot="afternoon", records={"1": {"blend_blocked": "x"}})
    assert should_push(blocked, slot="revision", moved=0, base_prep=same) is False
    clean = _prep(slot="afternoon", records={"1": {}})
    assert should_push(blocked, slot="revision", moved=0, base_prep=clean) is True


def test_auto_channel_map_turns_prep_alignment_into_jczq_match_ids(tmp_path):
    from nutmeg.decision.zucai_prep import write_auto_channel_map

    out = tmp_path / "jczq"
    day_dir = out / "daily" / "2026-09-26"
    day_dir.mkdir(parents=True)
    (day_dir / "sporttery_markets.json").write_text(json.dumps({"matchInfoList": [
        {"subMatchList": [{"matchNum": 6008, "matchNumStr": "周六008"},
                          {"matchNum": 6012, "matchNumStr": "周六012"}]}]}), encoding="utf-8")
    (day_dir / "jczq-legs-base.json").write_text(json.dumps({"legs": {
        "周六008": {"match_id": "m-008"}, "周六012": {"match_id": "m-012"}}}), encoding="utf-8")
    zdir = tmp_path / "zucai"
    zdir.mkdir()
    prep = {"issue": "26133", "run_date": "2026-09-26", "records": {
        "1": {"sporttery_match_num": None, "match_date": "2026-09-27"},
        "2": {"sporttery_match_num": "6008", "match_date": "2026-09-26"},
        "3": {"sporttery_match_num": "6012", "match_date": "2026-09-26"}}}

    path = write_auto_channel_map(prep, zucai_dir=zdir, output_dir=out)

    assert json.loads(path.read_text(encoding="utf-8")) == {"m-008": 2, "m-012": 3}
    assert not (zdir / "26133-channel-map.json").exists()   # 人工表不碰
