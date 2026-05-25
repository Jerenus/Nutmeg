"""Tests for jczq_bold_review — spec §16 bold-combo backtest."""

from __future__ import annotations

import json

from nutmeg.services.jczq_bold_combos import (
    HARD_LABEL,
    BoldLeg,
    BoldTicket,
    persist_sporttery_snapshot,
)
from nutmeg.services.jczq_bold_review import (
    _cumulative,
    _day_record,
    build_bold_review,
    grade_leg,
    grade_ticket,
    run_bold_review,
)


def _leg(match_no: str, market: str, pick_label: str, odds: float = 5.0) -> BoldLeg:
    return BoldLeg(
        match_no=match_no, league="L", home="主", away="客",
        pick=pick_label, tc_odds=odds, boldness=0.4, reason="r",
        market=market, pick_label=pick_label,
    )


def _ticket(ticket_id: str, kind: str, legs: list[BoldLeg]) -> BoldTicket:
    return BoldTicket(
        id=ticket_id, kind=kind, legs=legs, fold=len(legs),
        total_odds=25.0, avg_boldness=0.4, note="n",
    )


class _FakeResults:
    """A stand-in JczqResultProvider — returns a fixed result map, no network."""

    def __init__(self, results: dict) -> None:
        self._results = results

    def fetch_results(self, run_date: str) -> dict:
        return self._results


def _persist_snapshot(tmp_path, run_date: str = "2026-05-18") -> None:
    """Persist a 3-match Sporttery snapshot so the review can replay a plan."""

    def m(no: str, home: str) -> dict:
        return {
            "matchNumStr": no, "businessDate": run_date, "matchStatus": "Selling",
            "leagueAbbName": "芬超", "homeTeamAbbName": home, "awayTeamAbbName": "客",
            "had": {"h": "2.00", "d": "3.20", "a": "3.50"},
            "hhad": {"h": "3.10", "d": "3.30", "a": "2.10", "goalLine": "-1"},
            "ttg": {f"s{k}": str(4.0 + k) for k in range(8)},
            "crs": {"s01s00": "6.50", "s00s00": "9.00",
                    "s02s01": "7.50", "s03s02": "41.0"},
        }

    persist_sporttery_snapshot(run_date, tmp_path, {"matchInfoList": [
        {"businessDate": run_date, "subMatchList": [
            m("周一001", "A"), m("周一002", "B"), m("周一003", "C")]}]})


def test_grade_leg_hit_miss_pending() -> None:
    """A leg hits when actual == pick_label; a match with no result is 待定."""
    results = {"周一001": {"had": "胜", "crs": "2:1"}}
    assert grade_leg(_leg("周一001", "had", "胜"), results).hit is True
    assert grade_leg(_leg("周一001", "crs", "1:0"), results).hit is False
    assert grade_leg(_leg("周一009", "had", "胜"), results).hit is None


def test_grade_ticket_all_hit_and_pending() -> None:
    """Whole-ticket verdict — all-hit vs a ticket dragged to pending (spec §16)."""
    results = {
        "周一001": {"had": "胜"},
        "周一002": {"hhad": "让平"},
        "周一003": {},                       # no result → pending leg
    }
    win = grade_ticket(
        _ticket("大胆票1", "大胆票",
                [_leg("周一001", "had", "胜"), _leg("周一002", "hhad", "让平")]),
        results,
    )
    assert win.all_hit is True and win.hits == 2 and win.pending is False

    pend = grade_ticket(
        _ticket("大胆票2", "大胆票",
                [_leg("周一001", "had", "胜"), _leg("周一003", "had", "胜")]),
        results,
    )
    assert pend.pending is True and pend.all_hit is False and pend.graded == 1


def test_cumulative_accumulates_history() -> None:
    """_cumulative sums day records — the structural-signal view (spec §16).

    A pending anchor is excluded from the anchor denominator."""
    history = [
        {"date": "2026-05-18", "chaos": 0,
         "anchor": {"all_hit": True, "pending": False, "hits": 3, "graded": 3},
         "bold": {"tickets": 5, "ticket_hits": 0, "ticket_graded": 5,
                  "leg_hits": 4, "leg_graded": 16},
         "by_theme": {"冷门比分梦": {"tickets": 2, "ticket_hits": 0}}},
        {"date": "2026-05-19", "chaos": 7,
         "anchor": {"all_hit": False, "pending": False, "hits": 2, "graded": 3},
         "bold": {"tickets": 5, "ticket_hits": 1, "ticket_graded": 5,
                  "leg_hits": 6, "leg_graded": 15},
         "by_theme": {"冷门比分梦": {"tickets": 1, "ticket_hits": 1}}},
    ]
    cum = _cumulative(history)
    assert cum["days"] == 2
    assert cum["anchor"] == {"hits": 1, "total": 2}
    assert cum["bold_tickets"] == {"hits": 1, "total": 10}
    assert cum["bold_legs"] == {"hits": 10, "total": 31}
    # spec §24 — legacy schema (no per-theme legs/leg_hits) defaults to 0
    assert cum["by_theme"]["冷门比分梦"] == {
        "tickets": 3, "ticket_hits": 1, "legs": 0, "leg_hits": 0,
    }


