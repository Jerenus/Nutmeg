from __future__ import annotations

import json
from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.services.jczq_daily import JczqDailyAdvisorService
from nutmeg.services.jczq_review import JczqDailyReviewService
from nutmeg.storage.betting_plan_repository import DuckDbBettingPlanRepository
from nutmeg.storage.bootstrap import create_analytics_schema
from tests.test_jczq_daily_service import FakeProvider, FakeSender


class FakeResultProvider:
    source_page = "fake://okooo-results"

    def fetch_results(self, run_date: str):
        assert run_date == "2026-05-01"
        return {
            "周五001": {
                "score": "3:0",
                "half_score": "2:0",
                "had": "胜",
                "had_odds": "1.28",
                "hhad": "让胜",
                "hhad_odds": "1.95",
                "ttg": "3球",
                "ttg_odds": "3.45",
                "hafu": "胜/胜",
                "hafu_odds": "1.76",
                "crs": "3:0",
                "crs_odds": "12.0",
            },
            "周五003": {
                "score": "1:2",
                "half_score": "0:0",
                "had": "负",
                "had_odds": "2.46",
                "hhad": "让平",
                "hhad_odds": "3.80",
                "ttg": "3球",
                "ttg_odds": "4.05",
                "hafu": "平/负",
                "hafu_odds": "5.35",
                "crs": "1:2",
                "crs_odds": "10.0",
            },
            "周五004": {
                "score": "3:1",
                "half_score": "1:0",
                "had": "胜",
                "had_odds": "1.27",
                "hhad": "让胜",
                "hhad_odds": "1.93",
                "ttg": "4球",
                "ttg_odds": "4.80",
                "hafu": "胜/胜",
                "hafu_odds": "1.85",
                "crs": "3:1",
                "crs_odds": "9.0",
            },
            "周五005": {
                "score": "0:1",
                "half_score": "0:1",
                "had": "负",
                "had_odds": "3.45",
                "hhad": "让负",
                "hhad_odds": "1.75",
                "ttg": "1球",
                "ttg_odds": "6.5",
                "hafu": "负/负",
                "hafu_odds": "5.25",
                "crs": "0:1",
                "crs_odds": "13.0",
            },
        }


class FakeIterationResultProvider:
    source_page = "fake://okooo-iteration-results"

    def fetch_results(self, run_date: str):
        assert run_date == "2026-05-01"
        return {
            "周五001": {
                "score": "1:1",
                "half_score": "1:1",
                "had": "平",
                "had_odds": "4.90",
                "hhad": "让负",
                "hhad_odds": "2.95",
                "ttg": "2球",
                "ttg_odds": "3.20",
                "hafu": "平/平",
                "hafu_odds": "6.20",
                "crs": "1:1",
                "crs_odds": "9.00",
            },
            "周五003": {
                "score": "1:1",
                "half_score": "0:0",
                "had": "平",
                "had_odds": "2.77",
                "hhad": "让胜",
                "hhad_odds": "1.41",
                "ttg": "2球",
                "ttg_odds": "3.00",
                "hafu": "平/平",
                "hafu_odds": "3.95",
                "crs": "1:1",
                "crs_odds": "5.35",
            },
            "周五004": {
                "score": "1:1",
                "half_score": "0:0",
                "had": "平",
                "had_odds": "4.70",
                "hhad": "让负",
                "hhad_odds": "3.00",
                "ttg": "2球",
                "ttg_odds": "3.40",
                "hafu": "平/平",
                "hafu_odds": "7.00",
                "crs": "1:1",
                "crs_odds": "8.50",
            },
            "周五005": {
                "score": "1:1",
                "half_score": "0:0",
                "had": "平",
                "had_odds": "3.35",
                "hhad": "让负",
                "hhad_odds": "1.75",
                "ttg": "2球",
                "ttg_odds": "3.55",
                "hafu": "平/平",
                "hafu_odds": "5.25",
                "crs": "1:1",
                "crs_odds": "6.75",
            },
        }


