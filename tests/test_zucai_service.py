from __future__ import annotations

import json
from pathlib import Path

import pytest

from nutmeg.config.settings import AppSettings
from nutmeg.notifications.models import (
    DeliveryOutcome,
    DeliveryStatus,
    NotificationOutcome,
    NotificationStatus,
)
from nutmeg.services.zucai import ZucaiValidationError, ZucaiWorkflowService
from nutmeg.storage.betting_plan_repository import DuckDbBettingPlanRepository
from nutmeg.storage.bootstrap import create_analytics_schema


class RecordingNotificationService:
    def __init__(self, outcome: NotificationOutcome) -> None:
        self.outcome = outcome
        self.calls = []

    def publish(self, request, *, dry_run=False):
        self.calls.append((request, dry_run))
        return self.outcome


def _dry_run_outcome(destination: str = "1234") -> NotificationOutcome:
    return NotificationOutcome(
        notification_id=None,
        dedupe_key="zucai:dry-run",
        status=NotificationStatus.DRY_RUN,
        deliveries=(
            DeliveryOutcome(
                delivery_id=None,
                channel="telegram",
                recipient_key="owner",
                destination=destination,
                required=True,
                status=DeliveryStatus.DRY_RUN,
            ),
        ),
    )


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _issue_payload(match_count: int = 14) -> dict:
    return {
        "issue_id": "test-issue",
        "game_type": "sfc14",
        "sale_stop": "2026-04-26 20:30",
        "sources": [{"label": "official schedule", "url": "https://example.test/schedule"}],
        "matches": [
            {
                "match_no": index,
                "competition": "测试联赛",
                "home_team": f"主队{index}",
                "away_team": f"客队{index}",
                "match_date": "2026-04-26",
                "risk_flags": ["draw_risk"] if index % 4 == 0 else [],
                "notes": [f"第{index}场测试说明"],
            }
            for index in range(1, match_count + 1)
        ],
    }


def _odds_payload() -> dict:
    return {
        "issue_id": "test-issue",
        "captured_at": "2026-04-26 17:00 CST",
        "sources": [{"label": "odds source", "url": "https://example.test/odds"}],
        "matches": [
            {"match_no": index, "home": 1.45 + index / 100, "draw": 3.40, "away": 6.00}
            for index in range(1, 15)
        ],
    }


def test_zucai_service_loads_issue_odds_and_overrides(tmp_path) -> None:
    issue_file = _write_json(tmp_path / "issue.json", _issue_payload())
    odds_file = _write_json(tmp_path / "odds.json", _odds_payload())
    overrides_file = _write_json(
        tmp_path / "overrides.json",
        {
            "issue_id": "test-issue",
            "matches": [
                {
                    "match_no": 1,
                    "pick": "31",
                    "primary": "3",
                    "risk_tier": "cover",
                    "confidence": 0.61,
                    "rationale": "主胜主线，但防平。",
                }
            ],
        },
    )

    report = ZucaiWorkflowService().build_report(
        issue_file=issue_file,
        odds_file=odds_file,
        overrides_file=overrides_file,
    )

    assert report.issue.issue_id == "test-issue"
    assert len(report.issue.matches) == 14
    assert len(report.recommendations) == 14
    first = report.recommendations[0]
    assert first.pick == "31"
    assert first.primary == "3"
    assert first.override_applied is True
    assert first.odds_average == {"3": 1.46, "1": 3.4, "0": 6.0}
    assert any(plan.plan_type == "full14" and plan.stake_count > 0 for plan in report.plans)
    assert any(plan.plan_type == "renjiu" for plan in report.plans)
    payload = report.to_dict()
    assert payload["recommendations"][0]["pick"] == "31"
    assert payload["sources"][0]["label"] == "official schedule"


def test_zucai_service_rejects_issue_without_exactly_14_matches(tmp_path) -> None:
    issue_file = _write_json(tmp_path / "issue.json", _issue_payload(match_count=13))

    with pytest.raises(ZucaiValidationError, match="exactly 14"):
        ZucaiWorkflowService().build_report(issue_file=issue_file)


def test_zucai_service_warns_and_ignores_invalid_override(tmp_path) -> None:
    issue_file = _write_json(tmp_path / "issue.json", _issue_payload())
    overrides_file = _write_json(
        tmp_path / "overrides.json",
        {"issue_id": "test-issue", "matches": [{"match_no": 2, "pick": "32"}]},
    )

    report = ZucaiWorkflowService().build_report(
        issue_file=issue_file,
        overrides_file=overrides_file,
    )

    assert report.recommendations[1].override_applied is False
    assert any("invalid override pick" in warning for warning in report.warnings)


