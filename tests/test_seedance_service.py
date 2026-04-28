from __future__ import annotations

import json
from pathlib import Path

import pytest

from nutmeg.domain.daily_content import SeedanceTaskSpec
from nutmeg.services.seedance import SeedanceService, SeedanceValidationError


def _task() -> SeedanceTaskSpec:
    return SeedanceTaskSpec(
        task_key="001-vertical-segment-01",
        provider="volcengine-ark",
        model="doubao-seedance-2-0-260128",
        content=[{"type": "text", "text": "原创热血足球动画"}],
        resolution="720p",
        ratio="9:16",
        duration=15,
        seed=11,
        camera_fixed=False,
        watermark=True,
        generate_audio=False,
        safety_identifier="owner-hash",
    )


class FakeClient:
    def __init__(self) -> None:
        self.created: list[str] = []

    def create_task(self, spec: SeedanceTaskSpec) -> dict:
        self.created.append(spec.task_key)
        return {"id": "cgt-001", "status": "queued"}

    def get_task(self, task_id: str) -> dict:
        return {
            "id": task_id,
            "status": "succeeded",
            "content": {"video_url": "https://example.test/video.mp4"},
            "seed": 11,
            "resolution": "720p",
            "ratio": "9:16",
            "duration": 15,
        }


def test_seedance_submit_requires_confirmation(tmp_path) -> None:
    manifest = tmp_path / "seedance-manifest.json"
    manifest.write_text(
        json.dumps({"tasks": [_task().to_dict()]}, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(SeedanceValidationError, match="--confirm"):
        SeedanceService(client=FakeClient()).submit_manifest(manifest_path=manifest, confirm=False)


def test_seedance_submit_and_poll_updates_manifest(tmp_path) -> None:
    manifest = tmp_path / "seedance-manifest.json"
    manifest.write_text(
        json.dumps({"tasks": [_task().to_dict()]}, ensure_ascii=False),
        encoding="utf-8",
    )
    service = SeedanceService(client=FakeClient())

    submitted = service.submit_manifest(manifest_path=manifest, confirm=True)
    polled = service.poll_manifest(manifest_path=manifest, download=False)

    saved = json.loads(manifest.read_text(encoding="utf-8"))
    assert submitted["submitted"] == 1
    assert saved["tasks"][0]["provider_task_id"] == "cgt-001"
    assert polled["succeeded"] == 1
    assert saved["tasks"][0]["status"] in {"submitted", "succeeded"}


def test_seedance_submit_defaults_to_vertical_tasks_and_writes_status(tmp_path) -> None:
    vertical = _task().to_dict()
    vertical["match_id"] = "周一001"
    vertical["ratio_key"] = "vertical"
    horizontal = _task().to_dict()
    horizontal["task_key"] = "001-horizontal-segment-01"
    horizontal["ratio"] = "16:9"
    horizontal["match_id"] = "周一001"
    horizontal["ratio_key"] = "horizontal"
    manifest = tmp_path / "seedance-manifest.json"
    manifest.write_text(
        json.dumps({"run_id": "run-1", "tasks": [vertical, horizontal]}, ensure_ascii=False),
        encoding="utf-8",
    )
    fake = FakeClient()

    result = SeedanceService(client=fake).submit_manifest(manifest_path=manifest, confirm=True)

    saved = json.loads(manifest.read_text(encoding="utf-8"))
    status = json.loads((tmp_path / "seedance-status.json").read_text(encoding="utf-8"))
    assert result["submitted"] == 1
    assert fake.created == ["001-vertical-segment-01"]
    assert saved["tasks"][0]["provider_task_id"] == "cgt-001"
    assert saved["tasks"][1]["provider_task_id"] is None
    assert status["counts"]["submitted"] == 1
    assert status["counts"]["draft"] == 1


def test_seedance_poll_can_resolve_manifest_from_run_dir_and_concat(tmp_path) -> None:
    video_a = tmp_path / "segment-a.mp4"
    video_b = tmp_path / "segment-b.mp4"
    video_a.write_bytes(b"a")
    video_b.write_bytes(b"b")
    first = _task().to_dict()
    first.update(
        {
            "match_id": "周一001",
            "ratio_key": "vertical",
            "provider_task_id": "cgt-001",
            "status": "succeeded",
            "local_video_path": str(video_a),
        }
    )
    second = _task().to_dict()
    second.update(
        {
            "task_key": "001-vertical-segment-02",
            "match_id": "周一001",
            "ratio_key": "vertical",
            "provider_task_id": "cgt-002",
            "status": "succeeded",
            "local_video_path": str(video_b),
        }
    )
    manifest = tmp_path / "seedance-manifest.json"
    manifest.write_text(
        json.dumps({"run_id": "run-1", "run_dir": str(tmp_path), "tasks": [first, second]}),
        encoding="utf-8",
    )
    commands: list[list[str]] = []

    def runner(cmd, *, capture_output, text, check):
        commands.append(cmd)
        out_arg = cmd[-1]
        Path(out_arg).write_bytes(b"final")
        return type("Result", (), {"returncode": 0, "stderr": ""})()

    service = SeedanceService(client=FakeClient(), concat_runner=runner)

    result = service.poll_manifest(run_dir=tmp_path, download=False, concat=True)

    assert result["succeeded"] == 2
    assert result["concatenated"] == 1
    assert commands and commands[0][0] == "ffmpeg"
    assert (tmp_path / "matches" / "周一001" / "videos" / "final-vertical.mp4").exists()
