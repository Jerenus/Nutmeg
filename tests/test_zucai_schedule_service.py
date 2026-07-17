from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from nutmeg.notifications.models import NotificationOutcome, NotificationStatus
from nutmeg.services.zucai import ZucaiWorkflowService
from nutmeg.services.zucai_schedule import (
    ZucaiScheduledDeliveryService,
    ZucaiScheduleValidationError,
)

SAMPLE_DIR = Path("nutmeg/zucai/samples")


class DryRunNotificationService:
    def __init__(self) -> None:
        self.calls = []

    def publish(self, request, *, dry_run=False):
        self.calls.append((request, dry_run))
        return NotificationOutcome(
            notification_id=None,
            dedupe_key=request.dedupe_key,
            status=NotificationStatus.DRY_RUN,
        )


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _service() -> ZucaiScheduledDeliveryService:
    return ZucaiScheduledDeliveryService(
        workflow_service=ZucaiWorkflowService(
            notification_service=DryRunNotificationService()
        )
    )


def _copy_sample_snapshots(target: Path) -> dict[str, str]:
    target.mkdir(parents=True, exist_ok=True)
    mapping = {}
    for suffix in ["issue", "odds", "overrides"]:
        src = SAMPLE_DIR / f"26068-{suffix}.json"
        dst = target / f"26068-{suffix}.json"
        shutil.copy(src, dst)
        mapping[f"{suffix}_file"] = dst.name
    return mapping


def test_schedule_service_skips_no_issue_without_dispatch_or_artifacts(tmp_path) -> None:
    registry_file = _write_json(tmp_path / "registry.json", {"entries": []})

    result = _service().run(
        run_date="2026-04-27",
        slot="afternoon",
        registry_file=registry_file,
        output_dir=tmp_path / "out",
        run_record_file=tmp_path / "records.json",
        dispatch_telegram=True,
        dry_run=True,
    )

    assert result.status == "skipped_no_issue"
    assert result.issue_id is None
    assert result.skipped_reason == "no active traditional Zucai issue for run date"
    assert result.dispatch.status == "skipped"
    assert result.artifacts.markdown_path is None
    assert not (tmp_path / "out").exists()
    assert not (tmp_path / "records.json").exists()


def test_schedule_service_tolerates_missing_registry_and_bad_entries(tmp_path) -> None:
    missing_result = _service().run(
        run_date="2026-04-26",
        slot="afternoon",
        registry_file=tmp_path / "missing.json",
        output_dir=tmp_path / "out",
        run_record_file=tmp_path / "records.json",
    )
    assert missing_result.status == "skipped_no_issue"
    assert any("registry missing" in warning for warning in missing_result.warnings)

    bad_registry = _write_json(
        tmp_path / "bad-registry.json",
        {
            "entries": [
                {"issue_id": "26068", "enabled": False, "issue_file": "ignored.json"},
                {"enabled": True, "active_dates": ["2026-04-26"]},
            ]
        },
    )
    bad_result = _service().run(
        run_date="2026-04-26",
        slot="afternoon",
        registry_file=bad_registry,
        output_dir=tmp_path / "out",
        run_record_file=tmp_path / "records.json",
    )
    assert bad_result.status == "skipped_no_issue"
    assert any("missing issue_id" in warning for warning in bad_result.warnings)


def test_schedule_service_rejects_unknown_slot(tmp_path) -> None:
    with pytest.raises(ZucaiScheduleValidationError, match="Unsupported Zucai schedule slot"):
        _service().run(
            run_date="2026-04-26",
            slot="morning",
            registry_file=tmp_path / "registry.json",
            output_dir=tmp_path / "out",
            run_record_file=tmp_path / "records.json",
        )


def test_schedule_service_generates_afternoon_report_and_run_record(tmp_path) -> None:
    paths = _copy_sample_snapshots(tmp_path / "snapshots")
    registry_file = _write_json(
        tmp_path / "snapshots" / "registry.json",
        {
            "entries": [
                {
                    "issue_id": "26068",
                    "active_dates": ["2026-04-26"],
                    **paths,
                }
            ]
        },
    )

    result = _service().run(
        run_date="2026-04-26",
        slot="afternoon",
        registry_file=registry_file,
        output_dir=tmp_path / "scheduled",
        run_record_file=tmp_path / "records.json",
        dispatch_telegram=True,
        dry_run=True,
    )

    assert result.status == "dry_run"
    assert result.issue_id == "26068"
    assert result.slot_label == "16:00首版分析"
    assert result.report is not None
    assert len(result.report.recommendations) == 14
    assert result.artifacts.pdf_path is not None
    assert "2026-04-26-afternoon" in result.artifacts.pdf_path
    assert Path(result.artifacts.pdf_path).read_bytes().startswith(b"%PDF")
    assert result.dispatch.status == "dry_run"
    assert "16:00首版分析" in (result.dispatch.caption or "")

    records = json.loads((tmp_path / "records.json").read_text(encoding="utf-8"))["records"]
    assert len(records) == 1
    assert records[0]["slot"] == "afternoon"
    assert records[0]["dispatch_status"] == "dry_run"
    assert records[0]["pdf_path"] == result.artifacts.pdf_path