def test_zucai_information_bias_metadata_adjusts_comfort_favorite(tmp_path) -> None:
    issue_file = _write_json(tmp_path / "issue.json", _issue_payload())
    odds_file = _write_json(
        tmp_path / "odds.json",
        {
            "issue_id": "test-issue",
            "matches": [
                {"match_no": 1, "home": 1.89, "draw": 3.83, "away": 3.73},
                *[
                    {"match_no": index, "home": 1.45 + index / 100, "draw": 3.40, "away": 6.00}
                    for index in range(2, 15)
                ],
            ],
        },
    )
    overrides_file = _write_json(
        tmp_path / "overrides.json",
        {
            "issue_id": "test-issue",
            "matches": [
                {
                    "match_no": 1,
                    "public_pick": "3",
                    "value_pick": "0",
                    "narrative_bias": "主胜叙事过热，客胜被当成不合理方向。",
                }
            ],
        },
    )

    report = ZucaiWorkflowService().build_report(
        issue_file=issue_file,
        odds_file=odds_file,
        overrides_file=overrides_file,
    )

    first = report.recommendations[0]
    assert first.pick == "310"
    assert first.risk_tier == "bias_adjusted"
    assert first.override_applied is True
    assert "信息理解偏差" in first.rationale
    assert "information_bias_check" in first.warnings
    assert not report.warnings


def test_zucai_information_bias_does_not_overrule_hard_strength_gap(tmp_path) -> None:
    issue_file = _write_json(tmp_path / "issue.json", _issue_payload())
    odds_file = _write_json(
        tmp_path / "odds.json",
        {
            "issue_id": "test-issue",
            "matches": [
                {"match_no": 1, "home": 1.24, "draw": 6.81, "away": 9.60},
                *[
                    {"match_no": index, "home": 1.45 + index / 100, "draw": 3.40, "away": 6.00}
                    for index in range(2, 15)
                ],
            ],
        },
    )
    overrides_file = _write_json(
        tmp_path / "overrides.json",
        {
            "issue_id": "test-issue",
            "matches": [
                {
                    "match_no": 1,
                    "public_pick": "3",
                    "value_pick": "0",
                    "narrative_bias": "热门过热但真实强度差距很硬。",
                }
            ],
        },
    )

    report = ZucaiWorkflowService().build_report(
        issue_file=issue_file,
        odds_file=odds_file,
        overrides_file=overrides_file,
    )

    first = report.recommendations[0]
    assert first.pick == "3"
    assert first.risk_tier == "banker"
    assert first.override_applied is False
    assert not report.warnings


def test_zucai_override_plans_can_encode_288_yuan_renjiu_attack(tmp_path) -> None:
    issue_file = _write_json(tmp_path / "issue.json", _issue_payload())
    overrides_file = _write_json(
        tmp_path / "overrides.json",
        {
            "issue_id": "test-issue",
            "plans": [
                {
                    "name": "主攻票",
                    "plan_type": "renjiu",
                    "code": "310 10 3 3 31 - - 31 - - 3 10 - 10",
                },
                {
                    "name": "变量补强票",
                    "plan_type": "renjiu",
                    "code": "- 31 3 3 - 30 30 - 31 31 3 - 0 -",
                },
                {
                    "name": "冷门校准票",
                    "plan_type": "renjiu",
                    "code": "30 - 3 3 31 - 0 31 - - 3 10 - 0",
                },
            ],
        },
    )

    report = ZucaiWorkflowService().build_report(
        issue_file=issue_file,
        overrides_file=overrides_file,
    )

    assert [plan.cost_yuan for plan in report.plans] == [192, 64, 32]
    assert sum(plan.cost_yuan for plan in report.plans) == 288
    assert all(len(plan.selected_matches) == 9 for plan in report.plans)


def test_zucai_service_writes_markdown_pdf_and_report_json(tmp_path) -> None:
    service = ZucaiWorkflowService()
    report = service.build_report(
        issue_file=Path("nutmeg/zucai/samples/26068-issue.json"),
        odds_file=Path("nutmeg/zucai/samples/26068-odds.json"),
        overrides_file=Path("nutmeg/zucai/samples/26068-overrides.json"),
        output_dir=tmp_path,
        render_pdf=True,
    )

    assert report.artifacts.markdown_path is not None
    assert report.artifacts.pdf_path is not None
    assert report.artifacts.report_json_path is not None
    assert (
        Path(report.artifacts.markdown_path)
        .read_text(encoding="utf-8")
        .startswith("# Nutmeg 足彩第26068期14场报告")
    )
    assert Path(report.artifacts.pdf_path).read_bytes().startswith(b"%PDF")
    saved_payload = json.loads(Path(report.artifacts.report_json_path).read_text(encoding="utf-8"))
    assert saved_payload["issue"]["issue_id"] == "26068"


