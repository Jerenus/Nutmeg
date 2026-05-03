from __future__ import annotations

from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.storage.betting_plan_repository import DuckDbBettingPlanRepository
from nutmeg.storage.bootstrap import create_analytics_schema


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings(data_dir=tmp_path)


def _jczq_report_payload() -> dict:
    return {
        "run_date": "2026-05-02",
        "generated_at": "2026-05-02T08:49:24+00:00",
        "summary": "portfolio strategy",
        "artifacts": {"context_path": ".nutmeg-data/jczq/daily/2026-05-02/context.json"},
        "plans": [
            {
                "name": "基础稳健A",
                "kind": "stable_base",
                "description": "稳健底仓",
                "total_odds": 12.0,
                "two_yuan_return": 24.0,
                "risk_note": "低波动",
                "legs": [
                    {
                        "match_no": "周六001",
                        "league": "英超",
                        "home_team": "主队A",
                        "away_team": "客队A",
                        "pool": "had",
                        "play": "胜平负",
                        "pick": "胜",
                        "odds": 2.0,
                        "logic": "底仓锚点",
                        "goal_line": "",
                        "odds_update": "2026-05-02 12:00:00",
                    },
                    {
                        "match_no": "周六002",
                        "league": "意甲",
                        "home_team": "主队B",
                        "away_team": "客队B",
                        "pool": "had",
                        "play": "胜平负",
                        "pick": "平",
                        "odds": 6.0,
                        "logic": "防平",
                        "goal_line": "",
                        "odds_update": "2026-05-02 12:00:00",
                    },
                ],
            }
        ],
    }


def test_repository_records_final_jczq_report_idempotently(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    create_analytics_schema(settings)
    repository = DuckDbBettingPlanRepository(settings)

    first = repository.record_jczq_report(_jczq_report_payload())
    second = repository.record_jczq_report(_jczq_report_payload())

    assert first["run_id"] == "jczq:2026-05-02:final"
    assert second["run_id"] == first["run_id"]

    stored = repository.get_run("jczq:2026-05-02:final")

    assert stored is not None
    assert stored["game_type"] == "jczq"
    assert stored["run_date"] == "2026-05-02"
    assert len(stored["plans"]) == 1
    assert stored["plans"][0]["role"] == "stable_base"
    assert stored["plans"][0]["total_odds"] == 12.0
    assert [leg["pick"] for leg in stored["plans"][0]["legs"]] == ["胜", "平"]


def test_repository_records_jczq_review_with_same_play_oracle_odds(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    create_analytics_schema(settings)
    repository = DuckDbBettingPlanRepository(settings)
    repository.record_jczq_report(_jczq_report_payload())

    reviews = repository.record_jczq_review(
        _jczq_report_payload(),
        results={
            "周六001": {
                "score": "0:1",
                "half_score": "0:0",
                "had": "负",
                "had_odds": "4.20",
            },
            "周六002": {
                "score": "1:1",
                "half_score": "1:0",
                "had": "平",
                "had_odds": "3.10",
            },
        },
        review_date="2026-05-03",
    )

    assert reviews[0]["hit_count"] == 1
    assert reviews[0]["leg_count"] == 2
    assert reviews[0]["all_hit"] is False
    assert reviews[0]["settled_odds"] == 0.0
    assert reviews[0]["oracle_same_play_odds"] == 13.02
    assert reviews[0]["oracle_return_yuan"] == 26.04

    stored_reviews = repository.list_plan_reviews("jczq:2026-05-02:final")

    assert stored_reviews[0]["oracle_same_play_odds"] == 13.02
    assert stored_reviews[0]["legs"][0]["actual_pick"] == "负"
    assert stored_reviews[0]["legs"][0]["actual_odds"] == 4.2
