"""评判员记分(judge spec §2)。"""
from __future__ import annotations

from pathlib import Path

from nutmeg.services.worldcup.judge_ledger import (
    append_day,
    ledger_summary,
    load_ledger,
    reconcile_day,
)
from nutmeg.services.worldcup.predictions import (
    JudgePick,
    OpinionTicket,
    Predictions,
)
from nutmeg.services.worldcup.results import WcResult


def _pred(picks, ticket=None) -> Predictions:
    return Predictions(date="2026-06-12", judge="claude", picks=picks,
                       champion_pick={"team": "Argentina", "reason": "x"},
                       opinion_ticket=ticket)


def _pick(match_id, judgment, score="1-0", conf=4, upset=False,
          baseline="home", match_no="") -> JudgePick:
    return JudgePick(fixture=f"f-{match_id}", judgment=judgment, score=score,
                     reason="r", confidence=conf, upset_flag=upset,
                     baseline_pick=baseline, match_id=match_id,
                     match_no=match_no)


RESULTS = [
    WcResult("M01", "A", "B", "FT", "home", 1, 0, None),
    WcResult("M02", "C", "D", "FT", "away", 0, 2, None),
    WcResult("M03", "E", "F", "AET", "draw", None, None, "E"),
]


def test_reconcile_hits_and_misses() -> None:
    pred = _pred([
        _pick("M01", "home", score="1-0"),               # 判定中+比分中
        _pick("M02", "home", score="1-0", baseline="away"),  # 全错,基线中
        _pick("M03", "draw", score="1-1", upset=True, baseline="home"),
    ])
    entries = reconcile_day(pred, RESULTS)
    by_id = {e["match_id"]: e for e in entries if e["kind"] == "pick"}
    assert by_id["M01"]["judgment_hit"] is True
    assert by_id["M01"]["score_hit"] is True
    assert by_id["M02"]["judgment_hit"] is False
    assert by_id["M02"]["baseline_hit"] is True
    # AET:90 分钟比分不可知 → score_hit None;判平命中且偏离基线 → 爆冷命中
    assert by_id["M03"]["judgment_hit"] is True
    assert by_id["M03"]["score_hit"] is None
    assert by_id["M03"]["upset_hit"] is True


def test_reconcile_pending_when_result_missing() -> None:
    pred = _pred([_pick("M99", "home")])
    entries = reconcile_day(pred, RESULTS)
    assert entries[0]["pending"] is True


def test_ticket_pnl_win_and_loss() -> None:
    win = _pred([_pick("M01", "home", match_no="周四001")],
                ticket=OpinionTicket("周四001", "had", "home", odds=1.85))
    lose = _pred([_pick("M02", "home", match_no="周四002")],
                 ticket=OpinionTicket("周四002", "had", "home", odds=2.1))
    win_t = [e for e in reconcile_day(win, RESULTS) if e["kind"] == "ticket"][0]
    lose_t = [e for e in reconcile_day(lose, RESULTS) if e["kind"] == "ticket"][0]
    assert abs(win_t["pnl_yuan"] - 15 * 0.85) < 1e-9
    assert lose_t["pnl_yuan"] == -15


def test_ticket_missing_odds_pnl_none() -> None:
    pred = _pred([_pick("M01", "home", match_no="周四001")],
                 ticket=OpinionTicket("周四001", "had", "home", odds=None))
    t = [e for e in reconcile_day(pred, RESULTS) if e["kind"] == "ticket"][0]
    assert t["pnl_yuan"] is None


def test_append_day_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "judge-ledger.jsonl"
    pred = _pred([_pick("M01", "home")])
    append_day(path, "2026-06-12", reconcile_day(pred, RESULTS))
    append_day(path, "2026-06-12", reconcile_day(pred, RESULTS))  # 重跑
    entries = load_ledger(path)
    assert len([e for e in entries if e["kind"] == "pick"]) == 1


