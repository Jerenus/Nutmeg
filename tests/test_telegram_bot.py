from __future__ import annotations

import httpx
import pytest

from nutmeg.interfaces.bot.telegram import TelegramApiError, TelegramBotClient


class FakeHttpClient:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, object]]] = []
        self.responses: list[dict[str, object]] = []

    def post(self, path: str, json: dict[str, object]):
        self.posts.append((path, json))
        payload = self.responses.pop(0) if self.responses else {"ok": True, "result": {}}
        return FakeResponse(payload)


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


def test_telegram_client_sends_message_without_leaking_token_in_path_body() -> None:
    http = FakeHttpClient()
    client = TelegramBotClient(token="secret-token", http_client=http)

    result = client.send_message(chat_id=12345, text="hello")

    assert result == {"ok": True, "result": {}}
    assert http.posts == [("/botsecret-token/sendMessage", {"chat_id": 12345, "text": "hello"})]


def test_telegram_client_preserves_retry_after_from_http_429() -> None:
    class RateLimitedResponse:
        status_code = 429

        def json(self):
            return {
                "ok": False,
                "error_code": 429,
                "description": "Too Many Requests",
                "parameters": {"retry_after": 7},
            }

        def raise_for_status(self):
            raise httpx.HTTPStatusError(
                "rate limited",
                request=httpx.Request("POST", "https://api.telegram.org"),
                response=httpx.Response(429),
            )

    class RateLimitedHttpClient:
        def post(self, path, json):
            return RateLimitedResponse()

    client = TelegramBotClient(token="secret-token", http_client=RateLimitedHttpClient())

    with pytest.raises(TelegramApiError) as captured:
        client.send_message(chat_id=12345, text="hello")

    assert captured.value.error_code == 429
    assert captured.value.retry_after_seconds == 7


def test_telegram_client_sends_document_without_leaking_token_in_path_body(tmp_path) -> None:
    from nutmeg.interfaces.bot.telegram import TelegramBotClient

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True, "result": {"message_id": 7}}

    class HttpClient:
        def __init__(self):
            self.calls = []

        def post(self, path, data=None, files=None, json=None):
            self.calls.append({"path": path, "data": data, "files": files, "json": json})
            return Response()

    document = tmp_path / "report.pdf"
    document.write_bytes(b"%PDF-1.4\n")
    http = HttpClient()
    client = TelegramBotClient(token="telegram-secret", http_client=http)

    payload = client.send_document(chat_id=1234, document_path=document, caption="Zucai report")

    assert payload["ok"] is True
    call = http.calls[0]
    assert call["path"] == "/bottelegram-secret/sendDocument"
    assert call["data"] == {"chat_id": 1234, "caption": "Zucai report"}
    assert "telegram-secret" not in str(call["data"])
    assert call["files"]["document"][0] == "report.pdf"


