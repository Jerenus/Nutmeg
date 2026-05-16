# JCZQ 锐书赔率冲突引擎 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a 500.com European-odds scraper that feeds the existing `cross_check_signals` engine into the daily brief, with a conflict-signal store and an evidence-scaled stake ladder.

**Architecture:** A new `Five00EuropeanOddsProvider` scrapes 500.com (schedule page → match_id → 欧赔 detail pages), implementing the **already-existing** `EuropeanOddsReferenceProvider` protocol in `nutmeg/data/european_odds.py`. Its `EuropeanOddsQuote`s feed the **already-existing** `cross_check_signals()`; resulting `CrossCheckSignal`s render in a new brief section, persist to a conflict-signal store, get graded by the daily review, and drive a stake ladder.

**Tech Stack:** Python 3.12, httpx, pytest. Reuses `nutmeg/data/european_odds.py`.

**Spec:** `docs/superpowers/specs/2026-05-16-jczq-odds-conflict-engine-design.md`

> **⚠ Task 1 is a recon spike.** 500.com's real HTML/JSON structure cannot be known until fetched from a 500.com-reachable machine (plain curl from a non-CN host returns ~empty). Tasks 2-4 (parsers) are TDD'd against the fixtures Task 1 records. If Task 1 finds 500.com is only reachable via a headless browser, STOP and revise — that is a new-dependency decision for the user.

---

## File Structure

- `nutmeg/services/jczq_odds_reference.py` — **new** — `Five00EuropeanOddsProvider` + `parse_schedule` + `parse_ouzhi`.
- `nutmeg/services/jczq_conflict_store.py` — **new** — conflict-signal persistence + grading + stake ladder.
- `nutmeg/data/european_odds.py` — **existing, reused unchanged** — `cross_check_signals`, `EuropeanOddsQuote`, `CrossCheckSignal`, `EuropeanOddsReferenceProvider`.
- `nutmeg/services/jczq_brief.py` — **modify** — add `build_sporttery_implied` + render "锐书冲突点" section.
- `nutmeg/services/jczq_review.py` — **modify** — grade conflict legs into the store.
- `tests/fixtures/jczq/500_*.html`, `tests/fixtures/jczq/500_structure.md` — **new** — recorded HTML + structure note.
- `tests/test_jczq_odds_reference.py`, `tests/test_jczq_conflict_store.py` — **new**.

---

### Task 1: Recon 500.com data acquisition (spike — no TDD)

**Files:**
- Create: `tests/fixtures/jczq/500_schedule.html`
- Create: `tests/fixtures/jczq/500_ouzhi.html`
- Create: `tests/fixtures/jczq/500_structure.md`

- [ ] **Step 1: Fetch the JCZQ schedule page** (run on a machine that can reach 500.com)

```bash
curl -s -A "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15" \
  -H "Referer: https://www.500.com/" --compressed \
  "https://live.500.com/jczq.php" -o tests/fixtures/jczq/500_schedule.html
wc -c tests/fixtures/jczq/500_schedule.html
```
If the file is near-empty: open `live.500.com/jczq.php` in a browser, use devtools Network tab to find the XHR/JSON endpoint that populates the match list, and save that response instead (note its URL).

- [ ] **Step 2: Pick one match_id and fetch its 欧赔 page**

From the schedule, find a 周六NNN match's numeric 500.com `match_id`, then:
```bash
curl -s -A "Mozilla/5.0 ..." "https://odds.500.com/fenxi/ouzhi-<MATCH_ID>.shtml" \
  -o tests/fixtures/jczq/500_ouzhi.html
```

- [ ] **Step 3: Check whether a 大小球 (over/under) odds page exists**

On the same match's odds page, look for a 大小球 tab/URL (e.g. `dxq-<id>.shtml`). If it exists, `curl` it to `tests/fixtures/jczq/500_dxq.html`. Record the result — it decides whether `ttg` conflict is in v1 or deferred.

- [ ] **Step 4: Write the structure note**

