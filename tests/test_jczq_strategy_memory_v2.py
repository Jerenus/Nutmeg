"""Strategy memory v2: pattern_buckets + oracle_learnings + bias hint."""

from __future__ import annotations

import json
from pathlib import Path

from nutmeg.services.jczq_daily import JczqDailyAdvisorService
from nutmeg.services.jczq_review import JczqDailyReviewService
from nutmeg.services.jczq_strategy_memory import (
    compute_poisson_lambda_signals,
    oracle_learning_for,
    pattern_bucket_ev,
    render_decision_policy_notes,
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


def test_operator_strategy_notes_render_before_auto_policy_notes() -> None:
    memory = {
        "operator_strategy": {
            "notes": [
                "B 主方案最多 2 个 TTG 精确落点，至少 1 腿 HAD/HHAD 方向表达。",
                "E 禁止三场 0:0，改为 1 个比分核 + 宽事件组合。",
            ],
        },
        "decision_policy": {
            "notes": [
                "舒服盘继续按主客方向防平防冷，热门打出时不得误记为冷门。",
            ],
        },
    }

    assert render_decision_policy_notes(memory, limit=3) == [
        "B 主方案最多 2 个 TTG 精确落点，至少 1 腿 HAD/HHAD 方向表达。",
        "E 禁止三场 0:0，改为 1 个比分核 + 宽事件组合。",
        "舒服盘继续按主客方向防平防冷，热门打出时不得误记为冷门。",
    ]


# --------------------------------------------------------- R1 (5/08) λ calibration


def test_compute_poisson_lambda_signals_raises_floor_when_residuals_systematic() -> None:
    """R1 (5/08 落库): when 3+ recent crs legs in a league show goal_residual
    ≥ +0.5 (model under-priced goals), recommend a higher Poisson edge floor
    for that league's crs picks. 5/07 incident: 解放者杯 005 0:0 fitted λ=
    1.23+0.55 → expected 1.78 goals; actual 2 goals (residual +0.22, mild),
    but combined with high-vol leagues we want a buffer."""

    memory = {
        "poisson_residuals": [
            {"date": "2026-05-05", "league": "解放者杯", "pool": "crs",
             "pick": "0:0", "expected_goals": 1.78, "realized_goals": 3,
             "goal_residual": 1.22, "hit": False},
            {"date": "2026-05-06", "league": "解放者杯", "pool": "crs",
             "pick": "0:0", "expected_goals": 1.95, "realized_goals": 4,
             "goal_residual": 2.05, "hit": False},
            {"date": "2026-05-07", "league": "解放者杯", "pool": "crs",
             "pick": "0:0", "expected_goals": 2.10, "realized_goals": 2,
             "goal_residual": -0.10, "hit": False},
            {"date": "2026-05-04", "league": "意甲", "pool": "crs",
             "pick": "0:0", "expected_goals": 2.20, "realized_goals": 1,
             "goal_residual": -1.20, "hit": False},
        ],
    }

    signals = compute_poisson_lambda_signals(memory)
    assert "解放者杯" in signals
    libertadores = signals["解放者杯"]
    assert libertadores["sample_count"] == 3
    assert libertadores["avg_goal_residual"] > 0.5
    # raised floor must be ≥ default 0.15 when model under-prices goals
    assert libertadores["recommended_crs_min_edge"] >= 0.20

    # 意甲 has only 1 sample → not enough data, no recommendation
    assert "意甲" not in signals or signals["意甲"]["sample_count"] < 3


def test_compute_poisson_lambda_signals_returns_empty_when_no_data() -> None:
    assert compute_poisson_lambda_signals({}) == {}
    assert compute_poisson_lambda_signals({"poisson_residuals": []}) == {}


def test_review_populates_poisson_residuals_for_priced_legs(tmp_path: Path) -> None:
    """Integration: after a review, memory['poisson_residuals'] should
    contain per-leg goal_residual entries that downstream calibration can
    consume on subsequent days."""
    JczqDailyAdvisorService(provider=FakeProvider()).build_report(
        run_date="2026-05-01", output_dir=tmp_path
    )
    JczqDailyReviewService(result_provider=FakeFridayResultProvider()).build_review(
        run_date="2026-05-01", output_dir=tmp_path
    )
    memory = json.loads(
        (tmp_path / "memory" / "strategy-memory.json").read_text(encoding="utf-8")
    )
    residuals = memory.get("poisson_residuals") or []
    assert residuals, "review must persist Poisson residuals for R1 calibration"
    sample = residuals[0]
    for required in {"date", "league", "pool", "pick", "goal_residual", "hit"}:
        assert required in sample