def test_zucai_service_dry_run_dispatch_keeps_pdf_available(tmp_path) -> None:
    notifier = RecordingNotificationService(_dry_run_outcome())
    report = ZucaiWorkflowService(notification_service=notifier).build_report(
        issue_file=Path("nutmeg/zucai/samples/26068-issue.json"),
        odds_file=Path("nutmeg/zucai/samples/26068-odds.json"),
        overrides_file=Path("nutmeg/zucai/samples/26068-overrides.json"),
        output_dir=tmp_path,
        render_pdf=True,
        dispatch_telegram=True,
        dry_run=True,
        notification_stage="manual",
    )

    assert report.dispatch.status == "dry_run"
    assert report.dispatch.chat_ids == [1234]
    assert report.dispatch.document_path == report.artifacts.pdf_path
    assert "26068" in (report.dispatch.caption or "")
    assert notifier.calls[0][0].business_key == "26068"
    assert notifier.calls[0][0].stage == "manual"
    assert notifier.calls[0][1] is True


def test_zucai_service_grades_report_against_outcomes(tmp_path) -> None:
    service = ZucaiWorkflowService()
    report = service.build_report(
        issue_file=Path("nutmeg/zucai/samples/26068-issue.json"),
        odds_file=Path("nutmeg/zucai/samples/26068-odds.json"),
        overrides_file=Path("nutmeg/zucai/samples/26068-overrides.json"),
        output_dir=tmp_path,
        render_pdf=False,
    )
    grade = service.grade_report(
        report_file=Path(report.artifacts.report_json_path),
        outcomes_file=Path("nutmeg/zucai/samples/26068-outcomes.json"),
    )

    assert grade.issue_id == "26068"
    assert len(grade.match_results) == 14
    assert grade.match_results[0].hit is True
    assert grade.match_results[3].result == "1"
    assert grade.match_results[3].hit is True
    assert any(plan.covered for plan in grade.plan_results)
    assert grade.to_dict()["plan_results"][0]["hit_count"] >= 12


def test_zucai_service_records_final_plans_to_betting_db(tmp_path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    create_analytics_schema(settings)
    repository = DuckDbBettingPlanRepository(settings)
    service = ZucaiWorkflowService(betting_repository=repository)

    service.build_report(
        issue_file=Path("nutmeg/zucai/samples/26068-issue.json"),
        odds_file=Path("nutmeg/zucai/samples/26068-odds.json"),
        overrides_file=Path("nutmeg/zucai/samples/26068-overrides.json"),
        output_dir=tmp_path,
        record_final=True,
    )

    stored = repository.get_run("zucai:26068:final")

    assert stored is not None
    assert stored["game_type"] == "zucai"
    assert stored["plans"]
    assert stored["plans"][0]["legs"]
    assert stored["plans"][0]["legs"][0]["pool"] == "sfc14"


def test_zucai_service_records_grade_review_to_betting_db(tmp_path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    create_analytics_schema(settings)
    repository = DuckDbBettingPlanRepository(settings)
    service = ZucaiWorkflowService(betting_repository=repository)
    report = service.build_report(
        issue_file=Path("nutmeg/zucai/samples/26068-issue.json"),
        odds_file=Path("nutmeg/zucai/samples/26068-odds.json"),
        overrides_file=Path("nutmeg/zucai/samples/26068-overrides.json"),
        output_dir=tmp_path,
        record_final=True,
    )

    grade = service.grade_report(
        report_file=Path(report.artifacts.report_json_path),
        outcomes_file=Path("nutmeg/zucai/samples/26068-outcomes.json"),
        record_db=True,
    )

    stored_reviews = repository.list_plan_reviews("zucai:26068:final")

    assert grade.issue_id == "26068"
    assert stored_reviews
    assert any(review["all_hit"] for review in stored_reviews)
    assert stored_reviews[0]["legs"]


def test_zucai_service_grades_incomplete_outcomes_with_warnings(tmp_path) -> None:
    service = ZucaiWorkflowService()
    report = service.build_report(
        issue_file=Path("nutmeg/zucai/samples/26068-issue.json"),
        output_dir=tmp_path,
    )
    outcomes_file = _write_json(
        tmp_path / "outcomes.json", {"issue_id": "26068", "results": {"1": "3"}}
    )

    grade = service.grade_report(
        report_file=Path(report.artifacts.report_json_path),
        outcomes_file=outcomes_file,
    )

    assert grade.match_results[0].unresolved is False
    assert grade.match_results[1].unresolved is True
    assert any("missing outcome" in warning for warning in grade.warnings)