Create `tests/fixtures/jczq/500_structure.md` documenting: page encoding (likely `gb18030`/`gbk`); how `周六NNN → match_id` is located in the schedule HTML/JSON; the `ouzhi` page odds-table layout (which rows are bookmakers, which columns are 主胜/平/客胜, decimal vs fractional); whether the 大小球 page exists and its structure.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/jczq/
git commit -m "test(jczq): record 500.com recon fixtures for conflict engine"
```

> **FORK:** If Steps 1-2 only succeed via a headless browser (no HTTP/JSON path), stop here and report — adding a headless-browser dependency is a decision for the user, and Tasks 2-4 must be revised.

---

### Task 2: Parse the 500.com schedule into a match_id map

**Files:**
- Create: `nutmeg/services/jczq_odds_reference.py`
- Test: `tests/test_jczq_odds_reference.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path
from nutmeg.services.jczq_odds_reference import parse_schedule

_FIX = Path(__file__).parent / "fixtures" / "jczq"

def test_parse_schedule_returns_match_id_map():
    html = (_FIX / "500_schedule.html").read_text(encoding="gb18030", errors="replace")
    result = parse_schedule(html)
    assert isinstance(result, dict) and result, "should return a non-empty dict"
    import re
    for match_no, match_id in result.items():
        assert re.fullmatch(r"周[一二三四五六日]\d{3}", match_no), match_no
        assert re.fullmatch(r"\d+", str(match_id)), match_id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_jczq_odds_reference.py::test_parse_schedule_returns_match_id_map -v`
Expected: FAIL — `ImportError` / `parse_schedule` not defined.

- [ ] **Step 3: Implement `parse_schedule`**

In `nutmeg/services/jczq_odds_reference.py`, implement `parse_schedule(html: str) -> dict[str, str]` returning `{周六NNN: match_id}`. Use the selectors/regex documented in `tests/fixtures/jczq/500_structure.md` from Task 1. Follow the regex-parsing style of `OkoooJczqResultProvider._parse_result_rows` in `jczq_review.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_jczq_odds_reference.py::test_parse_schedule_returns_match_id_map -v` — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/jczq_odds_reference.py tests/test_jczq_odds_reference.py
git commit -m "feat(jczq): parse 500.com schedule into match_id map"
```

---

### Task 3: Parse a 500.com 欧赔 page into EuropeanOddsQuote list

**Files:**
- Modify: `nutmeg/services/jczq_odds_reference.py`
- Test: `tests/test_jczq_odds_reference.py`

- [ ] **Step 1: Write the failing test**

```python
from nutmeg.data.european_odds import EuropeanOddsQuote
from nutmeg.services.jczq_odds_reference import parse_ouzhi

def test_parse_ouzhi_returns_had_quotes():
    html = (_FIX / "500_ouzhi.html").read_text(encoding="gb18030", errors="replace")
    quotes = parse_ouzhi(html, match_no="周六001")
    assert quotes, "should return at least one quote"
    assert all(isinstance(q, EuropeanOddsQuote) for q in quotes)
    assert all(q.match_no == "周六001" and q.pool == "had" for q in quotes)
    assert all(q.pick in {"胜", "平", "负"} for q in quotes)
    assert all(q.price > 1.0 for q in quotes)
    # multi-bookmaker: at least 3 distinct bookmakers
    assert len({q.bookmaker for q in quotes}) >= 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_jczq_odds_reference.py::test_parse_ouzhi_returns_had_quotes -v`
Expected: FAIL — `parse_ouzhi` not defined.

- [ ] **Step 3: Implement `parse_ouzhi`**

Implement `parse_ouzhi(html: str, match_no: str) -> list[EuropeanOddsQuote]`. Per `500_structure.md`: iterate bookmaker rows, read the 主胜/平/客胜 decimal columns, emit one `EuropeanOddsQuote(match_no, bookmaker, pool="had", pick, price)` per (bookmaker, pick). Skip rows that fail to parse rather than raising.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_jczq_odds_reference.py::test_parse_ouzhi_returns_had_quotes -v` — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/jczq_odds_reference.py tests/test_jczq_odds_reference.py
git commit -m "feat(jczq): parse 500.com 欧赔 page into EuropeanOddsQuote list"
```

---

### Task 4: `Five00EuropeanOddsProvider` — orchestration, caching, fault tolerance

**Files:**
- Modify: `nutmeg/services/jczq_odds_reference.py`
- Test: `tests/test_jczq_odds_reference.py`

- [ ] **Step 1: Write the failing test** (injected fetcher — no real network)

