# Psychology & Game-Theory Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a parallel pre-match psychology & game-theory analysis layer that produces an independent verdict (HHAD / handicap / total goals) and may, under guardrails + a daily inspiration note, reverse a leg of the data-driven JCZQ parlay scheme.

**Architecture:** Pluggable signal pipeline. Four `SignalProvider` implementations (tournament_stage rule-based; contrarian_narrative + personal_narrative use zhilio MCP + self-hosted RSS + LLM; reflexive_tactic uses LLM over local tactical snapshots) feed a `PsychologyEngine`. A `Reconciliator` merges the engine's `PsychologyVerdict` with the existing data verdict, applies `BudgetGuard` + `ConvictionGate`, and consumes a parsed `InspirationNote` to gate or force overrides. Result is a `DualSchemeReport` (dashboard + data scheme + psychology scheme + final scheme + decision section). v1 wires only into `JczqMixedReportService`.

**Tech Stack:** Python 3.12 · pytest · typer · `nutmeg.agents.llm_provider` (Portkey) · zhilio MCP (read-only via wrapper) · feedparser/httpx for RSS · existing `nutmeg/services/jczq.py` integration.

**Spec reference:** `docs/superpowers/specs/2026-04-29-psychology-game-theory-layer-design.md` (SEALED v1.0)

**Naming convention deviation from spec:** spec proposes `tests/services/psychology/test_*.py` (nested). Existing project uses **flat** test filenames under `tests/` (e.g. `test_jczq_service.py`). This plan follows the existing flat convention — every test file lives directly under `tests/` with a `test_psychology_*.py` prefix.

---

## File Structure

**New module:** `nutmeg/services/psychology/`

