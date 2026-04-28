from __future__ import annotations

import json
from pathlib import Path

import pytest

from nutmeg.services.zucai import ZucaiWorkflowService
from nutmeg.services.zucai_schedule import ZucaiScheduledDeliveryService
from nutmeg.services.zucai_source import (
    ZucaiSourceSyncService,
    ZucaiSourceValidationError,
)

SAMPLE_SOURCE = Path("nutmeg/zucai/samples/26068-source-notice.html")


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def test_source_parser_extracts_valid_14_match_issue() -> None:
    service = ZucaiSourceSyncService()

    issues = service.parse_source_file(
        SAMPLE_SOURCE,
        source_label="official schedule",
        source_url="https://example.test/source",
    )

    assert len(issues) == 1
    issue = issues[0].issue
    assert issue.issue_id == "26068"
    assert issue.sale_start == "2026-04-24 20:00"
    assert issue.sale_stop == "2026-04-26 22:00"
    assert issue.draw_date == "2026-04-27"
    assert len(issue.matches) == 14
    assert issue.matches[0].match_no == 1
    assert issue.matches[0].competition == "英冠"
    assert issue.matches[3].competition == "荷乙"
    assert issue.matches[3].home_team == "海牙"
    assert issue.sources[0]["label"] == "official schedule"
    assert issue.sources[0]["url"] == "https://example.test/source"


def test_source_parser_warns_and_skips_malformed_14_match_section(tmp_path) -> None:
    malformed = tmp_path / "bad.html"
    malformed.write_text(
        "足球彩票胜负游戏（14场和任选9场）第99999期\n"
        "第99999期\n英冠\n1\n主队A\n客队B\n2026-04-26\n停售时间：2026-04-26 22:00",
        encoding="utf-8",
    )
    service = ZucaiSourceSyncService()

    issues, warnings = service.parse_source_text(
        malformed.read_text(encoding="utf-8"),
        source_label="bad source",
        source_url=None,
    )

    assert issues == []
    assert any("99999" in warning and "exactly 14" in warning for warning in warnings)


def test_source_sync_writes_issue_snapshot_and_registry(tmp_path) -> None:
    result = ZucaiSourceSyncService().sync(
        source_file=SAMPLE_SOURCE,
        run_date="2026-04-26",
        output_dir=tmp_path / "zucai",
        registry_file=tmp_path / "zucai" / "issues.json",
        source_label="official schedule",
        source_url="https://example.test/source",
    )

    assert result.parsed_count == 1
    assert result.active_issue_ids == ["26068"]
    issue_path = Path(result.written_issue_paths["26068"])
    assert issue_path.exists()
    payload = json.loads(issue_path.read_text(encoding="utf-8"))
    assert payload["issue_id"] == "26068"
    assert len(payload["matches"]) == 14
    registry = json.loads(Path(result.registry_path).read_text(encoding="utf-8"))
    assert registry["entries"][0]["issue_id"] == "26068"
    assert registry["entries"][0]["active_dates"] == ["2026-04-26"]
    assert registry["entries"][0]["issue_file"] == "26068-issue.json"


def test_source_sync_preserves_existing_registry_operator_paths(tmp_path) -> None:
    registry_file = _write_json(
        tmp_path / "issues.json",
        {
            "entries": [
                {
                    "issue_id": "26068",
                    "active_dates": ["2026-04-26"],
                    "issue_file": "old-issue.json",
                    "odds_file": "26068-odds.json",
                    "overrides_file": "26068-overrides.json",
                    "revision_odds_file": "26068-odds-1830.json",
                    "revision_overrides_file": "26068-overrides-1830.json",
                }
            ]
        },
    )

    ZucaiSourceSyncService().sync(
        source_file=SAMPLE_SOURCE,
        run_date="2026-04-26",
        output_dir=tmp_path,
        registry_file=registry_file,
    )

    entry = json.loads(registry_file.read_text(encoding="utf-8"))["entries"][0]
    assert entry["issue_file"] == "26068-issue.json"
    assert entry["odds_file"] == "26068-odds.json"
    assert entry["overrides_file"] == "26068-overrides.json"
    assert entry["revision_odds_file"] == "26068-odds-1830.json"
    assert entry["revision_overrides_file"] == "26068-overrides-1830.json"


def test_source_generated_registry_feeds_zucai_auto_run(tmp_path) -> None:
    sync = ZucaiSourceSyncService().sync(
        source_file=SAMPLE_SOURCE,
        run_date="2026-04-26",
        output_dir=tmp_path / "zucai",
        registry_file=tmp_path / "zucai" / "issues.json",
    )
    assert sync.active_issue_ids == ["26068"]

    run = ZucaiScheduledDeliveryService(
        workflow_service=ZucaiWorkflowService()
    ).run(
        run_date="2026-04-26",
        slot="afternoon",
        registry_file=Path(sync.registry_path),
        output_dir=tmp_path / "scheduled",
        run_record_file=tmp_path / "scheduled-runs.json",
        dispatch_telegram=False,
    )

    assert run.status == "generated"
    assert run.issue_id == "26068"
    assert run.report is not None
    assert len(run.report.recommendations) == 14
    assert Path(run.artifacts.pdf_path).read_bytes().startswith(b"%PDF")


def test_source_url_requires_live_fetch() -> None:
    with pytest.raises(ZucaiSourceValidationError, match="requires --live-fetch"):
        ZucaiSourceSyncService().sync(
            source_url="https://example.test/source.html",
            live_fetch=False,
            run_date="2026-04-26",
            output_dir=Path(".nutmeg-data/test"),
            registry_file=Path(".nutmeg-data/test/issues.json"),
        )
