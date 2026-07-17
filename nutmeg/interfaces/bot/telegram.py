from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from nutmeg.interfaces.bot.adapter import BotAdapter


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


@dataclass(slots=True, frozen=True)
class TelegramPollSummary:
    updates_seen: int
    messages_handled: int
    messages_denied: int
    messages_ignored: int
    next_offset: int | None


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

    def get_updates(self, *, offset: int | None = None, timeout: int = 10) -> list[dict[str, Any]]:
        payload: dict[str, object] = {"timeout": timeout}
        if offset is not None:
            payload["offset"] = offset
        response = self._client.post(self._path("getUpdates"), json=payload)
        data = _response_data(response, "getUpdates")
        result = data.get("result") or []
        if not isinstance(result, list):
            raise RuntimeError("Telegram getUpdates result was not a list.")
        return result

    def send_message(self, *, chat_id: int, text: str) -> dict[str, Any]:
        response = self._client.post(
            self._path("sendMessage"),
            json={"chat_id": chat_id, "text": text},
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


class TelegramBotRunner:
    def __init__(
        self,
        *,
        client: TelegramBotClient,
        bot_adapter: BotAdapter,
        allowed_chat_ids: set[int],
    ) -> None:
        self._client = client
        self._bot_adapter = bot_adapter
        self._allowed_chat_ids = allowed_chat_ids

    def poll_once(self, *, offset: int | None = None, timeout: int = 10) -> TelegramPollSummary:
        updates = self._client.get_updates(offset=offset, timeout=timeout)
        handled = 0
        denied = 0
        ignored = 0
        next_offset = offset
        for update in updates:
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                next_offset = max(next_offset or 0, update_id + 1)
            message = update.get("message")
            if not isinstance(message, dict):
                ignored += 1
                continue
            chat = message.get("chat")
            text = message.get("text")
            chat_id = chat.get("id") if isinstance(chat, dict) else None
            if not isinstance(chat_id, int) or not isinstance(text, str):
                ignored += 1
                continue
            if chat_id not in self._allowed_chat_ids:
                denied += 1
                self._client.send_message(
                    chat_id=chat_id,
                    text="Unauthorized chat id. This Nutmeg bot is owner-only.",
                )
                continue
            response = self._bot_adapter.handle_message(text)
            handled += 1
            self._client.send_message(chat_id=chat_id, text=response.text)
        return TelegramPollSummary(
            updates_seen=len(updates),
            messages_handled=handled,
            messages_denied=denied,
            messages_ignored=ignored,
            next_offset=next_offset,
        )


class TelegramOffsetStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def read(self) -> int | None:
        if not self.path.exists():
            return None
        try:
            value = int(self.path.read_text().strip())
        except (OSError, TypeError, ValueError):
            return None
        return value if value >= 0 else None

    def write(self, offset: int) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(f"{offset}\n")


@dataclass(slots=True, frozen=True)
class TelegramDaemonSummary:
    polls_run: int
    updates_seen: int
    messages_handled: int
    messages_denied: int
    messages_ignored: int
    next_offset: int | None
    stop_reason: str


class TelegramPollingDaemon:
    def __init__(
        self,
        *,
        runner: TelegramBotRunner,
        poll_interval_seconds: float,
        sleep_fn,
        offset_store: TelegramOffsetStore | None = None,
    ) -> None:
        self._runner = runner
        self._poll_interval_seconds = poll_interval_seconds
        self._sleep_fn = sleep_fn
        self._offset_store = offset_store

    def run(
        self,
        *,
        offset: int | None = None,
        timeout: int = 10,
        max_polls: int | None = None,
    ) -> TelegramDaemonSummary:
        polls_run = 0
        updates_seen = 0
        messages_handled = 0
        messages_denied = 0
        messages_ignored = 0
        next_offset = offset
        stop_reason = "max_polls" if max_polls == 0 else "running"

        try:
            while max_polls is None or polls_run < max_polls:
                summary = self._runner.poll_once(offset=next_offset, timeout=timeout)
                polls_run += 1
                updates_seen += summary.updates_seen
                messages_handled += summary.messages_handled
                messages_denied += summary.messages_denied
                messages_ignored += summary.messages_ignored
                next_offset = summary.next_offset
                if next_offset is not None and self._offset_store is not None:
                    self._offset_store.write(next_offset)
                if max_polls is not None and polls_run >= max_polls:
                    stop_reason = "max_polls"
                    break
                if self._poll_interval_seconds > 0:
                    self._sleep_fn(self._poll_interval_seconds)
        except KeyboardInterrupt:
            stop_reason = "interrupted"

        return TelegramDaemonSummary(
            polls_run=polls_run,
            updates_seen=updates_seen,
            messages_handled=messages_handled,
            messages_denied=messages_denied,
            messages_ignored=messages_ignored,
            next_offset=next_offset,
            stop_reason=stop_reason,
        )
