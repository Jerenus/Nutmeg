from __future__ import annotations

import json
from pathlib import Path

import pytest

from nutmeg.services.zucai import ZucaiWorkflowService
from nutmeg.services.zucai_odds_source import (
    ZucaiOddsSourceValidationError,
    ZucaiOddsSyncService,
)
from nutmeg.services.zucai_schedule import ZucaiScheduledDeliveryService
from nutmeg.services.zucai_source import ZucaiSourceSyncService

AFTERNOON = Path("nutmeg/zucai/samples/26068-odds-source-afternoon.html")
REVISION = Path("nutmeg/zucai/samples/26068-odds-source-revision.html")
SOURCE_NOTICE = Path("nutmeg/zucai/samples/26068-source-notice.html")


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def test_odds_parser_extracts_14_rows_and_metadata() -> None:
    service = ZucaiOddsSyncService()

    snapshot, warnings = service.parse_source_file(
        AFTERNOON,
        issue_id="26068",
        captured_at="2026-04-26 16:00 CST",
        source_label="afternoon odds",
        source_url="https://example.test/odds",
    )

    assert warnings == []
    assert snapshot["issue_id"] == "26068"
    assert snapshot["captured_at"] == "2026-04-26 16:00 CST"
    assert snapshot["sources"][0]["label"] == "afternoon odds"
    assert len(snapshot["matches"]) == 14
    assert snapshot["matches"][0]["match_no"] == 1
    assert snapshot["matches"][0]["home"] == 2.05
    assert snapshot["matches"][0]["draw"] == 3.45
    assert snapshot["matches"][0]["away"] == 3.50
    assert snapshot["matches"][0]["providers"][0]["name"] == "平均值"


def test_odds_parser_warns_and_rejects_incomplete_snapshot(tmp_path) -> None:
    bad = tmp_path / "bad-odds.html"
    bad.write_text(
        "足彩胜负游戏第99999期欧洲平均赔率\n"
        "采集时间：2026-04-26 16:00 CST\n"
        "场次\n主胜\n平局\n客胜\n1\n0\n3.2\n4.1",
        encoding="utf-8",
    )

    snapshot, warnings = ZucaiOddsSyncService().parse_source_file(
        bad,
        issue_id=None,
        captured_at=None,
        source_label="bad odds",
    )

    assert snapshot is None
    assert any("expected exactly 14" in warning for warning in warnings)


def test_odds_sync_writes_afternoon_snapshot_and_registry(tmp_path) -> None:
    registry_file = _write_json(
        tmp_path / "issues.json",
        {
            "entries": [
                {
                    "issue_id": "26068",
                    "enabled": True,
                    "active_dates": ["2026-04-26"],
                    "issue_file": "26068-issue.json",
                    "overrides_file": "26068-overrides.json",
                }
            ]
        },
    )

    result = ZucaiOddsSyncService().sync(
        source_file=AFTERNOON,
        issue_id="26068",
        slot="afternoon",
        captured_at="2026-04-26 16:00 CST",
        output_dir=tmp_path,
        registry_file=registry_file,
        source_label="afternoon odds",
    )

    assert result.issue_id == "26068"
    assert result.slot == "afternoon"
    assert result.parsed_count == 14
    odds_path = Path(result.odds_path)
    assert odds_path.exists()
    payload = json.loads(odds_path.read_text(encoding="utf-8"))
    assert payload["matches"][0]["home"] == 2.05
    entry = json.loads(registry_file.read_text(encoding="utf-8"))["entries"][0]
    assert entry["issue_file"] == "26068-issue.json"
    assert entry["overrides_file"] == "26068-overrides.json"
    assert entry["odds_file"] == "26068-odds.json"


