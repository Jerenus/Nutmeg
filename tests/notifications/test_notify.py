import hashlib
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

import nutmeg.notifications.notify as notify_module
from nutmeg.config.settings import get_settings
from nutmeg.interfaces.bot.telegram import TelegramApiError
from nutmeg.notifications.notify import notify, semantic_fingerprint


@pytest.fixture(autouse=True)
def _no_real_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even if a test forgets a fake client, nothing can reach the real bot."""
    monkeypatch.setenv("NUTMEG_TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS", "")
    get_settings.cache_clear()


class FakeClient:
    def __init__(self, failures: list[Exception] | None = None) -> None:
        self.failures = list(failures or [])
        self.messages: list[tuple[int, str]] = []
        self.documents: list[tuple[int, str]] = []

    def _maybe_fail(self) -> None:
        if self.failures:
            raise self.failures.pop(0)

    def send_message(self, *, chat_id: int, text: str) -> dict:
        self._maybe_fail()
        self.messages.append((chat_id, text))
        return {"ok": True}

    def send_document(self, *, chat_id: int, document_path: Path, caption=None) -> dict:
        self._maybe_fail()
        self.documents.append((chat_id, Path(document_path).name))
        return {"ok": True}


def _rows(ledger: Path) -> list[dict]:
    return [json.loads(line) for line in ledger.read_text("utf-8").splitlines()]


def _send(ledger: Path, client: FakeClient, *, kind="k", key="b:s", fp="f1", text="hello",
          **kwargs):
    return notify(kind, key, fp, text, client=client, chat_ids=[42], ledger=ledger,
                  sleep=lambda _s: None, **kwargs)


def test_same_identity_is_sent_once(tmp_path: Path) -> None:
    ledger = tmp_path / "notifications" / "ledger.jsonl"
    client = FakeClient()
    assert _send(ledger, client).status == "sent"
    assert _send(ledger, client).status == "deduplicated"
    assert client.messages == [(42, "hello")]
    [row] = _rows(ledger)
    assert row["status"] == "sent" and row["error"] is None
    assert (row["kind"], row["key"], row["fingerprint"]) == ("k", "b:s", "f1")
    # a new fingerprint (content changed) or another kind is a new message
    assert _send(ledger, client, fp="f2").status == "sent"
    assert _send(ledger, client, kind="other").status == "sent"
    assert len(client.messages) == 3


def test_transient_failure_is_retried_once_in_call(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    client = FakeClient([httpx.ConnectTimeout("slow")])
    sleeps: list[float] = []
    result = notify("k", "b:s", "f", "hi", client=client, chat_ids=[1], ledger=ledger,
                    sleep=sleeps.append)
    assert result.status == "sent"
    assert sleeps == [1.0] and client.messages == [(1, "hi")]
    assert [row["status"] for row in _rows(ledger)] == ["sent"]


def test_failed_send_is_recorded_and_retried_by_the_next_call(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    rejected = TelegramApiError("Bad Request", status_code=400, error_code=400)
    client = FakeClient([rejected])
    first = _send(ledger, client)
    assert first.status == "failed" and not first.is_success
    assert client.messages == []                       # permanent error: no in-call retry
    assert _send(ledger, client).status == "sent"      # next call re-attempts
    assert _send(ledger, client).status == "deduplicated"
    assert [row["status"] for row in _rows(ledger)] == ["failed", "sent"]
    assert "Bad Request" in _rows(ledger)[0]["error"]


def test_two_transient_failures_give_up_until_next_call(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    limited = TelegramApiError("Too Many", status_code=429, error_code=429,
                               retry_after_seconds=3)
    client = FakeClient([limited, httpx.ConnectError("down /bot123:SECRET/sendMessage")])
    sleeps: list[float] = []
    result = notify("k", "b:s", "f", "hi", client=client, chat_ids=[1], ledger=ledger,
                    sleep=sleeps.append)
    assert result.status == "failed" and sleeps == [3]
    assert "SECRET" not in result.error and "/bot***" in result.error


def test_attachments_follow_the_text(tmp_path: Path) -> None:
    report = tmp_path / "report.pdf"
    report.write_bytes(b"%PDF-1.4")
    client = FakeClient()
    result = _send(tmp_path / "ledger.jsonl", client, attachments=[report])
    assert result.status == "sent"
    assert client.messages == [(42, "hello")]
    assert client.documents == [(42, "report.pdf")]


def test_long_text_goes_out_as_consecutive_messages(tmp_path: Path) -> None:
    client = FakeClient()
    text = "x" * 5000
    _send(tmp_path / "ledger.jsonl", client, text=text)
    assert [len(body) for _chat, body in client.messages] == [4096, 904]
    assert "".join(body for _chat, body in client.messages) == text


def test_dry_run_neither_sends_nor_writes(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    client = FakeClient()
    assert _send(ledger, client, dry_run=True).status == "dry_run"
    assert client.messages == [] and not ledger.exists()


def test_unconfigured_telegram_is_a_recorded_failure(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    result = notify("k", "b:s", "f", "hi", ledger=ledger)
    assert result.status == "failed" and "not configured" in result.error
    assert _rows(ledger)[0]["status"] == "failed"


def test_default_ledger_lives_under_the_data_dir(tmp_path: Path) -> None:
    client = FakeClient()
    notify("k", "b:s", "f", "hi", client=client, chat_ids=[1])
    ledger = get_settings().data_dir / "notifications" / "ledger.jsonl"
    assert [row["key"] for row in _rows(ledger)] == ["b:s"]


def test_semantic_fingerprint_matches_the_outbox_digest() -> None:
    # same canonical-JSON sha256 the outbox stored, so old identities still match
    payload = {"stage": "morning", "body": "备料"}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
    assert semantic_fingerprint(payload) == hashlib.sha256(canonical).hexdigest()
    assert semantic_fingerprint({"b": 1, "a": 2}) == semantic_fingerprint({"a": 2, "b": 1})


def _scheduler_ops():
    script = Path(__file__).parents[2] / "scripts" / "openclaw" / "nutmeg_scheduler_ops.py"
    spec = importlib.util.spec_from_file_location("nutmeg_scheduler_ops_notify", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_scheduler_failure_then_recovery_sends_one_alert_each(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = FakeClient()
    monkeypatch.setenv("NUTMEG_TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS", "7")
    get_settings.cache_clear()
    monkeypatch.setattr(notify_module, "TelegramBotClient", lambda **_kw: sent)
    ops = _scheduler_ops()
    state = tmp_path / "ops-state.json"

    ops._record_operation_failure("am", "2026-10-08", "am failed: boom", state)
    ops._record_operation_failure("am", "2026-10-08", "am failed: boom", state)  # same → once
    ops._record_operation_success("am", "2026-10-08", state)
    ops._record_operation_success("am", "2026-10-08", state)  # already recovered → silent

    assert [text for _chat, text in sent.messages] == [
        "am failed: boom",
        "am recovered after a previous failed run",
    ]
    ledger = get_settings().data_dir / "notifications" / "ledger.jsonl"
    assert [row["kind"] for row in _rows(ledger)] == [
        "operations.failure", "operations.recovered"
    ]


class FailAt(FakeClient):
    """Raise the given errors on specific send calls (0-based, counting every send)."""

    def __init__(self, failures_at: dict[int, Exception]) -> None:
        super().__init__()
        self.failures_at = dict(failures_at)
        self.calls = 0

    def _maybe_fail(self) -> None:
        index, self.calls = self.calls, self.calls + 1
        if index in self.failures_at:
            raise self.failures_at.pop(index)


def test_retry_never_resends_a_part_already_delivered(tmp_path: Path) -> None:
    """10-08 复查：重试曾把已送达的聊天 / 分段再发一遍（chat 1 收两次）。"""
    client = FailAt({1: httpx.ConnectError("down")})       # chat 2 transient → in-call retry
    result = notify("k", "b:s", "f", "hi", client=client, chat_ids=[1, 2],
                    ledger=tmp_path / "ledger.jsonl", sleep=lambda _s: None)
    assert result.status == "sent"
    assert client.messages == [(1, "hi"), (2, "hi")]


def test_next_call_resumes_after_the_delivered_chunks(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    rejected = TelegramApiError("Bad Request", status_code=400, error_code=400)
    client = FailAt({1: rejected})                          # chunk 2 fails permanently
    text = "x" * 5000
    assert _send(ledger, client, text=text).status == "failed"
    assert _rows(ledger)[-1]["delivered"] == ["42:t0"]
    assert _send(ledger, client, text=text).status == "sent"
    assert [len(body) for _chat, body in client.messages] == [4096, 904]   # chunk 1 once
