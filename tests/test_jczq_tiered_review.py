"""Tests for jczq_tiered_review — spec §6."""
from __future__ import annotations

import json

from nutmeg.services.jczq_bold_combos import HARD_LABEL, persist_sporttery_snapshot
from nutmeg.services.jczq_tiered_review import (
    _merge_cross_version_by_theme,
    build_tiered_review,
    load_cross_version_history_dict,
    load_cross_version_retired_themes,
    replay_tiered_plan,
    run_tiered_review,
)


def test_merge_cross_version_by_theme_sums_counts() -> None:
    v1 = {
        "平局收割": {
            "tickets": 23, "ticket_hits": 0,
            "legs": 63, "leg_hits": 11,
        }
    }
    v2 = {
        "平局收割": {
            "tickets": 5, "ticket_hits": 0,
            "legs": 15, "leg_hits": 3,
        }
    }
    merged = _merge_cross_version_by_theme(v1, v2)
    assert merged["平局收割"]["tickets"] == 28
    assert merged["平局收割"]["legs"] == 78


def test_load_cross_version_retired_reads_v1_only(tmp_path) -> None:
    v1_hist = [{
        "date": "2026-05-25", "chaos": 8,
        "anchor": None, "bold": {},
        "by_theme": {
            "平局收割": {
                "tickets": 23, "ticket_hits": 0,
                "legs": 63, "leg_hits": 11,
            }
        },
    }]
    (tmp_path / "bold-review-history.json").write_text(
        json.dumps(v1_hist), encoding="utf-8"
    )
    retired = load_cross_version_retired_themes(tmp_path)
    assert any(rt.theme == "平局收割" for rt in retired)


def test_load_cross_version_history_dict_merges_both(tmp_path) -> None:
    v1_hist = [{
        "date": "2026-05-25", "chaos": 8,
        "anchor": None, "bold": {},
        "by_theme": {
            "平局收割": {
                "tickets": 23, "ticket_hits": 0,
                "legs": 63, "leg_hits": 11,
            }
        },
    }]
    v2_hist = [{
        "date": "2026-05-26", "chaos": 5,
        "by_theme": {
            "平局收割": {
                "tickets": 1, "ticket_hits": 0,
                "legs": 3, "leg_hits": 1,
            }
        },
    }]
    (tmp_path / "bold-review-history.json").write_text(
        json.dumps(v1_hist), encoding="utf-8"
    )
    (tmp_path / "tiered-plan-history.json").write_text(
        json.dumps(v2_hist), encoding="utf-8"
    )
    hist = load_cross_version_history_dict(tmp_path)
    slot = hist["by_theme"]["平局收割"]
    assert slot["tickets"] == 24
    assert slot["legs"] == 66


def test_load_cross_version_missing_files_returns_empty(tmp_path) -> None:
    assert load_cross_version_retired_themes(tmp_path) == ()
    # v2.1 §25.3 — history dict now also carries "records" for hhad health
    assert load_cross_version_history_dict(tmp_path) == {
        "by_theme": {}, "records": [],
    }


class _FakeResults:
    def __init__(self, results: dict) -> None:
        self._results = results

    def fetch_results(self, run_date: str) -> dict:
        return self._results


def _persist_snapshot(tmp_path, run_date: str = "2026-05-26") -> None:
    """Stage a 3-match Sporttery snapshot for replay."""

    def m(no: str, home: str) -> dict:
        return {
            "matchNumStr": no, "businessDate": run_date,
            "matchStatus": "Selling",
            "leagueAbbName": "测", "homeTeamAbbName": home,
            "awayTeamAbbName": "客",
            "had": {"h": "1.50", "d": "3.20", "a": "5.50"},
            "hhad": {"h": "1.84", "d": "3.30", "a": "3.50",
                     "goalLine": "-1"},
            "ttg": {f"s{k}": str(4.0 + k) for k in range(8)},
            "crs": {"s01s00": "6.50", "s00s00": "9.00",
                    "s02s01": "7.50"},
        }

    persist_sporttery_snapshot(run_date, tmp_path, {"matchInfoList": [
        {"businessDate": run_date, "subMatchList": [
            m("周二001", "A"), m("周二002", "B"), m("周二003", "C")]}]})


def test_build_tiered_review_no_snapshot_skips(tmp_path) -> None:
    review = build_tiered_review(
        "2099-01-01", tmp_path,
        result_provider=_FakeResults({}),
    )
    assert review.status == "no_snapshot"
    assert review.message.startswith(HARD_LABEL)
    assert "跳过复盘" in review.message


def test_build_tiered_review_grades_and_renders(tmp_path) -> None:
    _persist_snapshot(tmp_path)
    results = {
        "周二001": {"had": "胜", "hhad": "让胜", "ttg": "2球",
                    "crs": "1:0", "score": "1:0"},
        "周二002": {"had": "胜", "hhad": "让胜", "ttg": "2球",
                    "crs": "1:0", "score": "1:0"},
        "周二003": {"had": "胜", "hhad": "让胜", "ttg": "2球",
                    "crs": "1:0", "score": "1:0"},
    }
    review = build_tiered_review(
        "2026-05-26", tmp_path, result_provider=_FakeResults(results)
    )
    assert review.status == "reviewed"
    assert review.message.startswith(HARD_LABEL)
    assert "## 票面回测" in review.message
    assert "## 累计趋势" in review.message


