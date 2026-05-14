from __future__ import annotations

from nutmeg.interfaces.bot.telegram import (
    TelegramBotClient,
    TelegramBotRunner,
    TelegramOffsetStore,
)


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


def test_telegram_client_get_updates_uses_offset_and_timeout() -> None:
    http = FakeHttpClient()
    http.responses.append({"ok": True, "result": [{"update_id": 7}]})
    client = TelegramBotClient(token="secret-token", http_client=http)

    updates = client.get_updates(offset=5, timeout=3)

    assert updates == [{"update_id": 7}]
    assert http.posts == [("/botsecret-token/getUpdates", {"offset": 5, "timeout": 3})]


def test_telegram_runner_routes_allowed_messages_and_denies_unknown_chats() -> None:
    class StubAdapter:
        def handle_message(self, text: str):
            assert text == "/brief epl-001 Should I back Arsenal?"
            return type(
                "Response",
                (),
                {"status": "succeeded", "text": "Match Brief: Arsenal vs Spurs"},
            )()

    class StubClient:
        def __init__(self) -> None:
            self.sent: list[tuple[int, str]] = []

        def get_updates(self, *, offset: int | None, timeout: int) -> list[dict[str, object]]:
            assert offset == 10
            assert timeout == 1
            return [
                {
                    "update_id": 10,
                    "message": {
                        "chat": {"id": 111},
                        "text": "/brief epl-001 Should I back Arsenal?",
                    },
                },
                {
                    "update_id": 11,
                    "message": {"chat": {"id": 999}, "text": "/brief epl-001 nope"},
                },
            ]

        def send_message(self, *, chat_id: int, text: str):
            self.sent.append((chat_id, text))
            return {"ok": True}

    client = StubClient()
    runner = TelegramBotRunner(
        client=client,
        bot_adapter=StubAdapter(),
        allowed_chat_ids={111},
    )

    summary = runner.poll_once(offset=10, timeout=1)

    assert summary.updates_seen == 2
    assert summary.messages_handled == 1
    assert summary.messages_denied == 1
    assert summary.next_offset == 12
    assert client.sent == [
        (111, "Match Brief: Arsenal vs Spurs"),
        (999, "Unauthorized chat id. This Nutmeg bot is owner-only."),
    ]


def test_telegram_offset_store_round_trips_and_ignores_invalid_values(tmp_path) -> None:
    offset_path = tmp_path / "state" / "telegram.offset"
    store = TelegramOffsetStore(offset_path)

    assert store.read() is None

    store.write(123)

    assert offset_path.read_text() == "123\n"
    assert store.read() == 123

    offset_path.write_text("not-an-int")

    assert store.read() is None


def test_telegram_polling_daemon_runs_max_polls_and_aggregates_counts() -> None:
    from nutmeg.interfaces.bot.telegram import TelegramPollingDaemon, TelegramPollSummary

    class StubRunner:
        def __init__(self) -> None:
            self.calls: list[tuple[int | None, int]] = []
            self.summaries = [
                TelegramPollSummary(
                    updates_seen=2,
                    messages_handled=1,
                    messages_denied=1,
                    messages_ignored=0,
                    next_offset=12,
                ),
                TelegramPollSummary(
                    updates_seen=1,
                    messages_handled=1,
                    messages_denied=0,
                    messages_ignored=0,
                    next_offset=13,
                ),
            ]

        def poll_once(self, *, offset: int | None, timeout: int):
            self.calls.append((offset, timeout))
            return self.summaries.pop(0)

    sleeps: list[float] = []
    runner = StubRunner()
    daemon = TelegramPollingDaemon(runner=runner, poll_interval_seconds=0.5, sleep_fn=sleeps.append)

    summary = daemon.run(offset=10, timeout=1, max_polls=2)

    assert runner.calls == [(10, 1), (12, 1)]
    assert sleeps == [0.5]
    assert summary.polls_run == 2
    assert summary.updates_seen == 3
    assert summary.messages_handled == 2
    assert summary.messages_denied == 1
    assert summary.messages_ignored == 0
    assert summary.next_offset == 13
    assert summary.stop_reason == "max_polls"


def test_telegram_polling_daemon_persists_next_offset_after_each_poll(tmp_path) -> None:
    from nutmeg.interfaces.bot.telegram import TelegramPollingDaemon, TelegramPollSummary

    class StubRunner:
        def __init__(self) -> None:
            self.summaries = [
                TelegramPollSummary(
                    updates_seen=1,
                    messages_handled=1,
                    messages_denied=0,
                    messages_ignored=0,
                    next_offset=8,
                ),
                TelegramPollSummary(
                    updates_seen=1,
                    messages_handled=1,
                    messages_denied=0,
                    messages_ignored=0,
                    next_offset=9,
                ),
            ]

        def poll_once(self, *, offset: int | None, timeout: int):
            return self.summaries.pop(0)

    store = TelegramOffsetStore(tmp_path / "telegram.offset")
    daemon = TelegramPollingDaemon(
        runner=StubRunner(),
        poll_interval_seconds=0,
        sleep_fn=lambda _: None,
        offset_store=store,
    )

    summary = daemon.run(offset=7, timeout=1, max_polls=2)

    assert summary.next_offset == 9
    assert store.read() == 9


def test_telegram_polling_daemon_returns_interrupted_summary() -> None:
    from nutmeg.interfaces.bot.telegram import TelegramPollingDaemon, TelegramPollSummary

    class StubRunner:
        def __init__(self) -> None:
            self.calls = 0

        def poll_once(self, *, offset: int | None, timeout: int):
            self.calls += 1
            if self.calls == 1:
                return TelegramPollSummary(
                    updates_seen=1,
                    messages_handled=1,
                    messages_denied=0,
                    messages_ignored=0,
                    next_offset=8,
                )
            raise KeyboardInterrupt

    daemon = TelegramPollingDaemon(
        runner=StubRunner(),
        poll_interval_seconds=0,
        sleep_fn=lambda _: None,
    )

    summary = daemon.run(offset=7, timeout=1, max_polls=None)

    assert summary.polls_run == 1
    assert summary.updates_seen == 1
    assert summary.messages_handled == 1
    assert summary.next_offset == 8
    assert summary.stop_reason == "interrupted"


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


def test_bot_handles_renjiu_natural_language() -> None:
    from nutmeg.interfaces.bot.adapter import BotAdapter

    class StubRenjiuWorkflow:
        def __init__(self) -> None:
            self.calls = 0

        def run(self):
            self.calls += 1
            return {
                "status": "succeeded",
                "text": "任九第26074期三档方案已生成。\n主推：10 31 - 0 - 31 - 3 31 10 - 3 - 31（64注/128元）",
                "payload": {"mode": "zucai_renjiu_daily", "recommended_ticket_id": "main"},
            }

    workflow = StubRenjiuWorkflow()
    adapter = BotAdapter(workflow=None, renjiu_workflow=workflow)

    for message in ["今天任九方案", "做今天的14选9", "today's renjiu plan"]:
        response = adapter.handle_message(message)
        assert response.status == "succeeded"
        assert "任九第26074期" in response.text
        assert response.payload["mode"] == "zucai_renjiu_daily"

    assert workflow.calls == 3
