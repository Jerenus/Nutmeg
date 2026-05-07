from __future__ import annotations

from nutmeg.domain.video_worker import (
    MoneyPrinterTurboRequest,
    MoneyPrinterTurboTaskPacket,
    MoneyPrinterTurboTaskState,
)
from nutmeg.services.content import SHORT_VIDEO_DISCLAIMER


def test_moneyprinterturbo_request_uses_custom_script_and_safe_defaults() -> None:
    request = MoneyPrinterTurboRequest(
        video_subject="周四001 主队vs客队：赛前关键变量",
        video_script=f"这场只看节奏。{SHORT_VIDEO_DISCLAIMER}",
        video_terms=["football", "stadium", "match analysis"],
    )

    payload = request.to_payload()

    assert payload["video_subject"] == "周四001 主队vs客队：赛前关键变量"
    assert payload["video_script"].endswith(SHORT_VIDEO_DISCLAIMER)
    assert payload["video_terms"] == ["football", "stadium", "match analysis"]
    assert payload["video_aspect"] == "9:16"
    assert payload["video_count"] == 1
    assert payload["video_source"] == "pexels"
    assert payload["video_language"] == "zh-CN"
    assert payload["voice_name"] == "zh-CN-XiaoxiaoNeural-Female"
    assert payload["voice_rate"] == 1.08
    assert payload["bgm_volume"] == 0.12
    assert payload["subtitle_enabled"] is True


def test_task_packet_round_trips_with_request_and_provenance() -> None:
    request = MoneyPrinterTurboRequest(
        video_subject="周四001：先看节奏",
        video_script=f"先看开局节奏。{SHORT_VIDEO_DISCLAIMER}",
        video_terms=["football"],
    )
    packet = MoneyPrinterTurboTaskPacket(
        run_id="daily-content-20260507-120000",
        run_date="2026-05-07",
        match_id="周四001",
        match_no="周四001",
        title="周四001：先看节奏",
        script=request.video_script,
        request=request,
        source_paths={"voiceover_script_path": "matches/周四001/production-v2/voiceover-script.md"},
        compliance={"risk_level": "MEDIUM"},
    )

    restored = MoneyPrinterTurboTaskPacket.from_dict(packet.to_dict())

    assert restored == packet
    assert restored.request.to_payload()["video_script"] == request.video_script
    assert restored.source_paths["voiceover_script_path"].endswith("voiceover-script.md")
    assert restored.status == "draft"


def test_task_state_extracts_video_urls_from_worker_payload() -> None:
    state = MoneyPrinterTurboTaskState.from_worker_payload(
        match_id="周四001",
        task_id="mpt-task-1",
        payload={
            "state": 1,
            "progress": 100,
            "videos": ["http://localhost:8080/tasks/mpt-task-1/final-1.mp4"],
            "combined_videos": ["http://localhost:8080/tasks/mpt-task-1/combined-1.mp4"],
        },
    )

    assert state.match_id == "周四001"
    assert state.task_id == "mpt-task-1"
    assert state.worker_state == 1
    assert state.progress == 100
    assert state.video_urls == ["http://localhost:8080/tasks/mpt-task-1/final-1.mp4"]
    assert state.combined_video_urls == ["http://localhost:8080/tasks/mpt-task-1/combined-1.mp4"]
    assert state.status == "succeeded"
