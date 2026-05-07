from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nutmeg.services.content import SHORT_VIDEO_DISCLAIMER
from nutmeg.services.video_worker import VideoWorkerService, VideoWorkerValidationError


def _write_match_artifacts(
    run_dir: Path,
    *,
    match_id: str = "周四001",
    script: str | None = None,
    risk_level: str = "MEDIUM",
) -> Path:
    match_dir = run_dir / "matches" / match_id
    production_dir = match_dir / "production-v2"
    production_dir.mkdir(parents=True)
    final_script = script or f"这场只看开局节奏。{SHORT_VIDEO_DISCLAIMER}"
    (production_dir / "voiceover-script.md").write_text(final_script, encoding="utf-8")
    (production_dir / "content-brief.json").write_text(
        json.dumps(
            {
                "match_id": match_id,
                "selected_hook": "表面看是主场，其实先看压迫。",
                "main_contradiction": "主队的开局压迫，能不能压住客队的反击速度。",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (match_dir / "public-script.md").write_text(
        f"# {match_id} 主队 vs 客队\n\n{final_script}\n",
        encoding="utf-8",
    )
    (match_dir / "compliance.json").write_text(
        json.dumps(
            {"risk_level": risk_level, "publish_recommendation": "人工审核后可发"},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return match_dir


def test_build_packets_for_run_writes_mpt_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / "daily-content" / "20260507" / "run-120000"
    _write_match_artifacts(run_dir)

    result = VideoWorkerService().build_packets_for_run(
        run_dir=run_dir,
        run_id="daily-content-20260507-120000",
        run_date="2026-05-07",
    )

    manifest_path = run_dir / "moneyprinterturbo-manifest.json"
    task_path = run_dir / "matches" / "周四001" / "production-mpt" / "mpt-task.json"
    request_path = run_dir / "matches" / "周四001" / "production-mpt" / "request.json"
    quality_path = (
        run_dir / "matches" / "周四001" / "production-mpt" / "quality-report.json"
    )
    task = json.loads(task_path.read_text(encoding="utf-8"))
    request = json.loads(request_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert result["tasks"] == 1
    assert task["match_id"] == "周四001"
    assert task["status"] == "draft"
    assert task["request"]["video_script"].endswith(SHORT_VIDEO_DISCLAIMER)
    assert request["video_subject"].startswith("周四001")
    assert request["video_terms"] == ["football", "stadium", "training", "match analysis"]
    assert manifest["run_id"] == "daily-content-20260507-120000"
    assert manifest["tasks"][0]["task_path"] == str(task_path)
    assert json.loads(quality_path.read_text(encoding="utf-8"))["status"] == "review"


def test_build_packets_blocks_missing_disclaimer(tmp_path: Path) -> None:
    run_dir = tmp_path / "daily-content" / "20260507" / "run-120000"
    _write_match_artifacts(run_dir, script="这场只看开局节奏。")

    VideoWorkerService().build_packets_for_run(
        run_dir=run_dir,
        run_id="daily-content-20260507-120000",
        run_date="2026-05-07",
    )

    task_path = run_dir / "matches" / "周四001" / "production-mpt" / "mpt-task.json"
    quality_path = (
        run_dir / "matches" / "周四001" / "production-mpt" / "quality-report.json"
    )
    task = json.loads(task_path.read_text(encoding="utf-8"))
    quality = json.loads(quality_path.read_text(encoding="utf-8"))

    assert task["status"] == "blocked_by_disclaimer"
    assert task["error"] == "Missing required short-video disclaimer."
    assert quality["status"] == "blocked"


def test_build_packets_blocks_high_or_blocked_compliance(tmp_path: Path) -> None:
    run_dir = tmp_path / "daily-content" / "20260507" / "run-120000"
    _write_match_artifacts(run_dir, risk_level="BLOCKED")

    VideoWorkerService().build_packets_for_run(
        run_dir=run_dir,
        run_id="daily-content-20260507-120000",
        run_date="2026-05-07",
    )

    task_path = run_dir / "matches" / "周四001" / "production-mpt" / "mpt-task.json"
    task = json.loads(task_path.read_text(encoding="utf-8"))

    assert task["status"] == "blocked_by_compliance"
    assert task["error"] == "Compliance risk BLOCKED is not eligible for worker submission."


def test_build_packets_requires_run_dir(tmp_path: Path) -> None:
    missing = tmp_path / "missing-run"

    with pytest.raises(VideoWorkerValidationError, match="video-mpt-packet"):
        VideoWorkerService().build_packets_for_run(
            run_dir=missing,
            run_id="daily-content-20260507-120000",
            run_date="2026-05-07",
        )


class FakeMptClient:
    def __init__(self) -> None:
        self.created_payloads: list[dict[str, Any]] = []
        self.downloads: list[tuple[str, Path]] = []

    def create_video(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.created_payloads.append(payload)
        task_id = f"mpt-{len(self.created_payloads)}"
        return {
            "task_id": task_id,
            "raw": {"status": 200, "data": {"task_id": task_id}},
        }

    def query_task(self, task_id: str) -> dict[str, Any]:
        return {
            "state": 1,
            "progress": 100,
            "videos": [f"http://localhost:8080/tasks/{task_id}/final-1.mp4"],
            "combined_videos": [
                f"http://localhost:8080/tasks/{task_id}/combined-1.mp4"
            ],
        }

    def download_video(self, url: str, *, output_path: Path) -> Path:
        self.downloads.append((url, output_path))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"mp4")
        return output_path


def test_submit_run_requires_confirm(tmp_path: Path) -> None:
    run_dir = tmp_path / "daily-content" / "20260507" / "run-120000"
    _write_match_artifacts(run_dir)
    service = VideoWorkerService(client=FakeMptClient())
    service.build_packets_for_run(run_dir=run_dir, run_id="run-1", run_date="2026-05-07")

    try:
        service.submit_run(run_dir=run_dir, confirm=False)
    except VideoWorkerValidationError as exc:
        assert "--confirm" in str(exc)
    else:
        raise AssertionError("Expected VideoWorkerValidationError")


def test_submit_run_posts_draft_tasks_and_persists_task_id(tmp_path: Path) -> None:
    run_dir = tmp_path / "daily-content" / "20260507" / "run-120000"
    _write_match_artifacts(run_dir)
    client = FakeMptClient()
    service = VideoWorkerService(client=client)
    service.build_packets_for_run(run_dir=run_dir, run_id="run-1", run_date="2026-05-07")

    result = service.submit_run(run_dir=run_dir, confirm=True)

    task_path = run_dir / "matches" / "周四001" / "production-mpt" / "mpt-task.json"
    submit_path = (
        run_dir / "matches" / "周四001" / "production-mpt" / "submit-result.json"
    )
    status_path = run_dir / "moneyprinterturbo-status.json"
    task = json.loads(task_path.read_text(encoding="utf-8"))
    status = json.loads(status_path.read_text(encoding="utf-8"))

    assert result.submitted == 1
    assert result.skipped == 0
    assert client.created_payloads[0]["video_script"].endswith(SHORT_VIDEO_DISCLAIMER)
    assert task["status"] == "submitted"
    assert task["task_id"] == "mpt-1"
    assert json.loads(submit_path.read_text(encoding="utf-8"))["task_id"] == "mpt-1"
    assert status["tasks"][0]["task_id"] == "mpt-1"


def test_submit_run_skips_blocked_tasks(tmp_path: Path) -> None:
    run_dir = tmp_path / "daily-content" / "20260507" / "run-120000"
    _write_match_artifacts(run_dir, risk_level="BLOCKED")
    client = FakeMptClient()
    service = VideoWorkerService(client=client)
    service.build_packets_for_run(run_dir=run_dir, run_id="run-1", run_date="2026-05-07")

    result = service.submit_run(run_dir=run_dir, confirm=True)

    assert result.submitted == 0
    assert result.blocked == 1
    assert client.created_payloads == []


def test_poll_run_downloads_completed_videos(tmp_path: Path) -> None:
    run_dir = tmp_path / "daily-content" / "20260507" / "run-120000"
    _write_match_artifacts(run_dir)
    client = FakeMptClient()
    service = VideoWorkerService(client=client)
    service.build_packets_for_run(run_dir=run_dir, run_id="run-1", run_date="2026-05-07")
    service.submit_run(run_dir=run_dir, confirm=True)

    result = service.poll_run(run_dir=run_dir, download=True)

    match_status = json.loads(
        (
            run_dir / "matches" / "周四001" / "production-mpt" / "status.json"
        ).read_text(encoding="utf-8")
    )
    aggregate = json.loads(
        (run_dir / "moneyprinterturbo-status.json").read_text(encoding="utf-8")
    )

    assert result.succeeded == 1
    assert result.downloaded == 2
    assert len(client.downloads) == 2
    assert match_status["status"] == "succeeded"
    assert len(match_status["local_video_paths"]) == 2
    assert Path(match_status["local_video_paths"][0]).exists()
    assert aggregate["tasks"][0]["status"] == "succeeded"
