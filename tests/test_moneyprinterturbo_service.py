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
    prefixed = MoneyPrinterTurboConfig(
        base_url="http://localhost:8080/",
        api_prefix="/api/v1",
    )
    unprefixed = MoneyPrinterTurboConfig(
        base_url="http://localhost:8080",
        api_prefix="",
    )

    assert prefixed.endpoint("/videos") == "http://localhost:8080/api/v1/videos"
    assert prefixed.endpoint("tasks/mpt-1") == "http://localhost:8080/api/v1/tasks/mpt-1"
    assert unprefixed.endpoint("/videos") == "http://localhost:8080/videos"


def test_create_video_posts_payload_and_returns_task_id() -> None:
    http = FakeHttpClient()
    http.responses.append(FakeResponse({"status": 200, "data": {"task_id": "mpt-1"}}))
    client = MoneyPrinterTurboClient(
        config=MoneyPrinterTurboConfig(
            base_url="http://localhost:8080",
            api_prefix="/api/v1",
        ),
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
        config=MoneyPrinterTurboConfig(
            base_url="http://localhost:8080",
            api_prefix="/api/v1",
        ),
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
        config=MoneyPrinterTurboConfig(
            base_url="http://localhost:8080",
            api_prefix="/api/v1",
        ),
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
        config=MoneyPrinterTurboConfig(
            base_url="http://localhost:8080",
            api_prefix="/api/v1",
        ),
        http_client=http,
    )
    output = tmp_path / "videos" / "final-1.mp4"

    path = client.download_video(
        "http://localhost:8080/tasks/mpt-1/final-1.mp4",
        output_path=output,
    )

    assert path == output
    assert output.read_bytes() == b"mp4-bytes"
    assert http.requests[0]["method"] == "GET"


def test_health_reports_unreachable_without_raising() -> None:
    http = FakeHttpClient()
    http.responses.append(FakeResponse({"detail": "not found"}, status_code=404))
    client = MoneyPrinterTurboClient(
        config=MoneyPrinterTurboConfig(
            base_url="http://localhost:8080",
            api_prefix="/api/v1",
        ),
        http_client=http,
    )

    payload = client.health()

    assert payload["reachable"] is False
    assert payload["base_url"] == "http://localhost:8080"
    assert payload["api_prefix"] == "/api/v1"


def test_config_requires_base_url() -> None:
    with pytest.raises(MoneyPrinterTurboValidationError):
        MoneyPrinterTurboConfig(base_url="", api_prefix="/api/v1")
