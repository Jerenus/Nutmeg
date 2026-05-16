"""External IO and persistence for the psychology layer.

Consolidates the former ``llm``, ``sources/`` (news_cache, rss_provider,
zhilio_provider), ``calibration/recorder`` and ``inspiration`` modules into a
single boundary module. All side-effecting code (LLM completion, news caching,
RSS / zhilio fetching, JSONL recording, inspiration parsing and storage) lives
here. Pure domain types remain in :mod:`nutmeg.services.psychology.schemas`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from nutmeg.services.psychology.schemas import (
    DualSchemeReport,
    InspirationNote,
    InspirationTags,
)

# ---------------------------------------------------------------------------
# LLM completion (formerly llm.py)
# ---------------------------------------------------------------------------


class LLMCompletionError(RuntimeError):
    """Raised when the underlying LLM call fails or fake responses are exhausted."""


class LLMCompleter(Protocol):
    def complete(self, *, system: str, user: str) -> str: ...


@dataclass(slots=True)
class FakeLLMCompleter:
    responses: list[str] = field(default_factory=list)

    def complete(self, *, system: str, user: str) -> str:
        if not self.responses:
            raise LLMCompletionError("FakeLLMCompleter responses exhausted")
        return self.responses.pop(0)


@dataclass(slots=True)
class PortkeyLLMCompleter:
    """Production LLMCompleter wrapping PortkeySynthesisProvider."""

    portkey_provider: object

    def complete(self, *, system: str, user: str) -> str:
        try:
            response = self.portkey_provider._client.post(  # type: ignore[attr-defined]
                "/chat/completions",
                headers={
                    "authorization": f"Bearer {self.portkey_provider._api_key}",
                    "content-type": "application/json",
                },
                json={
                    "model": self.portkey_provider._model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.2,
                },
            )
            response.raise_for_status()
            text = self.portkey_provider._extract_text(response.json())
        except AttributeError as exc:
            raise LLMCompletionError("Portkey provider lacks raw completion internals") from exc
        except Exception as exc:  # noqa: BLE001 - normalize provider exceptions
            raise LLMCompletionError(str(exc)) from exc
        if not text:
            raise LLMCompletionError("Portkey provider returned no text")
        return str(text)


# ---------------------------------------------------------------------------
# News cache (formerly sources/news_cache.py)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# RSS provider (formerly sources/rss_provider.py)
# ---------------------------------------------------------------------------

RssFetcher = Callable[[str], dict[str, Any]]


def _matches(entry: dict[str, Any], query: str | None) -> bool:
    if not query:
        return True
    q = query.lower()
    haystack = " ".join([str(entry.get("title", "")), str(entry.get("summary", ""))]).lower()
    return q in haystack


@dataclass(slots=True)
class RssProvider:
    feeds: list[str]
    fetcher: RssFetcher
    cache: NewsCache

    def fetch(self, *, date: str, query: str | None) -> list[dict[str, Any]]:
        cache_key = f"rss:{','.join(self.feeds)}:{query or ''}"
        cached = self.cache.get(date=date, key=cache_key)
        if cached is not None:
            return cached
        merged: list[dict[str, Any]] = []
        for feed_url in self.feeds:
            try:
                payload = self.fetcher(feed_url)
            except Exception:  # noqa: BLE001 - external IO degradation path
                continue
            for entry in payload.get("entries") or []:
                if _matches(entry, query):
                    merged.append(
                        {
                            "title": entry.get("title", ""),
                            "link": entry.get("link", ""),
                            "summary": entry.get("summary", ""),
                            "feed": feed_url,
                        }
                    )
        self.cache.put(date=date, key=cache_key, payload=merged)
        return merged


# ---------------------------------------------------------------------------
# Zhilio provider (formerly sources/zhilio_provider.py)
# ---------------------------------------------------------------------------

CallSearchNews = Callable[..., dict[str, Any]]
CallHotlist = Callable[..., dict[str, Any]]


@dataclass(slots=True)
class ZhilioProvider:
    """Thin wrapper around zhilio MCP read tools."""

    call_search_news: CallSearchNews
    call_hotlist: CallHotlist
    cache: NewsCache

    def search_news(self, *, query: str, date: str, limit: int = 20) -> list[dict[str, Any]]:
        cached = self.cache.get(date=date, key=f"news:{query}:{limit}")
        if cached is not None:
            return cached
        try:
            response = self.call_search_news(query=query, limit=limit)
        except Exception:  # noqa: BLE001 - external IO degradation path
            return []
        items = list(response.get("items") or [])
        self.cache.put(date=date, key=f"news:{query}:{limit}", payload=items)
        return items

    def hotlist(self, *, date: str) -> list[dict[str, Any]]:
        cached = self.cache.get(date=date, key="hotlist")
        if cached is not None:
            return cached
        try:
            response = self.call_hotlist()
        except Exception:  # noqa: BLE001 - external IO degradation path
            return []
        items = list(response.get("items") or [])
        self.cache.put(date=date, key="hotlist", payload=items)
        return items


# ---------------------------------------------------------------------------
# Calibration recorder (formerly calibration/recorder.py)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Recorder:
    base_dir: Path

    def _path(self, date: str) -> Path:
        return self.base_dir / date / "recorder.jsonl"

    def record(self, *, date: str, report: DualSchemeReport) -> None:
        path = self._path(date)
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = []
        for final_leg, dash in zip(report.final_scheme.legs, report.dashboard_rows, strict=False):
            rows.append(
                {
                    "date": date,
                    "fixture_id": final_leg.fixture_id,
                    "leg_id": final_leg.leg_id,
                    "market": final_leg.market,
                    "data_pick": dash.data_pick,
                    "psych_pick": dash.psych_pick,
                    "final_pick": final_leg.outcome,
                    "provenance": final_leg.provenance,
                    "conviction": dash.conviction,
                    "hit": None,
                }
            )
        with path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def update_outcome(
        self, *, date: str, fixture_id: str, market: str, actual_outcome: str
    ) -> None:
        path = self._path(date)
        if not path.exists():
            return
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        for row in rows:
            if row["fixture_id"] == fixture_id and row["market"] == market:
                row["hit"] = row["final_pick"] == actual_outcome
        path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8"
        )

    def read(self, *, date: str) -> list[dict[str, Any]]:
        path = self._path(date)
        if not path.exists():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


# ---------------------------------------------------------------------------
# Inspiration parsing and storage (formerly inspiration.py)
# ---------------------------------------------------------------------------

LEAN_PSYCHOLOGY_KW = ("反着来", "反向", "心理", "直觉")
LEAN_DATA_KW = ("数据", "算法", "正常")
CONVICTION_HIGH_KW = ("必", "锁", "强")
CONVICTION_LOW_KW = ("微", "小", "或许")
FOCUS_TABLE = {
    "tournament_stage": ("淘汰", "决赛", "首回合", "次回合", "大赛"),
    "contrarian_narrative": ("舆论", "媒体", "热搜"),
    "personal_narrative": ("复仇", "首秀", "末战", "回归", "里程碑"),
    "reflexive_tactic": ("战术", "变招", "二阶", "压迫"),
}
FORCE_PSY_KW = ("今天必须", "强制心理", "心理强制")
FORCE_DATA_KW = ("强制数据", "数据强制")
SYSTEM_PROMPT = "Extract inspiration JSON tags."


@dataclass(slots=True)
class InspirationParser:
    llm: LLMCompleter

    def parse(self, text: str, *, date: str) -> InspirationNote:
        timestamp = datetime.now(tz=timezone.utc).isoformat()
        try:
            payload = json.loads(self.llm.complete(system=SYSTEM_PROMPT, user=text))
            tags = InspirationTags(
                str(payload.get("lean", "neutral")),
                str(payload.get("conviction", "medium")),
                list(payload.get("focus") or []),
                bool(payload.get("force_psychology", False)),
                bool(payload.get("force_data", False)),
            )  # type: ignore[arg-type]
            return InspirationNote(date, text, tags, "llm", timestamp)
        except (LLMCompletionError, ValueError, TypeError, json.JSONDecodeError):
            return InspirationNote(date, text, self._regex_parse(text), "regex_fallback", timestamp)

    def _regex_parse(self, text: str) -> InspirationTags:
        lean = "neutral"
        if any(k in text for k in LEAN_PSYCHOLOGY_KW):
            lean = "psychology"
        elif any(k in text for k in LEAN_DATA_KW):
            lean = "data"
        conviction = "medium"
        if any(k in text for k in CONVICTION_HIGH_KW):
            conviction = "high"
        elif any(k in text for k in CONVICTION_LOW_KW):
            conviction = "low"
        focus = [provider for provider, kws in FOCUS_TABLE.items() if any(k in text for k in kws)]
        return InspirationTags(
            lean=lean,
            conviction=conviction,
            focus=focus,
            force_psychology=any(k in text for k in FORCE_PSY_KW),
            force_data=any(k in text for k in FORCE_DATA_KW),
        )  # type: ignore[arg-type]


@dataclass(slots=True)
class InspirationStore:
    base_dir: Path

    def _dir(self, date: str) -> Path:
        return self.base_dir / date

    def write_raw(self, *, date: str, text: str) -> Path:
        path = self._dir(date) / "raw.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def write_parsed(
        self, *, date: str, tags: InspirationTags, raw_text: str, parse_method: str, timestamp: str
    ) -> Path:
        path = self._dir(date) / "parsed.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "date": date,
            "raw_text": raw_text,
            "parsed_tags": {
                "lean": tags.lean,
                "conviction": tags.conviction,
                "focus": tags.focus,
                "force_psychology": tags.force_psychology,
                "force_data": tags.force_data,
            },
            "parse_method": parse_method,
            "timestamp": timestamp,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def read(self, *, date: str) -> InspirationNote | None:
        path = self._dir(date) / "parsed.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        t = data["parsed_tags"]
        return InspirationNote(
            data["date"],
            data["raw_text"],
            InspirationTags(
                t["lean"],
                t["conviction"],
                list(t["focus"]),
                bool(t["force_psychology"]),
                bool(t["force_data"]),
            ),
            data["parse_method"],
            data["timestamp"],
        )