def test_summary_rates_and_absent() -> None:
    entries = [
        {"date": "2026-06-12", "kind": "pick", "match_id": "M01",
         "judgment_hit": True, "score_hit": True, "baseline_hit": True,
         "upset_flag": False, "upset_hit": False, "pending": False},
        {"date": "2026-06-12", "kind": "pick", "match_id": "M02",
         "judgment_hit": False, "score_hit": False, "baseline_hit": True,
         "upset_flag": True, "upset_hit": False, "pending": False},
        {"date": "2026-06-12", "kind": "ticket", "pnl_yuan": -15.0,
         "pending": False},
        {"date": "2026-06-13", "kind": "absent"},
        {"date": "2026-06-14", "kind": "pick", "match_id": "M09",
         "pending": True},
    ]
    s = ledger_summary(entries)
    assert s.n_picks == 2 and s.judgment_rate == 0.5 and s.score_rate == 0.5
    assert s.baseline_rate == 1.0
    assert s.upset_precision == 0.0
    assert s.ticket_pnl == -15.0
    assert s.absent_days == 1 and s.pending == 1


def test_reconcile_matches_by_fixture_pair_when_match_id_missing() -> None:
    """2026-07-06 根因修复:agent 写的 predictions 从不带 match_id,
    此前全部永久 pending;现按 fixture 队名对(经别名表)兜底匹配。"""
    aliases = {"甲队": "A", "乙队": "B"}
    pred = _pred([
        JudgePick(fixture="甲队 vs 乙队", judgment="home", score="1-0",
                  reason="r", confidence=4, match_no="周五001"),
    ])
    entries = reconcile_day(pred, RESULTS, team_aliases=aliases)
    assert entries[0]["pending"] is False
    assert entries[0]["judgment_hit"] is True


def test_reconcile_fixture_pair_prefers_latest_in_knockout_window() -> None:
    """同 pair 双遇(小组+淘汰):判定日在小组窗口后 → 取最近一次赛果。"""
    results = [
        WcResult("M10", "A", "B", "FT", "home", 2, 0, None),   # 小组赛
        WcResult("M60", "A", "B", "FT", "away", 0, 1, "B"),    # 淘汰赛
    ]
    aliases = {"甲队": "A", "乙队": "B"}
    ko_pred = Predictions(
        date="2026-07-03", judge="claude",
        picks=[JudgePick(fixture="甲队 vs 乙队", judgment="away", score="0-1",
                         reason="r", confidence=4)],
        champion_pick={"team": "X"}, opinion_ticket=None,
    )
    entries = reconcile_day(ko_pred, results, team_aliases=aliases)
    assert entries[0]["judgment_hit"] is True   # 命中的是 M60 的 away


def test_hhad_ticket_graded_with_line() -> None:
    """2026-07-06 修复:hhad 票此前按胜平负口径误评(英格兰 -1 恰胜1球=让平,
    旧代码会误记为赢)。"""
    results = [WcResult("M20", "A", "B", "FT", "home", 2, 1, None)]
    pred = _pred(
        [_pick("M20", "home", match_no="周三080")],
        ticket=OpinionTicket("周三080", "hhad", "home", odds=1.64, line=-1),
    )
    t = [e for e in reconcile_day(pred, results) if e["kind"] == "ticket"][0]
    assert t["ticket_outcome"] == "draw"        # 净胜1 - 1 = 0 → 让平
    assert t["pnl_yuan"] == -15.0               # 让胜票输


def test_hhad_ticket_line_from_market_snapshot_lookup() -> None:
    results = [WcResult("M21", "A", "B", "FT", "home", 3, 0, None)]
    pred = _pred(
        [_pick("M21", "home", match_no="周二078")],
        ticket=OpinionTicket("周二078", "hhad", "home", odds=1.60),  # line 未存
    )
    t = [e for e in reconcile_day(pred, results, hhad_lines={"周二078": -1.0})
         if e["kind"] == "ticket"][0]
    assert t["line"] == -1.0
    assert t["ticket_outcome"] == "home" and t["pnl_yuan"] == 9.0