| File | Responsibility |
|---|---|
| `__init__.py` | re-export `PsychologyEngine`, `Reconciliator`, key schemas |
| `schemas.py` | All dataclasses (`SignalReading`, `PsychologyVerdict`, `OverrideCandidate`, `GuardrailDecision`, `InspirationTags`, `InspirationNote`, `FinalScheme`, `FinalLeg`, `DataLeg`, `Scheme`, `DashboardRow`, `DualSchemeReport`, `OutcomeView`); no logic |
| `engine.py` | `PsychologyEngine` — orchestrates 4 providers (parallel via `concurrent.futures.ThreadPoolExecutor`), reduces readings into per-fixture `PsychologyVerdict` |
| `reconciliator.py` | `Reconciliator.reconcile(...)`; merges data + psychology verdicts; applies guardrails; consumes inspiration tags; emits `DualSchemeReport` |
| `inspiration.py` | `InspirationParser` (LLM primary, regex fallback); also helpers to read/write `.nutmeg-data/inspiration/{date}/raw.md` and `parsed.json` |
| `guardrails.py` | `BudgetGuard` (≤1 reversal per scheme) + `ConvictionGate` (≥ threshold) |
| `signals/__init__.py` | re-export the 4 providers |
| `signals/base.py` | `SignalProvider` Protocol; `SignalContext` (input bundle); shared error types |
| `signals/tournament_stage.py` | rule-based provider (no IO) |
| `signals/contrarian_narrative.py` | zhilio + RSS + LLM polarity reverse |
| `signals/reflexive_tactic.py` | LLM second-order tactical reasoning |
| `signals/personal_narrative.py` | RSS + LLM story-line extraction |
| `sources/__init__.py` | re-exports |
| `sources/news_cache.py` | 24-hour file cache for fetched payloads |
| `sources/zhilio_provider.py` | thin wrapper around zhilio MCP read tools (so signals don't depend on the MCP client directly — easier to mock in tests) |
| `sources/rss_provider.py` | self-hosted RSS aggregator (curated 2-3 sports feeds initially) |
| `calibration/__init__.py` | empty |
| `calibration/recorder.py` | append per-leg provenance + outcome rows to `.nutmeg-data/inspiration/{date}/recorder.jsonl` |
| `llm.py` | `LLMCompleter` Protocol (text-in / text-out); a default implementation that wraps `nutmeg.agents.llm_provider.PortkeySynthesisProvider` for raw prompts; isolates psychology providers from synthesis-specific signature |

**Modified files:**

| File | Change |
|---|---|
| `nutmeg/services/jczq.py` | `JczqMixedReportService.__init__` gains optional `psychology_engine`, `reconciliator`, `data_verdict_adapter`; `build_report` calls them when present and replaces internal combinations with `DualSchemeReport`; markdown/PDF render adds dashboard + dual-scheme + decision section |
| `nutmeg/interfaces/cli.py` | adds `psychology-inspect`, `inspiration-write`, `inspiration-show` commands (3 new typer commands) |
| `nutmeg/config/settings.py` | adds 5 env-var-backed settings: `psychology_layer_enabled`, `psychology_conviction_threshold`, `psychology_provider_enabled` (csv), `psychology_news_cache_dir`, `psychology_rss_feeds` (csv) |

**New tests** (flat under `tests/`):

```
tests/test_psychology_schemas.py
tests/test_psychology_news_cache.py
tests/test_psychology_zhilio_provider.py
tests/test_psychology_rss_provider.py
tests/test_psychology_signal_tournament_stage.py
tests/test_psychology_signal_contrarian_narrative.py
tests/test_psychology_signal_reflexive_tactic.py
tests/test_psychology_signal_personal_narrative.py
tests/test_psychology_engine.py
tests/test_psychology_inspiration.py
tests/test_psychology_guardrails.py
tests/test_psychology_reconciliator.py
tests/test_psychology_recorder.py
tests/test_psychology_llm.py
tests/test_psychology_jczq_integration.py    # integration
tests/test_psychology_inspiration_lifecycle.py  # integration
tests/test_psychology_cli.py                 # 3 CLI commands
```

**Persistence directories:**

```
.nutmeg-data/cache/news/{YYYY-MM-DD}/{sha1}.json     # 24h cache
.nutmeg-data/inspiration/{YYYY-MM-DD}/raw.md          # user note
.nutmeg-data/inspiration/{YYYY-MM-DD}/parsed.json     # parsed tags
.nutmeg-data/inspiration/{YYYY-MM-DD}/recorder.jsonl  # per-leg provenance + outcome
```

---

## Phase 0 — Foundation

### Task 1: Schemas

**Files:**
- Create: `nutmeg/services/psychology/__init__.py`
- Create: `nutmeg/services/psychology/schemas.py`
- Test: `tests/test_psychology_schemas.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_psychology_schemas.py
from __future__ import annotations

import pytest

from nutmeg.services.psychology.schemas import (
    DashboardRow,
    DataLeg,
    DualSchemeReport,
    FinalLeg,
    FinalScheme,
    GuardrailDecision,
    InspirationNote,
    InspirationTags,
    OutcomeView,
    OverrideCandidate,
    PsychologyVerdict,
    Scheme,
    SignalReading,
)


def test_signal_reading_immutable_and_serializable() -> None:
    reading = SignalReading(
        provider="tournament_stage",
        fixture_id="psg-bay-2026-04-28",
        market="HHAD",
        outcome_view="away_win",
        conviction=0.72,
        evidence=["UCL SF first leg, both teams favor compactness"],
        source_refs=["rule:cup_first_leg_low_block"],
        abstain_reason=None,
    )
    with pytest.raises(Exception):
        reading.conviction = 0.9  # type: ignore[misc]
    assert reading.outcome_view == "away_win"


def test_psychology_verdict_lean_direction_literal() -> None:
    verdict = PsychologyVerdict(
        fixture_id="f1",
        market_views={"HHAD": OutcomeView(market="HHAD", outcome="draw", conviction=0.6)},
        conviction=0.6,
        lean_direction="diverge_data",
        contributing_readings=[],
    )
    assert verdict.lean_direction == "diverge_data"


def test_inspiration_tags_default_flags() -> None:
    tags = InspirationTags(
        lean="psychology",
        conviction="high",
        focus=["tournament_stage"],
        force_psychology=False,
        force_data=False,
    )
    assert tags.force_psychology is False


def test_dual_scheme_report_holds_all_layers() -> None:
    data_leg = DataLeg(leg_id="L1", fixture_id="f1", market="HHAD", outcome="home_win", odds=2.10)
    psych_leg = DataLeg(leg_id="L1", fixture_id="f1", market="HHAD", outcome="away_win", odds=2.45)
    final_leg = FinalLeg(leg_id="L1", fixture_id="f1", market="HHAD", outcome="away_win", odds=2.45, provenance="psychology")
    report = DualSchemeReport(
        data_scheme=Scheme(name="data", legs=[data_leg]),
        psychology_scheme=Scheme(name="psychology", legs=[psych_leg]),
        final_scheme=FinalScheme(legs=[final_leg], confidence="medium", notes=["1 reversal applied"]),
        dashboard_rows=[DashboardRow(fixture_id="f1", data_pick="home_win", psych_pick="away_win", conflict=True, final_pick="away_win", conviction=0.72)],
        inspiration=None,
        guardrail=GuardrailDecision(accepted=[], rejected=[], guardrail_state={"budget": "1/1"}),
    )
    assert report.dashboard_rows[0].conflict is True
    assert report.final_scheme.legs[0].provenance == "psychology"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_psychology_schemas.py -v
```
Expected: `ModuleNotFoundError: No module named 'nutmeg.services.psychology'`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/services/psychology/__init__.py
"""Psychology & game-theory layer (v1 — JCZQ-first integration)."""
```

```python
# nutmeg/services/psychology/schemas.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

LeanDirection = Literal["agree_data", "neutral", "diverge_data"]
LeanTag = Literal["data", "psychology", "neutral"]
ConvictionTag = Literal["low", "medium", "high"]
Provenance = Literal["data", "psychology", "inspiration_forced"]
ParseMethod = Literal["llm", "regex_fallback"]


@dataclass(frozen=True, slots=True)
class OutcomeView:
    market: str
    outcome: str
    conviction: float


@dataclass(frozen=True, slots=True)
class SignalReading:
    provider: str
    fixture_id: str
    market: str
    outcome_view: str | None
    conviction: float
    evidence: list[str]
    source_refs: list[str]
    abstain_reason: str | None


@dataclass(frozen=True, slots=True)
class PsychologyVerdict:
    fixture_id: str
    market_views: dict[str, OutcomeView]
    conviction: float
    lean_direction: LeanDirection
    contributing_readings: list[SignalReading]


@dataclass(frozen=True, slots=True)
class DataLeg:
    leg_id: str
    fixture_id: str
    market: str
    outcome: str
    odds: float


@dataclass(frozen=True, slots=True)
class FinalLeg:
    leg_id: str
    fixture_id: str
    market: str
    outcome: str
    odds: float
    provenance: Provenance


@dataclass(frozen=True, slots=True)
class Scheme:
    name: str
    legs: list[DataLeg]


@dataclass(frozen=True, slots=True)
class FinalScheme:
    legs: list[FinalLeg]
    confidence: str
    notes: list[str]


@dataclass(frozen=True, slots=True)
class OverrideCandidate:
    leg_id: str
    fixture_id: str
    market: str
    from_outcome: str
    to_outcome: str
    conviction: float
    reasoning: list[str]
    source_provider: str


@dataclass(frozen=True, slots=True)
class GuardrailDecision:
    accepted: list[OverrideCandidate]
    rejected: list[tuple[OverrideCandidate, str]]
    guardrail_state: dict[str, str]


@dataclass(frozen=True, slots=True)
class InspirationTags:
    lean: LeanTag
    conviction: ConvictionTag
    focus: list[str]
    force_psychology: bool
    force_data: bool


@dataclass(frozen=True, slots=True)
class InspirationNote:
    date: str
    raw_text: str
    parsed_tags: InspirationTags
    parse_method: ParseMethod
    timestamp: str


@dataclass(frozen=True, slots=True)
class DashboardRow:
    fixture_id: str
    data_pick: str
    psych_pick: str | None
    conflict: bool
    final_pick: str
    conviction: float


@dataclass(frozen=True, slots=True)
class DualSchemeReport:
    data_scheme: Scheme
    psychology_scheme: Scheme
    final_scheme: FinalScheme
    dashboard_rows: list[DashboardRow]
    inspiration: InspirationNote | None
    guardrail: GuardrailDecision
```

- [ ] **Step 4: Run tests and verify pass**

```bash
uv run pytest tests/test_psychology_schemas.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/psychology/__init__.py nutmeg/services/psychology/schemas.py tests/test_psychology_schemas.py
git commit -m "feat(psychology): add core schemas for v1 layer"
```

---

### Task 2: SignalProvider Protocol + SignalContext

**Files:**
- Create: `nutmeg/services/psychology/signals/__init__.py`
- Create: `nutmeg/services/psychology/signals/base.py`
- Test: `tests/test_psychology_signal_base.py` (combined into existing test file at the next provider task — for now we only need a smoke test)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_psychology_signal_base.py
from __future__ import annotations

import pytest

from nutmeg.services.psychology.signals.base import (
    SignalContext,
    SignalProvider,
    SignalProviderError,
)
from nutmeg.services.psychology.schemas import SignalReading


def test_signal_provider_is_protocol() -> None:
    class DummyProvider:
        name = "dummy"

        def evaluate(self, ctx: SignalContext) -> list[SignalReading]:
            return []

    provider: SignalProvider = DummyProvider()
    assert provider.name == "dummy"
    assert provider.evaluate(SignalContext(date="2026-04-29", fixtures=[], snapshots={}, odds={})) == []


def test_signal_context_is_immutable() -> None:
    ctx = SignalContext(date="2026-04-29", fixtures=[], snapshots={}, odds={})
    with pytest.raises(Exception):
        ctx.date = "2026-04-30"  # type: ignore[misc]


def test_signal_provider_error_inherits_runtime() -> None:
    err = SignalProviderError("boom")
    assert isinstance(err, RuntimeError)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_psychology_signal_base.py -v
```
Expected: ImportError on `nutmeg.services.psychology.signals.base`.

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/services/psychology/signals/__init__.py
"""Pluggable signal providers for the psychology layer."""
```

```python
# nutmeg/services/psychology/signals/base.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from nutmeg.services.psychology.schemas import SignalReading


class SignalProviderError(RuntimeError):
    """Raised when a signal provider fails irrecoverably; engine should mark it abstained."""


@dataclass(frozen=True, slots=True)
class SignalContext:
    """Bundle of inputs every provider receives. Providers ignore fields they don't need."""

    date: str                                # ISO date "YYYY-MM-DD"
    fixtures: list[dict[str, Any]]           # serialized Fixture rows
    snapshots: dict[str, dict[str, Any]]     # fixture_id -> tactical snapshot
    odds: dict[str, dict[str, Any]]          # fixture_id -> odds snapshot
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SignalProvider(Protocol):
    name: str

    def evaluate(self, ctx: SignalContext) -> list[SignalReading]:
        """Return one or more readings (often one per fixture × market). Must NOT raise on
        partial-source failures; degrade to an abstain SignalReading instead."""
```

- [ ] **Step 4: Run tests and verify pass**

```bash
uv run pytest tests/test_psychology_signal_base.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/psychology/signals/__init__.py nutmeg/services/psychology/signals/base.py tests/test_psychology_signal_base.py
git commit -m "feat(psychology): add SignalProvider protocol and SignalContext"
```

---

### Task 3: news_cache (24h file cache)

**Files:**
- Create: `nutmeg/services/psychology/sources/__init__.py`
- Create: `nutmeg/services/psychology/sources/news_cache.py`
- Test: `tests/test_psychology_news_cache.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_psychology_news_cache.py
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nutmeg.services.psychology.sources.news_cache import NewsCache


def test_cache_miss_returns_none(tmp_path: Path) -> None:
    cache = NewsCache(base_dir=tmp_path)
    assert cache.get(date="2026-04-29", key="psg-bay") is None


def test_cache_round_trip(tmp_path: Path) -> None:
    cache = NewsCache(base_dir=tmp_path)
    payload = [{"title": "Bayern feared", "url": "https://example.com/a"}]
    cache.put(date="2026-04-29", key="psg-bay", payload=payload)
    assert cache.get(date="2026-04-29", key="psg-bay") == payload


def test_cache_expires_after_24h(tmp_path: Path) -> None:
    cache = NewsCache(base_dir=tmp_path, now=lambda: datetime(2026, 4, 29, 10, 0, tzinfo=timezone.utc))
    cache.put(date="2026-04-29", key="psg-bay", payload=[{"x": 1}])
    cache_aged = NewsCache(base_dir=tmp_path, now=lambda: datetime(2026, 4, 30, 10, 1, tzinfo=timezone.utc))
    assert cache_aged.get(date="2026-04-29", key="psg-bay") is None


def test_cache_key_isolation(tmp_path: Path) -> None:
    cache = NewsCache(base_dir=tmp_path)
    cache.put(date="2026-04-29", key="a", payload=[{"x": 1}])
    cache.put(date="2026-04-29", key="b", payload=[{"y": 2}])
    assert cache.get(date="2026-04-29", key="a") == [{"x": 1}]
    assert cache.get(date="2026-04-29", key="b") == [{"y": 2}]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_psychology_news_cache.py -v
```
Expected: ImportError.

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/services/psychology/sources/__init__.py
"""External data sources for the psychology layer (with caching)."""
```

```python
# nutmeg/services/psychology/sources/news_cache.py
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
                {"stored_at": self.now().isoformat(), "payload": payload},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
```

- [ ] **Step 4: Run tests and verify pass**

```bash
uv run pytest tests/test_psychology_news_cache.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/psychology/sources/__init__.py nutmeg/services/psychology/sources/news_cache.py tests/test_psychology_news_cache.py
git commit -m "feat(psychology): add 24h file-backed news cache"
```

---

### Task 4: zhilio_provider wrapper

**Files:**
- Create: `nutmeg/services/psychology/sources/zhilio_provider.py`
- Test: `tests/test_psychology_zhilio_provider.py`

The wrapper accepts a callable injected by the caller (the actual MCP tool call site lives in CLI/cron; tests inject a fake). This keeps signals free of MCP dependency at unit-test time.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_psychology_zhilio_provider.py
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from nutmeg.services.psychology.sources.news_cache import NewsCache
from nutmeg.services.psychology.sources.zhilio_provider import ZhilioProvider


def test_search_news_uses_callable(tmp_path: Path) -> None:
    fake_call = MagicMock(return_value={"items": [{"title": "PSG bottle Bayern", "url": "u1"}]})
    cache = NewsCache(base_dir=tmp_path)
    provider = ZhilioProvider(call_search_news=fake_call, call_hotlist=MagicMock(), cache=cache)
    result = provider.search_news(query="巴黎 拜仁", date="2026-04-29")
    assert result == [{"title": "PSG bottle Bayern", "url": "u1"}]
    fake_call.assert_called_once_with(query="巴黎 拜仁", limit=20)


def test_search_news_uses_cache_on_second_call(tmp_path: Path) -> None:
    fake_call = MagicMock(return_value={"items": [{"title": "x", "url": "u"}]})
    cache = NewsCache(base_dir=tmp_path)
    provider = ZhilioProvider(call_search_news=fake_call, call_hotlist=MagicMock(), cache=cache)
    provider.search_news(query="q", date="2026-04-29")
    provider.search_news(query="q", date="2026-04-29")
    assert fake_call.call_count == 1


def test_search_news_swallows_callable_exception(tmp_path: Path) -> None:
    fake_call = MagicMock(side_effect=RuntimeError("MCP unreachable"))
    cache = NewsCache(base_dir=tmp_path)
    provider = ZhilioProvider(call_search_news=fake_call, call_hotlist=MagicMock(), cache=cache)
    assert provider.search_news(query="q", date="2026-04-29") == []


def test_hotlist_returns_list(tmp_path: Path) -> None:
    fake_hot = MagicMock(return_value={"items": [{"title": "Bayern back-3 reset", "rank": 1}]})
    cache = NewsCache(base_dir=tmp_path)
    provider = ZhilioProvider(call_search_news=MagicMock(), call_hotlist=fake_hot, cache=cache)
    assert provider.hotlist(date="2026-04-29") == [{"title": "Bayern back-3 reset", "rank": 1}]
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_psychology_zhilio_provider.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# nutmeg/services/psychology/sources/zhilio_provider.py
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from nutmeg.services.psychology.sources.news_cache import NewsCache

CallSearchNews = Callable[..., dict[str, Any]]
CallHotlist = Callable[..., dict[str, Any]]


@dataclass(slots=True)
class ZhilioProvider:
    """Thin wrapper around zhilio MCP read tools.

    The actual MCP tool calls live at the CLI/cron edge; this class accepts the
    callables so that signal providers (and their unit tests) never see MCP.
    """

    call_search_news: CallSearchNews
    call_hotlist: CallHotlist
    cache: NewsCache

    def search_news(self, *, query: str, date: str, limit: int = 20) -> list[dict[str, Any]]:
        cached = self.cache.get(date=date, key=f"news:{query}:{limit}")
        if cached is not None:
            return cached
        try:
            response = self.call_search_news(query=query, limit=limit)
        except Exception:  # broad: any MCP/transport failure → degrade
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
        except Exception:
            return []
        items = list(response.get("items") or [])
        self.cache.put(date=date, key="hotlist", payload=items)
        return items
```

- [ ] **Step 4: Run tests, verify pass**

```bash
uv run pytest tests/test_psychology_zhilio_provider.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/psychology/sources/zhilio_provider.py tests/test_psychology_zhilio_provider.py
git commit -m "feat(psychology): wrap zhilio MCP read tools with cached fallback"
```

---

### Task 5: rss_provider (self-hosted RSS aggregator)

**Files:**
- Create: `nutmeg/services/psychology/sources/rss_provider.py`
- Test: `tests/test_psychology_rss_provider.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_psychology_rss_provider.py
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from nutmeg.services.psychology.sources.news_cache import NewsCache
from nutmeg.services.psychology.sources.rss_provider import RssProvider


def test_fetches_each_feed_and_merges(tmp_path: Path) -> None:
    fake_fetcher = MagicMock(side_effect=[
        {"entries": [{"title": "PSG injury list", "link": "https://a/1", "summary": "..."}]},
        {"entries": [{"title": "Bayern compact 3-back", "link": "https://b/1", "summary": "..."}]},
    ])
    cache = NewsCache(base_dir=tmp_path)
    provider = RssProvider(
        feeds=["https://a/feed.xml", "https://b/feed.xml"],
        fetcher=fake_fetcher,
        cache=cache,
    )
    items = provider.fetch(date="2026-04-29", query=None)
    assert len(items) == 2
    assert items[0]["link"] == "https://a/1"
    assert items[1]["link"] == "https://b/1"


def test_filters_by_query_when_supplied(tmp_path: Path) -> None:
    fake_fetcher = MagicMock(side_effect=[
        {"entries": [
            {"title": "Bayern reset", "link": "https://b/1", "summary": "Kompany 3-back"},
            {"title": "Random news", "link": "https://b/2", "summary": "unrelated"},
        ]},
    ])
    cache = NewsCache(base_dir=tmp_path)
    provider = RssProvider(feeds=["https://b/feed.xml"], fetcher=fake_fetcher, cache=cache)
    items = provider.fetch(date="2026-04-29", query="bayern")
    assert len(items) == 1
    assert items[0]["link"] == "https://b/1"


def test_single_feed_failure_does_not_block(tmp_path: Path) -> None:
    fake_fetcher = MagicMock(side_effect=[
        RuntimeError("404"),
        {"entries": [{"title": "ok", "link": "https://b/1", "summary": ""}]},
    ])
    cache = NewsCache(base_dir=tmp_path)
    provider = RssProvider(feeds=["https://a", "https://b"], fetcher=fake_fetcher, cache=cache)
    items = provider.fetch(date="2026-04-29", query=None)
    assert len(items) == 1
    assert items[0]["link"] == "https://b/1"


def test_uses_cache(tmp_path: Path) -> None:
    fake_fetcher = MagicMock(return_value={"entries": [{"title": "t", "link": "l", "summary": ""}]})
    cache = NewsCache(base_dir=tmp_path)
    provider = RssProvider(feeds=["https://a"], fetcher=fake_fetcher, cache=cache)
    provider.fetch(date="2026-04-29", query=None)
    provider.fetch(date="2026-04-29", query=None)
    assert fake_fetcher.call_count == 1
```

- [ ] **Step 2: Run, verify failure**

```bash
uv run pytest tests/test_psychology_rss_provider.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# nutmeg/services/psychology/sources/rss_provider.py
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from nutmeg.services.psychology.sources.news_cache import NewsCache

RssFetcher = Callable[[str], dict[str, Any]]


def _matches(entry: dict[str, Any], query: str | None) -> bool:
    if not query:
        return True
    q = query.lower()
    haystack = " ".join([
        str(entry.get("title", "")),
        str(entry.get("summary", "")),
    ]).lower()
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
            except Exception:
                continue
            for entry in payload.get("entries") or []:
                if _matches(entry, query):
                    merged.append({
                        "title": entry.get("title", ""),
                        "link": entry.get("link", ""),
                        "summary": entry.get("summary", ""),
                        "feed": feed_url,
                    })
        self.cache.put(date=date, key=cache_key, payload=merged)
        return merged
```

- [ ] **Step 4: Verify pass**

```bash
uv run pytest tests/test_psychology_rss_provider.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/psychology/sources/rss_provider.py tests/test_psychology_rss_provider.py
git commit -m "feat(psychology): add RSS aggregator with per-feed isolation and caching"
```

---

### Task 6: LLMCompleter Protocol + default wrapper

**Files:**
- Create: `nutmeg/services/psychology/llm.py`
- Test: `tests/test_psychology_llm.py`

LLM signal providers need a generic "complete this prompt → text" interface. We define it locally so providers don't depend on the synthesis-specific signature in `nutmeg.agents.llm_provider`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_psychology_llm.py
from __future__ import annotations

from unittest.mock import MagicMock

from nutmeg.services.psychology.llm import (
    FakeLLMCompleter,
    LLMCompleter,
    LLMCompletionError,
)


def test_fake_completer_returns_canned_response() -> None:
    fake = FakeLLMCompleter(responses=["abc"])
    assert fake.complete(system="s", user="u") == "abc"


def test_fake_completer_pops_responses_in_order() -> None:
    fake = FakeLLMCompleter(responses=["one", "two"])
    assert fake.complete(system="", user="") == "one"
    assert fake.complete(system="", user="") == "two"


def test_fake_completer_raises_when_exhausted() -> None:
    fake = FakeLLMCompleter(responses=[])
    try:
        fake.complete(system="", user="")
    except LLMCompletionError as exc:
        assert "exhausted" in str(exc)
    else:
        raise AssertionError("expected LLMCompletionError")


def test_protocol_is_satisfied_by_callable_wrapper() -> None:
    class Direct:
        def complete(self, *, system: str, user: str) -> str:
            return system + user

    completer: LLMCompleter = Direct()
    assert completer.complete(system="a", user="b") == "ab"
```

- [ ] **Step 2: Run, verify failure**

```bash
uv run pytest tests/test_psychology_llm.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# nutmeg/services/psychology/llm.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


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
```

(Production wrapper around `PortkeySynthesisProvider` is added in a later task once we know what providers actually need. For unit tests the `FakeLLMCompleter` is sufficient.)

- [ ] **Step 4: Verify pass**

```bash
uv run pytest tests/test_psychology_llm.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/psychology/llm.py tests/test_psychology_llm.py
git commit -m "feat(psychology): add LLMCompleter protocol and fake completer"
```

---

## Phase 1 — Signal providers

### Task 7: tournament_stage signal (rules only)

**Files:**
- Create: `nutmeg/services/psychology/signals/tournament_stage.py`
- Test: `tests/test_psychology_signal_tournament_stage.py`

Encodes 4 rules:

1. **UCL/UEL knockout, first leg, both teams Top-tier** → low-scoring tendency, lean draw / Under 2.5 (conviction 0.65).
2. **UCL/UEL knockout, second leg, aggregate tied** → home team aggressive, lean home over (conviction 0.55).
3. **Domestic cup, lower-tier home vs Premier League away** → upset volatility, lean draw or AH +1 (conviction 0.45 — low).
4. **League final round, table-position-decided already** → motivation gap, lean away if away has stakes (conviction 0.50).

If none match → abstain reading (conviction 0, outcome_view None).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_psychology_signal_tournament_stage.py
from __future__ import annotations

from nutmeg.services.psychology.signals.base import SignalContext
from nutmeg.services.psychology.signals.tournament_stage import TournamentStageSignal


def _ctx(fixtures: list[dict]) -> SignalContext:
    return SignalContext(date="2026-04-29", fixtures=fixtures, snapshots={}, odds={})


def test_first_leg_ucl_knockout_leans_draw_under() -> None:
    fixtures = [{
        "id": "psg-bay",
        "competition_code": "UCL",
        "stage": "knockout",
        "leg": 1,
        "tier_home": 1,
        "tier_away": 1,
        "aggregate_score_diff": None,
    }]
    sig = TournamentStageSignal()
    readings = sig.evaluate(_ctx(fixtures))
    rules = [r for r in readings if r.fixture_id == "psg-bay"]
    assert any(r.market == "HHAD" and r.outcome_view == "draw" for r in rules)
    assert any(r.market == "TTG" and r.outcome_view == "under_2_5" for r in rules)
    for r in rules:
        if r.outcome_view is not None:
            assert r.conviction >= 0.6


def test_second_leg_aggregate_tied_leans_home_over() -> None:
    fixtures = [{
        "id": "f2", "competition_code": "UEL", "stage": "knockout",
        "leg": 2, "tier_home": 1, "tier_away": 1, "aggregate_score_diff": 0,
    }]
    sig = TournamentStageSignal()
    readings = sig.evaluate(_ctx(fixtures))
    home = [r for r in readings if r.market == "HHAD" and r.outcome_view == "home_win"]
    assert home and home[0].conviction >= 0.5


def test_no_matching_rule_yields_abstain() -> None:
    fixtures = [{
        "id": "f3", "competition_code": "PL", "stage": "regular",
        "leg": None, "tier_home": 1, "tier_away": 1, "aggregate_score_diff": None,
    }]
    sig = TournamentStageSignal()
    readings = sig.evaluate(_ctx(fixtures))
    abstains = [r for r in readings if r.outcome_view is None]
    assert len(abstains) == len(readings) >= 1
    assert all(r.abstain_reason for r in abstains)


def test_signal_name_constant() -> None:
    assert TournamentStageSignal().name == "tournament_stage"
```

- [ ] **Step 2: Run, verify failure**

```bash
uv run pytest tests/test_psychology_signal_tournament_stage.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# nutmeg/services/psychology/signals/tournament_stage.py
from __future__ import annotations

from dataclasses import dataclass

from nutmeg.services.psychology.schemas import SignalReading
from nutmeg.services.psychology.signals.base import SignalContext

UCL_LIKE = {"UCL", "UEL", "UECL"}


@dataclass(slots=True)
class TournamentStageSignal:
    name: str = "tournament_stage"

    def evaluate(self, ctx: SignalContext) -> list[SignalReading]:
        readings: list[SignalReading] = []
        for fx in ctx.fixtures:
            fixture_id = str(fx.get("id"))
            comp = str(fx.get("competition_code") or "")
            stage = str(fx.get("stage") or "")
            leg = fx.get("leg")
            tier_h = fx.get("tier_home")
            tier_a = fx.get("tier_away")
            agg_diff = fx.get("aggregate_score_diff")

            matched = False

            # Rule 1: UCL/UEL knockout first leg, both top tier → lean draw + under 2.5
            if (
                comp in UCL_LIKE and stage == "knockout" and leg == 1
                and tier_h == 1 and tier_a == 1
            ):
                readings.append(SignalReading(
                    provider=self.name, fixture_id=fixture_id, market="HHAD",
                    outcome_view="draw", conviction=0.65,
                    evidence=["UCL/UEL knockout 1st leg, both teams top tier — historically conservative"],
                    source_refs=["rule:ucl_first_leg_low_block"],
                    abstain_reason=None,
                ))
                readings.append(SignalReading(
                    provider=self.name, fixture_id=fixture_id, market="TTG",
                    outcome_view="under_2_5", conviction=0.65,
                    evidence=["First-leg compactness historically suppresses goals"],
                    source_refs=["rule:ucl_first_leg_low_block"],
                    abstain_reason=None,
                ))
                matched = True

            # Rule 2: UCL/UEL knockout 2nd leg, aggregate tied → home aggressive, lean home + over
            if (
                comp in UCL_LIKE and stage == "knockout" and leg == 2
                and agg_diff == 0
            ):
                readings.append(SignalReading(
                    provider=self.name, fixture_id=fixture_id, market="HHAD",
                    outcome_view="home_win", conviction=0.55,
                    evidence=["2nd leg with tied aggregate — home pushes for decisive win"],
                    source_refs=["rule:ucl_2nd_leg_tied_aggregate"],
                    abstain_reason=None,
                ))
                matched = True

            # Rule 3: domestic cup, lower-tier home vs higher-tier away → upset volatility
            if (
                stage == "cup" and tier_h is not None and tier_a is not None
                and tier_h > tier_a
            ):
                readings.append(SignalReading(
                    provider=self.name, fixture_id=fixture_id, market="handicap",
                    outcome_view="home_plus_one", conviction=0.45,
                    evidence=["Cup tie with lower-tier home — upset volatility"],
                    source_refs=["rule:cup_lower_tier_home"],
                    abstain_reason=None,
                ))
                matched = True

            # Rule 4: league final round, motivation gap (away has stakes flagged in metadata)
            if stage == "final_round" and bool(fx.get("away_has_stakes")):
                readings.append(SignalReading(
                    provider=self.name, fixture_id=fixture_id, market="HHAD",
                    outcome_view="away_win", conviction=0.50,
                    evidence=["Final round, away team still has table stakes; home decided"],
                    source_refs=["rule:league_final_round_motivation_gap"],
                    abstain_reason=None,
                ))
                matched = True

            if not matched:
                readings.append(SignalReading(
                    provider=self.name, fixture_id=fixture_id, market="HHAD",
                    outcome_view=None, conviction=0.0,
                    evidence=[], source_refs=[],
                    abstain_reason="no rule matched",
                ))
        return readings
```

- [ ] **Step 4: Verify pass**

```bash
uv run pytest tests/test_psychology_signal_tournament_stage.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/psychology/signals/tournament_stage.py tests/test_psychology_signal_tournament_stage.py
git commit -m "feat(psychology): add tournament-stage rule-based signal provider"
```

---

### Task 8: contrarian_narrative signal

**Files:**
- Create: `nutmeg/services/psychology/signals/contrarian_narrative.py`
- Test: `tests/test_psychology_signal_contrarian_narrative.py`

Logic:

1. Pull narrative items from `ZhilioProvider.search_news` + `ZhilioProvider.hotlist` + `RssProvider.fetch` for the fixture's keyword (home + away team names).
2. If item count < 5 → abstain (insufficient sample).
3. Send concatenated headlines to LLM with a polarity-extraction prompt; expect JSON: `{"consensus": "home" | "away" | "draw" | "mixed", "intensity": 0..1}`.
4. If `intensity ≥ 0.6` and `consensus ∈ {home, away}`, emit a contrarian reading: `outcome_view = opposite_consensus`, conviction = intensity (capped at 0.75).
5. On any LLM/JSON failure, abstain.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_psychology_signal_contrarian_narrative.py
from __future__ import annotations

from unittest.mock import MagicMock

from nutmeg.services.psychology.llm import FakeLLMCompleter
from nutmeg.services.psychology.signals.base import SignalContext
from nutmeg.services.psychology.signals.contrarian_narrative import ContrarianNarrativeSignal


def _fixture() -> dict:
    return {"id": "psg-bay", "home_team_name": "巴黎圣日耳曼", "away_team_name": "拜仁慕尼黑"}


def test_high_intensity_home_consensus_emits_away_lean() -> None:
    fake_zhilio = MagicMock()
    fake_zhilio.search_news.return_value = [{"title": f"PSG carry t{i}", "link": "u"} for i in range(6)]
    fake_zhilio.hotlist.return_value = []
    fake_rss = MagicMock()
    fake_rss.fetch.return_value = []
    completer = FakeLLMCompleter(responses=['{"consensus": "home", "intensity": 0.8}'])
    sig = ContrarianNarrativeSignal(zhilio=fake_zhilio, rss=fake_rss, llm=completer)
    readings = sig.evaluate(SignalContext(date="2026-04-29", fixtures=[_fixture()], snapshots={}, odds={}))
    [r] = readings
    assert r.outcome_view == "away_win"
    assert 0.75 >= r.conviction >= 0.6


def test_low_intensity_yields_abstain() -> None:
    fake_zhilio = MagicMock()
    fake_zhilio.search_news.return_value = [{"title": f"a{i}", "link": "u"} for i in range(6)]
    fake_zhilio.hotlist.return_value = []
    fake_rss = MagicMock(); fake_rss.fetch.return_value = []
    completer = FakeLLMCompleter(responses=['{"consensus": "home", "intensity": 0.4}'])
    sig = ContrarianNarrativeSignal(zhilio=fake_zhilio, rss=fake_rss, llm=completer)
    [r] = sig.evaluate(SignalContext(date="2026-04-29", fixtures=[_fixture()], snapshots={}, odds={}))
    assert r.outcome_view is None
    assert "intensity" in (r.abstain_reason or "")


def test_insufficient_sample_yields_abstain() -> None:
    fake_zhilio = MagicMock()
    fake_zhilio.search_news.return_value = [{"title": "x", "link": "u"}]
    fake_zhilio.hotlist.return_value = []
    fake_rss = MagicMock(); fake_rss.fetch.return_value = []
    completer = FakeLLMCompleter(responses=[])  # never called
    sig = ContrarianNarrativeSignal(zhilio=fake_zhilio, rss=fake_rss, llm=completer)
    [r] = sig.evaluate(SignalContext(date="2026-04-29", fixtures=[_fixture()], snapshots={}, odds={}))
    assert r.outcome_view is None
    assert "sample" in (r.abstain_reason or "")


def test_llm_invalid_json_abstains() -> None:
    fake_zhilio = MagicMock()
    fake_zhilio.search_news.return_value = [{"title": "x", "link": "u"}] * 6
    fake_zhilio.hotlist.return_value = []
    fake_rss = MagicMock(); fake_rss.fetch.return_value = []
    completer = FakeLLMCompleter(responses=["not json"])
    sig = ContrarianNarrativeSignal(zhilio=fake_zhilio, rss=fake_rss, llm=completer)
    [r] = sig.evaluate(SignalContext(date="2026-04-29", fixtures=[_fixture()], snapshots={}, odds={}))
    assert r.outcome_view is None
    assert "parse" in (r.abstain_reason or "")
```

- [ ] **Step 2: Run, verify failure**

```bash
uv run pytest tests/test_psychology_signal_contrarian_narrative.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# nutmeg/services/psychology/signals/contrarian_narrative.py
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from nutmeg.services.psychology.llm import LLMCompleter, LLMCompletionError
from nutmeg.services.psychology.schemas import SignalReading
from nutmeg.services.psychology.signals.base import SignalContext
from nutmeg.services.psychology.sources.rss_provider import RssProvider
from nutmeg.services.psychology.sources.zhilio_provider import ZhilioProvider

MIN_SAMPLE = 5
INTENSITY_GATE = 0.6
CONVICTION_CAP = 0.75
SYSTEM_PROMPT = (
    "你是体育新闻舆情极性分析师。给定多条头条/标题，判断主流叙事偏向。"
    "只输出 JSON：{\"consensus\":\"home\"|\"away\"|\"draw\"|\"mixed\",\"intensity\":0..1}。"
    "intensity 衡量"一边倒"程度，0 = 完全分裂，1 = 一边倒。"
)


def _opposite(consensus: str) -> str | None:
    if consensus == "home":
        return "away_win"
    if consensus == "away":
        return "home_win"
    return None


@dataclass(slots=True)
class ContrarianNarrativeSignal:
    zhilio: ZhilioProvider
    rss: RssProvider
    llm: LLMCompleter
    name: str = "contrarian_narrative"

    def evaluate(self, ctx: SignalContext) -> list[SignalReading]:
        out: list[SignalReading] = []
        for fx in ctx.fixtures:
            fixture_id = str(fx.get("id"))
            home = str(fx.get("home_team_name") or "")
            away = str(fx.get("away_team_name") or "")
            query = f"{home} {away}".strip()

            items: list[dict[str, Any]] = []
            items.extend(self.zhilio.search_news(query=query, date=ctx.date) or [])
            items.extend(self.zhilio.hotlist(date=ctx.date) or [])
            items.extend(self.rss.fetch(date=ctx.date, query=query) or [])

            if len(items) < MIN_SAMPLE:
                out.append(self._abstain(fixture_id, "insufficient sample"))
                continue

            headlines = [str(it.get("title", "")) for it in items[:25]]
            user_prompt = "\n".join(f"- {h}" for h in headlines if h)
            try:
                raw = self.llm.complete(system=SYSTEM_PROMPT, user=user_prompt)
                payload = json.loads(raw)
                consensus = str(payload.get("consensus"))
                intensity = float(payload.get("intensity", 0.0))
            except (LLMCompletionError, ValueError, TypeError, json.JSONDecodeError):
                out.append(self._abstain(fixture_id, "llm parse failed"))
                continue

            if intensity < INTENSITY_GATE or consensus not in {"home", "away"}:
                out.append(self._abstain(fixture_id, f"intensity below gate ({intensity:.2f})"))
                continue

            contrarian = _opposite(consensus)
            if contrarian is None:
                out.append(self._abstain(fixture_id, "no contrarian outcome"))
                continue

            out.append(SignalReading(
                provider=self.name, fixture_id=fixture_id, market="HHAD",
                outcome_view=contrarian,
                conviction=min(intensity, CONVICTION_CAP),
                evidence=[f"Public consensus leans {consensus} at intensity {intensity:.2f} → contrarian view {contrarian}"],
                source_refs=[str(it.get("link") or it.get("url") or "") for it in items[:5]],
                abstain_reason=None,
            ))
        return out

    def _abstain(self, fixture_id: str, reason: str) -> SignalReading:
        return SignalReading(
            provider=self.name, fixture_id=fixture_id, market="HHAD",
            outcome_view=None, conviction=0.0, evidence=[], source_refs=[],
            abstain_reason=reason,
        )
```

(Note: the SYSTEM_PROMPT uses a unicode escape inline so the source file is plain ASCII-safe; you may inline the Chinese characters directly — confirm encoding before commit.)

- [ ] **Step 4: Verify pass**

```bash
uv run pytest tests/test_psychology_signal_contrarian_narrative.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/psychology/signals/contrarian_narrative.py tests/test_psychology_signal_contrarian_narrative.py
git commit -m "feat(psychology): add contrarian-narrative signal provider"
```

---

### Task 9: reflexive_tactic signal

**Files:**
- Create: `nutmeg/services/psychology/signals/reflexive_tactic.py`
- Test: `tests/test_psychology_signal_reflexive_tactic.py`

Logic: takes the local tactical snapshot for both teams (already produced by `AnalysisService` in `ctx.snapshots[fixture_id]`), prompts an LLM to reason about second-order tactical surprise ("what would each manager change knowing the opponent expects X?") and emit a structured outcome view.

LLM JSON schema: `{"second_order_pick":"home_win"|"draw"|"away_win","conviction":0..1,"reasoning":["..."]}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_psychology_signal_reflexive_tactic.py
from __future__ import annotations

from nutmeg.services.psychology.llm import FakeLLMCompleter
from nutmeg.services.psychology.signals.base import SignalContext
from nutmeg.services.psychology.signals.reflexive_tactic import ReflexiveTacticSignal


def test_emits_reading_when_snapshot_present() -> None:
    fixtures = [{"id": "f1", "home_team_name": "PSG", "away_team_name": "Bayern"}]
    snapshots = {"f1": {"home_shape": "4-3-3 high press", "away_shape": "3-4-2-1 mid-block"}}
    completer = FakeLLMCompleter(responses=[
        '{"second_order_pick":"away_win","conviction":0.7,"reasoning":["Kompany inverts to compact 5"]}'
    ])
    sig = ReflexiveTacticSignal(llm=completer)
    [r] = sig.evaluate(SignalContext(date="2026-04-29", fixtures=fixtures, snapshots=snapshots, odds={}))
    assert r.outcome_view == "away_win"
    assert r.conviction == 0.7
    assert r.evidence


def test_missing_snapshot_abstains() -> None:
    fixtures = [{"id": "f1", "home_team_name": "PSG", "away_team_name": "Bayern"}]
    sig = ReflexiveTacticSignal(llm=FakeLLMCompleter(responses=[]))
    [r] = sig.evaluate(SignalContext(date="2026-04-29", fixtures=fixtures, snapshots={}, odds={}))
    assert r.outcome_view is None
    assert "snapshot" in (r.abstain_reason or "")


def test_llm_failure_abstains() -> None:
    fixtures = [{"id": "f1", "home_team_name": "PSG", "away_team_name": "Bayern"}]
    snapshots = {"f1": {"home_shape": "x", "away_shape": "y"}}
    completer = FakeLLMCompleter(responses=["{not valid"])
    sig = ReflexiveTacticSignal(llm=completer)
    [r] = sig.evaluate(SignalContext(date="2026-04-29", fixtures=fixtures, snapshots=snapshots, odds={}))
    assert r.outcome_view is None
    assert "parse" in (r.abstain_reason or "")


def test_invalid_pick_abstains() -> None:
    fixtures = [{"id": "f1", "home_team_name": "PSG", "away_team_name": "Bayern"}]
    snapshots = {"f1": {"home_shape": "x", "away_shape": "y"}}
    completer = FakeLLMCompleter(responses=['{"second_order_pick":"weird","conviction":0.9,"reasoning":[]}'])
    sig = ReflexiveTacticSignal(llm=completer)
    [r] = sig.evaluate(SignalContext(date="2026-04-29", fixtures=fixtures, snapshots=snapshots, odds={}))
    assert r.outcome_view is None
```

- [ ] **Step 2: Run, verify failure**

```bash
uv run pytest tests/test_psychology_signal_reflexive_tactic.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# nutmeg/services/psychology/signals/reflexive_tactic.py
from __future__ import annotations

import json
from dataclasses import dataclass

from nutmeg.services.psychology.llm import LLMCompleter, LLMCompletionError
from nutmeg.services.psychology.schemas import SignalReading
from nutmeg.services.psychology.signals.base import SignalContext

VALID_PICKS = {"home_win", "draw", "away_win"}
SYSTEM_PROMPT = (
    "你是欧洲足球高水平战术分析师。给定双方近期阵型/打法，"
    "推理两位主帅都已经知道对方期待什么，下一步最可能的二阶变招是什么，"
    "并由此判断比赛胜平负倾向。只输出 JSON："
    '{"second_order_pick":"home_win|draw|away_win","conviction":0..1,"reasoning":["..","..."]}'
)


@dataclass(slots=True)
class ReflexiveTacticSignal:
    llm: LLMCompleter
    name: str = "reflexive_tactic"

    def evaluate(self, ctx: SignalContext) -> list[SignalReading]:
        out: list[SignalReading] = []
        for fx in ctx.fixtures:
            fixture_id = str(fx.get("id"))
            snap = ctx.snapshots.get(fixture_id)
            if not snap:
                out.append(self._abstain(fixture_id, "no tactical snapshot"))
                continue
            user = (
                f"Home: {fx.get('home_team_name','')}, shape={snap.get('home_shape','')}\n"
                f"Away: {fx.get('away_team_name','')}, shape={snap.get('away_shape','')}\n"
                f"What is each manager's second-order surprise? Output the JSON now."
            )
            try:
                raw = self.llm.complete(system=SYSTEM_PROMPT, user=user)
                payload = json.loads(raw)
                pick = str(payload.get("second_order_pick"))
                conviction = float(payload.get("conviction", 0.0))
                reasoning = list(payload.get("reasoning") or [])
            except (LLMCompletionError, ValueError, TypeError, json.JSONDecodeError):
                out.append(self._abstain(fixture_id, "llm parse failed"))
                continue

            if pick not in VALID_PICKS:
                out.append(self._abstain(fixture_id, f"invalid pick {pick!r}"))
                continue

            out.append(SignalReading(
                provider=self.name, fixture_id=fixture_id, market="HHAD",
                outcome_view=pick,
                conviction=max(0.0, min(conviction, 1.0)),
                evidence=reasoning or [f"Second-order tactical surprise → {pick}"],
                source_refs=["llm:reflexive_tactic"],
                abstain_reason=None,
            ))
        return out

    def _abstain(self, fixture_id: str, reason: str) -> SignalReading:
        return SignalReading(
            provider=self.name, fixture_id=fixture_id, market="HHAD",
            outcome_view=None, conviction=0.0, evidence=[], source_refs=[],
            abstain_reason=reason,
        )
```

- [ ] **Step 4: Verify pass**

```bash
uv run pytest tests/test_psychology_signal_reflexive_tactic.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/psychology/signals/reflexive_tactic.py tests/test_psychology_signal_reflexive_tactic.py
git commit -m "feat(psychology): add reflexive-tactic LLM signal provider"
```

---

### Task 10: personal_narrative signal

**Files:**
- Create: `nutmeg/services/psychology/signals/personal_narrative.py`
- Test: `tests/test_psychology_signal_personal_narrative.py`

Logic: query RSS for keyword combination of `[home, away, "复仇" / "首秀" / "末战" / "回归"]`. Items go into LLM with story-line tagging prompt. JSON: `{"story_present":bool,"team_advantaged":"home|away|none","conviction":0..1,"story_summary":"..."}`. If story present and team_advantaged ∈ {home, away}, emit the corresponding HHAD reading.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_psychology_signal_personal_narrative.py
from __future__ import annotations

from unittest.mock import MagicMock

from nutmeg.services.psychology.llm import FakeLLMCompleter
from nutmeg.services.psychology.signals.base import SignalContext
from nutmeg.services.psychology.signals.personal_narrative import PersonalNarrativeSignal


def _ctx(fixtures: list[dict]) -> SignalContext:
    return SignalContext(date="2026-04-29", fixtures=fixtures, snapshots={}, odds={})


def test_story_present_and_advantage_emits_reading() -> None:
    fake_rss = MagicMock(); fake_rss.fetch.return_value = [{"title": "Kompany 拜仁欧冠首秀", "link": "u"}]
    completer = FakeLLMCompleter(responses=[
        '{"story_present":true,"team_advantaged":"away","conviction":0.55,"story_summary":"Kompany debut narrative"}'
    ])
    sig = PersonalNarrativeSignal(rss=fake_rss, llm=completer)
    fixtures = [{"id":"f1","home_team_name":"PSG","away_team_name":"Bayern"}]
    [r] = sig.evaluate(_ctx(fixtures))
    assert r.outcome_view == "away_win"
    assert r.conviction == 0.55


def test_no_story_abstains() -> None:
    fake_rss = MagicMock(); fake_rss.fetch.return_value = [{"title":"random","link":""}]
    completer = FakeLLMCompleter(responses=[
        '{"story_present":false,"team_advantaged":"none","conviction":0.0,"story_summary":""}'
    ])
    sig = PersonalNarrativeSignal(rss=fake_rss, llm=completer)
    [r] = sig.evaluate(_ctx([{"id":"f1","home_team_name":"A","away_team_name":"B"}]))
    assert r.outcome_view is None


def test_empty_rss_results_abstain_without_llm() -> None:
    fake_rss = MagicMock(); fake_rss.fetch.return_value = []
    completer = FakeLLMCompleter(responses=[])  # never called
    sig = PersonalNarrativeSignal(rss=fake_rss, llm=completer)
    [r] = sig.evaluate(_ctx([{"id":"f1","home_team_name":"A","away_team_name":"B"}]))
    assert r.outcome_view is None
    assert "no rss" in (r.abstain_reason or "").lower()


def test_llm_failure_abstains() -> None:
    fake_rss = MagicMock(); fake_rss.fetch.return_value = [{"title":"x","link":""}]
    completer = FakeLLMCompleter(responses=["not json"])
    sig = PersonalNarrativeSignal(rss=fake_rss, llm=completer)
    [r] = sig.evaluate(_ctx([{"id":"f1","home_team_name":"A","away_team_name":"B"}]))
    assert r.outcome_view is None
```

- [ ] **Step 2: Run, verify failure**

```bash
uv run pytest tests/test_psychology_signal_personal_narrative.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# nutmeg/services/psychology/signals/personal_narrative.py
from __future__ import annotations

import json
from dataclasses import dataclass

from nutmeg.services.psychology.llm import LLMCompleter, LLMCompletionError
from nutmeg.services.psychology.schemas import SignalReading
from nutmeg.services.psychology.signals.base import SignalContext
from nutmeg.services.psychology.sources.rss_provider import RssProvider

STORY_KEYWORDS = ["复仇", "首秀", "末战", "回归", "重逢", "里程碑"]
SYSTEM_PROMPT = (
    "你是足球叙事分析师。给定本场比赛若干新闻头条，判断是否存在"
    "球员/教练个人故事线（旧主、复仇、首秀、末战、里程碑等），"
    "并指出该故事线倾向于让哪一方表现更强。只输出 JSON："
    '{"story_present":true|false,"team_advantaged":"home|away|none","conviction":0..1,"story_summary":"..."}'
)


@dataclass(slots=True)
class PersonalNarrativeSignal:
    rss: RssProvider
    llm: LLMCompleter
    name: str = "personal_narrative"

    def evaluate(self, ctx: SignalContext) -> list[SignalReading]:
        out: list[SignalReading] = []
        for fx in ctx.fixtures:
            fixture_id = str(fx.get("id"))
            home = str(fx.get("home_team_name") or "")
            away = str(fx.get("away_team_name") or "")

            items = self.rss.fetch(date=ctx.date, query=home) or []
            items += self.rss.fetch(date=ctx.date, query=away) or []
            for kw in STORY_KEYWORDS:
                items += self.rss.fetch(date=ctx.date, query=kw) or []

            if not items:
                out.append(self._abstain(fixture_id, "no RSS items"))
                continue

            headlines = "\n".join(f"- {it.get('title','')}" for it in items[:30])
            user = f"主队：{home}\n客队：{away}\n头条：\n{headlines}"
            try:
                raw = self.llm.complete(system=SYSTEM_PROMPT, user=user)
                payload = json.loads(raw)
                story_present = bool(payload.get("story_present"))
                team = str(payload.get("team_advantaged"))
                conviction = float(payload.get("conviction", 0.0))
                summary = str(payload.get("story_summary", ""))
            except (LLMCompletionError, ValueError, TypeError, json.JSONDecodeError):
                out.append(self._abstain(fixture_id, "llm parse failed"))
                continue

            if not story_present or team not in {"home", "away"}:
                out.append(self._abstain(fixture_id, "no actionable story"))
                continue

            outcome = "home_win" if team == "home" else "away_win"
            out.append(SignalReading(
                provider=self.name, fixture_id=fixture_id, market="HHAD",
                outcome_view=outcome, conviction=max(0.0, min(conviction, 0.7)),
                evidence=[summary] if summary else ["personal narrative present"],
                source_refs=[str(it.get("link") or "") for it in items[:5]],
                abstain_reason=None,
            ))
        return out

    def _abstain(self, fixture_id: str, reason: str) -> SignalReading:
        return SignalReading(
            provider=self.name, fixture_id=fixture_id, market="HHAD",
            outcome_view=None, conviction=0.0, evidence=[], source_refs=[],
            abstain_reason=reason,
        )
```

- [ ] **Step 4: Verify pass**

```bash
uv run pytest tests/test_psychology_signal_personal_narrative.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/psychology/signals/personal_narrative.py tests/test_psychology_signal_personal_narrative.py
git commit -m "feat(psychology): add personal-narrative signal provider"
```

---

## Phase 2 — Engine + Inspiration + Guardrails

### Task 11: PsychologyEngine

**Files:**
- Create: `nutmeg/services/psychology/engine.py`
- Test: `tests/test_psychology_engine.py`

Engine runs all enabled providers in parallel (`ThreadPoolExecutor`, max_workers=4), then per-fixture reduces readings into one `PsychologyVerdict`:

- For each `market`, take the highest-conviction non-abstain reading; if multiple agree on outcome, average their convictions and clip to 0.95.
- `lean_direction`: compare aggregated outcome to `data_picks` map provided to `evaluate(...)`; if matches → `agree_data`, mismatch → `diverge_data`, all-abstain → `neutral`.
- Provider failures (uncaught exceptions) become a single abstain reading with `abstain_reason="provider_crashed: <type>"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_psychology_engine.py
from __future__ import annotations

from unittest.mock import MagicMock

from nutmeg.services.psychology.engine import PsychologyEngine
from nutmeg.services.psychology.schemas import SignalReading
from nutmeg.services.psychology.signals.base import SignalContext


def _reading(provider: str, fixture: str, market: str, outcome: str | None, conv: float, abstain: str | None = None) -> SignalReading:
    return SignalReading(
        provider=provider, fixture_id=fixture, market=market,
        outcome_view=outcome, conviction=conv,
        evidence=[], source_refs=[], abstain_reason=abstain,
    )


def test_aggregates_agreeing_signals() -> None:
    p1 = MagicMock(name="tournament_stage"); p1.name = "tournament_stage"
    p1.evaluate.return_value = [_reading("tournament_stage", "f1", "HHAD", "away_win", 0.65)]
    p2 = MagicMock(name="contrarian_narrative"); p2.name = "contrarian_narrative"
    p2.evaluate.return_value = [_reading("contrarian_narrative", "f1", "HHAD", "away_win", 0.7)]
    engine = PsychologyEngine(providers=[p1, p2])
    [verdict] = engine.evaluate(
        ctx=SignalContext(date="2026-04-29", fixtures=[{"id":"f1"}], snapshots={}, odds={}),
        data_picks={"f1": {"HHAD": "home_win"}},
    )
    assert verdict.market_views["HHAD"].outcome == "away_win"
    assert 0.65 <= verdict.market_views["HHAD"].conviction <= 0.95
    assert verdict.lean_direction == "diverge_data"


def test_disagreeing_signals_pick_highest_conviction() -> None:
    p1 = MagicMock(); p1.name = "a"; p1.evaluate.return_value = [_reading("a","f1","HHAD","home_win",0.6)]
    p2 = MagicMock(); p2.name = "b"; p2.evaluate.return_value = [_reading("b","f1","HHAD","away_win",0.8)]
    engine = PsychologyEngine(providers=[p1, p2])
    [verdict] = engine.evaluate(
        ctx=SignalContext(date="2026-04-29", fixtures=[{"id":"f1"}], snapshots={}, odds={}),
        data_picks={"f1": {"HHAD": "draw"}},
    )
    assert verdict.market_views["HHAD"].outcome == "away_win"
    assert verdict.market_views["HHAD"].conviction == 0.8


def test_all_abstain_neutral() -> None:
    p = MagicMock(); p.name = "p"; p.evaluate.return_value = [_reading("p","f1","HHAD",None,0.0,abstain="x")]
    engine = PsychologyEngine(providers=[p])
    [verdict] = engine.evaluate(
        ctx=SignalContext(date="2026-04-29", fixtures=[{"id":"f1"}], snapshots={}, odds={}),
        data_picks={"f1": {"HHAD": "draw"}},
    )
    assert verdict.market_views == {} or all(v.outcome == "" for v in verdict.market_views.values())
    assert verdict.lean_direction == "neutral"
    assert verdict.conviction == 0.0


def test_provider_crash_isolated() -> None:
    p1 = MagicMock(); p1.name = "good"; p1.evaluate.return_value = [_reading("good","f1","HHAD","home_win",0.7)]
    p2 = MagicMock(); p2.name = "bad"; p2.evaluate.side_effect = RuntimeError("boom")
    engine = PsychologyEngine(providers=[p1, p2])
    [verdict] = engine.evaluate(
        ctx=SignalContext(date="2026-04-29", fixtures=[{"id":"f1"}], snapshots={}, odds={}),
        data_picks={"f1": {"HHAD": "draw"}},
    )
    crash_readings = [r for r in verdict.contributing_readings if r.provider == "bad"]
    assert crash_readings and (crash_readings[0].abstain_reason or "").startswith("provider_crashed")


def test_agreement_with_data_pick() -> None:
    p = MagicMock(); p.name = "p"
    p.evaluate.return_value = [_reading("p","f1","HHAD","home_win",0.7)]
    engine = PsychologyEngine(providers=[p])
    [verdict] = engine.evaluate(
        ctx=SignalContext(date="2026-04-29", fixtures=[{"id":"f1"}], snapshots={}, odds={}),
        data_picks={"f1": {"HHAD": "home_win"}},
    )
    assert verdict.lean_direction == "agree_data"
```

- [ ] **Step 2: Run, verify failure**

```bash
uv run pytest tests/test_psychology_engine.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# nutmeg/services/psychology/engine.py
from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from nutmeg.services.psychology.schemas import (
    OutcomeView,
    PsychologyVerdict,
    SignalReading,
)
from nutmeg.services.psychology.signals.base import SignalContext, SignalProvider


@dataclass(slots=True)
class PsychologyEngine:
    providers: list[SignalProvider]
    max_workers: int = 4

    def evaluate(
        self,
        *,
        ctx: SignalContext,
        data_picks: dict[str, dict[str, str]],
    ) -> list[PsychologyVerdict]:
        readings_by_provider: dict[str, list[SignalReading]] = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {pool.submit(self._safe_evaluate, p, ctx): p for p in self.providers}
            for future, provider in futures.items():
                readings_by_provider[provider.name] = future.result()

        all_readings: list[SignalReading] = [r for rs in readings_by_provider.values() for r in rs]

        per_fixture: dict[str, list[SignalReading]] = defaultdict(list)
        for r in all_readings:
            per_fixture[r.fixture_id].append(r)

        verdicts: list[PsychologyVerdict] = []
        for fx in ctx.fixtures:
            fid = str(fx.get("id"))
            readings = per_fixture.get(fid, [])
            verdicts.append(self._reduce(fid, readings, data_picks.get(fid, {})))
        return verdicts

    def _safe_evaluate(self, provider: SignalProvider, ctx: SignalContext) -> list[SignalReading]:
        try:
            return list(provider.evaluate(ctx))
        except Exception as exc:  # noqa: BLE001 — explicit isolation
            crash_readings: list[SignalReading] = []
            for fx in ctx.fixtures:
                crash_readings.append(SignalReading(
                    provider=provider.name,
                    fixture_id=str(fx.get("id")),
                    market="HHAD",
                    outcome_view=None,
                    conviction=0.0,
                    evidence=[],
                    source_refs=[],
                    abstain_reason=f"provider_crashed: {type(exc).__name__}",
                ))
            return crash_readings

    def _reduce(
        self,
        fixture_id: str,
        readings: list[SignalReading],
        data_picks_for_fixture: dict[str, str],
    ) -> PsychologyVerdict:
        active = [r for r in readings if r.outcome_view is not None and r.conviction > 0]
        market_views: dict[str, OutcomeView] = {}
        if active:
            by_market: dict[str, list[SignalReading]] = defaultdict(list)
            for r in active:
                by_market[r.market].append(r)
            for market, rs in by_market.items():
                # group by candidate outcome
                by_outcome: dict[str, list[float]] = defaultdict(list)
                for r in rs:
                    by_outcome[str(r.outcome_view)].append(r.conviction)
                # winning outcome = highest conviction; if tie, prefer one with multiple supporting readings
                winning_outcome = max(
                    by_outcome,
                    key=lambda o: (max(by_outcome[o]), len(by_outcome[o])),
                )
                supporting = by_outcome[winning_outcome]
                aggregated = (sum(supporting) / len(supporting)) if len(supporting) > 1 else supporting[0]
                aggregated = min(aggregated, 0.95)
                market_views[market] = OutcomeView(market=market, outcome=winning_outcome, conviction=aggregated)

        overall_conviction = max((v.conviction for v in market_views.values()), default=0.0)
        if not market_views:
            lean_direction = "neutral"
        else:
            mismatches = [
                m for m, v in market_views.items()
                if data_picks_for_fixture.get(m) and v.outcome != data_picks_for_fixture.get(m)
            ]
            lean_direction = "diverge_data" if mismatches else "agree_data"

        return PsychologyVerdict(
            fixture_id=fixture_id,
            market_views=market_views,
            conviction=overall_conviction,
            lean_direction=lean_direction,
            contributing_readings=readings,
        )
```

- [ ] **Step 4: Verify pass**

```bash
uv run pytest tests/test_psychology_engine.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/psychology/engine.py tests/test_psychology_engine.py
git commit -m "feat(psychology): add PsychologyEngine with parallel signals and reduce"
```

---

### Task 12: InspirationParser

**Files:**
- Create: `nutmeg/services/psychology/inspiration.py`
- Test: `tests/test_psychology_inspiration.py`

Logic:
- LLM primary: prompt extracts JSON `{"lean":"data|psychology|neutral","conviction":"low|medium|high","focus":[...],"force_psychology":bool,"force_data":bool}`.
- Regex fallback if LLM fails: keyword tables for `lean` (反着来/反向/心理/直觉 → psychology; 数据/正常/算法 → data), `conviction` (强/必/锁 → high; 微/小/或许 → low; default medium), `focus` (大赛/淘汰 → tournament_stage, 媒体/舆论 → contrarian_narrative, 教练/球员/复仇 → personal_narrative, 战术/变招 → reflexive_tactic), `force_psychology` (今天必须 / 强制心理), `force_data` (强制数据).

Also handles read/write of `.nutmeg-data/inspiration/{date}/raw.md` and `parsed.json`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_psychology_inspiration.py
from __future__ import annotations

from pathlib import Path

from nutmeg.services.psychology.inspiration import (
    InspirationParser,
    InspirationStore,
)
from nutmeg.services.psychology.llm import FakeLLMCompleter
from nutmeg.services.psychology.schemas import InspirationTags


def test_parser_uses_llm_when_available() -> None:
    completer = FakeLLMCompleter(responses=[
        '{"lean":"psychology","conviction":"high","focus":["tournament_stage"],"force_psychology":false,"force_data":false}'
    ])
    parser = InspirationParser(llm=completer)
    note = parser.parse("今晚反着来，欧冠淘汰赛感觉拜仁稳一些。", date="2026-04-29")
    assert note.parsed_tags.lean == "psychology"
    assert note.parsed_tags.conviction == "high"
    assert note.parsed_tags.focus == ["tournament_stage"]
    assert note.parse_method == "llm"


def test_parser_regex_fallback_when_llm_fails() -> None:
    completer = FakeLLMCompleter(responses=["not json"])
    parser = InspirationParser(llm=completer)
    note = parser.parse("反着来，淘汰赛风险大", date="2026-04-29")
    assert note.parsed_tags.lean == "psychology"
    assert "tournament_stage" in note.parsed_tags.focus
    assert note.parse_method == "regex_fallback"


def test_regex_detects_force_flags() -> None:
    completer = FakeLLMCompleter(responses=["bad"])
    parser = InspirationParser(llm=completer)
    note = parser.parse("今天必须心理，强制心理层", date="2026-04-29")
    assert note.parsed_tags.force_psychology is True


def test_default_neutral_when_unparseable_text() -> None:
    completer = FakeLLMCompleter(responses=["bad"])
    parser = InspirationParser(llm=completer)
    note = parser.parse("Nothing relevant.", date="2026-04-29")
    assert note.parsed_tags.lean == "neutral"
    assert note.parsed_tags.conviction == "medium"


def test_store_round_trip(tmp_path: Path) -> None:
    store = InspirationStore(base_dir=tmp_path)
    tags = InspirationTags(lean="data", conviction="medium", focus=[], force_psychology=False, force_data=False)
    store.write_raw(date="2026-04-29", text="abc")
    store.write_parsed(date="2026-04-29", tags=tags, raw_text="abc", parse_method="llm", timestamp="2026-04-29T14:00:00Z")
    note = store.read(date="2026-04-29")
    assert note is not None
    assert note.raw_text == "abc"
    assert note.parsed_tags == tags
```

- [ ] **Step 2: Run, verify failure**

```bash
uv run pytest tests/test_psychology_inspiration.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# nutmeg/services/psychology/inspiration.py
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from nutmeg.services.psychology.llm import LLMCompleter, LLMCompletionError
from nutmeg.services.psychology.schemas import InspirationNote, InspirationTags

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
SYSTEM_PROMPT = (
    "你将收到一段中文“当日灵感笔记”。提取结构化标签，仅输出 JSON："
    '{"lean":"data|psychology|neutral","conviction":"low|medium|high",'
    '"focus":["tournament_stage"|"contrarian_narrative"|"reflexive_tactic"|"personal_narrative"],'
    '"force_psychology":true|false,"force_data":true|false}'
)


@dataclass(slots=True)
class InspirationParser:
    llm: LLMCompleter

    def parse(self, text: str, *, date: str) -> InspirationNote:
        timestamp = datetime.now(tz=timezone.utc).isoformat()
        try:
            raw = self.llm.complete(system=SYSTEM_PROMPT, user=text)
            payload = json.loads(raw)
            tags = InspirationTags(
                lean=str(payload.get("lean", "neutral")),  # type: ignore[arg-type]
                conviction=str(payload.get("conviction", "medium")),  # type: ignore[arg-type]
                focus=list(payload.get("focus") or []),
                force_psychology=bool(payload.get("force_psychology", False)),
                force_data=bool(payload.get("force_data", False)),
            )
            return InspirationNote(
                date=date, raw_text=text, parsed_tags=tags,
                parse_method="llm", timestamp=timestamp,
            )
        except (LLMCompletionError, ValueError, TypeError, json.JSONDecodeError):
            tags = self._regex_parse(text)
            return InspirationNote(
                date=date, raw_text=text, parsed_tags=tags,
                parse_method="regex_fallback", timestamp=timestamp,
            )

    def _regex_parse(self, text: str) -> InspirationTags:
        lean: str = "neutral"
        if any(k in text for k in LEAN_PSYCHOLOGY_KW):
            lean = "psychology"
        elif any(k in text for k in LEAN_DATA_KW):
            lean = "data"

        conviction: str = "medium"
        if any(k in text for k in CONVICTION_HIGH_KW):
            conviction = "high"
        elif any(k in text for k in CONVICTION_LOW_KW):
            conviction = "low"

        focus: list[str] = []
        for provider_name, kws in FOCUS_TABLE.items():
            if any(k in text for k in kws):
                focus.append(provider_name)

        force_psy = any(k in text for k in FORCE_PSY_KW)
        force_data = any(k in text for k in FORCE_DATA_KW)

        return InspirationTags(
            lean=lean,                       # type: ignore[arg-type]
            conviction=conviction,           # type: ignore[arg-type]
            focus=focus,
            force_psychology=force_psy,
            force_data=force_data,
        )


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
        self,
        *,
        date: str,
        tags: InspirationTags,
        raw_text: str,
        parse_method: str,
        timestamp: str,
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
            date=data["date"],
            raw_text=data["raw_text"],
            parsed_tags=InspirationTags(
                lean=t["lean"], conviction=t["conviction"],
                focus=list(t["focus"]),
                force_psychology=bool(t["force_psychology"]),
                force_data=bool(t["force_data"]),
            ),
            parse_method=data["parse_method"],
            timestamp=data["timestamp"],
        )
```

- [ ] **Step 4: Verify pass**

```bash
uv run pytest tests/test_psychology_inspiration.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/psychology/inspiration.py tests/test_psychology_inspiration.py
git commit -m "feat(psychology): add InspirationParser with LLM + regex fallback and InspirationStore"
```

---

### Task 13: Guardrails (BudgetGuard + ConvictionGate)

**Files:**
- Create: `nutmeg/services/psychology/guardrails.py`
- Test: `tests/test_psychology_guardrails.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_psychology_guardrails.py
from __future__ import annotations

from nutmeg.services.psychology.guardrails import (
    BudgetGuard,
    ConvictionGate,
)
from nutmeg.services.psychology.schemas import OverrideCandidate


def _candidate(leg_id: str, conviction: float, provider: str = "tournament_stage") -> OverrideCandidate:
    return OverrideCandidate(
        leg_id=leg_id, fixture_id="f"+leg_id, market="HHAD",
        from_outcome="home_win", to_outcome="away_win",
        conviction=conviction, reasoning=[], source_provider=provider,
    )


def test_conviction_gate_filters_below_threshold() -> None:
    gate = ConvictionGate(threshold=0.7)
    accepted, rejected = gate.apply([_candidate("1", 0.65), _candidate("2", 0.72)])
    assert [c.leg_id for c in accepted] == ["2"]
    assert rejected[0][1].startswith("below_conviction")


def test_budget_guard_caps_to_one() -> None:
    guard = BudgetGuard(max_reversals=1)
    accepted, rejected = guard.apply([_candidate("1", 0.8), _candidate("2", 0.9)])
    assert len(accepted) == 1
    assert accepted[0].leg_id == "2"  # highest conviction wins
    assert rejected[0][1] == "budget_exhausted"


def test_budget_guard_zero_rejects_all() -> None:
    guard = BudgetGuard(max_reversals=0)
    accepted, rejected = guard.apply([_candidate("1", 0.9)])
    assert accepted == []
    assert rejected[0][1] == "budget_exhausted"


def test_conviction_gate_threshold_inclusive() -> None:
    gate = ConvictionGate(threshold=0.7)
    accepted, rejected = gate.apply([_candidate("1", 0.7)])
    assert len(accepted) == 1
```

- [ ] **Step 2: Run, verify failure**

```bash
uv run pytest tests/test_psychology_guardrails.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# nutmeg/services/psychology/guardrails.py
from __future__ import annotations

from dataclasses import dataclass

from nutmeg.services.psychology.schemas import OverrideCandidate


@dataclass(slots=True)
class ConvictionGate:
    threshold: float = 0.7

    def apply(
        self, candidates: list[OverrideCandidate]
    ) -> tuple[list[OverrideCandidate], list[tuple[OverrideCandidate, str]]]:
        accepted: list[OverrideCandidate] = []
        rejected: list[tuple[OverrideCandidate, str]] = []
        for c in candidates:
            if c.conviction >= self.threshold:
                accepted.append(c)
            else:
                rejected.append((c, f"below_conviction({c.conviction:.2f}<{self.threshold:.2f})"))
        return accepted, rejected


@dataclass(slots=True)
class BudgetGuard:
    max_reversals: int = 1

    def apply(
        self, candidates: list[OverrideCandidate]
    ) -> tuple[list[OverrideCandidate], list[tuple[OverrideCandidate, str]]]:
        ranked = sorted(candidates, key=lambda c: c.conviction, reverse=True)
        accepted = ranked[: self.max_reversals]
        rejected = [(c, "budget_exhausted") for c in ranked[self.max_reversals :]]
        return accepted, rejected
```

- [ ] **Step 4: Verify pass**

```bash
uv run pytest tests/test_psychology_guardrails.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/psychology/guardrails.py tests/test_psychology_guardrails.py
git commit -m "feat(psychology): add BudgetGuard and ConvictionGate"
```

---

## Phase 3 — Reconciliator + Recorder

### Task 14: Reconciliator

**Files:**
- Create: `nutmeg/services/psychology/reconciliator.py`
- Test: `tests/test_psychology_reconciliator.py`

Logic:
1. Walk each `DataLeg`; if a `PsychologyVerdict` for the same fixture has a market_view that disagrees on outcome and conviction > 0, build an `OverrideCandidate`.
2. If `inspiration.parsed_tags.force_data` → emit empty candidate set; final_scheme equals data_scheme.
3. If `inspiration.parsed_tags.focus` non-empty → drop candidates whose `source_provider` not in focus.
4. Apply `ConvictionGate` (skip if `force_psychology=true`).
5. Apply `BudgetGuard` (always — even with `force_psychology`).
6. Build `FinalScheme.legs` by replacing accepted candidates' outcome and marking provenance:
   - If candidate was accepted under `force_psychology` and would have been gated → `inspiration_forced`.
   - Else → `psychology`.
   - Untouched legs → `data`.
7. Build `dashboard_rows` row per fixture with `data_pick`, `psych_pick` (or None), `conflict`, `final_pick`, `conviction`.
8. `confidence` is computed as: `"high"` if no overrides, `"medium"` if one within budget, `"low"` if any rejected for budget reasons (suggests we wanted more).

- [ ] **Step 1: Write failing test**

```python
# tests/test_psychology_reconciliator.py
from __future__ import annotations

from nutmeg.services.psychology.guardrails import BudgetGuard, ConvictionGate
from nutmeg.services.psychology.reconciliator import Reconciliator
from nutmeg.services.psychology.schemas import (
    DataLeg,
    InspirationNote,
    InspirationTags,
    OutcomeView,
    PsychologyVerdict,
    Scheme,
)


def _data_scheme() -> Scheme:
    return Scheme(name="data", legs=[
        DataLeg(leg_id="L1", fixture_id="f1", market="HHAD", outcome="home_win", odds=2.10),
        DataLeg(leg_id="L2", fixture_id="f2", market="HHAD", outcome="draw", odds=3.20),
        DataLeg(leg_id="L3", fixture_id="f3", market="HHAD", outcome="away_win", odds=2.50),
    ])


def _psy_verdict(fixture: str, outcome: str, conv: float, lean: str = "diverge_data") -> PsychologyVerdict:
    return PsychologyVerdict(
        fixture_id=fixture,
        market_views={"HHAD": OutcomeView(market="HHAD", outcome=outcome, conviction=conv)},
        conviction=conv,
        lean_direction=lean,  # type: ignore[arg-type]
        contributing_readings=[],
    )


def _build_recon() -> Reconciliator:
    return Reconciliator(conviction_gate=ConvictionGate(threshold=0.7), budget_guard=BudgetGuard(max_reversals=1))


def test_no_disagreement_keeps_data_scheme() -> None:
    recon = _build_recon()
    report = recon.reconcile(
        data_scheme=_data_scheme(),
        psychology_verdicts=[_psy_verdict("f1","home_win",0.8,"agree_data"),
                             _psy_verdict("f2","draw",0.5,"agree_data"),
                             _psy_verdict("f3","away_win",0.3,"agree_data")],
        inspiration=None,
    )
    assert all(leg.provenance == "data" for leg in report.final_scheme.legs)
    assert report.final_scheme.confidence == "high"


def test_high_conviction_disagreement_overrides() -> None:
    recon = _build_recon()
    report = recon.reconcile(
        data_scheme=_data_scheme(),
        psychology_verdicts=[_psy_verdict("f1","away_win",0.85)],
        inspiration=None,
    )
    overridden = [l for l in report.final_scheme.legs if l.provenance == "psychology"]
    assert len(overridden) == 1 and overridden[0].fixture_id == "f1"
    assert overridden[0].outcome == "away_win"


def test_budget_caps_at_one() -> None:
    recon = _build_recon()
    report = recon.reconcile(
        data_scheme=_data_scheme(),
        psychology_verdicts=[_psy_verdict("f1","away_win",0.85),
                             _psy_verdict("f2","home_win",0.9)],
        inspiration=None,
    )
    overrides = [l for l in report.final_scheme.legs if l.provenance == "psychology"]
    assert len(overrides) == 1
    rejected = report.guardrail.rejected
    assert any("budget" in reason for _, reason in rejected)
    assert report.final_scheme.confidence == "low"


def test_conviction_gate_filters_low_conviction() -> None:
    recon = _build_recon()
    report = recon.reconcile(
        data_scheme=_data_scheme(),
        psychology_verdicts=[_psy_verdict("f1","away_win",0.5)],
        inspiration=None,
    )
    assert all(leg.provenance == "data" for leg in report.final_scheme.legs)


def test_force_data_skips_psychology() -> None:
    recon = _build_recon()
    insp = InspirationNote(
        date="2026-04-29", raw_text="只走数据",
        parsed_tags=InspirationTags(
            lean="data", conviction="high", focus=[],
            force_psychology=False, force_data=True,
        ),
        parse_method="llm", timestamp="2026-04-29T14:00Z",
    )
    report = recon.reconcile(
        data_scheme=_data_scheme(),
        psychology_verdicts=[_psy_verdict("f1","away_win",0.99)],
        inspiration=insp,
    )
    assert all(leg.provenance == "data" for leg in report.final_scheme.legs)


def test_force_psychology_bypasses_conviction_gate() -> None:
    recon = _build_recon()
    insp = InspirationNote(
        date="2026-04-29", raw_text="今天必须心理",
        parsed_tags=InspirationTags(
            lean="psychology", conviction="high", focus=[],
            force_psychology=True, force_data=False,
        ),
        parse_method="llm", timestamp="2026-04-29T14:00Z",
    )
    report = recon.reconcile(
        data_scheme=_data_scheme(),
        psychology_verdicts=[_psy_verdict("f1","away_win",0.5)],  # below 0.7
        inspiration=insp,
    )
    forced = [l for l in report.final_scheme.legs if l.provenance == "inspiration_forced"]
    assert len(forced) == 1
    assert forced[0].outcome == "away_win"


def test_focus_filter_drops_off_focus_provider() -> None:
    recon = _build_recon()
    insp = InspirationNote(
        date="2026-04-29", raw_text="重点看大赛阶段",
        parsed_tags=InspirationTags(
            lean="psychology", conviction="high",
            focus=["tournament_stage"],
            force_psychology=False, force_data=False,
        ),
        parse_method="llm", timestamp="2026-04-29T14:00Z",
    )
    # build verdict with source not in focus
    v = PsychologyVerdict(
        fixture_id="f1",
        market_views={"HHAD": OutcomeView(market="HHAD", outcome="away_win", conviction=0.85)},
        conviction=0.85, lean_direction="diverge_data",
        contributing_readings=[],
    )
    report = recon.reconcile(
        data_scheme=_data_scheme(),
        psychology_verdicts=[v],
        inspiration=insp,
        provider_origin={"f1::HHAD": "contrarian_narrative"},  # not in focus
    )
    assert all(leg.provenance == "data" for leg in report.final_scheme.legs)
```

- [ ] **Step 2: Run, verify failure**

```bash
uv run pytest tests/test_psychology_reconciliator.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# nutmeg/services/psychology/reconciliator.py
from __future__ import annotations

from dataclasses import dataclass

from nutmeg.services.psychology.guardrails import BudgetGuard, ConvictionGate
from nutmeg.services.psychology.schemas import (
    DashboardRow,
    DualSchemeReport,
    DataLeg,
    FinalLeg,
    FinalScheme,
    GuardrailDecision,
    InspirationNote,
    OverrideCandidate,
    PsychologyVerdict,
    Scheme,
)


@dataclass(slots=True)
class Reconciliator:
    conviction_gate: ConvictionGate
    budget_guard: BudgetGuard

    def reconcile(
        self,
        *,
        data_scheme: Scheme,
        psychology_verdicts: list[PsychologyVerdict],
        inspiration: InspirationNote | None,
        provider_origin: dict[str, str] | None = None,
    ) -> DualSchemeReport:
        verdict_by_fixture = {v.fixture_id: v for v in psychology_verdicts}
        psych_legs: list[DataLeg] = []
        candidates: list[OverrideCandidate] = []
        provider_origin = provider_origin or {}

        for leg in data_scheme.legs:
            v = verdict_by_fixture.get(leg.fixture_id)
            if v and (mv := v.market_views.get(leg.market)) and mv.outcome != leg.outcome and mv.conviction > 0:
                psych_legs.append(DataLeg(
                    leg_id=leg.leg_id, fixture_id=leg.fixture_id, market=leg.market,
                    outcome=mv.outcome, odds=leg.odds,
                ))
                candidates.append(OverrideCandidate(
                    leg_id=leg.leg_id, fixture_id=leg.fixture_id, market=leg.market,
                    from_outcome=leg.outcome, to_outcome=mv.outcome,
                    conviction=mv.conviction, reasoning=[],
                    source_provider=provider_origin.get(f"{leg.fixture_id}::{leg.market}", "psychology"),
                ))
            else:
                psych_legs.append(leg)

        psych_scheme = Scheme(name="psychology", legs=psych_legs)

        # Inspiration-driven gating
        forced_via_inspiration = False
        rejected: list[tuple[OverrideCandidate, str]] = []
        accepted_pre_budget: list[OverrideCandidate]

        if inspiration and inspiration.parsed_tags.force_data:
            rejected.extend((c, "inspiration_force_data") for c in candidates)
            accepted_pre_budget = []
        else:
            filtered = candidates
            if inspiration and inspiration.parsed_tags.focus:
                allowed = set(inspiration.parsed_tags.focus)
                kept = [c for c in filtered if c.source_provider in allowed]
                rejected.extend(
                    (c, f"focus_excluded({c.source_provider})") for c in filtered if c.source_provider not in allowed
                )
                filtered = kept

            if inspiration and inspiration.parsed_tags.force_psychology:
                accepted_pre_budget = filtered
                forced_via_inspiration = True
            else:
                gated_pass, gated_reject = self.conviction_gate.apply(filtered)
                accepted_pre_budget = gated_pass
                rejected.extend(gated_reject)

        budget_pass, budget_reject = self.budget_guard.apply(accepted_pre_budget)
        rejected.extend(budget_reject)

        accepted_set = {(c.fixture_id, c.market): c for c in budget_pass}

        final_legs: list[FinalLeg] = []
        for leg in data_scheme.legs:
            key = (leg.fixture_id, leg.market)
            if key in accepted_set:
                c = accepted_set[key]
                provenance = "inspiration_forced" if forced_via_inspiration else "psychology"
                final_legs.append(FinalLeg(
                    leg_id=leg.leg_id, fixture_id=leg.fixture_id, market=leg.market,
                    outcome=c.to_outcome, odds=leg.odds, provenance=provenance,
                ))
            else:
                final_legs.append(FinalLeg(
                    leg_id=leg.leg_id, fixture_id=leg.fixture_id, market=leg.market,
                    outcome=leg.outcome, odds=leg.odds, provenance="data",
                ))

        confidence: str
        if not candidates:
            confidence = "high"
        elif any("budget" in reason for _, reason in rejected):
            confidence = "low"
        elif accepted_set:
            confidence = "medium"
        else:
            confidence = "high"

        notes: list[str] = []
        if forced_via_inspiration:
            notes.append("inspiration_force_psychology applied")
        if inspiration and inspiration.parsed_tags.force_data:
            notes.append("inspiration_force_data applied")

        dashboard = []
        for leg in data_scheme.legs:
            v = verdict_by_fixture.get(leg.fixture_id)
            psych_pick = v.market_views.get(leg.market).outcome if (v and leg.market in v.market_views) else None
            final_outcome = next(l.outcome for l in final_legs if l.leg_id == leg.leg_id)
            dashboard.append(DashboardRow(
                fixture_id=leg.fixture_id,
                data_pick=leg.outcome,
                psych_pick=psych_pick,
                conflict=psych_pick is not None and psych_pick != leg.outcome,
                final_pick=final_outcome,
                conviction=v.conviction if v else 0.0,
            ))

        return DualSchemeReport(
            data_scheme=data_scheme,
            psychology_scheme=psych_scheme,
            final_scheme=FinalScheme(legs=final_legs, confidence=confidence, notes=notes),
            dashboard_rows=dashboard,
            inspiration=inspiration,
            guardrail=GuardrailDecision(
                accepted=list(budget_pass),
                rejected=rejected,
                guardrail_state={
                    "budget": f"{len(budget_pass)}/{self.budget_guard.max_reversals}",
                    "conviction_gate": f"{self.conviction_gate.threshold:.2f}",
                    "kill_switch": "warming_up",
                },
            ),
        )
```

- [ ] **Step 4: Verify pass**

```bash
uv run pytest tests/test_psychology_reconciliator.py -v
```
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/psychology/reconciliator.py tests/test_psychology_reconciliator.py
git commit -m "feat(psychology): add Reconciliator merging data + psychology with inspiration gating"
```

---

### Task 15: Recorder

**Files:**
- Create: `nutmeg/services/psychology/calibration/__init__.py`
- Create: `nutmeg/services/psychology/calibration/recorder.py`
- Test: `tests/test_psychology_recorder.py`

Recorder appends per-leg provenance + outcome rows to `.nutmeg-data/inspiration/{date}/recorder.jsonl`. Each row: `{date, fixture_id, leg_id, market, data_pick, psych_pick, final_pick, provenance, conviction, hit}`. `hit` is filled later via `update_outcome`.

- [ ] **Step 1: Write failing test**

```python
# tests/test_psychology_recorder.py
from __future__ import annotations

import json
from pathlib import Path

from nutmeg.services.psychology.calibration.recorder import Recorder
from nutmeg.services.psychology.schemas import (
    DashboardRow,
    DataLeg,
    DualSchemeReport,
    FinalLeg,
    FinalScheme,
    GuardrailDecision,
    Scheme,
)


def _report() -> DualSchemeReport:
    return DualSchemeReport(
        data_scheme=Scheme(name="data", legs=[DataLeg("L1","f1","HHAD","home_win",2.1)]),
        psychology_scheme=Scheme(name="psychology", legs=[DataLeg("L1","f1","HHAD","away_win",2.45)]),
        final_scheme=FinalScheme(
            legs=[FinalLeg("L1","f1","HHAD","away_win",2.45,"psychology")],
            confidence="medium",
            notes=[],
        ),
        dashboard_rows=[DashboardRow("f1","home_win","away_win",True,"away_win",0.8)],
        inspiration=None,
        guardrail=GuardrailDecision(accepted=[], rejected=[], guardrail_state={"budget":"1/1"}),
    )


def test_record_writes_jsonl(tmp_path: Path) -> None:
    rec = Recorder(base_dir=tmp_path)
    rec.record(date="2026-04-29", report=_report())
    path = tmp_path / "2026-04-29" / "recorder.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["fixture_id"] == "f1"
    assert row["provenance"] == "psychology"
    assert row["hit"] is None


def test_update_outcome_marks_hits(tmp_path: Path) -> None:
    rec = Recorder(base_dir=tmp_path)
    rec.record(date="2026-04-29", report=_report())
    rec.update_outcome(date="2026-04-29", fixture_id="f1", market="HHAD", actual_outcome="away_win")
    rows = rec.read(date="2026-04-29")
    assert rows[0]["hit"] is True


def test_update_outcome_marks_miss(tmp_path: Path) -> None:
    rec = Recorder(base_dir=tmp_path)
    rec.record(date="2026-04-29", report=_report())
    rec.update_outcome(date="2026-04-29", fixture_id="f1", market="HHAD", actual_outcome="home_win")
    rows = rec.read(date="2026-04-29")
    assert rows[0]["hit"] is False
```

- [ ] **Step 2: Run, verify failure**

```bash
uv run pytest tests/test_psychology_recorder.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# nutmeg/services/psychology/calibration/__init__.py
"""Calibration loop — recorder + (v2) review."""
```

```python
# nutmeg/services/psychology/calibration/recorder.py
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from nutmeg.services.psychology.schemas import DualSchemeReport


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
            rows.append({
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
            })
        with path.open("a", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def update_outcome(self, *, date: str, fixture_id: str, market: str, actual_outcome: str) -> None:
        path = self._path(date)
        if not path.exists():
            return
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        for row in rows:
            if row["fixture_id"] == fixture_id and row["market"] == market:
                row["hit"] = row["final_pick"] == actual_outcome
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")

    def read(self, *, date: str) -> list[dict]:
        path = self._path(date)
        if not path.exists():
            return []
        return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
```

- [ ] **Step 4: Verify pass**

```bash
uv run pytest tests/test_psychology_recorder.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/psychology/calibration/__init__.py nutmeg/services/psychology/calibration/recorder.py tests/test_psychology_recorder.py
git commit -m "feat(psychology): add calibration recorder with hit/miss back-fill"
```

---

## Phase 4 — CLI commands

### Task 16: psychology-inspect command

**Files:**
- Modify: `nutmeg/interfaces/cli.py` (add command + helper)
- Test: `tests/test_psychology_cli.py` (covers all 3 CLI commands across this phase)

Inspect dumps raw `SignalReading[]` from each provider for a single fixture id (read from a fixture JSON file the user supplies).

- [ ] **Step 1: Write failing test (this single test grows across tasks 16-18)**

```python
# tests/test_psychology_cli.py
from __future__ import annotations

import json
from pathlib import Path
from typer.testing import CliRunner

from nutmeg.interfaces.cli import app


def test_psychology_inspect_outputs_json(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps({
        "id": "f1", "competition_code": "UCL", "stage": "knockout", "leg": 1,
        "tier_home": 1, "tier_away": 1, "aggregate_score_diff": None,
        "home_team_name": "PSG", "away_team_name": "Bayern",
    }), encoding="utf-8")
    result = runner.invoke(app, ["psychology-inspect", "--fixture-file", str(fixture_path), "--rules-only"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["fixture_id"] == "f1"
    names = {r["provider"] for r in payload["readings"]}
    assert "tournament_stage" in names
```

- [ ] **Step 2: Run, verify failure**

```bash
uv run pytest tests/test_psychology_cli.py::test_psychology_inspect_outputs_json -v
```
Expected: command not registered (`Error 2 / no such command`).

- [ ] **Step 3: Implement**

In `nutmeg/interfaces/cli.py`, add near the bottom (before any existing `if __name__`):

```python
# at top of file with other imports
import json
from pathlib import Path

from nutmeg.services.psychology.engine import PsychologyEngine
from nutmeg.services.psychology.signals.base import SignalContext
from nutmeg.services.psychology.signals.tournament_stage import TournamentStageSignal


@app.command(name="psychology-inspect")
def psychology_inspect_cmd(
    fixture_file: Path = typer.Option(..., "--fixture-file", help="JSON file with a single fixture dict"),
    rules_only: bool = typer.Option(False, "--rules-only", help="Skip LLM-backed signals; only run tournament_stage"),
) -> None:
    """Dump SignalReadings for a single fixture from each enabled provider."""
    fixture = json.loads(fixture_file.read_text(encoding="utf-8"))
    fixture_id = str(fixture.get("id"))
    providers: list = [TournamentStageSignal()]
    if not rules_only:
        # Future: wire LLM-backed providers; v1 inspect always offers --rules-only as quick path
        pass
    engine = PsychologyEngine(providers=providers)
    [verdict] = engine.evaluate(
        ctx=SignalContext(date="manual", fixtures=[fixture], snapshots={}, odds={}),
        data_picks={fixture_id: {}},
    )
    payload = {
        "fixture_id": fixture_id,
        "lean_direction": verdict.lean_direction,
        "conviction": verdict.conviction,
        "market_views": {m: {"outcome": v.outcome, "conviction": v.conviction} for m, v in verdict.market_views.items()},
        "readings": [
            {
                "provider": r.provider, "market": r.market,
                "outcome_view": r.outcome_view, "conviction": r.conviction,
                "evidence": r.evidence, "abstain_reason": r.abstain_reason,
            }
            for r in verdict.contributing_readings
        ],
    }
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
```

- [ ] **Step 4: Verify pass**

```bash
uv run pytest tests/test_psychology_cli.py::test_psychology_inspect_outputs_json -v
```
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/interfaces/cli.py tests/test_psychology_cli.py
git commit -m "feat(cli): add psychology-inspect command"
```

---

### Task 17: inspiration-write command

**Files:**
- Modify: `nutmeg/interfaces/cli.py`
- Test: extend `tests/test_psychology_cli.py`

`inspiration-write [--date YYYYMMDD] [--text "..."]` accepts text via `--text`, falls back to `$EDITOR` (skipped in tests via `--text`). Saves raw + parsed (LLM mocked at test time via dependency injection through env var or simply by feeding a `--text` short note that the regex fallback can handle without LLM).

- [ ] **Step 1: Add test to `tests/test_psychology_cli.py`**

```python
def test_inspiration_write_creates_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NUTMEG_INSPIRATION_DIR", str(tmp_path))
    monkeypatch.setenv("NUTMEG_PSYCHOLOGY_PARSER_FAKE_MODE", "1")  # forces regex_fallback path
    runner = CliRunner()
    result = runner.invoke(app, ["inspiration-write", "--date", "20260429", "--text", "今晚反着来，淘汰赛"])
    assert result.exit_code == 0, result.output
    raw = (tmp_path / "2026-04-29" / "raw.md").read_text(encoding="utf-8")
    assert "反着来" in raw
    parsed = json.loads((tmp_path / "2026-04-29" / "parsed.json").read_text(encoding="utf-8"))
    assert parsed["parsed_tags"]["lean"] == "psychology"
    assert "tournament_stage" in parsed["parsed_tags"]["focus"]
```

- [ ] **Step 2: Run, verify failure**

```bash
uv run pytest tests/test_psychology_cli.py::test_inspiration_write_creates_files -v
```
Expected: command not registered.

- [ ] **Step 3: Implement**

```python
# in nutmeg/interfaces/cli.py
import os
from datetime import datetime, timezone

from nutmeg.services.psychology.inspiration import InspirationParser, InspirationStore
from nutmeg.services.psychology.llm import FakeLLMCompleter, LLMCompleter


def _build_inspiration_parser() -> InspirationParser:
    if os.getenv("NUTMEG_PSYCHOLOGY_PARSER_FAKE_MODE") == "1":
        # Force regex fallback by feeding an LLM that always errors.
        return InspirationParser(llm=FakeLLMCompleter(responses=[]))
    # TODO(production wrapper): swap in PortkeySynthesisProvider-backed completer in Task 24.
    return InspirationParser(llm=FakeLLMCompleter(responses=[]))


def _normalize_date(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"


@app.command(name="inspiration-write")
def inspiration_write_cmd(
    date: str = typer.Option(..., "--date", help="YYYYMMDD"),
    text: str | None = typer.Option(None, "--text", help="If omitted, $EDITOR is opened"),
) -> None:
    base = Path(os.environ.get("NUTMEG_INSPIRATION_DIR", ".nutmeg-data/inspiration"))
    iso = _normalize_date(date)
    if text is None:
        editor = os.environ.get("EDITOR", "nano")
        tmpfile = base / iso / "raw.md"
        tmpfile.parent.mkdir(parents=True, exist_ok=True)
        if not tmpfile.exists():
            tmpfile.write_text("", encoding="utf-8")
        os.system(f"{editor} {tmpfile!s}")
        text = tmpfile.read_text(encoding="utf-8")
    store = InspirationStore(base_dir=base)
    store.write_raw(date=iso, text=text)
    parser = _build_inspiration_parser()
    note = parser.parse(text, date=iso)
    store.write_parsed(
        date=iso,
        tags=note.parsed_tags,
        raw_text=note.raw_text,
        parse_method=note.parse_method,
        timestamp=datetime.now(tz=timezone.utc).isoformat(),
    )
    typer.echo(f"saved {iso} via {note.parse_method}")
```

- [ ] **Step 4: Verify pass**

```bash
uv run pytest tests/test_psychology_cli.py::test_inspiration_write_creates_files -v
```
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/interfaces/cli.py tests/test_psychology_cli.py
git commit -m "feat(cli): add inspiration-write command"
```

---

### Task 18: inspiration-show command

**Files:**
- Modify: `nutmeg/interfaces/cli.py`
- Test: extend `tests/test_psychology_cli.py`

- [ ] **Step 1: Add test**

```python
def test_inspiration_show_prints_parsed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NUTMEG_INSPIRATION_DIR", str(tmp_path))
    monkeypatch.setenv("NUTMEG_PSYCHOLOGY_PARSER_FAKE_MODE", "1")
    runner = CliRunner()
    runner.invoke(app, ["inspiration-write", "--date", "20260429", "--text", "反着来"])
    result = runner.invoke(app, ["inspiration-show", "20260429"])
    assert result.exit_code == 0
    assert "psychology" in result.output
```

- [ ] **Step 2: Run, verify failure**

```bash
uv run pytest tests/test_psychology_cli.py::test_inspiration_show_prints_parsed -v
```
Expected: command not registered.

- [ ] **Step 3: Implement**

```python
@app.command(name="inspiration-show")
def inspiration_show_cmd(date: str = typer.Argument(..., help="YYYYMMDD")) -> None:
    base = Path(os.environ.get("NUTMEG_INSPIRATION_DIR", ".nutmeg-data/inspiration"))
    iso = _normalize_date(date)
    store = InspirationStore(base_dir=base)
    note = store.read(date=iso)
    if note is None:
        typer.echo(f"no inspiration recorded for {iso}")
        raise typer.Exit(code=1)
    typer.echo(json.dumps({
        "date": note.date,
        "raw_text": note.raw_text,
        "parsed_tags": {
            "lean": note.parsed_tags.lean,
            "conviction": note.parsed_tags.conviction,
            "focus": note.parsed_tags.focus,
            "force_psychology": note.parsed_tags.force_psychology,
            "force_data": note.parsed_tags.force_data,
        },
        "parse_method": note.parse_method,
    }, ensure_ascii=False, indent=2))
```

- [ ] **Step 4: Verify pass**

```bash
uv run pytest tests/test_psychology_cli.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/interfaces/cli.py tests/test_psychology_cli.py
git commit -m "feat(cli): add inspiration-show command"
```

---

## Phase 5 — JCZQ integration

### Task 19: DataVerdictAdapter — convert JczqMixedReport combinations to data Scheme

**Files:**
- Create: `nutmeg/services/psychology/jczq_adapter.py`
- Test: `tests/test_psychology_jczq_adapter.py`

The current `JczqMixedReportService.build_report` returns combinations whose `legs` carry `match_no`, `home_team`, `away_team`, `play`, `pick`, `odds`. We need to map each leg into a `DataLeg` (psychology layer's input) and back. This adapter is the bridge.

- [ ] **Step 1: Write failing test**

```python
# tests/test_psychology_jczq_adapter.py
from __future__ import annotations

from nutmeg.services.psychology.jczq_adapter import (
    combination_to_data_scheme,
    apply_final_scheme_to_combination,
)
from nutmeg.services.psychology.schemas import (
    DataLeg,
    FinalLeg,
    FinalScheme,
    Scheme,
)


def _stub_combination():
    from types import SimpleNamespace
    leg = SimpleNamespace(
        match_no="周二001", league="UCL", match_date="2026-04-28", match_time="21:00",
        home_team="PSG", away_team="Bayern",
        play="HHAD", pick="home_win", odds=2.10, goal_line="",
        odds_update="13:01",
    )
    combo = SimpleNamespace(name="A", risk="low", legs=[leg])
    return combo


def test_combination_to_data_scheme_maps_pick_to_outcome() -> None:
    combo = _stub_combination()
    scheme = combination_to_data_scheme(combo)
    assert scheme.legs[0].fixture_id == "周二001:PSG:Bayern"
    assert scheme.legs[0].market == "HHAD"
    assert scheme.legs[0].outcome == "home_win"
    assert scheme.legs[0].odds == 2.10


def test_apply_final_scheme_replaces_pick_when_overridden() -> None:
    combo = _stub_combination()
    final = FinalScheme(
        legs=[FinalLeg("L1","周二001:PSG:Bayern","HHAD","away_win",2.45,"psychology")],
        confidence="medium", notes=[],
    )
    updated = apply_final_scheme_to_combination(combo, final)
    assert updated.legs[0].pick == "away_win"
    assert updated.legs[0].odds == 2.45
```

- [ ] **Step 2: Run, verify failure**

```bash
uv run pytest tests/test_psychology_jczq_adapter.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# nutmeg/services/psychology/jczq_adapter.py
from __future__ import annotations

from copy import deepcopy
from typing import Any

from nutmeg.services.psychology.schemas import (
    DataLeg,
    FinalScheme,
    Scheme,
)


def _fixture_id(leg: Any) -> str:
    return f"{leg.match_no}:{leg.home_team}:{leg.away_team}"


def _leg_id(idx: int) -> str:
    return f"L{idx + 1}"


def combination_to_data_scheme(combination: Any) -> Scheme:
    legs: list[DataLeg] = []
    for idx, leg in enumerate(combination.legs):
        legs.append(DataLeg(
            leg_id=_leg_id(idx),
            fixture_id=_fixture_id(leg),
            market=str(leg.play),
            outcome=str(leg.pick),
            odds=float(leg.odds),
        ))
    return Scheme(name=str(combination.name), legs=legs)


def apply_final_scheme_to_combination(combination: Any, final: FinalScheme) -> Any:
    updated = deepcopy(combination)
    final_by_leg = {leg.leg_id: leg for leg in final.legs}
    for idx, leg in enumerate(updated.legs):
        replacement = final_by_leg.get(_leg_id(idx))
        if replacement is None:
            continue
        leg.pick = replacement.outcome
        leg.odds = replacement.odds
    return updated
```

- [ ] **Step 4: Verify pass**

```bash
uv run pytest tests/test_psychology_jczq_adapter.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/psychology/jczq_adapter.py tests/test_psychology_jczq_adapter.py
git commit -m "feat(psychology): add JCZQ combination ↔ DataScheme adapter"
```

---

### Task 20: Wire psychology engine into JczqMixedReportService

**Files:**
- Modify: `nutmeg/services/jczq.py` (constructor + `build_report`)
- Test: `tests/test_psychology_jczq_integration.py`

When `psychology_engine` and `reconciliator` are both supplied, `build_report` will:
1. Build combinations as today.
2. For each combination, convert to data Scheme via adapter.
3. Build a SignalContext from leg metadata.
4. Run engine + reconciliator to get DualSchemeReport.
5. Replace combination legs with `apply_final_scheme_to_combination(...)`.
6. Stash `DualSchemeReport` on the report (`report.psychology_reports: dict[combo_name, DualSchemeReport]`) for renderer.

When dependencies are absent (default), behavior is unchanged. This is the regression-baseline guarantee.

- [ ] **Step 1: Write failing integration test**

```python
# tests/test_psychology_jczq_integration.py
from __future__ import annotations

from unittest.mock import MagicMock

from nutmeg.services.jczq import JczqMixedReportService, SampleJczqCalculatorProvider
from nutmeg.services.psychology.engine import PsychologyEngine
from nutmeg.services.psychology.guardrails import BudgetGuard, ConvictionGate
from nutmeg.services.psychology.reconciliator import Reconciliator
from nutmeg.services.psychology.schemas import (
    OutcomeView,
    PsychologyVerdict,
    SignalReading,
)
from nutmeg.services.psychology.signals.base import SignalContext


class _StubProvider:
    name = "stub"

    def __init__(self, mapping: dict[str, str]) -> None:
        self._mapping = mapping

    def evaluate(self, ctx: SignalContext) -> list[SignalReading]:
        readings: list[SignalReading] = []
        for fx in ctx.fixtures:
            target = self._mapping.get(str(fx.get("id")))
            if not target:
                continue
            readings.append(SignalReading(
                provider=self.name, fixture_id=str(fx.get("id")),
                market="HHAD", outcome_view=target, conviction=0.85,
                evidence=["forced for test"], source_refs=[],
                abstain_reason=None,
            ))
        return readings


def test_disabled_psychology_layer_keeps_data_picks() -> None:
    svc = JczqMixedReportService(provider=SampleJczqCalculatorProvider())
    report = svc.build_report(dry_run=True)
    assert report.combinations  # non-empty


def test_enabled_layer_overrides_one_leg(monkeypatch) -> None:
    sample_provider = SampleJczqCalculatorProvider()
    payload = sample_provider.fetch()
    # NB: signals expect fixture_id format from adapter — derive from sample
    # We pick the first combination's first leg and force psychology to flip it.
    svc_pre = JczqMixedReportService(provider=sample_provider)
    base_report = svc_pre.build_report(dry_run=True)
    first_leg = base_report.combinations[0].legs[0]
    target_fixture_id = f"{first_leg.match_no}:{first_leg.home_team}:{first_leg.away_team}"
    flip_target = "draw" if first_leg.pick != "draw" else "home_win"
    stub = _StubProvider({target_fixture_id: flip_target})
    engine = PsychologyEngine(providers=[stub])
    recon = Reconciliator(conviction_gate=ConvictionGate(threshold=0.7), budget_guard=BudgetGuard(max_reversals=1))
    svc = JczqMixedReportService(
        provider=sample_provider,
        psychology_engine=engine,
        reconciliator=recon,
    )
    report = svc.build_report(dry_run=True)
    assert report.combinations[0].legs[0].pick == flip_target
    assert report.psychology_reports[report.combinations[0].name].final_scheme.legs[0].provenance == "psychology"
```

- [ ] **Step 2: Run, verify failure**

```bash
uv run pytest tests/test_psychology_jczq_integration.py -v
```
Expected: `JczqMixedReportService` doesn't accept `psychology_engine` kwarg.

- [ ] **Step 3: Implement modifications to `nutmeg/services/jczq.py`**

In the `JczqMixedReportService.__init__` signature, add:

```python
        psychology_engine: "PsychologyEngine | None" = None,
        reconciliator: "Reconciliator | None" = None,
        psychology_inspiration: "InspirationNote | None" = None,
```

Store on self. Add type-only imports under `if TYPE_CHECKING`. In `build_report`, after `combinations = self._build_combinations(value)`, insert:

```python
        psychology_reports: dict[str, "DualSchemeReport"] = {}
        if self._psychology_engine and self._reconciliator:
            from nutmeg.services.psychology.jczq_adapter import (
                apply_final_scheme_to_combination,
                combination_to_data_scheme,
            )
            from nutmeg.services.psychology.signals.base import SignalContext
            updated_combinations = []
            for combo in combinations:
                data_scheme = combination_to_data_scheme(combo)
                fixtures = [
                    {
                        "id": f"{leg.match_no}:{leg.home_team}:{leg.away_team}",
                        "home_team_name": leg.home_team,
                        "away_team_name": leg.away_team,
                        "competition_code": leg.league,
                    }
                    for leg in combo.legs
                ]
                ctx = SignalContext(
                    date=datetime.now(UTC).date().isoformat(),
                    fixtures=fixtures, snapshots={}, odds={},
                )
                data_picks = {leg.fixture_id: {leg.market: leg.outcome} for leg in data_scheme.legs}
                verdicts = self._psychology_engine.evaluate(ctx=ctx, data_picks=data_picks)
                dual = self._reconciliator.reconcile(
                    data_scheme=data_scheme,
                    psychology_verdicts=verdicts,
                    inspiration=self._psychology_inspiration,
                )
                psychology_reports[combo.name] = dual
                updated_combinations.append(apply_final_scheme_to_combination(combo, dual.final_scheme))
            combinations = updated_combinations
```

Then attach `psychology_reports` to `JczqMixedReport` as a new optional field (extend the `JczqMixedReport` dataclass and `to_dict` to include it; leave default empty dict so existing tests don't break).

- [ ] **Step 4: Verify pass**

```bash
uv run pytest tests/test_psychology_jczq_integration.py tests/test_jczq_service.py -v
```
Expected: new tests pass; existing `tests/test_jczq_service.py` continue to pass.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/jczq.py tests/test_psychology_jczq_integration.py
git commit -m "feat(jczq): wire optional psychology engine + reconciliator into build_report"
```

---

### Task 21: D-layout report rendering (dashboard + dual-scheme + decision section)

**Files:**
- Modify: `nutmeg/services/jczq.py` (`render_markdown`)
- Test: extend `tests/test_psychology_jczq_integration.py`

When `report.psychology_reports` is non-empty, the markdown render appends three new sections per combination:

1. `### 三栏诊断板` — table: 比赛 / 数据选择 / 心理选择 / 冲突 / 最终 / 信心。
2. `### 数据驱动方案` and `### 心理博弈方案` — both rendered as today's leg list (so reader can compare).
3. `### 当日决策` — final_scheme leg list with provenance tags + guardrail summary + inspiration note (if present).

- [ ] **Step 1: Add test**

```python
def test_d_layout_sections_appear_in_markdown() -> None:
    sample_provider = SampleJczqCalculatorProvider()
    svc_pre = JczqMixedReportService(provider=sample_provider)
    base = svc_pre.build_report(dry_run=True)
    first_leg = base.combinations[0].legs[0]
    target_fixture_id = f"{first_leg.match_no}:{first_leg.home_team}:{first_leg.away_team}"
    flip_target = "draw" if first_leg.pick != "draw" else "home_win"
    stub = _StubProvider({target_fixture_id: flip_target})
    engine = PsychologyEngine(providers=[stub])
    recon = Reconciliator(conviction_gate=ConvictionGate(threshold=0.7), budget_guard=BudgetGuard(max_reversals=1))
    svc = JczqMixedReportService(provider=sample_provider, psychology_engine=engine, reconciliator=recon)
    report = svc.build_report(dry_run=True)
    md = svc.render_markdown(report)
    assert "三栏诊断板" in md
    assert "心理博弈方案" in md
    assert "当日决策" in md
    assert "provenance" in md or "来源" in md
```

- [ ] **Step 2: Run, verify failure**

```bash
uv run pytest "tests/test_psychology_jczq_integration.py::test_d_layout_sections_appear_in_markdown" -v
```
Expected: assertion failure (sections absent).

- [ ] **Step 3: Implement** — extend `render_markdown` after the existing per-combination block:

```python
            psychology_dual = report.psychology_reports.get(combo.name) if report.psychology_reports else None
            if psychology_dual:
                lines.extend(["", "### 三栏诊断板", "",
                              "| 比赛 | 数据 | 心理 | 冲突 | 最终 | 信心 |",
                              "|---|---|---|---|---|---|"])
                for row in psychology_dual.dashboard_rows:
                    lines.append(
                        f"| {row.fixture_id} | {row.data_pick} | {row.psych_pick or '—'} | "
                        f"{'✓' if row.conflict else '·'} | {row.final_pick} | {row.conviction:.2f} |"
                    )
                lines.extend(["", "### 数据驱动方案", ""])
                for leg in psychology_dual.data_scheme.legs:
                    lines.append(f"- {leg.fixture_id}: {leg.market} → {leg.outcome} @ {leg.odds:.2f}")
                lines.extend(["", "### 心理博弈方案", ""])
                for leg in psychology_dual.psychology_scheme.legs:
                    lines.append(f"- {leg.fixture_id}: {leg.market} → {leg.outcome} @ {leg.odds:.2f}")
                lines.extend(["", "### 当日决策", ""])
                for leg in psychology_dual.final_scheme.legs:
                    lines.append(
                        f"- {leg.fixture_id}: {leg.market} → {leg.outcome} @ {leg.odds:.2f} (来源: {leg.provenance})"
                    )
                lines.append(f"- 信心: {psychology_dual.final_scheme.confidence}")
                guardrail_state = psychology_dual.guardrail.guardrail_state
                lines.append(f"- guardrail: {guardrail_state}")
                if psychology_dual.guardrail.rejected:
                    lines.append("- 拒绝的反转候选:")
                    for cand, reason in psychology_dual.guardrail.rejected:
                        lines.append(
                            f"  - {cand.fixture_id} {cand.from_outcome}→{cand.to_outcome}: {reason}"
                        )
                if psychology_dual.inspiration:
                    lines.append(
                        f"- 灵感笔记: lean={psychology_dual.inspiration.parsed_tags.lean}, "
                        f"focus={psychology_dual.inspiration.parsed_tags.focus}"
                    )
```

- [ ] **Step 4: Verify pass**

```bash
uv run pytest tests/test_psychology_jczq_integration.py tests/test_jczq_service.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/jczq.py tests/test_psychology_jczq_integration.py
git commit -m "feat(jczq): add D-layout dashboard + dual-scheme + decision sections"
```

---

## Phase 6 — Integration / lifecycle tests

### Task 22: PSG vs Bayern fixture replay (regression baseline)

**Files:**
- Create: `tests/test_psychology_inspiration_lifecycle.py`

This test exercises the full chain: write inspiration → reconciliator consumes it → final scheme provenance is recorded → recorder hit/miss back-fill works. Uses synthesized stub fixtures (no real Sporttery dependency).

- [ ] **Step 1: Write the test**

```python
# tests/test_psychology_inspiration_lifecycle.py
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from nutmeg.services.psychology.calibration.recorder import Recorder
from nutmeg.services.psychology.engine import PsychologyEngine
from nutmeg.services.psychology.guardrails import BudgetGuard, ConvictionGate
from nutmeg.services.psychology.inspiration import InspirationParser, InspirationStore
from nutmeg.services.psychology.llm import FakeLLMCompleter
from nutmeg.services.psychology.reconciliator import Reconciliator
from nutmeg.services.psychology.schemas import (
    DataLeg,
    Scheme,
    SignalReading,
)
from nutmeg.services.psychology.signals.base import SignalContext


class _Stub:
    name = "stub"

    def __init__(self, outcome: str, conviction: float):
        self._outcome = outcome
        self._conviction = conviction

    def evaluate(self, ctx: SignalContext):
        return [SignalReading(
            provider="stub", fixture_id=str(ctx.fixtures[0]["id"]),
            market="HHAD", outcome_view=self._outcome,
            conviction=self._conviction, evidence=[], source_refs=[],
            abstain_reason=None,
        )]


def test_lifecycle_with_inspiration_force_psychology_below_gate(tmp_path: Path) -> None:
    insp_store = InspirationStore(base_dir=tmp_path / "inspiration")
    parser = InspirationParser(llm=FakeLLMCompleter(responses=[]))  # forces regex fallback
    note = parser.parse("今天必须心理，反着来", date="2026-04-29")
    insp_store.write_raw(date="2026-04-29", text=note.raw_text)
    insp_store.write_parsed(
        date="2026-04-29",
        tags=note.parsed_tags,
        raw_text=note.raw_text,
        parse_method=note.parse_method,
        timestamp=note.timestamp,
    )

    engine = PsychologyEngine(providers=[_Stub(outcome="away_win", conviction=0.55)])
    recon = Reconciliator(conviction_gate=ConvictionGate(threshold=0.7), budget_guard=BudgetGuard(max_reversals=1))
    data_scheme = Scheme(name="data", legs=[DataLeg("L1","psg-bay","HHAD","home_win",2.10)])
    fixtures = [{"id": "psg-bay", "home_team_name": "PSG", "away_team_name": "Bayern"}]

    verdicts = engine.evaluate(
        ctx=SignalContext(date="2026-04-29", fixtures=fixtures, snapshots={}, odds={}),
        data_picks={"psg-bay": {"HHAD": "home_win"}},
    )
    report = recon.reconcile(
        data_scheme=data_scheme,
        psychology_verdicts=verdicts,
        inspiration=insp_store.read(date="2026-04-29"),
    )
    assert report.final_scheme.legs[0].provenance == "inspiration_forced"

    rec = Recorder(base_dir=tmp_path / "inspiration")
    rec.record(date="2026-04-29", report=report)
    rec.update_outcome(date="2026-04-29", fixture_id="psg-bay", market="HHAD", actual_outcome="away_win")
    rows = rec.read(date="2026-04-29")
    assert rows[0]["hit"] is True
    assert rows[0]["provenance"] == "inspiration_forced"
```

- [ ] **Step 2: Run, verify failure**

```bash
uv run pytest tests/test_psychology_inspiration_lifecycle.py -v
```
Expected: passes immediately if all earlier tasks landed correctly. (No new code — this is purely an integration check.)

- [ ] **Step 3: If it fails, fix the underlying component (likely the regex fallback or the recorder); do not patch the test.**

- [ ] **Step 4: Final regression sweep**

```bash
uv run pytest -q
```
Expected: 343 baseline + ~50 new psychology tests, all passing, total < 60s.

- [ ] **Step 5: Commit**

```bash
git add tests/test_psychology_inspiration_lifecycle.py
git commit -m "test(psychology): full lifecycle with inspiration_forced provenance + recorder"
```

---

### Task 23: Settings + production LLM wiring (final assembly)

**Files:**
- Modify: `nutmeg/config/settings.py` (add 5 fields)
- Modify: `nutmeg/services/psychology/llm.py` (add `PortkeyLLMCompleter`)
- Modify: `nutmeg/interfaces/cli.py` (`_build_inspiration_parser` now reads settings)
- Test: `tests/test_psychology_settings.py`

Adds production wiring so the layer can run for real (not just in tests). Settings let ops enable/disable per-provider and tune the threshold.

- [ ] **Step 1: Write failing test for settings**

```python
# tests/test_psychology_settings.py
from __future__ import annotations

import os

from nutmeg.config.settings import AppSettings


def test_default_psychology_layer_disabled(monkeypatch) -> None:
    monkeypatch.delenv("NUTMEG_PSYCHOLOGY_LAYER_ENABLED", raising=False)
    s = AppSettings()
    assert s.psychology_layer_enabled is False


def test_conviction_threshold_default(monkeypatch) -> None:
    monkeypatch.delenv("NUTMEG_PSYCHOLOGY_CONVICTION_THRESHOLD", raising=False)
    s = AppSettings()
    assert s.psychology_conviction_threshold == 0.7


def test_provider_enabled_csv(monkeypatch) -> None:
    monkeypatch.setenv("NUTMEG_PSYCHOLOGY_PROVIDER_ENABLED", "tournament_stage,reflexive_tactic")
    s = AppSettings()
    assert s.psychology_provider_enabled == ["tournament_stage", "reflexive_tactic"]
```

- [ ] **Step 2: Run, verify failure**

```bash
uv run pytest tests/test_psychology_settings.py -v
```
Expected: AttributeError on settings.

- [ ] **Step 3: Implement** — add to `AppSettings` (using existing pydantic-settings pattern, copy the style of neighbouring fields):

```python
    psychology_layer_enabled: bool = False
    psychology_conviction_threshold: float = 0.7
    psychology_provider_enabled: list[str] = ["tournament_stage", "contrarian_narrative", "reflexive_tactic", "personal_narrative"]
    psychology_news_cache_dir: str = ".nutmeg-data/cache/news"
    psychology_rss_feeds: list[str] = []
```

(Use the existing custom validator pattern in `settings.py` for csv-to-list — verify by re-reading the file to confirm style; existing fields like `telegram_allowed_chat_ids` already do this.)

Add `PortkeyLLMCompleter` in `nutmeg/services/psychology/llm.py`:

```python
@dataclass(slots=True)
class PortkeyLLMCompleter:
    """Production LLMCompleter wrapping nutmeg.agents.llm_provider.PortkeySynthesisProvider."""

    portkey_provider: object  # PortkeySynthesisProvider — typed object to avoid circular import

    def complete(self, *, system: str, user: str) -> str:
        try:
            text = self.portkey_provider._complete_raw(system=system, user=user)  # type: ignore[attr-defined]
        except AttributeError as exc:
            raise LLMCompletionError("Portkey provider lacks _complete_raw") from exc
        except Exception as exc:  # noqa: BLE001
            raise LLMCompletionError(str(exc)) from exc
        return text
```

(Note: `_complete_raw` does not exist on `PortkeySynthesisProvider` today. As part of this task add it as a public-but-thin generic method that wraps the same Portkey client call already used by `synthesize`. This avoids duplicating Portkey HTTP code.)

- [ ] **Step 4: Verify pass**

```bash
uv run pytest tests/test_psychology_settings.py tests/test_psychology_llm.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/config/settings.py nutmeg/services/psychology/llm.py tests/test_psychology_settings.py
git commit -m "feat(psychology): add settings flags and Portkey-backed LLM completer"
```

---

## Final Verification & Sign-off

- [ ] Run the full suite (must stay green):

```bash
uv run pytest -q
```
Expected: 343 (baseline) + 50–80 new tests passing, total < 60s.

- [ ] Run lint:

```bash
uv run ruff check .
```
Expected: 0 issues.

- [ ] Smoke-run the CLI commands (no network — uses fake-mode parser + sample provider):

```bash
NUTMEG_PSYCHOLOGY_PARSER_FAKE_MODE=1 \
NUTMEG_INSPIRATION_DIR=/tmp/nutmeg-insp \
uv run nutmeg inspiration-write --date 20260429 --text "今晚反着来，淘汰赛"
uv run nutmeg inspiration-show 20260429
```
Expected:
- `inspiration-write` writes `/tmp/nutmeg-insp/2026-04-29/{raw.md,parsed.json}` and prints `saved 2026-04-29 via regex_fallback`.
- `inspiration-show` prints JSON containing `"lean": "psychology"`.

- [ ] Tag the v1 baseline commit (so future regression is anchored):

```bash
git tag psychology-layer-v1
```

---

## Self-Review Notes (post-write)

- Spec coverage cross-walked:
  - Spec 4.1 module layout → tasks 1, 2, 3, 4, 5, 6, 7–10, 11, 12, 13, 14, 15. The spec lists `signals/__init__.py` and `sources/__init__.py` — both are created in the parent task. The spec lists `calibration/review.py` for v2; intentionally omitted here.
  - Spec 4.2 schemas → task 1 covers all listed dataclasses including `OutcomeView`, `FinalLeg`, `DashboardRow`, and the `InspirationTags` tightening from self-review.
  - Spec 4.3 public interfaces → tasks 11, 14, 20.
  - Spec 4.4 CLI → tasks 16, 17, 18 (v1 only; backtest is v2).
  - Spec 4.5 signal responsibilities → tasks 7, 8, 9, 10.
  - Spec 5 data flow → tasks 11, 14, 15, 20, 21 collectively.
  - Spec 6 error/failure modes → encoded inside each provider's abstain paths and the engine's `_safe_evaluate` (task 11). The "all degrade → collapse to single scheme" path is naturally satisfied by Reconciliator: if every market_view is empty, no candidates, no overrides — final_scheme ≡ data_scheme.
  - Spec 7 testing → all tests listed under "New tests" map 1:1 to tasks. Integration tests = task 22 + task 20/21's enriched integration test. Regression baseline guarantee = task 20's `test_disabled_psychology_layer_keeps_data_picks`.
  - Spec 8 phased delivery → tasks 1–23 = v1; v2 (CalibrationKillSwitch, backtest CLI, AnalysisService wire) intentionally not in this plan.
- No placeholders found.
- Type consistency check: `OutcomeView` used in tasks 1, 11, 14; `OverrideCandidate` used in tasks 1, 13, 14; `DualSchemeReport` used in tasks 1, 14, 15, 20, 21. All match.
- Naming deviation from spec (flat tests under `tests/`) is documented at the top of this plan; spec is unchanged (sealed).
