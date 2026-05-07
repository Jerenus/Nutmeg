# MoneyPrinterTurbo Video Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local-Docker MoneyPrinterTurbo worker path so Nutmeg can turn its existing daily football video scripts into submitted, polled, downloaded video artifacts without giving up script ownership or compliance control.

**Architecture:** Nutmeg remains the orchestration and content brain. A focused domain module defines serializable worker packets, a MoneyPrinterTurbo HTTP adapter owns API calls and downloads, and a video-worker service maps existing run artifacts into MPT task folders, submission state, status files, and quality reports. CLI commands mirror the existing Seedance/Remotion boundaries and require `--confirm` before any worker submission.

**Tech Stack:** Python 3.12, dataclasses, Typer, httpx, pathlib/json artifacts, existing `DailyContentService`, pytest, ruff.

---

## File Structure

- Create `nutmeg/domain/video_worker.py`
  - Serializable dataclasses for MPT request payloads, task packets, task states, submission summaries, and poll summaries.
  - Keep this file free of HTTP and filesystem side effects except `to_dict` / `from_dict` conversion helpers.
- Create `nutmeg/services/moneyprinterturbo.py`
  - HTTP adapter for local MoneyPrinterTurbo Docker API.
  - Own URL construction, env-backed config, response contract parsing, task polling, health checks, and file downloads.
- Create `nutmeg/services/video_worker.py`
  - Filesystem orchestration for run directories.
  - Build `production-mpt` artifacts from existing `production-v2` outputs.
  - Submit pending tasks through an injected client.
  - Poll task status, download videos, and write aggregate status.
- Modify `nutmeg/interfaces/cli.py`
  - Add builders for the MPT client and video-worker service.
  - Add `video-mpt-packet`, `video-mpt-submit`, `video-mpt-poll`, and `video-mpt-health` commands.
- Modify `docs/video-production-v2.md`
  - Document the new MPT worker route and local Docker smoke commands.
- Create `tests/test_video_worker_domain.py`
  - Domain serialization and request payload defaults.
- Create `tests/test_moneyprinterturbo_service.py`
  - URL construction, create-video parsing, task polling, download behavior, and health checks with fake HTTP clients.
- Create `tests/test_video_worker_service.py`
  - Run-dir packet generation, compliance blocking, submit, poll, download, and aggregate manifests.
- Modify `tests/test_cli.py`
  - CLI coverage for packet generation, submit refusal without `--confirm`, submit success with fake service, poll success, and health output.

## Implementation Tasks

### Task 1: Domain Models For MPT Worker Packets

**Files:**
- Create: `nutmeg/domain/video_worker.py`
- Test: `tests/test_video_worker_domain.py`

- [ ] **Step 1: Write failing domain tests**

Create `tests/test_video_worker_domain.py`:

```python
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
```

- [ ] **Step 2: Run the domain tests to verify they fail**

Run:

```bash
uv run pytest tests/test_video_worker_domain.py -q
```

Expected: FAIL because `nutmeg.domain.video_worker` does not exist.

- [ ] **Step 3: Create the domain implementation**

Create `nutmeg/domain/video_worker.py`:

```python
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
            source_paths={str(k): str(v) for k, v in dict(payload.get("source_paths") or {}).items()},
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
        status = _status_from_worker_payload(worker_state=worker_state, progress=progress, error=error)
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
```

- [ ] **Step 4: Run the domain tests to verify they pass**

Run:

```bash
uv run pytest tests/test_video_worker_domain.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

Run:

```bash
git add nutmeg/domain/video_worker.py tests/test_video_worker_domain.py
git commit -m "feat: add moneyprinterturbo worker domain models"
```

Expected: commit succeeds and only the two listed files are staged.

### Task 2: MoneyPrinterTurbo HTTP Adapter

**Files:**
- Create: `nutmeg/services/moneyprinterturbo.py`
- Test: `tests/test_moneyprinterturbo_service.py`

- [ ] **Step 1: Write failing adapter tests**

Create `tests/test_moneyprinterturbo_service.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from nutmeg.services.moneyprinterturbo import (
    MoneyPrinterTurboClient,
    MoneyPrinterTurboConfig,
    MoneyPrinterTurboProviderError,
    MoneyPrinterTurboValidationError,
)


@dataclass
class FakeResponse:
    payload: dict[str, Any] | bytes
    status_code: int = 200

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        if not isinstance(self.payload, dict):
            raise ValueError("not json")
        return self.payload

    @property
    def content(self) -> bytes:
        if isinstance(self.payload, bytes):
            return self.payload
        return b"json"


class FakeHttpClient:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.responses: list[FakeResponse] = []
        self.closed = False

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.requests.append({"method": method, "url": url, **kwargs})
        return self.responses.pop(0)

    def close(self) -> None:
        self.closed = True


def test_config_builds_urls_with_prefix_and_empty_prefix() -> None:
    prefixed = MoneyPrinterTurboConfig(base_url="http://localhost:8080/", api_prefix="/api/v1")
    unprefixed = MoneyPrinterTurboConfig(base_url="http://localhost:8080", api_prefix="")

    assert prefixed.endpoint("/videos") == "http://localhost:8080/api/v1/videos"
    assert prefixed.endpoint("tasks/mpt-1") == "http://localhost:8080/api/v1/tasks/mpt-1"
    assert unprefixed.endpoint("/videos") == "http://localhost:8080/videos"


def test_create_video_posts_payload_and_returns_task_id() -> None:
    http = FakeHttpClient()
    http.responses.append(FakeResponse({"status": 200, "data": {"task_id": "mpt-1"}}))
    client = MoneyPrinterTurboClient(
        config=MoneyPrinterTurboConfig(base_url="http://localhost:8080", api_prefix="/api/v1"),
        http_client=http,
    )

    result = client.create_video({"video_subject": "subject", "video_script": "script"})

    assert result["task_id"] == "mpt-1"
    assert result["raw"]["status"] == 200
    assert http.requests[0]["method"] == "POST"
    assert http.requests[0]["url"] == "http://localhost:8080/api/v1/videos"
    assert http.requests[0]["json"] == {"video_subject": "subject", "video_script": "script"}


def test_create_video_rejects_missing_task_id_contract() -> None:
    http = FakeHttpClient()
    http.responses.append(FakeResponse({"status": 200, "data": {}}))
    client = MoneyPrinterTurboClient(
        config=MoneyPrinterTurboConfig(base_url="http://localhost:8080", api_prefix="/api/v1"),
        http_client=http,
    )

    with pytest.raises(MoneyPrinterTurboProviderError, match="task_id"):
        client.create_video({"video_subject": "subject"})


