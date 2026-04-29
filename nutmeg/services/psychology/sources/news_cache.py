from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_TTL_HOURS = 24


@dataclass(slots=True)
class NewsCache:
    base_dir: Path
    ttl_hours: int = DEFAULT_TTL_HOURS
    now: Callable[[], datetime] = lambda: datetime.now(tz=timezone.utc)

    def _path(self, *, date: str, key: str) -> Path:
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
        return self.base_dir / date / f"{digest}.json"

    def get(self, *, date: str, key: str) -> list[dict[str, Any]] | None:
        path = self._path(date=date, key=key)
        if not path.exists():
            return None
        record = json.loads(path.read_text(encoding="utf-8"))
        stored_at = datetime.fromisoformat(record["stored_at"])
        if self.now() - stored_at > timedelta(hours=self.ttl_hours):
            return None
        return record["payload"]

    def put(self, *, date: str, key: str, payload: list[dict[str, Any]]) -> None:
        path = self._path(date=date, key=key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"stored_at": self.now().isoformat(), "payload": payload}, ensure_ascii=False
            ),
            encoding="utf-8",
        )
