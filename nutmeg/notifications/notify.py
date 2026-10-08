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
import os
import re
import sqlite3
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
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
    if (kind, key, fingerprint) in _sent(path):
        return NotifyResult("deduplicated")
    error = _deliver(text, [Path(item) for item in attachments], client, chat_ids, sleep)
    row = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "kind": kind,
        "key": key,
        "fingerprint": fingerprint,
        "status": "failed" if error else "sent",
        "error": error,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return NotifyResult("failed", error) if error else NotifyResult("sent")


def _deliver(
    text: str,
    attachments: list[Path],
    client: Any,
    chat_ids: Sequence[int] | None,
    sleep: Callable[[float], None],
) -> str | None:
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
        return "telegram not configured (NUTMEG_TELEGRAM_BOT_TOKEN / _ALLOWED_CHAT_IDS)"
    chunks = [text[i : i + TEXT_LIMIT] for i in range(0, len(text), TEXT_LIMIT)]
    retried = False
    while True:
        try:
            for chat_id in chat_ids:
                for chunk in chunks:
                    client.send_message(chat_id=chat_id, text=chunk)
                for attachment in attachments:
                    client.send_document(chat_id=chat_id, document_path=attachment)
            return None
        except Exception as exc:  # noqa: BLE001 - recorded in the ledger, retried next call
            delay = _transient_delay(exc)
            if retried or delay is None:
                redacted = re.sub(r"/bot[^/\s]+", "/bot***", str(exc))
                return f"{type(exc).__name__}: {redacted}"[:500]
            retried = True
            sleep(delay)


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


def _sent(path: Path) -> set[tuple[str, str, str]]:
    sent = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue  # a torn last line never blocks sending
        if row.get("status") == "sent":
            sent.add((row.get("kind"), row.get("key"), row.get("fingerprint")))
    return sent


def _ensure_ledger(path: Path) -> None:
    """Create the ledger on first use, seeded from the retired SQL outbox.

    Cutover (2026-10-08): every notification ``state/state.db`` marks ``sent`` is imported
    as a ``sent`` row, so nothing already delivered goes out again. state.db is read-only
    here and stays on disk. Idempotent: the import runs only while the ledger is absent, and
    the seeded ledger appears atomically (hard link), so a crash or a racing process never
    leaves a half-imported ledger.
    """
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = _legacy_sent(path.parent.parent / "state" / "state.db")
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )
    try:
        os.link(tmp, path)
    except FileExistsError:
        pass
    finally:
        tmp.unlink(missing_ok=True)


def _legacy_sent(state_db: Path) -> list[dict[str, Any]]:
    if not state_db.is_file():
        return []
    con = sqlite3.connect(f"{state_db.resolve().as_uri()}?mode=ro", uri=True)
    try:
        records = con.execute(
            "SELECT kind, business_key, stage, semantic_fingerprint, updated_at "
            "FROM notifications WHERE status = 'sent' ORDER BY created_at"
        ).fetchall()
    except sqlite3.OperationalError:  # no outbox table in this state.db
        return []
    finally:
        con.close()
    return [
        {
            "ts": _utc_to_local(updated_at),
            "kind": kind,
            "key": f"{business_key}:{stage}",
            "fingerprint": fingerprint,
            "status": "sent",
            "error": None,
            "via": "state.db",
        }
        for kind, business_key, stage, fingerprint, updated_at in records
    ]


def _utc_to_local(value: object) -> str:
    """The outbox stored naive UTC timestamps; the ledger writes local time with offset."""
    try:
        stamp = datetime.fromisoformat(str(value)).replace(tzinfo=UTC)
    except ValueError:
        return str(value)
    return stamp.astimezone().isoformat(timespec="seconds")