def test_query_task_returns_data_payload() -> None:
    http = FakeHttpClient()
    http.responses.append(
        FakeResponse(
            {
                "status": 200,
                "data": {
                    "state": 1,
                    "progress": 100,
                    "videos": ["http://localhost:8080/tasks/mpt-1/final-1.mp4"],
                },
            }
        )
    )
    client = MoneyPrinterTurboClient(
        config=MoneyPrinterTurboConfig(base_url="http://localhost:8080", api_prefix="/api/v1"),
        http_client=http,
    )

    data = client.query_task("mpt-1")

    assert data["progress"] == 100
    assert data["videos"] == ["http://localhost:8080/tasks/mpt-1/final-1.mp4"]
    assert http.requests[0]["url"] == "http://localhost:8080/api/v1/tasks/mpt-1"


def test_download_video_writes_bytes(tmp_path: Path) -> None:
    http = FakeHttpClient()
    http.responses.append(FakeResponse(b"mp4-bytes"))
    client = MoneyPrinterTurboClient(
        config=MoneyPrinterTurboConfig(base_url="http://localhost:8080", api_prefix="/api/v1"),
        http_client=http,
    )
    output = tmp_path / "videos" / "final-1.mp4"

    path = client.download_video("http://localhost:8080/tasks/mpt-1/final-1.mp4", output_path=output)

    assert path == output
    assert output.read_bytes() == b"mp4-bytes"
    assert http.requests[0]["method"] == "GET"


def test_health_reports_unreachable_without_raising() -> None:
    http = FakeHttpClient()
    http.responses.append(FakeResponse({"detail": "not found"}, status_code=404))
    client = MoneyPrinterTurboClient(
        config=MoneyPrinterTurboConfig(base_url="http://localhost:8080", api_prefix="/api/v1"),
        http_client=http,
    )

    payload = client.health()

    assert payload["reachable"] is False
    assert payload["base_url"] == "http://localhost:8080"
    assert payload["api_prefix"] == "/api/v1"


def test_config_requires_base_url() -> None:
    with pytest.raises(MoneyPrinterTurboValidationError):
        MoneyPrinterTurboConfig(base_url="", api_prefix="/api/v1")
```

- [ ] **Step 2: Run the adapter tests to verify they fail**

Run:

```bash
uv run pytest tests/test_moneyprinterturbo_service.py -q
```

Expected: FAIL because `nutmeg.services.moneyprinterturbo` does not exist.

- [ ] **Step 3: Create the HTTP adapter**

Create `nutmeg/services/moneyprinterturbo.py`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from nutmeg.domain.video_worker import (
    DEFAULT_MPT_BGM_VOLUME,
    DEFAULT_MPT_VIDEO_SOURCE,
    DEFAULT_MPT_VOICE,
)


class MoneyPrinterTurboValidationError(ValueError):
    pass


class MoneyPrinterTurboProviderError(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class MoneyPrinterTurboConfig:
    base_url: str = "http://localhost:8080"
    api_prefix: str = "/api/v1"
    timeout_seconds: float = 60.0
    default_voice: str = DEFAULT_MPT_VOICE
    default_video_source: str = DEFAULT_MPT_VIDEO_SOURCE
    default_bgm_volume: float = DEFAULT_MPT_BGM_VOLUME

    def __post_init__(self) -> None:
        if not self.base_url.strip():
            raise MoneyPrinterTurboValidationError("MPT_BASE_URL must not be empty.")
        if self.timeout_seconds <= 0:
            raise MoneyPrinterTurboValidationError("MPT_TIMEOUT_SECONDS must be greater than 0.")

    @classmethod
    def from_env(cls) -> MoneyPrinterTurboConfig:
        return cls(
            base_url=os.environ.get("MPT_BASE_URL", "http://localhost:8080"),
            api_prefix=os.environ.get("MPT_API_PREFIX", "/api/v1"),
            timeout_seconds=float(os.environ.get("MPT_TIMEOUT_SECONDS", "60")),
            default_voice=os.environ.get("MPT_DEFAULT_VOICE", DEFAULT_MPT_VOICE),
            default_video_source=os.environ.get("MPT_DEFAULT_VIDEO_SOURCE", DEFAULT_MPT_VIDEO_SOURCE),
            default_bgm_volume=float(os.environ.get("MPT_DEFAULT_BGM_VOLUME", str(DEFAULT_MPT_BGM_VOLUME))),
        )

    def endpoint(self, path: str) -> str:
        root = self.base_url.rstrip("/")
        prefix = self.api_prefix.strip("/")
        suffix = path.strip("/")
        if prefix:
            return f"{root}/{prefix}/{suffix}"
        return f"{root}/{suffix}"


class MoneyPrinterTurboClient:
    def __init__(
        self,
        *,
        config: MoneyPrinterTurboConfig | None = None,
        http_client: Any | None = None,
    ) -> None:
        self.config = config or MoneyPrinterTurboConfig.from_env()
        self._http_client = http_client

    def create_video(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._request("POST", self.config.endpoint("/videos"), json=payload)
        body = self._json_body(response, context="create video")
        data = self._data_payload(body, context="create video")
        task_id = data.get("task_id")
        if not task_id:
            raise MoneyPrinterTurboProviderError("MoneyPrinterTurbo create-video response missing task_id.")
        return {"task_id": str(task_id), "raw": body}

    def query_task(self, task_id: str) -> dict[str, Any]:
        response = self._request("GET", self.config.endpoint(f"/tasks/{task_id}"))
        body = self._json_body(response, context=f"query task {task_id}")
        return self._data_payload(body, context=f"query task {task_id}")

    def download_video(self, url: str, *, output_path: Path) -> Path:
        response = self._request("GET", url)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(bytes(response.content))
        if output_path.stat().st_size == 0:
            raise MoneyPrinterTurboProviderError(f"Downloaded video is empty: {output_path}")
        return output_path

    def health(self) -> dict[str, Any]:
        try:
            response = self._request("GET", self.config.endpoint("/tasks"), params={"page": 1, "page_size": 1})
            body = self._json_body(response, context="health")
        except Exception as exc:
            return {
                "reachable": False,
                "base_url": self.config.base_url.rstrip("/"),
                "api_prefix": self.config.api_prefix,
                "error": str(exc),
            }
        return {
            "reachable": True,
            "base_url": self.config.base_url.rstrip("/"),
            "api_prefix": self.config.api_prefix,
            "status": body.get("status"),
        }

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        client = self._http_client or httpx.Client(timeout=self.config.timeout_seconds)
        close_client = self._http_client is None
        try:
            response = client.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except Exception as exc:
            raise MoneyPrinterTurboProviderError(f"MoneyPrinterTurbo request failed: {exc}") from exc
        finally:
            if close_client:
                client.close()

    def _json_body(self, response: Any, *, context: str) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError as exc:
            raise MoneyPrinterTurboProviderError(f"MoneyPrinterTurbo {context} returned non-JSON.") from exc
        if not isinstance(body, dict):
            raise MoneyPrinterTurboProviderError(f"MoneyPrinterTurbo {context} returned non-object JSON.")
        return body

    def _data_payload(self, body: dict[str, Any], *, context: str) -> dict[str, Any]:
        data = body.get("data")
        if not isinstance(data, dict):
            raise MoneyPrinterTurboProviderError(f"MoneyPrinterTurbo {context} response missing data object.")
        return data
```

