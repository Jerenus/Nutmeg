from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

DEFAULT_MPT_TERMS = ["football", "stadium", "training", "match analysis"]
DEFAULT_MPT_VOICE = "zh-CN-XiaoxiaoNeural-Female"
DEFAULT_MPT_VIDEO_SOURCE = "pexels"
DEFAULT_MPT_BGM_VOLUME = 0.12


@dataclass(slots=True, frozen=True)
class MoneyPrinterTurboRequest:
    video_subject: str
    video_script: str
    video_terms: list[str] = field(default_factory=lambda: list(DEFAULT_MPT_TERMS))
    video_aspect: str = "9:16"
    video_concat_mode: str = "random"
    video_transition_mode: str = "Shuffle"
    video_clip_duration: int = 5
    video_count: int = 1
    video_source: str = DEFAULT_MPT_VIDEO_SOURCE
    video_language: str = "zh-CN"
    voice_name: str = DEFAULT_MPT_VOICE
    voice_volume: float = 1.0
    voice_rate: float = 1.08
    bgm_type: str = "random"
    bgm_file: str = ""
    bgm_volume: float = DEFAULT_MPT_BGM_VOLUME
    subtitle_enabled: bool = True
    subtitle_position: str = "bottom"
    custom_position: float = 70.0
    font_name: str = "STHeitiMedium.ttc"
    text_fore_color: str = "#FFFFFF"
    text_background_color: bool | str = True
    font_size: int = 60
    stroke_color: str = "#000000"
    stroke_width: float = 1.5
    n_threads: int = 2
    paragraph_number: int = 1

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> MoneyPrinterTurboRequest:
        values = dict(payload)
        if isinstance(values.get("video_terms"), tuple):
            values["video_terms"] = list(values["video_terms"])
        return cls(**values)


@dataclass(slots=True, frozen=True)
class MoneyPrinterTurboTaskPacket:
    run_id: str
    run_date: str
    match_id: str
    match_no: str
    title: str
    script: str
    request: MoneyPrinterTurboRequest
    source_paths: dict[str, str]
    compliance: dict[str, Any]
    status: str = "draft"
    task_id: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_date": self.run_date,
            "match_id": self.match_id,
            "match_no": self.match_no,
            "title": self.title,
            "script": self.script,
            "request": self.request.to_payload(),
            "source_paths": self.source_paths,
            "compliance": self.compliance,
            "status": self.status,
            "task_id": self.task_id,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> MoneyPrinterTurboTaskPacket:
        return cls(
            run_id=str(payload["run_id"]),
            run_date=str(payload["run_date"]),
            match_id=str(payload["match_id"]),
            match_no=str(payload["match_no"]),
            title=str(payload["title"]),
            script=str(payload["script"]),
            request=MoneyPrinterTurboRequest.from_dict(dict(payload["request"])),
            source_paths={
                str(key): str(value)
                for key, value in dict(payload.get("source_paths") or {}).items()
            },
            compliance=dict(payload.get("compliance") or {}),
            status=str(payload.get("status") or "draft"),
            task_id=payload.get("task_id"),
            error=payload.get("error"),
        )


@dataclass(slots=True, frozen=True)
class MoneyPrinterTurboTaskState:
    match_id: str
    task_id: str
    status: str
    worker_state: int | None
    progress: int | None
    video_urls: list[str]
    combined_video_urls: list[str]
    local_video_paths: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_id": self.match_id,
            "task_id": self.task_id,
            "status": self.status,
            "worker_state": self.worker_state,
            "progress": self.progress,
            "video_urls": self.video_urls,
            "combined_video_urls": self.combined_video_urls,
            "local_video_paths": self.local_video_paths,
            "raw": self.raw,
            "error": self.error,
        }

    @classmethod
    def from_worker_payload(
        cls,
        *,
        match_id: str,
        task_id: str,
        payload: dict[str, Any],
    ) -> MoneyPrinterTurboTaskState:
        videos = [str(item) for item in payload.get("videos") or []]
        combined = [str(item) for item in payload.get("combined_videos") or []]
        worker_state = _int_or_none(payload.get("state"))
        progress = _int_or_none(payload.get("progress"))
        error = payload.get("error")
        status = _status_from_worker_payload(
            worker_state=worker_state,
            progress=progress,
            error=error,
        )
        if status == "running" and (videos or combined):
            status = "succeeded"
        return cls(
            match_id=match_id,
            task_id=task_id,
            status=status,
            worker_state=worker_state,
            progress=progress,
            video_urls=videos,
            combined_video_urls=combined,
            raw=payload,
            error=str(error) if error else None,
        )


@dataclass(slots=True, frozen=True)
class VideoWorkerSubmissionResult:
    manifest_path: str
    submitted: int
    skipped: int
    blocked: int
    failed: int
    tasks: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class VideoWorkerPollResult:
    status_path: str
    succeeded: int
    running: int
    failed: int
    blocked: int
    downloaded: int
    tasks: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _status_from_worker_payload(
    *,
    worker_state: int | None,
    progress: int | None,
    error: Any,
) -> str:
    if error:
        return "failed"
    if progress == 100 or worker_state == 1:
        return "succeeded"
    if worker_state is not None or progress is not None:
        return "running"
    return "unknown"
