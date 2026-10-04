from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx


class TelegramApiError(RuntimeError):
    def __init__(
        self,
        description: str,
        *,
        status_code: int | None = None,
        error_code: int | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(description)
        self.status_code = status_code
        self.error_code = error_code
        self.retry_after_seconds = retry_after_seconds


class TelegramBotClient:
    def __init__(
        self,
        *,
        token: str,
        base_url: str = "https://api.telegram.org",
        http_client=None,
        timeout: float = 20.0,
    ) -> None:
        self._token = token
        self._client = http_client or httpx.Client(base_url=base_url, timeout=timeout)


    def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        reply_markup: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, object] = {"chat_id": chat_id, "text": text}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        response = self._client.post(
            self._path("sendMessage"),
            json=payload,
        )
        data = _response_data(response, "sendMessage")
        return data


    def send_document(
        self,
        *,
        chat_id: int,
        document_path: Path | str,
        caption: str | None = None,
    ) -> dict[str, Any]:
        path = Path(document_path)
        with path.open("rb") as handle:
            response = self._client.post(
                self._path("sendDocument"),
                data={"chat_id": chat_id, "caption": caption or ""},
                files={"document": (path.name, handle, "application/pdf")},
            )
        data = _response_data(response, "sendDocument")
        return data

    def _path(self, method: str) -> str:
        return f"/bot{self._token}/{method}"


def _api_error(response, data: dict[str, Any], method: str) -> TelegramApiError:
    parameters = data.get("parameters")
    retry_after = parameters.get("retry_after") if isinstance(parameters, dict) else None
    return TelegramApiError(
        str(data.get("description") or f"Telegram {method} returned ok=false."),
        status_code=getattr(response, "status_code", None),
        error_code=data.get("error_code") if isinstance(data.get("error_code"), int) else None,
        retry_after_seconds=float(retry_after) if isinstance(retry_after, (int, float)) else None,
    )


def _response_data(response, method: str) -> dict[str, Any]:
    try:
        data = response.json()
    except (TypeError, ValueError) as exc:
        response.raise_for_status()
        raise TelegramApiError(f"Telegram {method} returned invalid JSON.") from exc
    if not isinstance(data, dict):
        raise TelegramApiError(f"Telegram {method} returned a non-object response.")
    if not data.get("ok"):
        raise _api_error(response, data, method)
    response.raise_for_status()
    return data