```python
from nutmeg.domain.jczq_daily import JczqDailyMatch
from nutmeg.services.jczq_odds_reference import Five00EuropeanOddsProvider

def _match(no): return JczqDailyMatch(
    match_no=no, match_date="2026-05-16", match_time="21:30:00", league="德甲",
    home_team="H", away_team="A", status="Selling", hot_direction="", role="",
    confidence_note="", candidates=[])

def test_provider_returns_quotes_via_injected_fetcher():
    sched = (_FIX / "500_schedule.html").read_text(encoding="gb18030", errors="replace")
    ouzhi = (_FIX / "500_ouzhi.html").read_text(encoding="gb18030", errors="replace")
    def fake_get(url: str) -> str:
        return sched if "jczq" in url else ouzhi
    provider = Five00EuropeanOddsProvider(get=fake_get)
    # use a match_no that exists in the recorded schedule fixture
    quotes = provider.quotes_for([_match("周六001")])
    assert all(q.pool == "had" for q in quotes)

def test_provider_returns_empty_on_fetch_failure():
    def boom(url: str) -> str:
        raise RuntimeError("network down")
    provider = Five00EuropeanOddsProvider(get=boom)
    assert provider.quotes_for([_match("周六001")]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_jczq_odds_reference.py -k provider -v`
Expected: FAIL — `Five00EuropeanOddsProvider` not defined.

- [ ] **Step 3: Implement the provider**