def test_run_tiered_review_writes_artifacts(tmp_path) -> None:
    _persist_snapshot(tmp_path)
    run_tiered_review(
        "2026-05-26", tmp_path,
        result_provider=_FakeResults({"周二001": {"had": "胜"}}),
    )
    run_dir = tmp_path / "daily" / "2026-05-26"
    assert (run_dir / "tiered-plan-review.md").exists()
    assert (run_dir / "tiered-plan-review.json").exists()


def test_day_record_includes_version_field(tmp_path) -> None:
    """spec §27.4 — every day record carries a version tag for grouping."""
    _persist_snapshot(tmp_path)
    build_tiered_review(
        "2026-05-26", tmp_path,
        result_provider=_FakeResults({"周二001": {"had": "胜"}}),
    )

    history = json.loads(
        (tmp_path / "tiered-plan-history.json").read_text(encoding="utf-8")
    )
    assert history, "history should contain at least one record"
    assert all("version" in rec for rec in history), (
        f"every record needs a version, got: {[r.get('version') for r in history]}"
    )


def test_day_record_includes_let_neg_one_shadow_when_snapshot_present(
    tmp_path,
) -> None:
    """spec §27.6 — let-neg-one shadow field populated when snapshot exists
    and a graded hhad leg has goal_line == -1.0 (the snapshot in this test
    sets goalLine='-1' for every match)."""
    _persist_snapshot(tmp_path)
    results = {
        "周二001": {
            "had": "胜", "hhad": "让平", "ttg": "1球",
            "crs": "1:0", "score": "1:0",
        },
        "周二002": {
            "had": "胜", "hhad": "让平", "ttg": "1球",
            "crs": "1:0", "score": "1:0",
        },
        "周二003": {
            "had": "胜", "hhad": "让胜", "ttg": "2球",
            "crs": "2:0", "score": "2:0",
        },
    }
    build_tiered_review(
        "2026-05-26", tmp_path, result_provider=_FakeResults(results),
    )

    history = json.loads(
        (tmp_path / "tiered-plan-history.json").read_text(encoding="utf-8")
    )
    rec = history[0]
    # by_hhad_actual_let_neg_one is the shadow field — schema-level presence test
    assert "by_hhad_actual_let_neg_one" in rec, (
        "spec §27.6 field missing from day record when snapshot was available"
    )


def test_build_tiered_review_history_idempotent(tmp_path) -> None:
    _persist_snapshot(tmp_path)
    provider = _FakeResults({"周二001": {"had": "胜"}})
    build_tiered_review("2026-05-26", tmp_path, result_provider=provider)
    build_tiered_review("2026-05-26", tmp_path, result_provider=provider)
    hist = json.loads(
        (tmp_path / "tiered-plan-history.json").read_text(encoding="utf-8")
    )
    assert len(hist) == 1
    assert hist[0]["date"] == "2026-05-26"


def test_replay_tiered_plan_ignores_same_day_history(tmp_path) -> None:
    _persist_snapshot(tmp_path)
    same_day_history = [{
        "date": "2026-05-26",
        "by_theme": {
            "平局收割": {
                "tickets": 23, "ticket_hits": 0,
                "legs": 63, "leg_hits": 11,
            },
        },
        "by_hhad_actual": {"让胜": 30},
    }]
    (tmp_path / "tiered-plan-history.json").write_text(
        json.dumps(same_day_history), encoding="utf-8"
    )

    plan = replay_tiered_plan("2026-05-26", tmp_path)

    assert plan is not None
    assert plan.retired_themes == ()
    assert plan.hhad_health["total_legs"] == 0


def test_build_tiered_review_grades_saved_markdown_plan(tmp_path) -> None:
    _persist_snapshot(tmp_path)
    run_dir = tmp_path / "daily" / "2026-05-26"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "tiered-plan.md").write_text(
        "\n".join([
            HARD_LABEL,
            "",
            "💰 今日方案 · 总建议金额 ¥35（multiplier=1.00×）· 首推一张 = A",
            "**当天大盘面混乱值：8/100（平静）** · 2026-05-26",
            "",
            "### A 稳健底仓（2串1 · 合计赔率 2.25 · ¥35 · ⭐⭐⭐⭐）",
            "- 周二001 A vs 客 ｜ [胜平负] **胜** @ 1.50",
            "- 周二002 B vs 客 ｜ [胜平负] **胜** @ 1.50",
            "",
            "### B 主方案",
            "> 今日 B 档：候选不足或赔率档命不中。",
            "",
            "### D 反大众",
            "> 今日 D 档：候选不足或赔率档命不中。",
            "",
            "### E 极限娱乐",
            "> 今日 E 档：候选不足或赔率档命不中。",
        ]),
        encoding="utf-8",
    )
    results = {
        "周二001": {"had": "胜"},
        "周二002": {"had": "胜"},
    }

    review = build_tiered_review(
        "2026-05-26", tmp_path, result_provider=_FakeResults(results)
    )

    assert review.tiers[0] is not None
    assert review.tiers[0].fold == 2
    assert review.tiers[0].all_hit is True
    assert review.tiers[1:] == [None, None, None]


def test_tiered_review_no_banned_words(tmp_path) -> None:
    _persist_snapshot(tmp_path)
    review = build_tiered_review(
        "2026-05-26", tmp_path,
        result_provider=_FakeResults({"周二001": {"had": "胜"}}),
    )
    body = review.message[len(HARD_LABEL):]
    for word in ("胜率", "edge", "+EV", "正期望", "推荐下注", "重仓"):
        assert word not in body, f"banned word leaked: {word}"