def test_hhad_ticket_aet_draw_margin_zero() -> None:
    """AET/PEN 90' 必为平 → margin 0,无需精确比分即可评 hhad。"""
    results = [WcResult("M22", "A", "B", "AET", "draw", None, None, "A")]
    pred = _pred(
        [_pick("M22", "draw", match_no="周五087")],
        ticket=OpinionTicket("周五087", "hhad", "away", odds=2.62, line=-2),
    )
    t = [e for e in reconcile_day(pred, results) if e["kind"] == "ticket"][0]
    assert t["ticket_outcome"] == "away"        # 0 + (-2) < 0 → 让负
    assert abs(t["pnl_yuan"] - 15 * 1.62) < 1e-9


def test_unrecognized_ticket_pick_stays_pending_not_loss() -> None:
    """2026-07-06 code-review:pick 标签无法识别时必须 pending,绝不静默记 −stake。"""
    results = [WcResult("M30", "A", "B", "FT", "home", 2, 0, None)]
    pred = _pred(
        [_pick("M30", "home", match_no="周三080")],
        ticket=OpinionTicket("周三080", "hhad", "受让平未知档", odds=1.9, line=-1),
    )
    t = [e for e in reconcile_day(pred, results) if e["kind"] == "ticket"][0]
    assert t["pending"] is True
    assert "pnl_yuan" not in t


def test_hhad_ticket_without_line_stays_pending() -> None:
    results = [WcResult("M23", "A", "B", "FT", "home", 2, 0, None)]
    pred = _pred(
        [_pick("M23", "home", match_no="周六090")],
        ticket=OpinionTicket("周六090", "hhad", "draw", odds=3.5),
    )
    t = [e for e in reconcile_day(pred, results) if e["kind"] == "ticket"][0]
    assert t["pending"] is True


def test_reconcile_recent_sweeps_old_pending(tmp_path: Path) -> None:
    """窗口(3天)外仍 pending 的历史日期,赛果就绪后自动补结。"""
    import json as _json

    from nutmeg.services.worldcup.judge_ledger import reconcile_recent
    from nutmeg.services.worldcup.results import save_results

    old = "2026-06-20"
    daily = tmp_path / "daily" / old
    daily.mkdir(parents=True)
    (daily / "predictions.json").write_text(_json.dumps({
        "date": old, "judge": "claude",
        "picks": [{"fixture": "f", "match_no": "周六001", "match_id": "M01",
                   "judgment": "home", "score": "1-0", "reason": "r",
                   "confidence": 4}],
        "champion_pick": {"team": "X"}, "opinion_ticket": None,
        "written_at": old,
    }, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "wc2026").mkdir()
    save_results(tmp_path / "wc2026" / "results.json", [])
    reconcile_recent(tmp_path, today="2026-06-21")   # 赛果未到 → pending
    assert load_ledger(tmp_path / "wc2026" / "judge-ledger.jsonl")[0]["pending"]

    save_results(tmp_path / "wc2026" / "results.json", RESULTS)
    reconcile_recent(tmp_path, today="2026-07-06")   # 窗口早已滑过 → 补扫救回
    entries = load_ledger(tmp_path / "wc2026" / "judge-ledger.jsonl")
    by_date = [e for e in entries if e.get("date") == old and e["kind"] == "pick"]
    assert by_date[0]["pending"] is False and by_date[0]["judgment_hit"] is True


def test_reconcile_recent_skips_pre_launch_days(tmp_path: Path) -> None:
    """评判员层上线(2026-06-12)之前的日子不计缺席。"""
    from nutmeg.services.worldcup.judge_ledger import reconcile_recent

    for d in ("2026-06-10", "2026-06-11", "2026-06-12"):
        (tmp_path / "daily" / d).mkdir(parents=True)
    (tmp_path / "wc2026").mkdir()
    (tmp_path / "wc2026" / "results.json").write_text("[]", encoding="utf-8")
    reconcile_recent(tmp_path, today="2026-06-13")
    entries = load_ledger(tmp_path / "wc2026" / "judge-ledger.jsonl")
    absents = [e for e in entries if e.get("kind") == "absent"]
    assert [e["date"] for e in absents] == ["2026-06-12"]