- [ ] **Step 4: Run the adapter tests to verify they pass**

Run:

```bash
uv run pytest tests/test_moneyprinterturbo_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Run ruff on new service files**

Run:

```bash
uv run ruff check nutmeg/domain/video_worker.py nutmeg/services/moneyprinterturbo.py tests/test_video_worker_domain.py tests/test_moneyprinterturbo_service.py
```

Expected: PASS. If ruff reports long lines, split only the reported lines without changing behavior.

- [ ] **Step 6: Commit Task 2**

Run:

```bash
git add nutmeg/services/moneyprinterturbo.py tests/test_moneyprinterturbo_service.py
git commit -m "feat: add moneyprinterturbo api client"
```

Expected: commit succeeds and Task 1 files are not restaged unless ruff changed them.

### Task 3: Packet Generation Service

**Files:**
- Create: `nutmeg/services/video_worker.py`
- Test: `tests/test_video_worker_service.py`

- [ ] **Step 1: Write failing packet-generation tests**

Create the first part of `tests/test_video_worker_service.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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
    (match_dir / "public-script.md").write_text(f"# {match_id} 主队 vs 客队\n\n{final_script}\n", encoding="utf-8")
    (match_dir / "compliance.json").write_text(
        json.dumps({"risk_level": risk_level, "publish_recommendation": "人工审核后可发"}, ensure_ascii=False),
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
    quality_path = run_dir / "matches" / "周四001" / "production-mpt" / "quality-report.json"
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

    task = json.loads(
        (run_dir / "matches" / "周四001" / "production-mpt" / "mpt-task.json").read_text(encoding="utf-8")
    )
    quality = json.loads(
        (run_dir / "matches" / "周四001" / "production-mpt" / "quality-report.json").read_text(encoding="utf-8")
    )

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

    task = json.loads(
        (run_dir / "matches" / "周四001" / "production-mpt" / "mpt-task.json").read_text(encoding="utf-8")
    )

    assert task["status"] == "blocked_by_compliance"
    assert task["error"] == "Compliance risk BLOCKED is not eligible for worker submission."


def test_build_packets_requires_run_dir(tmp_path: Path) -> None:
    missing = tmp_path / "missing-run"

    try:
        VideoWorkerService().build_packets_for_run(
            run_dir=missing,
            run_id="daily-content-20260507-120000",
            run_date="2026-05-07",
        )
    except VideoWorkerValidationError as exc:
        assert "video-mpt-packet" in str(exc)
    else:
        raise AssertionError("Expected VideoWorkerValidationError")
```

- [ ] **Step 2: Run the packet-generation tests to verify they fail**

Run:

```bash
uv run pytest tests/test_video_worker_service.py -q
```

Expected: FAIL because `nutmeg.services.video_worker` does not exist.

- [ ] **Step 3: Create the packet-generation service**

Create `nutmeg/services/video_worker.py` with packet generation support:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nutmeg.domain.video_worker import (
    DEFAULT_MPT_TERMS,
    MoneyPrinterTurboRequest,
    MoneyPrinterTurboTaskPacket,
)
from nutmeg.services.content import ContentComplianceChecker, SHORT_VIDEO_DISCLAIMER
from nutmeg.services.moneyprinterturbo import MoneyPrinterTurboClient


class VideoWorkerValidationError(ValueError):
    pass


class VideoWorkerService:
    def __init__(self, *, client: MoneyPrinterTurboClient | None = None) -> None:
        self._client = client

    def build_packets_for_run(
        self,
        *,
        run_dir: Path | str,
        run_id: str | None = None,
        run_date: str | None = None,
    ) -> dict[str, Any]:
        root = Path(run_dir)
        if not root.exists():
            raise VideoWorkerValidationError(
                f"Run directory not found: {root}. Generate it with `nutmeg video-mpt-packet`."
            )
        matches_dir = root / "matches"
        if not matches_dir.exists():
            raise VideoWorkerValidationError(f"Run directory has no matches folder: {matches_dir}")
        resolved_run_id = run_id or root.name
        resolved_run_date = run_date or _run_date_from_path(root)
        manifest_tasks: list[dict[str, Any]] = []
        for match_dir in sorted(path for path in matches_dir.iterdir() if path.is_dir()):
            packet = self._build_match_packet(
                match_dir=match_dir,
                run_id=resolved_run_id,
                run_date=resolved_run_date,
            )
            mpt_dir = match_dir / "production-mpt"
            mpt_dir.mkdir(parents=True, exist_ok=True)
            task_path = mpt_dir / "mpt-task.json"
            request_path = mpt_dir / "request.json"
            quality_path = mpt_dir / "quality-report.json"
            _write_json(task_path, packet.to_dict())
            _write_json(request_path, packet.request.to_payload())
            _write_json(quality_path, _quality_report_for_packet(packet))
            manifest_tasks.append(
                {
                    "match_id": packet.match_id,
                    "status": packet.status,
                    "task_id": packet.task_id,
                    "task_path": str(task_path),
                    "request_path": str(request_path),
                    "quality_report_path": str(quality_path),
                }
            )
        manifest = {
            "run_id": resolved_run_id,
            "run_date": resolved_run_date,
            "worker": "moneyprinterturbo",
            "run_dir": str(root),
            "tasks": manifest_tasks,
        }
        manifest_path = root / "moneyprinterturbo-manifest.json"
        status_path = root / "moneyprinterturbo-status.json"
        _write_json(manifest_path, manifest)
        _write_json(status_path, {"run_id": resolved_run_id, "tasks": manifest_tasks})
        return {"manifest_path": str(manifest_path), "status_path": str(status_path), "tasks": len(manifest_tasks)}

    def _build_match_packet(
        self,
        *,
        match_dir: Path,
        run_id: str,
        run_date: str,
    ) -> MoneyPrinterTurboTaskPacket:
        match_id = match_dir.name
        production_dir = match_dir / "production-v2"
        voiceover_path = production_dir / "voiceover-script.md"
        brief_path = production_dir / "content-brief.json"
        compliance_path = match_dir / "compliance.json"
        script = _read_text(voiceover_path)
        brief = _read_json(brief_path)
        compliance = _read_json(compliance_path) if compliance_path.exists() else {}
        title = _title_from_brief(match_id=match_id, brief=brief)
        request = MoneyPrinterTurboRequest(
            video_subject=title,
            video_script=script,
            video_terms=list(DEFAULT_MPT_TERMS),
        )
        status = "draft"
        error = None
        risk_level = str(compliance.get("risk_level") or "UNKNOWN")
        if risk_level in {"HIGH", "BLOCKED"}:
            status = "blocked_by_compliance"
            error = f"Compliance risk {risk_level} is not eligible for worker submission."
        elif SHORT_VIDEO_DISCLAIMER not in script:
            status = "blocked_by_disclaimer"
            error = "Missing required short-video disclaimer."
        else:
            checker = ContentComplianceChecker()
            assessment = checker.assess(
                titles=[title],
                short_video_script=script,
                long_article=script + SHORT_VIDEO_DISCLAIMER,
            )
            if assessment.risk_level in {"HIGH", "BLOCKED"}:
                status = "blocked_by_compliance"
                error = f"Compliance risk {assessment.risk_level} is not eligible for worker submission."
        return MoneyPrinterTurboTaskPacket(
            run_id=run_id,
            run_date=run_date,
            match_id=match_id,
            match_no=str(brief.get("match_no") or brief.get("match_id") or match_id),
            title=title,
            script=script,
            request=request,
            source_paths={
                "voiceover_script_path": str(voiceover_path),
                "content_brief_path": str(brief_path),
                "compliance_path": str(compliance_path),
            },
            compliance=compliance,
            status=status,
            error=error,
        )


def _title_from_brief(*, match_id: str, brief: dict[str, Any]) -> str:
    hook = str(brief.get("selected_hook") or brief.get("main_contradiction") or "赛前关键变量")
    hook = hook.strip().replace("\n", " ")
    if len(hook) > 36:
        hook = hook[:36]
    return f"{match_id}：{hook}"


def _run_date_from_path(root: Path) -> str:
    parent = root.parent.name
    if len(parent) == 8 and parent.isdigit():
        return f"{parent[:4]}-{parent[4:6]}-{parent[6:]}"
    return "unknown"


def _quality_report_for_packet(packet: MoneyPrinterTurboTaskPacket) -> dict[str, Any]:
    gates = [
        {
            "gate": "script_compliance",
            "status": "pass" if packet.status == "draft" else "blocked",
            "detail": packet.error or "Script is eligible for MoneyPrinterTurbo submission.",
        },
        {
            "gate": "artifact_lineage",
            "status": "pass",
            "detail": f"run_id={packet.run_id}; match_id={packet.match_id}",
        },
    ]
    return {"status": "review" if packet.status == "draft" else "blocked", "gates": gates}


def _read_text(path: Path) -> str:
    if not path.exists():
        raise VideoWorkerValidationError(f"Required video worker input missing: {path}")
    return path.read_text(encoding="utf-8").strip()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise VideoWorkerValidationError(f"Required video worker input missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise VideoWorkerValidationError(f"Invalid JSON artifact: {path}") from exc
    if not isinstance(payload, dict):
        raise VideoWorkerValidationError(f"JSON artifact must be an object: {path}")
    return payload


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
```

- [ ] **Step 4: Run the packet-generation tests to verify they pass**

Run:

```bash
uv run pytest tests/test_video_worker_service.py -q
```

Expected: PASS for the four packet-generation tests.

- [ ] **Step 5: Commit Task 3**

Run:

```bash
git add nutmeg/services/video_worker.py tests/test_video_worker_service.py
git commit -m "feat: build moneyprinterturbo task packets"
```

Expected: commit succeeds.

### Task 4: Submit, Poll, Download, And Status Persistence

**Files:**
- Modify: `nutmeg/services/video_worker.py`
- Modify: `tests/test_video_worker_service.py`

- [ ] **Step 1: Append failing submit/poll tests**

Append to `tests/test_video_worker_service.py`:

```python

class FakeMptClient:
    def __init__(self) -> None:
        self.created_payloads: list[dict[str, Any]] = []
        self.downloads: list[tuple[str, Path]] = []

    def create_video(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.created_payloads.append(payload)
        return {"task_id": f"mpt-{len(self.created_payloads)}", "raw": {"status": 200, "data": {"task_id": f"mpt-{len(self.created_payloads)}"}}}

    def query_task(self, task_id: str) -> dict[str, Any]:
        return {
            "state": 1,
            "progress": 100,
            "videos": [f"http://localhost:8080/tasks/{task_id}/final-1.mp4"],
            "combined_videos": [f"http://localhost:8080/tasks/{task_id}/combined-1.mp4"],
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
    submit_path = run_dir / "matches" / "周四001" / "production-mpt" / "submit-result.json"
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
        (run_dir / "matches" / "周四001" / "production-mpt" / "status.json").read_text(encoding="utf-8")
    )
    aggregate = json.loads((run_dir / "moneyprinterturbo-status.json").read_text(encoding="utf-8"))

    assert result.succeeded == 1
    assert result.downloaded == 2
    assert len(client.downloads) == 2
    assert match_status["status"] == "succeeded"
    assert len(match_status["local_video_paths"]) == 2
    assert Path(match_status["local_video_paths"][0]).exists()
    assert aggregate["tasks"][0]["status"] == "succeeded"
```

- [ ] **Step 2: Run the new service tests to verify they fail**

Run:

```bash
uv run pytest tests/test_video_worker_service.py -q
```

Expected: FAIL because `submit_run` and `poll_run` do not exist.

- [ ] **Step 3: Extend `VideoWorkerService` imports**

Modify the import from `nutmeg.domain.video_worker` in `nutmeg/services/video_worker.py` to include these classes:

```python
from nutmeg.domain.video_worker import (
    DEFAULT_MPT_TERMS,
    MoneyPrinterTurboRequest,
    MoneyPrinterTurboTaskPacket,
    MoneyPrinterTurboTaskState,
    VideoWorkerPollResult,
    VideoWorkerSubmissionResult,
)
```

- [ ] **Step 4: Add submit and poll methods inside `VideoWorkerService`**

Insert these methods in `VideoWorkerService` after `build_packets_for_run`:

```python
    def submit_run(
        self,
        *,
        run_dir: Path | str,
        confirm: bool,
        match_id: str | None = None,
    ) -> VideoWorkerSubmissionResult:
        if not confirm:
            raise VideoWorkerValidationError(
                "MoneyPrinterTurbo video generation requires explicit --confirm."
            )
        client = self._require_client()
        root = Path(run_dir)
        manifest = _load_manifest(root)
        submitted = skipped = blocked = failed = 0
        task_rows: list[dict[str, Any]] = []
        for row in manifest.get("tasks") or []:
            if match_id and row.get("match_id") != match_id:
                skipped += 1
                continue
            task_path = Path(str(row["task_path"]))
            packet = MoneyPrinterTurboTaskPacket.from_dict(_read_json(task_path))
            if packet.status.startswith("blocked"):
                blocked += 1
                task_rows.append({"match_id": packet.match_id, "status": packet.status, "task_id": packet.task_id})
                continue
            if packet.task_id:
                skipped += 1
                task_rows.append({"match_id": packet.match_id, "status": packet.status, "task_id": packet.task_id})
                continue
            try:
                response = client.create_video(packet.request.to_payload())
            except Exception as exc:
                failed += 1
                failed_packet = _replace_packet(packet, status="failed_submit", error=str(exc))
                _write_json(task_path, failed_packet.to_dict())
                _write_json(task_path.parent / "submit-result.json", {"status": "failed", "error": str(exc)})
                task_rows.append({"match_id": packet.match_id, "status": "failed_submit", "task_id": None, "error": str(exc)})
                continue
            submitted += 1
            task_id = str(response["task_id"])
            submitted_packet = _replace_packet(packet, status="submitted", task_id=task_id, error=None)
            _write_json(task_path, submitted_packet.to_dict())
            _write_json(task_path.parent / "submit-result.json", response)
            task_rows.append({"match_id": packet.match_id, "status": "submitted", "task_id": task_id})
        status_path = root / "moneyprinterturbo-status.json"
        _write_json(status_path, {"run_id": manifest.get("run_id"), "tasks": task_rows})
        return VideoWorkerSubmissionResult(
            manifest_path=str(root / "moneyprinterturbo-manifest.json"),
            submitted=submitted,
            skipped=skipped,
            blocked=blocked,
            failed=failed,
            tasks=task_rows,
        )

    def poll_run(
        self,
        *,
        run_dir: Path | str,
        download: bool = False,
        match_id: str | None = None,
    ) -> VideoWorkerPollResult:
        client = self._require_client()
        root = Path(run_dir)
        manifest = _load_manifest(root)
        succeeded = running = failed = blocked = downloaded = 0
        task_rows: list[dict[str, Any]] = []
        for row in manifest.get("tasks") or []:
            if match_id and row.get("match_id") != match_id:
                continue
            task_path = Path(str(row["task_path"]))
            packet = MoneyPrinterTurboTaskPacket.from_dict(_read_json(task_path))
            if packet.status.startswith("blocked"):
                blocked += 1
                task_rows.append({"match_id": packet.match_id, "status": packet.status, "task_id": packet.task_id})
                continue
            if not packet.task_id:
                running += 1
                task_rows.append({"match_id": packet.match_id, "status": "not_submitted", "task_id": None})
                continue
            try:
                payload = client.query_task(packet.task_id)
                state = MoneyPrinterTurboTaskState.from_worker_payload(
                    match_id=packet.match_id,
                    task_id=packet.task_id,
                    payload=payload,
                )
                if download and state.status == "succeeded":
                    local_paths = self._download_state_videos(client=client, state=state, mpt_dir=task_path.parent)
                    state = MoneyPrinterTurboTaskState(
                        match_id=state.match_id,
                        task_id=state.task_id,
                        status=state.status,
                        worker_state=state.worker_state,
                        progress=state.progress,
                        video_urls=state.video_urls,
                        combined_video_urls=state.combined_video_urls,
                        local_video_paths=local_paths,
                        raw=state.raw,
                        error=state.error,
                    )
                    downloaded += len(local_paths)
            except Exception as exc:
                state = MoneyPrinterTurboTaskState(
                    match_id=packet.match_id,
                    task_id=packet.task_id,
                    status="failed",
                    worker_state=None,
                    progress=None,
                    video_urls=[],
                    combined_video_urls=[],
                    raw={},
                    error=str(exc),
                )
            if state.status == "succeeded":
                succeeded += 1
            elif state.status == "failed":
                failed += 1
            else:
                running += 1
            _write_json(task_path.parent / "status.json", state.to_dict())
            _write_json(task_path.parent / "quality-report.json", _quality_report_for_state(packet=packet, state=state))
            task_rows.append(state.to_dict())
        status_path = root / "moneyprinterturbo-status.json"
        _write_json(status_path, {"run_id": manifest.get("run_id"), "tasks": task_rows})
        return VideoWorkerPollResult(
            status_path=str(status_path),
            succeeded=succeeded,
            running=running,
            failed=failed,
            blocked=blocked,
            downloaded=downloaded,
            tasks=task_rows,
        )

    def _download_state_videos(
        self,
        *,
        client: MoneyPrinterTurboClient,
        state: MoneyPrinterTurboTaskState,
        mpt_dir: Path,
    ) -> list[str]:
        videos_dir = mpt_dir / "videos"
        local_paths: list[str] = []
        for index, url in enumerate(state.video_urls, start=1):
            path = client.download_video(url, output_path=videos_dir / f"final-{index}.mp4")
            local_paths.append(str(path))
        for index, url in enumerate(state.combined_video_urls, start=1):
            path = client.download_video(url, output_path=videos_dir / f"combined-{index}.mp4")
            local_paths.append(str(path))
        return local_paths

    def _require_client(self) -> MoneyPrinterTurboClient:
        if self._client is None:
            self._client = MoneyPrinterTurboClient()
        return self._client
```

- [ ] **Step 5: Add helper functions at the bottom of `video_worker.py`**

Append these helpers after `_write_json`:

```python

def _load_manifest(root: Path) -> dict[str, Any]:
    manifest_path = root / "moneyprinterturbo-manifest.json"
    if not manifest_path.exists():
        raise VideoWorkerValidationError(
            f"MoneyPrinterTurbo manifest not found: {manifest_path}. Run `nutmeg video-mpt-packet` first."
        )
    return _read_json(manifest_path)


def _replace_packet(
    packet: MoneyPrinterTurboTaskPacket,
    *,
    status: str,
    task_id: str | None = None,
    error: str | None = None,
) -> MoneyPrinterTurboTaskPacket:
    return MoneyPrinterTurboTaskPacket(
        run_id=packet.run_id,
        run_date=packet.run_date,
        match_id=packet.match_id,
        match_no=packet.match_no,
        title=packet.title,
        script=packet.script,
        request=packet.request,
        source_paths=packet.source_paths,
        compliance=packet.compliance,
        status=status,
        task_id=task_id if task_id is not None else packet.task_id,
        error=error,
    )


def _quality_report_for_state(
    *,
    packet: MoneyPrinterTurboTaskPacket,
    state: MoneyPrinterTurboTaskState,
) -> dict[str, Any]:
    has_remote_video = bool(state.video_urls or state.combined_video_urls)
    has_local_video = bool(state.local_video_paths)
    gates = [
        {
            "gate": "worker_contract",
            "status": "pass" if state.task_id else "fail",
            "detail": f"task_id={state.task_id}",
        },
        {
            "gate": "download_integrity",
            "status": "pass" if has_local_video else "review" if has_remote_video else "pending",
            "detail": ";".join(state.local_video_paths) if has_local_video else "No downloaded video yet.",
        },
        {
            "gate": "artifact_lineage",
            "status": "pass",
            "detail": f"run_id={packet.run_id}; match_id={packet.match_id}; task_id={state.task_id}",
        },
    ]
    if state.error:
        gates.append({"gate": "worker_error", "status": "fail", "detail": state.error})
    return {"status": "pass" if has_local_video and not state.error else "review", "gates": gates}
```

- [ ] **Step 6: Run submit/poll tests to verify they pass**

Run:

```bash
uv run pytest tests/test_video_worker_service.py -q
```

Expected: PASS.

- [ ] **Step 7: Run focused ruff check**

Run:

```bash
uv run ruff check nutmeg/services/video_worker.py tests/test_video_worker_service.py
```

Expected: PASS.

- [ ] **Step 8: Commit Task 4**

Run:

```bash
git add nutmeg/services/video_worker.py tests/test_video_worker_service.py
git commit -m "feat: submit and poll moneyprinterturbo tasks"
```

Expected: commit succeeds.

### Task 5: CLI Commands

**Files:**
- Modify: `nutmeg/interfaces/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Append failing CLI tests**

Append these tests near the existing video command tests in `tests/test_cli.py`:

```python

def test_video_mpt_packet_command_writes_worker_manifest(tmp_path, monkeypatch) -> None:
    from nutmeg.interfaces import cli as cli_module

    run_dir = tmp_path / "20260507" / "run-120000"

    class FakeRun:
        run_id = "daily-content-20260507-120000"
        run_date = "2026-05-07"

        class Artifacts:
            run_dir = str(run_dir)

        artifacts = Artifacts()
        matches = [object()]

        def to_dict(self):
            return {"run_id": self.run_id, "run_date": self.run_date, "artifacts": {"run_dir": str(run_dir)}}

    class FakeDailyContentService:
        def build_run(self, **kwargs):
            run_dir.mkdir(parents=True)
            return FakeRun()

    class FakeVideoWorkerService:
        def build_packets_for_run(self, **kwargs):
            assert kwargs["run_dir"] == run_dir
            assert kwargs["run_id"] == "daily-content-20260507-120000"
            assert kwargs["run_date"] == "2026-05-07"
            return {"manifest_path": str(run_dir / "moneyprinterturbo-manifest.json"), "status_path": str(run_dir / "moneyprinterturbo-status.json"), "tasks": 1}

    monkeypatch.setattr(cli_module, "build_daily_content_service", lambda provider="live": FakeDailyContentService())
    monkeypatch.setattr(cli_module, "build_video_worker_service", lambda: FakeVideoWorkerService())

    result = runner.invoke(
        app,
        [
            "video-mpt-packet",
            "--date",
            "2026-05-07",
            "--provider",
            "sample",
            "--output-dir",
            str(tmp_path),
            "--format",
            "json",
        ],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0, result.stdout
    assert payload["tasks"] == 1
    assert payload["manifest_path"].endswith("moneyprinterturbo-manifest.json")


def test_video_mpt_submit_command_refuses_without_confirm(tmp_path, monkeypatch) -> None:
    from nutmeg.interfaces import cli as cli_module
    from nutmeg.services.video_worker import VideoWorkerValidationError

    class FakeVideoWorkerService:
        def submit_run(self, **kwargs):
            raise VideoWorkerValidationError("MoneyPrinterTurbo video generation requires explicit --confirm.")

    monkeypatch.setattr(cli_module, "build_video_worker_service", lambda: FakeVideoWorkerService())

    result = runner.invoke(app, ["video-mpt-submit", "--run-dir", str(tmp_path), "--format", "json"])

    assert result.exit_code == 2
    assert "--confirm" in result.stdout


def test_video_mpt_submit_command_returns_json(tmp_path, monkeypatch) -> None:
    from nutmeg.domain.video_worker import VideoWorkerSubmissionResult
    from nutmeg.interfaces import cli as cli_module

    class FakeVideoWorkerService:
        def submit_run(self, **kwargs):
            assert kwargs["run_dir"] == tmp_path
            assert kwargs["confirm"] is True
            assert kwargs["match_id"] == "周四001"
            return VideoWorkerSubmissionResult(
                manifest_path=str(tmp_path / "moneyprinterturbo-manifest.json"),
                submitted=1,
                skipped=0,
                blocked=0,
                failed=0,
                tasks=[{"match_id": "周四001", "task_id": "mpt-1", "status": "submitted"}],
            )

    monkeypatch.setattr(cli_module, "build_video_worker_service", lambda: FakeVideoWorkerService())

    result = runner.invoke(
        app,
        [
            "video-mpt-submit",
            "--run-dir",
            str(tmp_path),
            "--confirm",
            "--match-id",
            "周四001",
            "--format",
            "json",
        ],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0, result.stdout
    assert payload["submitted"] == 1
    assert payload["tasks"][0]["task_id"] == "mpt-1"


def test_video_mpt_poll_command_returns_json(tmp_path, monkeypatch) -> None:
    from nutmeg.domain.video_worker import VideoWorkerPollResult
    from nutmeg.interfaces import cli as cli_module

    class FakeVideoWorkerService:
        def poll_run(self, **kwargs):
            assert kwargs["run_dir"] == tmp_path
            assert kwargs["download"] is True
            assert kwargs["match_id"] is None
            return VideoWorkerPollResult(
                status_path=str(tmp_path / "moneyprinterturbo-status.json"),
                succeeded=1,
                running=0,
                failed=0,
                blocked=0,
                downloaded=2,
                tasks=[{"match_id": "周四001", "status": "succeeded"}],
            )

    monkeypatch.setattr(cli_module, "build_video_worker_service", lambda: FakeVideoWorkerService())

    result = runner.invoke(
        app,
        ["video-mpt-poll", "--run-dir", str(tmp_path), "--download", "--format", "json"],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0, result.stdout
    assert payload["succeeded"] == 1
    assert payload["downloaded"] == 2


def test_video_mpt_health_command_returns_json(monkeypatch) -> None:
    from nutmeg.interfaces import cli as cli_module

    class FakeMptClient:
        def health(self):
            return {"reachable": True, "base_url": "http://localhost:8080", "api_prefix": "/api/v1"}

    monkeypatch.setattr(cli_module, "build_moneyprinterturbo_client", lambda: FakeMptClient())

    result = runner.invoke(app, ["video-mpt-health", "--format", "json"])
    payload = json.loads(result.stdout)

    assert result.exit_code == 0, result.stdout
    assert payload["reachable"] is True
    assert payload["base_url"] == "http://localhost:8080"
```

- [ ] **Step 2: Run the CLI tests to verify they fail**

Run:

```bash
uv run pytest tests/test_cli.py::test_video_mpt_packet_command_writes_worker_manifest tests/test_cli.py::test_video_mpt_submit_command_refuses_without_confirm tests/test_cli.py::test_video_mpt_submit_command_returns_json tests/test_cli.py::test_video_mpt_poll_command_returns_json tests/test_cli.py::test_video_mpt_health_command_returns_json -q
```

Expected: FAIL because the CLI commands and builders do not exist.

- [ ] **Step 3: Add imports to `nutmeg/interfaces/cli.py`**

Add after the existing Remotion import block:

```python
from nutmeg.services.moneyprinterturbo import (
    MoneyPrinterTurboClient,
    MoneyPrinterTurboConfig,
    MoneyPrinterTurboProviderError,
    MoneyPrinterTurboValidationError,
)
from nutmeg.services.video_worker import VideoWorkerService, VideoWorkerValidationError
```

- [ ] **Step 4: Add CLI option constants**

Add near the existing video and Seedance option constants:

```python
VIDEO_MPT_RUN_DIR_OPTION = typer.Option(..., "--run-dir")
VIDEO_MPT_MATCH_ID_OPTION = typer.Option(None, "--match-id")
```

- [ ] **Step 5: Add builder functions**

Add after `build_remotion_render_service`:

```python

def build_moneyprinterturbo_client() -> MoneyPrinterTurboClient:
    return MoneyPrinterTurboClient(config=MoneyPrinterTurboConfig.from_env())


def build_video_worker_service() -> VideoWorkerService:
    return VideoWorkerService(client=build_moneyprinterturbo_client())
```

- [ ] **Step 6: Add the four CLI commands**

Add after `video_production_packet` and before `video_render`:

```python
@app.command("video-mpt-packet")
def video_mpt_packet(
    date: str = DAILY_CONTENT_DATE_OPTION,
    provider: str = DAILY_CONTENT_PROVIDER_OPTION,
    output_dir: Path = DAILY_CONTENT_OUTPUT_DIR_OPTION,
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    try:
        daily_service = build_daily_content_service(provider=provider)
        run = daily_service.build_run(
            run_date=_resolve_daily_content_date(date),
            output_dir=output_dir,
            provider_label=provider,
            render_pdf=False,
        )
        payload = build_video_worker_service().build_packets_for_run(
            run_dir=Path(str(run.artifacts.run_dir)),
            run_id=run.run_id,
            run_date=run.run_date,
        )
    except (ContentValidationError, JczqProviderError, JczqSelectionError, VideoWorkerValidationError) as exc:
        console.print(str(exc))
        raise typer.Exit(code=2) from exc
    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    console.print(
        f"video-mpt-packet tasks={payload['tasks']} manifest={payload['manifest_path']}"
    )


@app.command("video-mpt-submit")
def video_mpt_submit(
    run_dir: Path = VIDEO_MPT_RUN_DIR_OPTION,
    confirm: bool = typer.Option(False, "--confirm"),
    match_id: str | None = VIDEO_MPT_MATCH_ID_OPTION,
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    try:
        result = build_video_worker_service().submit_run(
            run_dir=run_dir,
            confirm=confirm,
            match_id=match_id,
        )
    except (VideoWorkerValidationError, MoneyPrinterTurboValidationError, MoneyPrinterTurboProviderError) as exc:
        console.print(str(exc))
        raise typer.Exit(code=2) from exc
    payload = result.to_dict()
    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    console.print(
        "video-mpt-submit "
        f"submitted={payload['submitted']} skipped={payload['skipped']} "
        f"blocked={payload['blocked']} failed={payload['failed']}"
    )


@app.command("video-mpt-poll")
def video_mpt_poll(
    run_dir: Path = VIDEO_MPT_RUN_DIR_OPTION,
    download: bool = typer.Option(False, "--download"),
    match_id: str | None = VIDEO_MPT_MATCH_ID_OPTION,
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    try:
        result = build_video_worker_service().poll_run(
            run_dir=run_dir,
            download=download,
            match_id=match_id,
        )
    except (VideoWorkerValidationError, MoneyPrinterTurboValidationError, MoneyPrinterTurboProviderError) as exc:
        console.print(str(exc))
        raise typer.Exit(code=2) from exc
    payload = result.to_dict()
    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    console.print(
        "video-mpt-poll "
        f"succeeded={payload['succeeded']} running={payload['running']} "
        f"failed={payload['failed']} blocked={payload['blocked']} downloaded={payload['downloaded']}"
    )


@app.command("video-mpt-health")
def video_mpt_health(
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    payload = build_moneyprinterturbo_client().health()
    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    status = "reachable" if payload.get("reachable") else "unreachable"
    console.print(
        f"video-mpt-health {status} base_url={payload.get('base_url')} api_prefix={payload.get('api_prefix')}"
    )
```

- [ ] **Step 7: Run CLI tests to verify they pass**

Run:

```bash
uv run pytest tests/test_cli.py::test_video_mpt_packet_command_writes_worker_manifest tests/test_cli.py::test_video_mpt_submit_command_refuses_without_confirm tests/test_cli.py::test_video_mpt_submit_command_returns_json tests/test_cli.py::test_video_mpt_poll_command_returns_json tests/test_cli.py::test_video_mpt_health_command_returns_json -q
```

Expected: PASS.

- [ ] **Step 8: Run focused CLI ruff check**

Run:

```bash
uv run ruff check nutmeg/interfaces/cli.py tests/test_cli.py
```

Expected: PASS. If ruff reports import ordering, run `uv run ruff check --fix nutmeg/interfaces/cli.py tests/test_cli.py` and inspect the diff.

- [ ] **Step 9: Commit Task 5**

Run:

```bash
git add nutmeg/interfaces/cli.py tests/test_cli.py
git commit -m "feat: add moneyprinterturbo video worker cli"
```

Expected: commit succeeds.

### Task 6: Documentation And Verification

**Files:**
- Modify: `docs/video-production-v2.md`
- Test: existing focused test suite

- [ ] **Step 1: Update the video production docs**

Modify `docs/video-production-v2.md` to include this section after `Local No-Spend Smoke`:

```markdown
## MoneyPrinterTurbo Worker Path

Nutmeg can also use a local Docker MoneyPrinterTurbo service as a faceless-video worker. In this path, Nutmeg still owns match selection, public scripts, disclaimers, and compliance checks. MoneyPrinterTurbo handles TTS, stock material selection, subtitles, BGM, and final video assembly.

Start MoneyPrinterTurbo separately:

```bash
cd MoneyPrinterTurbo
docker compose up
```

Default API configuration:

```bash
export MPT_BASE_URL=http://localhost:8080
export MPT_API_PREFIX=/api/v1
```

If the local deployment exposes unprefixed routes, use:

```bash
export MPT_API_PREFIX=
```

Build local worker packets without submitting external work:

```bash
nutmeg video-mpt-packet --date 2026-04-26 --provider sample --output-dir .nutmeg-data/daily-content-smoke --format json
```

Submit only after review:

```bash
nutmeg video-mpt-submit --run-dir .nutmeg-data/daily-content-smoke/20260426/run-120000 --confirm --format json
```

Poll and download completed videos:

```bash
nutmeg video-mpt-poll --run-dir .nutmeg-data/daily-content-smoke/20260426/run-120000 --download --format json
```

The run directory records `moneyprinterturbo-manifest.json`, `moneyprinterturbo-status.json`, and per-match `production-mpt` folders. Manual visual review remains required before publishing because stock footage can be generic or off-topic.
```

- [ ] **Step 2: Run all focused Python tests**

Run:

```bash
uv run pytest tests/test_video_worker_domain.py tests/test_moneyprinterturbo_service.py tests/test_video_worker_service.py tests/test_cli.py::test_video_mpt_packet_command_writes_worker_manifest tests/test_cli.py::test_video_mpt_submit_command_refuses_without_confirm tests/test_cli.py::test_video_mpt_submit_command_returns_json tests/test_cli.py::test_video_mpt_poll_command_returns_json tests/test_cli.py::test_video_mpt_health_command_returns_json -q
```

Expected: PASS.

- [ ] **Step 3: Run focused ruff**

Run:

```bash
uv run ruff check nutmeg/domain/video_worker.py nutmeg/services/moneyprinterturbo.py nutmeg/services/video_worker.py nutmeg/interfaces/cli.py tests/test_video_worker_domain.py tests/test_moneyprinterturbo_service.py tests/test_video_worker_service.py tests/test_cli.py
```

Expected: PASS.

- [ ] **Step 4: Compile modified Python modules**

Run:

```bash
uv run python -m compileall nutmeg/domain/video_worker.py nutmeg/services/moneyprinterturbo.py nutmeg/services/video_worker.py nutmeg/interfaces/cli.py
```

Expected: PASS and compile output lists the four paths without syntax errors.

- [ ] **Step 5: Generate a no-submit sample packet**

Run:

```bash
uv run nutmeg video-mpt-packet --date 2026-04-26 --provider sample --output-dir .nutmeg-data/video-mpt-smoke --format json
```

Expected: exit code 0, JSON includes `manifest_path`, and no HTTP request is sent to MoneyPrinterTurbo.

- [ ] **Step 6: Verify submit safety without `--confirm`**

Use the `run_dir` from Step 5 and run:

```bash
uv run nutmeg video-mpt-submit --run-dir .nutmeg-data/video-mpt-smoke/20260426/run-120000 --format json
```

Expected: exit code 2 and output contains `--confirm`. If the run folder suffix differs from `run-120000`, substitute the actual `run_dir` printed by Step 5.

- [ ] **Step 7: Commit docs and verification-ready code**

Run:

```bash
git add docs/video-production-v2.md
git commit -m "docs: document moneyprinterturbo worker workflow"
```

Expected: commit succeeds. If Task 6 required fixes in code or tests, include those exact changed files in this commit only after rerunning Steps 2 through 4.

## Self-Review Checklist

- [ ] Spec Section 2 Goals are covered by Tasks 1 through 6: local MPT worker, Nutmeg-owned scripts, adapter boundary, persisted artifacts, and existing Remotion/Seedance preservation.
- [ ] Spec Section 3 Non-Goals are preserved: no vendoring, no MPT script rewriting, no publishing, no remote requirement, and no implicit submission.
- [ ] Spec Section 4 configurable prefix is implemented in `MoneyPrinterTurboConfig.endpoint` and tested with `/api/v1` and empty prefix.
- [ ] Spec Section 6 artifact layout is implemented by `VideoWorkerService.build_packets_for_run`, `submit_run`, and `poll_run`.
- [ ] Spec Section 7 custom-script mapping is implemented by `MoneyPrinterTurboRequest.to_payload` and packet-generation tests.
- [ ] Spec Section 8 CLI commands are covered by Task 5 tests.
- [ ] Spec Sections 10 and 11 error handling and quality gates are covered by service tests and `quality-report.json` generation.
- [ ] Placeholder scan passes: the plan contains no unfinished marker words and no undefined method names in later tasks.
- [ ] Type consistency passes: `VideoWorkerSubmissionResult`, `VideoWorkerPollResult`, `MoneyPrinterTurboTaskPacket`, and `MoneyPrinterTurboTaskState` names match across domain, service, CLI, and tests.
