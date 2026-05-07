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
            raise MoneyPrinterTurboValidationError(
                "MPT_TIMEOUT_SECONDS must be greater than 0."
            )

    @classmethod
    def from_env(cls) -> MoneyPrinterTurboConfig:
        return cls(
            base_url=os.environ.get("MPT_BASE_URL", "http://localhost:8080"),
            api_prefix=os.environ.get("MPT_API_PREFIX", "/api/v1"),
            timeout_seconds=float(os.environ.get("MPT_TIMEOUT_SECONDS", "60")),
            default_voice=os.environ.get("MPT_DEFAULT_VOICE", DEFAULT_MPT_VOICE),
            default_video_source=os.environ.get(
                "MPT_DEFAULT_VIDEO_SOURCE",
                DEFAULT_MPT_VIDEO_SOURCE,
            ),
            default_bgm_volume=float(
                os.environ.get("MPT_DEFAULT_BGM_VOLUME", str(DEFAULT_MPT_BGM_VOLUME))
            ),
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
            raise MoneyPrinterTurboProviderError(
                "MoneyPrinterTurbo create-video response missing task_id."
            )
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
            response = self._request(
                "GET",
                self.config.endpoint("/tasks"),
                params={"page": 1, "page_size": 1},
            )
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
            raise MoneyPrinterTurboProviderError(
                f"MoneyPrinterTurbo request failed: {exc}"
            ) from exc
        finally:
            if close_client:
                client.close()

    def _json_body(self, response: Any, *, context: str) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError as exc:
            raise MoneyPrinterTurboProviderError(
                f"MoneyPrinterTurbo {context} returned non-JSON."
            ) from exc
        if not isinstance(body, dict):
            raise MoneyPrinterTurboProviderError(
                f"MoneyPrinterTurbo {context} returned non-object JSON."
            )
        return body

    def _data_payload(self, body: dict[str, Any], *, context: str) -> dict[str, Any]:
        data = body.get("data")
        if not isinstance(data, dict):
            raise MoneyPrinterTurboProviderError(
                f"MoneyPrinterTurbo {context} response missing data object."
            )
        return data