def test_build_bold_review_no_snapshot_skips(tmp_path) -> None:
    """A date with no snapshot → honest 跳过, and the okooo provider is never
    touched (spec §16)."""
    class _NoFetch:
        def fetch_results(self, run_date: str) -> dict:
            raise AssertionError("must not fetch when there is no snapshot")

    review = build_bold_review("2099-01-01", tmp_path, result_provider=_NoFetch())
    assert review.status == "no_snapshot"
    assert review.message.startswith("🎲")
    assert "跳过复盘" in review.message


def test_build_bold_review_grades_and_renders(tmp_path) -> None:
    """A full review — replay the plan, grade it, render report + history."""
    _persist_snapshot(tmp_path)
    results = {
        "周一001": {"had": "胜", "hhad": "让胜", "ttg": "2球", "crs": "1:0",
                    "score": "1:0"},
        "周一002": {"had": "平", "hhad": "让平", "ttg": "3球", "crs": "1:1",
                    "score": "1:1"},
        "周一003": {"had": "负", "hhad": "让负", "ttg": "4球", "crs": "1:3",
                    "score": "1:3"},
    }
    review = build_bold_review(
        "2026-05-18", tmp_path, result_provider=_FakeResults(results)
    )
    assert review.status == "reviewed"
    assert review.message.startswith("🎲")
    assert "## 票面回测" in review.message
    assert "## 累计趋势" in review.message
    assert review.bold_tickets

    history = json.loads(
        (tmp_path / "bold-review-history.json").read_text(encoding="utf-8")
    )
    assert len(history) == 1 and history[0]["date"] == "2026-05-18"


def test_build_bold_review_history_idempotent(tmp_path) -> None:
    """Re-reviewing the same date replaces its history entry, never dupes it."""
    _persist_snapshot(tmp_path)
    provider = _FakeResults({"周一001": {"had": "胜"}})
    build_bold_review("2026-05-18", tmp_path, result_provider=provider)
    build_bold_review("2026-05-18", tmp_path, result_provider=provider)

    history = json.loads(
        (tmp_path / "bold-review-history.json").read_text(encoding="utf-8")
    )
    assert len(history) == 1


def test_bold_review_message_has_no_advantage_wording(tmp_path) -> None:
    """The review report carries no banned advantage wording (spec §0/§7/§16)."""
    _persist_snapshot(tmp_path)
    review = build_bold_review(
        "2026-05-18", tmp_path,
        result_provider=_FakeResults({"周一001": {"had": "胜"}}),
    )
    # the 🎲 label legitimately negates "edge" — scan the body after it.
    body = review.message[len(HARD_LABEL):]
    for word in ("胜率", "edge", "+EV", "正期望", "推荐下注", "重仓"):
        assert word not in body, f"advantage word leaked: {word}"