def test_schedule_service_revision_uses_separate_artifacts_and_caption(tmp_path) -> None:
    paths = _copy_sample_snapshots(tmp_path / "snapshots")
    registry_file = _write_json(
        tmp_path / "snapshots" / "registry.json",
        {"entries": [{"issue_id": "26068", "active_dates": ["2026-04-26"], **paths}]},
    )
    service = _service()

    afternoon = service.run(
        run_date="2026-04-26",
        slot="afternoon",
        registry_file=registry_file,
        output_dir=tmp_path / "scheduled",
        run_record_file=tmp_path / "records.json",
        dispatch_telegram=True,
        dry_run=True,
    )
    revision = service.run(
        run_date="2026-04-26",
        slot="revision",
        registry_file=registry_file,
        output_dir=tmp_path / "scheduled",
        run_record_file=tmp_path / "records.json",
        dispatch_telegram=True,
        dry_run=True,
    )

    assert revision.status == "dry_run"
    assert revision.slot_label == "18:30修正确认"
    assert afternoon.artifacts.pdf_path != revision.artifacts.pdf_path
    assert "2026-04-26-revision" in (revision.artifacts.pdf_path or "")
    assert "18:30修正确认" in (revision.dispatch.caption or "")
    records = json.loads((tmp_path / "records.json").read_text(encoding="utf-8"))["records"]
    assert [record["slot"] for record in records] == ["afternoon", "revision"]


def test_schedule_service_revision_uses_revision_specific_overrides(tmp_path) -> None:
    paths = _copy_sample_snapshots(tmp_path / "snapshots")
    revision_overrides = _write_json(
        tmp_path / "snapshots" / "26068-revision-overrides.json",
        {
            "issue_id": "26068",
            "matches": [
                {
                    "match_no": 1,
                    "pick": "0",
                    "primary": "0",
                    "risk_tier": "volatile",
                    "confidence": 0.52,
                    "rationale": "临场修正为防客胜。",
                }
            ],
        },
    )
    registry_file = _write_json(
        tmp_path / "snapshots" / "registry.json",
        {
            "entries": [
                {
                    "issue_id": "26068",
                    "active_dates": ["2026-04-26"],
                    **paths,
                    "revision_overrides_file": revision_overrides.name,
                }
            ]
        },
    )

    result = _service().run(
        run_date="2026-04-26",
        slot="revision",
        registry_file=registry_file,
        output_dir=tmp_path / "scheduled",
        run_record_file=tmp_path / "records.json",
    )

    assert result.report is not None
    assert result.report.recommendations[0].pick == "0"
    assert result.report.recommendations[0].override_applied is True


def test_schedule_service_skips_duplicate_and_force_regenerates(tmp_path) -> None:
    paths = _copy_sample_snapshots(tmp_path / "snapshots")
    registry_file = _write_json(
        tmp_path / "snapshots" / "registry.json",
        {"entries": [{"issue_id": "26068", "active_dates": ["2026-04-26"], **paths}]},
    )
    service = _service()
    kwargs = dict(
        run_date="2026-04-26",
        slot="afternoon",
        registry_file=registry_file,
        output_dir=tmp_path / "scheduled",
        run_record_file=tmp_path / "records.json",
        dispatch_telegram=True,
        dry_run=True,
    )

    first = service.run(**kwargs)
    duplicate = service.run(**kwargs)
    forced = service.run(**kwargs, force=True)

    assert first.status == "dry_run"
    assert duplicate.status == "skipped_duplicate"
    assert duplicate.dispatch.status == "skipped"
    assert forced.status == "dry_run"
    records = json.loads((tmp_path / "records.json").read_text(encoding="utf-8"))["records"]
    assert [record["status"] for record in records] == ["dry_run", "dry_run"]


def test_launchd_templates_call_expected_slots_and_times() -> None:
    afternoon = Path("ops/launchd/com.nutmeg.zucai.afternoon.plist").read_text(
        encoding="utf-8"
    )
    revision = Path("ops/launchd/com.nutmeg.zucai.revision.plist").read_text(
        encoding="utf-8"
    )

    assert "<integer>16</integer>" in afternoon
    assert "<integer>0</integer>" in afternoon
    assert "--slot" in afternoon and "afternoon" in afternoon
    assert "<integer>18</integer>" in revision
    assert "<integer>30</integer>" in revision
    assert "--slot" in revision and "revision" in revision
    assert "--dispatch-telegram" in afternoon
    assert "--no-dry-run" in revision
