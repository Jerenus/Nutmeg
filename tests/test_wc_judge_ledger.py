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