def _seed_user_revision_hafu_pattern(tmp_path: Path) -> None:
    """Activate user_revision_hafu_draw_away so 周五003 hafu 平/负 enters main.

    Without this seed the new EV-driven scorer prefers 平/平 over 平/负 when
    they sit in the same hafu pool — that is the desired post-fix behavior.
    The test exercises the user-revision path that explicitly promotes 平/负
    after enough positive reinforcement.
    """

    memory_dir = tmp_path / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    (memory_dir / "strategy-memory.json").write_text(
        json.dumps(
            {
                "version": 1,
                "sample_count": 0,
                "patterns": {
                    "user_revision_hafu_draw_away": {
                        "label": "用户修正-半全场平/负",
                        "hits": 2,
                        "misses": 0,
                    }
                },
                "insights": [],
                "recent_inspirations": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_daily_review_grades_saved_context_and_highlights_strategy_lessons(tmp_path: Path) -> None:
    _seed_user_revision_hafu_pattern(tmp_path)
    JczqDailyAdvisorService(provider=FakeProvider()).build_report(
        run_date="2026-05-01", output_dir=tmp_path
    )

    report = JczqDailyReviewService(result_provider=FakeResultProvider()).build_review(
        run_date="2026-05-01", output_dir=tmp_path
    )

    assert report["run_date"] == "2026-05-01"
    assert report["results"]["周五005"]["had"] == "负"
    # Rule H: hafu legs no longer survive in non-extreme plans. The user-
    # revision pattern still drives 周五003 into main, but as a non-hafu pick.
    周五003_legs = [
        item for item in report["graded_legs"] if item["match_no"] == "周五003"
    ]
    assert 周五003_legs, "user-revision pattern should still surface 周五003"
    non_extreme_周五003 = [
        item
        for item in 周五003_legs
        if "extreme" not in str(item.get("plan_kind", "")).lower()
    ]
    assert all(item["pool"] != "hafu" for item in non_extreme_周五003)
    assert any(
        item["match_no"] == "周五005" and item["actual"] == "负"
        for item in report["graded_legs"]
    )
    assert "005" in report["message"] and "防平防冷" in report["message"]
    assert Path(report["artifacts"]["markdown_path"]).exists()


def test_daily_review_updates_strategy_memory(tmp_path: Path) -> None:
    _seed_user_revision_hafu_pattern(tmp_path)
    JczqDailyAdvisorService(provider=FakeProvider()).build_report(
        run_date="2026-05-01", output_dir=tmp_path
    )

    report = JczqDailyReviewService(result_provider=FakeResultProvider()).build_review(
        run_date="2026-05-01", output_dir=tmp_path
    )

    memory_path = tmp_path / "memory" / "strategy-memory.json"
    assert memory_path.exists()
    memory = json.loads(memory_path.read_text(encoding="utf-8"))
    assert memory["last_review_date"] == "2026-05-01"
    assert memory["sample_count"] == 1
    # Rule H stripped the hafu 平/负 pick before grading, so the pattern's hits
    # counter no longer auto-increments via that flow. The pattern is still
    # tracked for backward compatibility / future re-enablement; we just don't
    # require a fresh hit here.
    assert "user_revision_hafu_draw_away" in memory["patterns"]
    assert memory["patterns"]["comfort_risk_draw_or_cold"]["hits"] >= 1
    # Rule H stripped the hafu 平/负 leg before grading, so the user-revision
    # pattern no longer auto-records a hit. recent_inspirations now captures
    # comfort-risk notes (e.g. 周五005 实际负兑现).
    assert memory["recent_inspirations"], "recent_inspirations should still capture other patterns"
    assert "策略记忆已更新" in report["message"]


def test_daily_review_dispatches_postmortem_text(tmp_path: Path) -> None:
    JczqDailyAdvisorService(provider=FakeProvider()).build_report(
        run_date="2026-05-01", output_dir=tmp_path
    )
    sender = FakeSender()

    report = JczqDailyReviewService(
        result_provider=FakeResultProvider(), telegram_sender=sender, telegram_chat_ids=[7627818415]
    ).build_review(
        run_date="2026-05-01",
        output_dir=tmp_path,
        dispatch_telegram=True,
        dry_run=False,
    )

    assert report["dispatch"]["status"] == "sent"
    assert sender.messages[0][0] == 7627818415
    assert "赛后复盘" in sender.messages[0][1]


def test_daily_review_records_db_backtest_with_oracle_odds(tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    create_analytics_schema(settings)
    repository = DuckDbBettingPlanRepository(settings)
    JczqDailyAdvisorService(provider=FakeProvider(), betting_repository=repository).build_report(
        run_date="2026-05-01",
        output_dir=tmp_path,
        record_final=True,
    )

    report = JczqDailyReviewService(
        result_provider=FakeResultProvider(),
        betting_repository=repository,
    ).build_review(run_date="2026-05-01", output_dir=tmp_path)

    assert report["betting_db"]["run_id"] == "jczq:2026-05-01:final"
    assert report["betting_db"]["plan_reviews"]
    assert any(
        item["oracle_same_play_odds"] > 0 for item in report["betting_db"]["plan_reviews"]
    )
    assert "同玩法正确赔率" in report["message"]


def test_daily_review_enriches_graded_legs_with_poisson_and_narrative_fields(
    tmp_path: Path,
) -> None:
    """R8 (5/08 落库): graded_legs must carry expected_edge, narrative_tag,
    expected_goals, realized_goals, goal_residual so R1's λ-calibration
    feedback loop can distinguish 'modeled correctly but unlucky' from
    'model under-priced goals systematically'.
    """
    JczqDailyAdvisorService(provider=FakeProvider()).build_report(
        run_date="2026-05-01", output_dir=tmp_path
    )

    report = JczqDailyReviewService(result_provider=FakeResultProvider()).build_review(
        run_date="2026-05-01", output_dir=tmp_path
    )

    legs = report["graded_legs"]
    assert legs, "review must produce graded legs"
    for leg in legs:
        assert "narrative_tag" in leg
        assert leg["narrative_tag"] in {
            "chalk_favorite",
            "cold_reverse",
            "draw",
            "low_goals",
            "high_goals",
            "score_picks",
            "hafu",
            "other",
        }
        # Poisson coverage is best-effort: hhad has no model price, and a
        # league/match without enough info also returns None. The keys
        # must be present even if the values are None.
        assert "expected_edge" in leg
        assert "expected_goals" in leg
        assert "realized_goals" in leg
        assert "goal_residual" in leg
    # At least one leg from a Poisson-priced pool should have a real edge.
    priced_with_edge = [
        leg
        for leg in legs
        if leg["pool"] in {"had", "ttg", "crs", "hafu"} and leg["expected_edge"] is not None
    ]
    assert priced_with_edge, "at least one Poisson-priced leg must have expected_edge"


def test_daily_review_writes_executable_decision_policy(tmp_path: Path) -> None:
    JczqDailyAdvisorService(provider=FakeProvider()).build_report(
        run_date="2026-05-01", output_dir=tmp_path
    )

    report = JczqDailyReviewService(
        result_provider=FakeIterationResultProvider(),
    ).build_review(run_date="2026-05-01", output_dir=tmp_path)

    memory_path = tmp_path / "memory" / "strategy-memory.json"
    memory = json.loads(memory_path.read_text(encoding="utf-8"))
    policy = memory["decision_policy"]

    assert policy["rules"]["stable_base"]["active"] is True
    assert policy["rules"]["stable_base"]["action"] == "downgrade_low_price_bankers"
    assert policy["rules"]["total_goals"]["active"] is True
    assert "2球" in policy["rules"]["total_goals"]["preferred_picks"]
    assert policy["rules"]["hafu"]["active"] is True
    assert policy["rules"]["reuse_guard"]["active"] is True
    # Rule I/J scrubs reduce per-match leg counts, so the specific match that
    # surfaces in reuse_guard depends on which legs survive the Poisson floor.
    # The invariant we still want: reuse_guard flags at least one repeatedly-
    # missed match.
    assert policy["rules"]["reuse_guard"]["match_nos"], (
        "reuse_guard should flag at least one repeatedly-missed match"
    )
    assert any("强胆低赔" in note for note in policy["notes"])
    assert any("2球" in note for note in policy["notes"])
    assert report["strategy_memory"]["decision_policy"]["rules"]["hafu"]["active"] is True
    assert "策略迭代规则" in report["message"]


# --- conflict-store grading -------------------------------------------------


def test_grade_conflict_store_maps_per_pool_winners(tmp_path: Path) -> None:
    from nutmeg.data.european_odds import CrossCheckSignal
    from nutmeg.services.jczq_conflict_store import ConflictStore
    from nutmeg.services.jczq_review import grade_conflict_store

    store = ConflictStore(tmp_path / "conflict-signals.json")
    store.record(
        "2026-05-15",
        [
            CrossCheckSignal("周五001", "had", "负", 0.30, 0.40, 0.05, 0.04),
            CrossCheckSignal("周五003", "had", "胜", 0.30, 0.40, 0.05, 0.04),
        ],
        sporttery_odds={"周五001": 3.10, "周五003": 2.40},
    )

    grade_conflict_store(
        store,
        run_date="2026-05-15",
        results={
            "周五001": {"had": "负", "ttg": "2球"},
            "周五003": {"had": "负", "ttg": "3球"},
        },
    )

    rows = store.load()
    by_match = {row["match_no"]: row for row in rows}
    assert by_match["周五001"]["hit"] is True
    assert abs(by_match["周五001"]["realized_return"] - 3.10) < 1e-9
    assert by_match["周五003"]["hit"] is False
    assert by_match["周五003"]["realized_return"] == 0.0


def test_daily_review_grades_conflict_signal_store(tmp_path: Path) -> None:
    from nutmeg.data.european_odds import CrossCheckSignal
    from nutmeg.services.jczq_conflict_store import ConflictStore

    JczqDailyAdvisorService(provider=FakeProvider()).build_report(
        run_date="2026-05-01", output_dir=tmp_path
    )

    # Seed a conflict signal as if the engine had emitted it on the run date.
    store_path = tmp_path / "memory" / "conflict-signals.json"
    store = ConflictStore(store_path)
    store.record(
        "2026-05-01",
        [CrossCheckSignal("周五005", "had", "负", 0.30, 0.42, 0.06, 0.05)],
        sporttery_odds={"周五005": 3.45},
    )
    assert store.load()[0]["hit"] is None

    JczqDailyReviewService(result_provider=FakeResultProvider()).build_review(
        run_date="2026-05-01", output_dir=tmp_path
    )

    # FakeResultProvider has 周五005 had == "负" → the signal is graded a hit.
    graded = ConflictStore(store_path).load()[0]
    assert graded["hit"] is True
    assert abs(graded["realized_return"] - 3.45) < 1e-9