```python
import httpx
from collections.abc import Callable, Iterable
from nutmeg.domain.jczq_daily import JczqDailyMatch
from nutmeg.data.european_odds import EuropeanOddsQuote

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15"

def _default_get(url: str) -> str:
    resp = httpx.get(url, headers={"User-Agent": _UA, "Referer": "https://www.500.com/"},
                     timeout=20.0, follow_redirects=True)
    resp.raise_for_status()
    return resp.content.decode("gb18030", errors="replace")

class Five00EuropeanOddsProvider:
    """Implements european_odds.EuropeanOddsReferenceProvider via 500.com scraping."""
    _SCHEDULE_URL = "https://live.500.com/jczq.php"
    _OUZHI_URL = "https://odds.500.com/fenxi/ouzhi-{mid}.shtml"

    def __init__(self, *, get: Callable[[str], str] = _default_get) -> None:
        self._get = get

    def quotes_for(self, matches: Iterable[JczqDailyMatch]) -> list[EuropeanOddsQuote]:
        wanted = {m.match_no for m in matches}
        try:
            id_map = parse_schedule(self._get(self._SCHEDULE_URL))
        except Exception:
            return []
        quotes: list[EuropeanOddsQuote] = []
        for match_no, mid in id_map.items():
            if match_no not in wanted:
                continue
            try:
                html = self._get(self._OUZHI_URL.format(mid=mid))
                quotes.extend(parse_ouzhi(html, match_no))
            except Exception:
                continue  # per-match fault tolerance
        return quotes
```
(Disk caching to `.nutmeg-data/jczq/daily/<date>/european-odds.json` is added in Task 6 where the run-date is in scope.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_jczq_odds_reference.py -v` — Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/jczq_odds_reference.py tests/test_jczq_odds_reference.py
git commit -m "feat(jczq): Five00EuropeanOddsProvider orchestration + fault tolerance"
```

---

### Task 5: `build_sporttery_implied` — vig-free implied probabilities for had

**Files:**
- Modify: `nutmeg/services/jczq_brief.py`
- Test: `tests/test_jczq_brief_conflict.py` (new)

- [ ] **Step 1: Write the failing test**

```python
from nutmeg.domain.jczq_daily import JczqDailyMatch, JczqDailyLeg
from nutmeg.services.jczq_brief import build_sporttery_implied

def _leg(no, pick, odds):
    return JczqDailyLeg(match_no=no, league="德甲", home_team="H", away_team="A",
                        pool="had", play="胜平负", pick=pick, odds=odds, logic="")

def test_build_sporttery_implied_devigs_had():
    m = JczqDailyMatch(match_no="周六001", match_date="2026-05-16", match_time="21:30:00",
        league="德甲", home_team="H", away_team="A", status="Selling", hot_direction="",
        role="", confidence_note="",
        candidates=[_leg("周六001","胜",2.0), _leg("周六001","平",3.5), _leg("周六001","负",4.0)])
    out = build_sporttery_implied([m])
    probs = out["周六001"]
    total = sum(probs.values())
    assert abs(total - 1.0) < 1e-9, "vig-free probs must sum to 1"
    assert probs[("had","胜")] > probs[("had","平")] > probs[("had","负")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_jczq_brief_conflict.py::test_build_sporttery_implied_devigs_had -v`
Expected: FAIL — `build_sporttery_implied` not defined.

- [ ] **Step 3: Implement `build_sporttery_implied`**

```python
def build_sporttery_implied(matches):
    """{match_no: {(pool, pick): vig_free_prob}} for the had pool."""
    out: dict[str, dict[tuple[str, str], float]] = {}
    for m in matches:
        had = {leg.pick: leg.odds for leg in m.candidates
               if leg.pool == "had" and leg.odds and leg.odds > 0}
        if set(had) != {"胜", "平", "负"}:
            continue
        raw = {pick: 1.0 / odds for pick, odds in had.items()}
        total = sum(raw.values())
        out[m.match_no] = {("had", pick): r / total for pick, r in raw.items()}
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_jczq_brief_conflict.py::test_build_sporttery_implied_devigs_had -v` — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/jczq_brief.py tests/test_jczq_brief_conflict.py
git commit -m "feat(jczq): build_sporttery_implied vig-free had probabilities"
```

---

### Task 6: Render the "锐书冲突点" brief section

**Files:**
- Modify: `nutmeg/services/jczq_brief.py`
- Test: `tests/test_jczq_brief_conflict.py`

- [ ] **Step 1: Write the failing test**

```python
from nutmeg.data.european_odds import EuropeanOddsQuote
from nutmeg.services.jczq_brief import render_conflict_section

def test_render_conflict_section_lists_signals_and_coverage():
    sporttery = {"周六001": {("had","胜"):0.40, ("had","平"):0.28, ("had","负"):0.32}}
    quotes = [
        EuropeanOddsQuote("周六001","Pinnacle","had","胜",2.10),
        EuropeanOddsQuote("周六001","Bet365","had","胜",2.05),
        EuropeanOddsQuote("周六001","William Hill","had","胜",2.08),
    ]
    text = render_conflict_section(sporttery, quotes, covered={"周六001"}, uncovered={"周六007"})
    assert "锐书冲突点" in text
    assert "周六001" in text          # a signal row
    assert "周六007" in text          # coverage note: no european data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_jczq_brief_conflict.py::test_render_conflict_section_lists_signals_and_coverage -v`
Expected: FAIL — `render_conflict_section` not defined.

- [ ] **Step 3: Implement `render_conflict_section`**

In `jczq_brief.py`, implement `render_conflict_section(sporttery_implied, european_quotes, *, covered, uncovered) -> str`. It calls `cross_check_signals(sporttery_implied, european_quotes)` from `nutmeg.data.european_odds`, renders a markdown table `## 锐书冲突点` (columns: 编号 / 池 / pick / 体彩隐含 / 欧赔隐含 / delta / dispersion), then a coverage line listing `covered` vs `uncovered` match counts. Sort rows by `abs(delta)` desc.

- [ ] **Step 4: Wire it into `build_brief`**

In the brief-assembly function, after Section 4 (Poisson +EV table): build matches → `build_sporttery_implied`; instantiate `Five00EuropeanOddsProvider`; `quotes = provider.quotes_for(matches)`; cache quotes to `.nutmeg-data/jczq/daily/<run_date>/european-odds.json`; `covered = {q.match_no for q in quotes}`; `uncovered = {m.match_no for m in matches} - covered`; append `render_conflict_section(...)`. Wrap the provider call in try/except → on failure append a line "锐书数据不可用，本日跳过冲突检测".

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_jczq_brief_conflict.py -v` — Expected: PASS. Then `uv run pytest tests/ -k brief -v` — Expected: existing brief tests still PASS.

- [ ] **Step 6: Commit**

```bash
git add nutmeg/services/jczq_brief.py tests/test_jczq_brief_conflict.py
git commit -m "feat(jczq): render 锐书冲突点 brief section via cross_check_signals"
```

---

### Task 7: Conflict-signal store — persist + grade

**Files:**
- Create: `nutmeg/services/jczq_conflict_store.py`
- Test: `tests/test_jczq_conflict_store.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path
from nutmeg.data.european_odds import CrossCheckSignal
from nutmeg.services.jczq_conflict_store import ConflictStore

def _sig(no): return CrossCheckSignal(no, "had", "胜", 0.32, 0.40, 0.03, 0.08)

def test_store_round_trips_and_grades(tmp_path: Path):
    store = ConflictStore(tmp_path / "conflict-signals.json")
    store.record("2026-05-16", [_sig("周六001")], sporttery_odds={"周六001": 3.10})
    store.grade("2026-05-16", results={"周六001": "胜"})
    rows = store.load()
    assert len(rows) == 1
    assert rows[0]["hit"] is True
    assert abs(rows[0]["realized_return"] - 3.10) < 1e-9

def test_store_grade_miss_returns_zero(tmp_path: Path):
    store = ConflictStore(tmp_path / "c.json")
    store.record("2026-05-16", [_sig("周六001")], sporttery_odds={"周六001": 3.10})
    store.grade("2026-05-16", results={"周六001": "负"})
    assert store.load()[0]["realized_return"] == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_jczq_conflict_store.py -v` — Expected: FAIL — `ConflictStore` not defined.

- [ ] **Step 3: Implement `ConflictStore`**

```python
import json
from dataclasses import asdict
from pathlib import Path
from nutmeg.data.european_odds import CrossCheckSignal

class ConflictStore:
    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    def load(self) -> list[dict]:
        if not self._path.exists():
            return []
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return []

    def _save(self, rows: list[dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    def record(self, date: str, signals: list[CrossCheckSignal],
               *, sporttery_odds: dict[str, float]) -> None:
        rows = self.load()
        for s in signals:
            rows.append({"date": date, **asdict(s),
                         "sporttery_odds": sporttery_odds.get(s.match_no),
                         "hit": None, "realized_return": None})
        self._save(rows)

    def grade(self, date: str, *, results: dict[str, str]) -> None:
        rows = self.load()
        for row in rows:
            if row["date"] != date or row["hit"] is not None:
                continue
            actual = results.get(row["match_no"])
            if actual is None:
                continue
            row["hit"] = (actual == row["pick"])
            odds = row.get("sporttery_odds") or 0.0
            row["realized_return"] = odds if row["hit"] else 0.0
        self._save(rows)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_jczq_conflict_store.py -v` — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/jczq_conflict_store.py tests/test_jczq_conflict_store.py
git commit -m "feat(jczq): conflict-signal store with record + grade"
```

---

### Task 8: Stake ladder — evidence-scaled phase resolution

**Files:**
- Modify: `nutmeg/services/jczq_conflict_store.py`
- Test: `tests/test_jczq_conflict_store.py`

- [ ] **Step 1: Write the failing test**

```python
from nutmeg.services.jczq_conflict_store import resolve_stake_phase

def test_stake_phase_ladder():
    assert resolve_stake_phase(graded_count=5,  rolling_roi=1.2).name == "OBSERVE"
    assert resolve_stake_phase(graded_count=20, rolling_roi=1.05).name == "SMALL"
    assert resolve_stake_phase(graded_count=50, rolling_roi=1.10).name == "NORMAL"
    assert resolve_stake_phase(graded_count=30, rolling_roi=0.90).name == "KILL"
    # KILL takes precedence over SMALL/NORMAL when ROI is bad
    assert resolve_stake_phase(graded_count=50, rolling_roi=0.90).name == "KILL"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_jczq_conflict_store.py::test_stake_phase_ladder -v`
Expected: FAIL — `resolve_stake_phase` not defined.

- [ ] **Step 3: Implement `resolve_stake_phase`**

```python
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class StakePhase:
    name: str               # OBSERVE / SMALL / NORMAL / KILL
    max_pct_per_signal: float
    note: str

def resolve_stake_phase(*, graded_count: int, rolling_roi: float) -> StakePhase:
    if graded_count >= 25 and rolling_roi < 0.95:
        return StakePhase("KILL", 0.0, "暂停 — 滚动 ROI < 0.95，复审 thesis")
    if graded_count >= 40 and rolling_roi > 1.05:
        return StakePhase("NORMAL", 0.30, "冲突腿可作主仓")
    if graded_count >= 15 and rolling_roi > 1.0:
        return StakePhase("SMALL", 0.10, "小注 5-10% 日预算")
    return StakePhase("OBSERVE", 0.02, "观察期 — 纸面或 ≤2%/信号")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_jczq_conflict_store.py::test_stake_phase_ladder -v` — Expected: PASS.

- [ ] **Step 5: Add a `phase()` convenience on `ConflictStore`**

Add method `phase(self) -> StakePhase`: from `self.load()`, take graded rows (`hit is not None`), `graded_count = len(graded)`, `rolling_roi = sum(realized_return) / graded_count` (guard divide-by-zero → ROI 1.0 when count 0), return `resolve_stake_phase(...)`.

- [ ] **Step 6: Run tests + commit**

Run: `uv run pytest tests/test_jczq_conflict_store.py -v` — Expected: PASS.
```bash
git add nutmeg/services/jczq_conflict_store.py tests/test_jczq_conflict_store.py
git commit -m "feat(jczq): stake-phase ladder driven by conflict-signal ROI"
```

---

### Task 9: Review integration — grade conflict signals on the next-day review

**Files:**
- Modify: `nutmeg/services/jczq_review.py`
- Test: `tests/test_jczq_review.py` (add to existing)

- [ ] **Step 1: Write the failing test**

```python
def test_review_grades_conflict_store(tmp_path):
    from nutmeg.data.european_odds import CrossCheckSignal
    from nutmeg.services.jczq_conflict_store import ConflictStore
    store = ConflictStore(tmp_path / "conflict-signals.json")
    store.record("2026-05-15",
                 [CrossCheckSignal("周五001","had","负",0.30,0.40,0.04,0.05)],
                 sporttery_odds={"周五001": 3.10})
    # had result for 周五001 on 2026-05-15 was 负 (see review fixture)
    from nutmeg.services.jczq_review import grade_conflict_store
    grade_conflict_store(store, run_date="2026-05-15",
                         results={"周五001": {"had": "负"}})
    assert store.load()[0]["hit"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_jczq_review.py::test_review_grades_conflict_store -v`
Expected: FAIL — `grade_conflict_store` not defined.

- [ ] **Step 3: Implement `grade_conflict_store`**

In `jczq_review.py`, add `grade_conflict_store(store, *, run_date, results)`: map `results` (the review's per-match per-pool winners) into `{match_no: winning_had_pick}`, call `store.grade(run_date, results=...)`. Then call it from `JczqDailyReviewService` after results are fetched, using `ConflictStore(output_dir / "memory" / "conflict-signals.json")`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_jczq_review.py -v` — Expected: PASS (new + existing).

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/jczq_review.py tests/test_jczq_review.py
git commit -m "feat(jczq): grade conflict-signal store on daily review"
```

---

### Task 10: Full-suite verification

- [ ] **Step 1: Run the whole suite**

Run: `uv run pytest tests/ -q` — Expected: all PASS (existing count + the new conflict-engine tests).

- [ ] **Step 2: Smoke-test the brief** (on a 500.com-reachable machine)

Run: `uv run nutmeg jczq-daily-brief --date <today>` — Expected: a `## 锐书冲突点` section renders (with signals, or a graceful "锐书数据不可用" line).

- [ ] **Step 3: Commit any fixes, then update AGENTS.md**

Add a short "锐书冲突引擎" entry to `AGENTS.md` describing the new brief section + the OBSERVE/SMALL/NORMAL/KILL stake ladder, so the daily SOP reflects it.

```bash
git add AGENTS.md
git commit -m "docs(jczq): document 锐书冲突引擎 in AGENTS SOP"
```

---

## ttg (总进球) — deferred follow-on

Per spec §4 & §6.3b, `ttg` conflict is included only if Task 1 finds a usable 500.com 大小球 page. If so, add a follow-on task group: `parse_dxq` (over/under lines) → difference into bucket probabilities (clamp negatives, renormalize) → feed `cross_check_signals` with `pool="ttg"`. If Task 1 finds no 大小球 page, ttg stays out of v1 — had-only ships.

## Notes for the executing engineer

- `nutmeg/data/european_odds.py` is **done** — do not reimplement `cross_check_signals`, `EuropeanOddsQuote`, `CrossCheckSignal`. Import and use them.
- Chinese-site scraping pattern is established in `OkoooJczqResultProvider` (`jczq_review.py`): `httpx` + `gb18030` decode + regex row parsing. Mirror it.
- Every network-touching component degrades to empty/`[]` on failure — the brief must never crash because 500.com is down.
- This is an OBSERVE-phase launch: the engine produces signals; stakes stay tiny until the store accumulates ≥15-40 graded signals with ROI > 1.0.
