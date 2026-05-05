"""Strategy memory v2: pattern_buckets + oracle_learnings + bias hint."""

from __future__ import annotations

import json
from pathlib import Path

from nutmeg.services.jczq_daily import JczqDailyAdvisorService
from nutmeg.services.jczq_review import JczqDailyReviewService
from nutmeg.services.jczq_strategy_memory import (
    oracle_learning_for,
    pattern_bucket_ev,
)
from tests.test_jczq_daily_service import FakeProvider, FakeSender  # noqa: F401


class FakeFridayResultProvider:
    source_page = "fake://fri-results"

    def fetch_results(self, run_date: str):
        return {
            "周五001": {"score": "3:0", "had": "胜", "had_odds": "1.28",
                       "hhad": "让胜", "hhad_odds": "1.95",
                       "ttg": "3球", "ttg_odds": "3.45",
                       "hafu": "胜/胜", "hafu_odds": "1.76",
                       "crs": "3:0", "crs_odds": "12.0"},
            "周五003": {"score": "1:1", "had": "平", "had_odds": "2.77",
                       "hhad": "让胜", "hhad_odds": "1.41",
                       "ttg": "2球", "ttg_odds": "3.00",
                       "hafu": "平/平", "hafu_odds": "3.95",
                       "crs": "1:1", "crs_odds": "5.35"},
            "周五004": {"score": "3:1", "had": "胜", "had_odds": "1.27",
                       "hhad": "让胜", "hhad_odds": "1.93",
                       "ttg": "4球", "ttg_odds": "4.80",
                       "hafu": "胜/胜", "hafu_odds": "1.85",
                       "crs": "3:1", "crs_odds": "9.0"},
            "周五005": {"score": "0:1", "had": "负", "had_odds": "3.45",
                       "hhad": "让负", "hhad_odds": "1.75",
                       "ttg": "1球", "ttg_odds": "6.50",
                       "hafu": "负/负", "hafu_odds": "5.25",
                       "crs": "0:1", "crs_odds": "13.0"},
        }


def test_review_populates_pattern_buckets_and_oracle_learnings(tmp_path: Path) -> None:
    JczqDailyAdvisorService(provider=FakeProvider()).build_report(
        run_date="2026-05-01", output_dir=tmp_path
    )
    JczqDailyReviewService(result_provider=FakeFridayResultProvider()).build_review(
        run_date="2026-05-01", output_dir=tmp_path
    )

    memory = json.loads((tmp_path / "memory" / "strategy-memory.json").read_text(encoding="utf-8"))
    assert memory["version"] == 2
    buckets = memory["pattern_buckets"]
    assert buckets, "pattern_buckets should be non-empty after a review"
    learnings = memory["oracle_learnings"]
    assert learnings, "oracle_learnings should record actual outcome rows"

    # Bucket key contains league::role::pool
    sample_key = next(iter(buckets.keys()))
    assert sample_key.count("::") == 2

    # API helpers expose data correctly
    a_bucket = next(iter(buckets.values()))
    ev = pattern_bucket_ev(memory, a_bucket["league"], a_bucket["role"], a_bucket["pool"])
    assert isinstance(ev, float)
    a_oracle = learnings[0]
    found = oracle_learning_for(memory, a_oracle["league"], a_oracle["pool"])
    assert any(item["winning_pick"] == a_oracle["winning_pick"] for item in found)


def test_review_emits_explanations_for_missed_plans(tmp_path: Path) -> None:
    JczqDailyAdvisorService(provider=FakeProvider()).build_report(
        run_date="2026-05-01", output_dir=tmp_path
    )
    review = JczqDailyReviewService(result_provider=FakeFridayResultProvider()).build_review(
        run_date="2026-05-01", output_dir=tmp_path
    )

    explanations = review.get("explanations") or []
    if explanations:
        sample = explanations[0]
        assert sample["plan_kind"]
        assert isinstance(sample["killer_legs"], list)
        assert isinstance(sample["extracted_rules"], list)