def test_day_record_by_theme_aggregates_legs_and_leg_hits() -> None:
    """spec §24 — _day_record's by_theme slot tracks accumulated graded legs +
    leg hits per theme, so §24 retirement can read a real 30-leg threshold.

    Two 平局收割 tickets (a 3-leg full-hit and a 3-leg 1/3 hit) → theme slot
    must report ``legs=6`` (all 6 legs graded), ``leg_hits=4`` (3+1), and
    ``ticket_hits=1`` (only the full-hit ticket counts). Pending legs (no
    actual) are excluded from ``legs`` denominator."""
    from nutmeg.services.jczq_bold_review import GradedLeg, GradedTicket

    def _gl(mn, market, pick, hit):
        return GradedLeg(
            match_no=mn, market=market, pick_label=pick,
            tc_odds=4.0, actual=pick if hit else "其它", hit=hit,
        )

    def _gt(tid, theme, legs, all_hit, pending):
        graded = sum(1 for lg in legs if lg.hit is not None)
        hits = sum(1 for lg in legs if lg.hit is True)
        return GradedTicket(
            ticket_id=tid, kind="大胆票", theme=theme, fold=len(legs),
            total_odds=20.0, legs=legs, hits=hits, graded=graded,
            all_hit=all_hit, pending=pending,
        )

    bold = [
        _gt("大胆票1", "平局收割",
            [_gl("M1", "had", "平", True),
             _gl("M2", "hhad", "让平", True),
             _gl("M3", "had", "平", True)],
            all_hit=True, pending=False),
        _gt("大胆票2", "平局收割",
            [_gl("M4", "had", "平", True),
             _gl("M5", "hhad", "让平", False),
             _gl("M6", "had", "平", False)],
            all_hit=False, pending=False),
    ]
    rec = _day_record("2026-05-25", chaos=8, anchor=None, bold=bold)

    slot = rec["by_theme"]["平局收割"]
    assert slot["tickets"] == 2
    assert slot["ticket_hits"] == 1
    assert slot["legs"] == 6
    assert slot["leg_hits"] == 4


def test_day_record_by_theme_excludes_pending_legs_from_legs_count() -> None:
    """spec §24 — a leg with ``hit is None`` (待定 — match has no result yet)
    must NOT increment the theme's ``legs`` denominator. Otherwise a pending
    跨日 leg would push the theme over the 30-leg threshold prematurely."""
    from nutmeg.services.jczq_bold_review import GradedLeg, GradedTicket

    legs = [
        GradedLeg(match_no="M1", market="had", pick_label="平",
                  tc_odds=4.0, actual="平", hit=True),
        GradedLeg(match_no="M2", market="had", pick_label="平",
                  tc_odds=4.0, actual=None, hit=None),  # 待定
    ]
    bold = [GradedTicket(
        ticket_id="大胆票1", kind="大胆票", theme="平局收割", fold=2,
        total_odds=20.0, legs=legs, hits=1, graded=1,
        all_hit=False, pending=True,
    )]
    rec = _day_record("2026-05-25", chaos=8, anchor=None, bold=bold)

    slot = rec["by_theme"]["平局收割"]
    assert slot["legs"] == 1, "待定 leg must not count toward graded denominator"
    assert slot["leg_hits"] == 1
    assert slot["tickets"] == 1
    assert slot["ticket_hits"] == 0  # pending ticket is not a ticket_hit


def test_cumulative_aggregates_theme_legs_and_handles_legacy_records() -> None:
    """spec §24 — _cumulative sums theme-level legs/leg_hits; legacy day records
    (no legs/leg_hits keys) accumulate as 0 so old history keeps loading."""
    history = [
        # New-schema day
        {"date": "2026-05-25", "chaos": 8,
         "anchor": None,
         "bold": {"tickets": 2, "ticket_hits": 1, "ticket_graded": 2,
                  "leg_hits": 4, "leg_graded": 6},
         "by_theme": {"平局收割":
                      {"tickets": 2, "ticket_hits": 1, "legs": 6, "leg_hits": 4}}},
        # Legacy day — old schema without legs/leg_hits per theme
        {"date": "2026-05-24", "chaos": 8,
         "anchor": None,
         "bold": {"tickets": 5, "ticket_hits": 0, "ticket_graded": 5,
                  "leg_hits": 0, "leg_graded": 16},
         "by_theme": {"平局收割": {"tickets": 5, "ticket_hits": 0}}},
    ]
    cum = _cumulative(history)
    slot = cum["by_theme"]["平局收割"]
    assert slot["tickets"] == 7
    assert slot["ticket_hits"] == 1
    assert slot["legs"] == 6  # legacy day contributes 0 legs
    assert slot["leg_hits"] == 4


def test_run_bold_review_writes_artifacts(tmp_path) -> None:
    """run_bold_review writes bold-review.md / .json under daily/<date>/."""
    _persist_snapshot(tmp_path)
    run_bold_review(
        "2026-05-18", tmp_path,
        result_provider=_FakeResults({"周一001": {"had": "胜"}}),
    )
    run_dir = tmp_path / "daily" / "2026-05-18"
    assert (run_dir / "bold-review.md").exists()
    payload = json.loads((run_dir / "bold-review.json").read_text(encoding="utf-8"))
    assert payload["status"] == "reviewed"
    assert payload["run_date"] == "2026-05-18"
