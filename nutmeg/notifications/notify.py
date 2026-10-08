"""Outbound Telegram notifications: one call, one append-only JSONL ledger.

Replaces the 2026-07 four-table SQL outbox (notifications / deliveries / attempts /
artifacts in ``state/state.db``). Its real load was 162 notifications in three months,
161 delivered on the first attempt, so the guarantee kept here is the one that matters:
an identical message is sent at most once, and a failed send is recorded and re-attempted
by the next call with the same identity.

Identity = ``(kind, key, fingerprint)``. Publishers moved off the outbox pass
``key = f"{business_key}:{stage}"`` of their old request and the same fingerprint, so the
outbox's dedupe key ``kind:business_key:stage:fingerprint`` maps one-to-one.

Ledger = ``<data_dir>/notifications/ledger.jsonl``, one JSON object per send attempt:
``ts``, ``kind``, ``key``, ``fingerprint``, ``status`` (``sent`` | ``failed``), ``error``.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from nutmeg.interfaces.bot.telegram import TelegramApiError, TelegramBotClient

TEXT_LIMIT = 4096
"""Telegram sendMessage limit; longer text goes out as consecutive messages."""


@dataclass(frozen=True)
class NotifyResult:
    status: str  # sent | deduplicated | dry_run | failed
    error: str | None = None

    @property
    def is_success(self) -> bool:
        return self.status != "failed"


def semantic_fingerprint(payload: Any) -> str:
    """sha256 of canonical JSON (the digest the old outbox stored, so identities carry over)."""
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def default_ledger() -> Path:
    from nutmeg.config.settings import get_settings

    return get_settings().data_dir / "notifications" / "ledger.jsonl"


def notify(
    kind: str,
    key: str,
    fingerprint: str,
    text: str,
    *,
    attachments: Sequence[Path | str] = (),
    client: Any = None,
    chat_ids: Sequence[int] | None = None,
    ledger: Path | None = None,
    dry_run: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> NotifyResult:
    """Send ``text`` (then each attachment as a document) unless this identity was sent.

    ``client``/``chat_ids`` default to the settings' bot token and allowed chat ids.
    Dry-run touches neither Telegram nor the ledger. A transient failure (timeout, network,
    429, 5xx) is retried once in-call; any failure is recorded and retried next call.
    """
    if not (text.strip() or attachments):
        raise ValueError("notification needs text or an attachment")
    if dry_run:
        return NotifyResult("dry_run")
    path = Path(ledger) if ledger is not None else default_ledger()
    _ensure_ledger(path)
    sent, done = _progress(path, (kind, key, fingerprint))
    if sent:
        return NotifyResult("deduplicated")
    error, done = _deliver(text, [Path(item) for item in attachments], client, chat_ids,
                           sleep, done)
    row = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "kind": kind,
        "key": key,
        "fingerprint": fingerprint,
        "status": "failed" if error else "sent",
        "error": error,
    }
    if error:
        row["delivered"] = sorted(done)  # the next call sends only what is still owed
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return NotifyResult("failed", error) if error else NotifyResult("sent")


def _deliver(
    text: str,
    attachments: list[Path],
    client: Any,
    chat_ids: Sequence[int] | None,
    sleep: Callable[[float], None],
    done: set[str],
) -> tuple[str | None, set[str]]:
    """Send every (chat, chunk / attachment) part not in ``done``; returns (error, done).

    A part is never sent twice: an in-call retry resumes at the part that failed, and a
    failed call records what it delivered so the next call resumes there too."""
    if client is None or chat_ids is None:
        from nutmeg.config.settings import get_settings

        settings = get_settings()
        if chat_ids is None:
            raw = settings.telegram_allowed_chat_ids or ""
            chat_ids = sorted({int(chunk) for chunk in raw.split(",") if chunk.strip()})
        if client is None and settings.telegram_bot_token:
            client = TelegramBotClient(
                token=settings.telegram_bot_token, base_url=settings.telegram_api_base_url
            )
    if client is None or not chat_ids:
        return "telegram not configured (NUTMEG_TELEGRAM_BOT_TOKEN / _ALLOWED_CHAT_IDS)", done
    chunks = [text[i : i + TEXT_LIMIT] for i in range(0, len(text), TEXT_LIMIT)]
    parts = []
    for chat_id in chat_ids:
        parts += [(f"{chat_id}:t{i}", client.send_message, {"chat_id": chat_id, "text": chunk})
                  for i, chunk in enumerate(chunks)]
        parts += [(f"{chat_id}:d{i}", client.send_document,
                   {"chat_id": chat_id, "document_path": attachment})
                  for i, attachment in enumerate(attachments)]
    done = set(done)
    retried = False
    for part_id, send, kwargs in parts:
        if part_id in done:
            continue
        while True:
            try:
                send(**kwargs)
            except Exception as exc:  # noqa: BLE001 - recorded in the ledger, retried next call
                delay = _transient_delay(exc)
                if retried or delay is None:
                    redacted = re.sub(r"/bot[^/\s]+", "/bot***", str(exc))
                    return f"{type(exc).__name__}: {redacted}"[:500], done
                retried = True
                sleep(delay)
            else:
                done.add(part_id)
                break
    return None, done


def _transient_delay(exc: Exception) -> float | None:
    if isinstance(exc, TelegramApiError):
        if 429 in (exc.error_code, exc.status_code):
            return min(exc.retry_after_seconds or 1.0, 30.0)
        if exc.status_code is not None and exc.status_code >= 500:
            return 1.0
        return None
    if isinstance(exc, httpx.RequestError):
        return 1.0
    return None


def _progress(path: Path, identity: tuple[str, str, str]) -> tuple[bool, set[str]]:
    """(already sent?, parts delivered by earlier failed attempts) for one identity."""
    sent, done = False, set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue  # a torn last line never blocks sending
        if (row.get("kind"), row.get("key"), row.get("fingerprint")) != identity:
            continue
        sent = sent or row.get("status") == "sent"
        done.update(row.get("delivered") or [])
    return sent, done


def _ensure_ledger(path: Path) -> None:
    """Create an empty ledger on first use. (The 2026-10-08 cutover seeded the production
    ledger with the 162 rows the retired SQL outbox had delivered; that one-time import and
    state.db are gone.)"""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()