def test_odds_sync_revision_preserves_afternoon_odds_and_updates_revision(tmp_path) -> None:
    registry_file = _write_json(
        tmp_path / "issues.json",
        {"entries": [{"issue_id": "26068", "issue_file": "26068-issue.json"}]},
    )
    service = ZucaiOddsSyncService()
    service.sync(
        source_file=AFTERNOON,
        issue_id="26068",
        slot="afternoon",
        captured_at="2026-04-26 16:00 CST",
        output_dir=tmp_path,
        registry_file=registry_file,
    )
    service.sync(
        source_file=REVISION,
        issue_id="26068",
        slot="revision",
        captured_at="2026-04-26 18:30 CST",
        output_dir=tmp_path,
        registry_file=registry_file,
    )

    entry = json.loads(registry_file.read_text(encoding="utf-8"))["entries"][0]
    assert entry["odds_file"] == "26068-odds.json"
    assert entry["revision_odds_file"] == "26068-odds-revision.json"
    revision_payload = json.loads((tmp_path / entry["revision_odds_file"]).read_text())
    assert revision_payload["matches"][0]["home"] == 2.22


def test_odds_synced_revision_registry_feeds_zucai_auto_run(tmp_path) -> None:
    source_sync = ZucaiSourceSyncService().sync(
        source_file=SOURCE_NOTICE,
        run_date="2026-04-26",
        output_dir=tmp_path / "zucai",
        registry_file=tmp_path / "zucai" / "issues.json",
    )
    registry_file = Path(source_sync.registry_path)
    ZucaiOddsSyncService().sync(
        source_file=AFTERNOON,
        issue_id="26068",
        slot="afternoon",
        captured_at="2026-04-26 16:00 CST",
        output_dir=tmp_path / "zucai",
        registry_file=registry_file,
    )
    ZucaiOddsSyncService().sync(
        source_file=REVISION,
        issue_id="26068",
        slot="revision",
        captured_at="2026-04-26 18:30 CST",
        output_dir=tmp_path / "zucai",
        registry_file=registry_file,
    )

    run = ZucaiScheduledDeliveryService(workflow_service=ZucaiWorkflowService()).run(
        run_date="2026-04-26",
        slot="revision",
        registry_file=registry_file,
        output_dir=tmp_path / "scheduled",
        run_record_file=tmp_path / "scheduled-runs.json",
    )

    assert run.status == "generated"
    assert run.report is not None
    assert run.report.recommendations[0].odds_average == {"3": 2.22, "1": 3.38, "0": 3.18}


def test_odds_source_url_requires_live_fetch() -> None:
    with pytest.raises(ZucaiOddsSourceValidationError, match="requires --live-fetch"):
        ZucaiOddsSyncService().sync(
            source_url="https://example.test/odds.html",
            live_fetch=False,
            issue_id="26068",
            slot="afternoon",
            captured_at="2026-04-26 16:00 CST",
            output_dir=Path(".nutmeg-data/test"),
            registry_file=Path(".nutmeg-data/test/issues.json"),
        )


def test_sync_archives_every_capture_append_only(tmp_path) -> None:
    """同一 slot 重复抓取必须逐份存档,不得原地覆盖丢失历史。

    位移特征(伤停/战意的无泄漏代理)依赖跨时点快照;2026-09-14 闭环实验发现
    覆盖写导致每期只剩 2 个同日快照,位移中位数仅 0.5pp,特征无法成立。
    """
    service = ZucaiOddsSyncService()
    out = tmp_path / "zucai"
    registry = tmp_path / "registry.json"

    first = service.sync(
        source_file=AFTERNOON,
        issue_id="26068",
        slot="afternoon",
        captured_at="2026-04-26 10:00 CST",
        output_dir=out,
        registry_file=registry,
    )
    second = service.sync(
        source_file=AFTERNOON,
        issue_id="26068",
        slot="afternoon",
        captured_at="2026-04-26 16:00 CST",
        output_dir=out,
        registry_file=registry,
    )

    # 规范文件仍是最新一份(既有读端不受影响)
    canonical = out / "26068-odds.json"
    assert canonical.exists()
    assert json.loads(canonical.read_text())["captured_at"] == "2026-04-26 16:00 CST"

    # 存档目录保留了两次抓取
    archived = sorted((out / "snapshots").glob("26068-odds-*.json"))
    assert len(archived) == 2, f"append-only 存档缺失: {archived}"
    stamps = {json.loads(p.read_text())["captured_at"] for p in archived}
    assert stamps == {"2026-04-26 10:00 CST", "2026-04-26 16:00 CST"}
    assert first.archive_path != second.archive_path
