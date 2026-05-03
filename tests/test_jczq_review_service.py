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


def test_daily_review_grades_saved_context_and_highlights_strategy_lessons(tmp_path: Path) -> None:
    JczqDailyAdvisorService(provider=FakeProvider()).build_report(
        run_date="2026-05-01", output_dir=tmp_path
    )

    report = JczqDailyReviewService(result_provider=FakeResultProvider()).build_review(
        run_date="2026-05-01", output_dir=tmp_path
    )

    assert report["run_date"] == "2026-05-01"
    assert report["results"]["周五005"]["had"] == "负"
    assert any(
        item["match_no"] == "周五003"
        and item["pool"] == "hafu"
        and item["pick"] == "平/负"
        and item["hit"] is True
        for item in report["graded_legs"]
    )
    assert any(
        item["match_no"] == "周五005" and item["actual"] == "负"
        for item in report["graded_legs"]
    )
    assert "003修正为平/负命中" in report["message"]
    assert "005" in report["message"] and "防平防冷" in report["message"]
    assert Path(report["artifacts"]["markdown_path"]).exists()


def test_daily_review_updates_strategy_memory(tmp_path: Path) -> None:
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
    assert memory["patterns"]["user_revision_hafu_draw_away"]["hits"] >= 1
    assert memory["patterns"]["comfort_risk_draw_or_cold"]["hits"] >= 1
    assert any(
        "003" in item["note"] and "平/负" in item["note"]
        for item in memory["recent_inspirations"]
    )
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
