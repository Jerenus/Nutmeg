# Bold-Combo Multi-Market Extension Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the delivered bold-combo engine from 胜平负-only to four 体彩 markets (胜平负 / 让球 / 总进球 / 比分), so it assembles cross-market 3/4/5-fold parlays — keeping the welded 🎲 entertainment label and no-edge framing.

**Architecture:** The 比分 (crs) market is the finest-grained 体彩 market; 胜平负/总进球/让球 are deterministic aggregations of the scoreline distribution. A new pure module `nutmeg/services/jczq_bold_markets.py` de-vigs the 体彩 crs odds and aggregates them — the basis of the new 「盘口内部一致性冲突」 signal (体彩 disagreeing with itself). 总进球 also gets a true external reference from a new `parse_over_under` (国际大小球). `jczq_bold_combos.py` gains a per-market boldness composition with per-market weight normalization, cross-market leg selection, and a Rule-O cross-market combination generator. The complete 体彩 market is sourced from the Sporttery `getMatchCalculatorV1` API and persisted as a per-day snapshot so `--replay` is reproducible. **No predictive model is imported.**

**Tech Stack:** Python 3.13, `uv run pytest`, existing `nutmeg/data/fcom500.py` parsers, Typer CLI.

**Spec:** `docs/superpowers/specs/2026-05-18-bold-combo-multimarket-design.md`

---

## Scope note

This extends `2026-05-18-bold-combo-engine-design.md` (v1, delivered). All v1 hard constraints carry over and must stay green: the welded `HARD_LABEL`, no advantage wording (`胜率/edge/+EV/正期望/推荐下注/重仓`), and no predictive-model import. v1's 39 `tests/test_jczq_bold_combos.py` tests must keep passing — every change is **additive** (new `BoldMatch` fields default empty; a had-only `BoldMatch` scores exactly as in v1).

## Data reality (verified — see spec §1, §8)

- **完整体彩盘**: Sporttery `getMatchCalculatorV1.qry?channel=c&poolCode=had,hhad,ttg,crs,hafu`. Each `subMatchList` match carries flat pool dicts: `had`/`hhad` = `{h,d,a,...}`, `ttg` = `{s0..s7, sNf,...}`, `crs` = `{s00s00.., s1sh/s1sd/s1sa, ...f}`. `goalLine` lives on the `hhad` pool. Quota-free.
- **国际欧赔** (胜平负): `parse_european_1x2` (existing, has `opening_odds` + `per_book_odds`).
- **国际大小球** (总进球外部参照): `daxiao-{fid}.shtml`, same datatb shape as 亚盘 — a new `parse_over_under`.
- 让球/比分 have **no** clean international odds on 500.com — the internal-consistency signal covers them.

## File Structure

- `nutmeg/data/fcom500.py` — **modify**: add `_daxiao_url`, `parse_over_under`, `_safe_parse_page`, `collect_bold_odds` (returns raw `MarketOdds`, keeping opening/per-book odds the conflict-engine provider discards).
- `nutmeg/services/jczq_bold_markets.py` — **create**: pure 体彩 market math — crs scoreline de-vig + aggregation to had/ttg/hhad + ttg→over/under. No I/O, no model.
- `nutmeg/services/jczq_bold_combos.py` — **modify**: market vocabulary, `BoldMatch` multi-market fields, `BoldLeg.market`/`pick_label`, `internal_conflict`/`external_conflict_ttg`, per-market boldness with normalized weights, cross-market leg selection + Rule-O combos, Sporttery loader + snapshot I/O, renderer market labels.
- `nutmeg/interfaces/cli/jczq.py` — **modify**: `jczq-bold-combos` — live fetch + snapshot persist, `--replay` from snapshot.
- `tests/test_fcom500.py` — **modify**: `parse_over_under` test.
- `tests/test_jczq_bold_markets.py` — **create**: aggregation tests.
- `tests/test_jczq_bold_combos.py` — **modify**: multi-market signal / composition / combo / loader tests.
- `tests/test_cli.py` — **modify**: `jczq-bold-combos` multi-market smoke test.

---

## Task 1: 大小球 parser — `parse_over_under`

**Files:** Modify `nutmeg/data/fcom500.py`; Test `tests/test_fcom500.py`

The 大小球 (daxiao) page has the same `id="datatb"` bookmaker-row shape as 亚盘: each international row's first `pl_table_data` is `[<td>over</td>, <td ref="-N.NN">line</td>, <td>under</td>]`. Reuse `_book_rows` + `_parse_line_table`. The bold engine's 总进球 external-conflict + dispersion signals need this.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_fcom500.py`:

```python
def test_parse_over_under_reads_international_daxiao() -> None:
    from nutmeg.data.fcom500 import parse_over_under

    html = (FIXTURES / "daxiao-1366371.html").read_text(encoding="gb2312", errors="ignore")
    market = parse_over_under(html)

    assert market is not None
    assert market.independent is True
    assert market.odds["over"] > 0 and market.odds["under"] > 0
    # line is the median over/under line, a positive numeric string.
    assert float(market.line) > 0
    # fair probabilities de-vig to ~1 over the 2-way market.
    assert abs(sum(market.fair_probability.values()) - 1.0) < 1e-6
    # per-book odds feed the dispersion signal — one entry per international book.
    assert len(market.per_book_odds["over"]) == market.bookmaker_count
    assert market.bookmaker_count >= 2
```

`FIXTURES` is the existing module-level `Path` to `tests/fixtures/fcom500/` in that file — confirm it exists at the top of `tests/test_fcom500.py`; if the constant has another name, use that name.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fcom500.py::test_parse_over_under_reads_international_daxiao -v`
Expected: FAIL — `ImportError: cannot import name 'parse_over_under'`.

- [ ] **Step 3: Write minimal implementation**

In `nutmeg/data/fcom500.py`, after `_ouzhi_url` add:

```python
def _daxiao_url(fid: str) -> str:
    return f"https://odds.500.com/fenxi/daxiao-{fid}.shtml"
```

After `parse_handicap` add:

```python
def parse_over_under(html: str) -> MarketOdds | None:
    """Parse the 大小球 (daxiao) page into average international over/under odds.

    Same datatb shape as 亚盘: each international bookmaker row's first
    ``pl_table_data`` is ``[over_odds, <td ref>line</td>, under_odds]``. Excludes
    the 竞彩官方 (体彩) row — the result is a true 体彩-independent signal.
    ``line`` is the median over/under line (magnitude — the ``ref`` is signed).
    ``per_book_odds`` carries each book's over/under for the dispersion signal.
    Returns ``None`` when no international row parses.
    """
    over: list[float] = []
    under: list[float] = []
    lines: list[float] = []
    for row_id, body in _book_rows(html):
        if row_id == _SPORTTERY_ROW_ID:
            continue
        first_table = _RE_PL_TABLE.search(body)
        if not first_table:
            continue
        parsed = _parse_line_table(first_table.group(0))
        if parsed is None:
            continue
        over_odds, under_odds, line_value, _text = parsed
        if over_odds <= 0 or under_odds <= 0:
            continue
        over.append(over_odds)
        under.append(under_odds)
        lines.append(abs(line_value))

    if not over:
        return None
    odds = {
        "over": round(sum(over) / len(over), 4),
        "under": round(sum(under) / len(under), 4),
    }
    lines.sort()
    median_line = lines[len(lines) // 2]
    return MarketOdds(
        odds=odds,
        fair_probability=_devig(odds),
        independent=True,
        line=f"{median_line:g}",
        bookmaker_count=len(over),
        per_book_odds={"over": over, "under": under},
    )
```

Add `"parse_over_under"` to the module `__all__` list.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_fcom500.py -v`
Expected: PASS (the new test + all existing fcom500 tests).

- [ ] **Step 5: Commit**

```bash
git add nutmeg/data/fcom500.py tests/test_fcom500.py
git commit -m "feat(fcom500): parse_over_under — international 大小球 odds"
```

## Task 2: Bold-engine odds collector — `collect_bold_odds`

**Files:** Modify `nutmeg/data/fcom500.py`; Test `tests/test_fcom500.py`

`Fcom500OddsProvider.collect()` maps parsed odds onto domain `MarketOddsSnapshot` objects, which **drop** `opening_odds` + `per_book_odds` — so the bold engine's drift/dispersion signals get nothing from it. The bold engine needs the **raw** `MarketOdds`. Add a dedicated collector returning raw `MarketOdds` for 欧赔 + 大小球.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_fcom500.py`:

```python
def test_collect_bold_odds_returns_raw_market_odds() -> None:
    from nutmeg.data.fcom500 import MarketOdds, collect_bold_odds

    list_html = (FIXTURES / "jczq-list.html").read_text(encoding="gb2312", errors="ignore")
    ouzhi = (FIXTURES / "ouzhi-1366371.html").read_text(encoding="gb2312", errors="ignore")
    daxiao = (FIXTURES / "daxiao-1366371.html").read_text(encoding="gb2312", errors="ignore")

    class FakeClient:
        def get(self, url: str) -> str:
            if "trade.500.com/jczq" in url:
                return list_html
            if "ouzhi-1366371" in url:
                return ouzhi
            if "daxiao-1366371" in url:
                return daxiao
            raise RuntimeError(f"unexpected fetch: {url}")

    result = collect_bold_odds(FakeClient())

    # 周日001 (fid 1366371) has both pages → both raw markets, with per-book odds.
    entry = result["周日001"]
    assert isinstance(entry["match_winner"], MarketOdds)
    assert isinstance(entry["over_under"], MarketOdds)
    assert entry["match_winner"].per_book_odds["home"]      # opening/per-book kept
    assert entry["over_under"].per_book_odds["over"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fcom500.py::test_collect_bold_odds_returns_raw_market_odds -v`
Expected: FAIL — `ImportError: cannot import name 'collect_bold_odds'`.

- [ ] **Step 3: Write minimal implementation**

In `nutmeg/data/fcom500.py`, after `parse_over_under` add:

```python
def _safe_parse_page(client: Fcom500Client, url: str, parser) -> MarketOdds | None:
    """Fetch + parse one analysis page, degrading to ``None`` on any error."""
    try:
        html = client.get(url)
    except Exception:  # noqa: BLE001 — a missing page degrades that market
        logger.warning("fcom500: fetch failed for %s — market degraded", url)
        return None
    try:
        return parser(html)
    except Exception:  # noqa: BLE001 — a parse failure degrades that market
        logger.warning("fcom500: parse failed for %s — market degraded", url)
        return None


def collect_bold_odds(client: Fcom500Client) -> dict[str, dict[str, MarketOdds]]:
    """Collect the bold engine's 国际 odds as raw ``MarketOdds`` per match.

    Returns ``{match_no: {"match_winner": MarketOdds, "over_under": MarketOdds}}``.
    Unlike ``Fcom500OddsProvider`` (which maps to domain ``MarketOddsSnapshot``
    and drops opening/per-book odds), this keeps the raw ``MarketOdds`` so the
    bold engine's drift + dispersion signals have their inputs. Any page
    fetch/parse failure degrades that match/market — never crashes.
    """
    try:
        list_html = client.get(_JCZQ_LIST_URL)
    except Exception:  # noqa: BLE001 — degrade, never crash
        logger.warning("fcom500: 竞彩 list fetch failed — no bold odds", exc_info=True)
        return {}
    result: dict[str, dict[str, MarketOdds]] = {}
    for match in parse_jczq_list(list_html):
        entry: dict[str, MarketOdds] = {}
        euro = _safe_parse_page(client, _ouzhi_url(match.fid), parse_european_1x2)
        if euro is not None:
            entry["match_winner"] = euro
        over_under = _safe_parse_page(client, _daxiao_url(match.fid), parse_over_under)
        if over_under is not None:
            entry["over_under"] = over_under
        if entry:
            result[match.match_no] = entry
    return result
```

Add `"collect_bold_odds"` to `__all__`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_fcom500.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/data/fcom500.py tests/test_fcom500.py
git commit -m "feat(fcom500): collect_bold_odds — raw MarketOdds for the bold engine"
```

## Task 3: 比分 scoreline distribution + crs→胜平负 aggregation

**Files:** Create `nutmeg/services/jczq_bold_markets.py`; Create `tests/test_jczq_bold_markets.py`

The 体彩 crs pool keys are `sHHsAA` (zero-padded exact scoreline, e.g. `s02s01` = 2:1) plus three lumped 其他 buckets `s1sh` (胜其他) / `s1sd` (平其他) / `s1sa` (负其他). De-vig all of them into a scoreline distribution; crs→had aggregation is clean (every outcome has a definite 主/平/客 sign, including the 其他 buckets).

- [ ] **Step 1: Write the failing test**

Create `tests/test_jczq_bold_markets.py`:

```python
"""Tests for the bold engine's 体彩 multi-market math (pure, no I/O)."""

from nutmeg.services.jczq_bold_markets import (
    aggregate_crs_to_had,
    crs_scoreline_distribution,
)


def test_crs_scoreline_distribution_devigs_exact_and_other() -> None:
    # Three exact scorelines + one 其他 bucket; equal odds → equal de-vigged mass.
    crs_odds = {"s01s00": 4.0, "s00s00": 4.0, "s00s01": 4.0, "s1sa": 4.0}

    exact, other = crs_scoreline_distribution(crs_odds)

    assert set(exact) == {(1, 0), (0, 0), (0, 1)}
    assert set(other) == {"away"}
    total = sum(exact.values()) + sum(other.values())
    assert abs(total - 1.0) < 1e-9          # de-vigged over ALL crs outcomes
    assert abs(exact[(1, 0)] - 0.25) < 1e-9


def test_aggregate_crs_to_had_sums_by_sign() -> None:
    # 1:0 → home, 0:0 → draw, 0:1 → away, 其他负 → away. Equal mass 0.25 each.
    crs_odds = {"s01s00": 4.0, "s00s00": 4.0, "s00s01": 4.0, "s1sa": 4.0}

    had = aggregate_crs_to_had(*crs_scoreline_distribution(crs_odds))

    assert abs(had["home"] - 0.25) < 1e-9
    assert abs(had["draw"] - 0.25) < 1e-9
    assert abs(had["away"] - 0.50) < 1e-9   # 0:1 + 其他负
    assert abs(sum(had.values()) - 1.0) < 1e-9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_jczq_bold_markets.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nutmeg.services.jczq_bold_markets'`.

- [ ] **Step 3: Write minimal implementation**

Create `nutmeg/services/jczq_bold_markets.py`:

```python
"""体彩 multi-market math for the bold-combo engine — pure, no I/O, no model.

The 比分 (crs) market is the finest-grained 体彩 market: 胜平负 / 总进球 / 让球
are each a deterministic aggregation of the scoreline distribution. These
helpers de-vig the 体彩 crs odds and aggregate them — the basis of the spec §3
「盘口内部一致性冲突」 signal (the 体彩 board disagreeing with itself).

This module imports NO predictive model and performs NO I/O.
"""

from __future__ import annotations

import re

# A crs odds key is an exact scoreline ``sHHsAA`` (zero-padded goal counts) ...
_RE_CRS_EXACT = re.compile(r"^s(\d{2})s(\d{2})$")
# ... or a lumped 其他 bucket: ``s1sh`` 胜其他 / ``s1sd`` 平其他 / ``s1sa`` 负其他.
_RE_CRS_OTHER = re.compile(r"^s1s([hda])$")
# 其他 bucket letter → the 胜平负 outcome it unambiguously belongs to.
_CRS_OTHER_TO_HAD: dict[str, str] = {"h": "home", "d": "draw", "a": "away"}

# 总进球 buckets — total_0..total_7 (total_7 is the 7+ bucket). Mirrors the
# Sporttery ttg pool keys s0..s7.
TTG_BUCKETS: tuple[str, ...] = tuple(f"total_{k}" for k in range(8))


def crs_scoreline_distribution(
    crs_odds: dict[str, float],
) -> tuple[dict[tuple[int, int], float], dict[str, float]]:
    """De-vig a 体彩 crs pool into a scoreline distribution.

    ``crs_odds`` maps raw Sporttery crs keys (``sHHsAA`` exact, ``s1sX`` 其他;
    the ``...f`` flag keys must already be excluded by the caller) to decimal
    odds. Returns ``(exact, other)``: ``exact`` maps ``(home_goals,
    away_goals)`` → probability, ``other`` maps ``"home"/"draw"/"away"`` →
    probability for the lumped 其他 buckets. The two together de-vig to sum ~1.
    Empty / unusable input → two empty dicts (graceful degradation).
    """
    inverse_exact: dict[tuple[int, int], float] = {}
    inverse_other: dict[str, float] = {}
    for key, odds in crs_odds.items():
        if not odds or odds <= 0:
            continue
        exact_m = _RE_CRS_EXACT.match(key)
        if exact_m:
            score = (int(exact_m.group(1)), int(exact_m.group(2)))
            inverse_exact[score] = 1.0 / odds
            continue
        other_m = _RE_CRS_OTHER.match(key)
        if other_m:
            inverse_other[_CRS_OTHER_TO_HAD[other_m.group(1)]] = 1.0 / odds
    total = sum(inverse_exact.values()) + sum(inverse_other.values())
    if total <= 0:
        return {}, {}
    exact = {k: v / total for k, v in inverse_exact.items()}
    other = {k: v / total for k, v in inverse_other.items()}
    return exact, other


def aggregate_crs_to_had(
    exact: dict[tuple[int, int], float], other: dict[str, float]
) -> dict[str, float]:
    """Aggregate a crs scoreline distribution into 胜平负 probabilities.

    Every crs outcome has a definite 主/平/客 sign — exact scorelines by
    ``home_goals`` vs ``away_goals``, the 其他 buckets by construction — so this
    aggregation is exact (spec §3: crs→had 聚合干净). Sums to ~1.
    """
    had = {"home": 0.0, "draw": 0.0, "away": 0.0}
    for (home_goals, away_goals), prob in exact.items():
        if home_goals > away_goals:
            had["home"] += prob
        elif home_goals == away_goals:
            had["draw"] += prob
        else:
            had["away"] += prob
    for outcome, prob in other.items():
        had[outcome] += prob
    return had
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_jczq_bold_markets.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/jczq_bold_markets.py tests/test_jczq_bold_markets.py
git commit -m "feat(bold-markets): crs scoreline de-vig + crs→胜平负 aggregation"
```

## Task 4: crs→总进球 / crs→让球 / 总进球→大小球 aggregation

**Files:** Modify `nutmeg/services/jczq_bold_markets.py`; Test `tests/test_jczq_bold_markets.py`

crs→ttg and crs→hhad aggregations exclude the 其他 buckets (no definite total / handicap side) and **re-normalize** over the exact mass — spec §3 marks these approximate. `aggregate_ttg_to_over_under` collapses a total-goals distribution onto a daxiao line.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_jczq_bold_markets.py`:

```python
from nutmeg.services.jczq_bold_markets import (
    aggregate_crs_to_hhad,
    aggregate_crs_to_ttg,
    aggregate_ttg_to_over_under,
)


def test_aggregate_crs_to_ttg_buckets_by_total_and_renormalizes() -> None:
    # 1:0 (total 1), 1:1 (total 2), 2:1 (total 3) — equal exact mass, plus an
    # 其他 bucket that must be DROPPED then re-normalized away.
    exact = {(1, 0): 0.25, (1, 1): 0.25, (2, 1): 0.25}
    other = {"home": 0.25}

    ttg = aggregate_crs_to_ttg(exact)

    assert set(ttg) == {f"total_{k}" for k in range(8)}
    assert abs(sum(ttg.values()) - 1.0) < 1e-9          # re-normalized over exact mass
    assert abs(ttg["total_1"] - 1 / 3) < 1e-9           # 0.25 / 0.75
    assert ttg["total_0"] == 0.0


def test_aggregate_crs_to_ttg_caps_at_total_7() -> None:
    ttg = aggregate_crs_to_ttg({(5, 3): 0.5, (4, 4): 0.5})  # totals 8 and 8
    assert abs(ttg["total_7"] - 1.0) < 1e-9               # 7+ bucket


def test_aggregate_crs_to_hhad_shifts_by_line() -> None:
    # line -1 (home gives 1): 2:0 → adj 1:0 让胜, 1:0 → adj 0:0 让平,
    # 0:1 → adj -1:1 让负. Equal mass.
    exact = {(2, 0): 1 / 3, (1, 0): 1 / 3, (0, 1): 1 / 3}

    hhad = aggregate_crs_to_hhad(exact, line=-1.0)

    assert abs(hhad["home"] - 1 / 3) < 1e-9
    assert abs(hhad["draw"] - 1 / 3) < 1e-9
    assert abs(hhad["away"] - 1 / 3) < 1e-9
    assert abs(sum(hhad.values()) - 1.0) < 1e-9


def test_aggregate_ttg_to_over_under_splits_on_line() -> None:
    ttg_fair = {f"total_{k}": 0.0 for k in range(8)}
    ttg_fair["total_1"] = 0.4   # under 2.5
    ttg_fair["total_2"] = 0.2   # under 2.5
    ttg_fair["total_3"] = 0.4   # over 2.5

    ou = aggregate_ttg_to_over_under(ttg_fair, line=2.5)

    assert abs(ou["over"] - 0.4) < 1e-9
    assert abs(ou["under"] - 0.6) < 1e-9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_jczq_bold_markets.py -v`
Expected: FAIL — `ImportError` for the new names.

- [ ] **Step 3: Write minimal implementation**

Append to `nutmeg/services/jczq_bold_markets.py`:

```python
def _renormalize(dist: dict[str, float]) -> dict[str, float]:
    """Scale a distribution to sum 1; an all-zero distribution is returned as-is."""
    total = sum(dist.values())
    if total <= 0:
        return dist
    return {k: v / total for k, v in dist.items()}


def aggregate_crs_to_ttg(exact: dict[tuple[int, int], float]) -> dict[str, float]:
    """Aggregate exact crs scorelines into 总进球 buckets total_0..total_7.

    Each scoreline contributes to bucket ``home+away`` (capped at total_7 = 7+).
    The 其他 buckets carry no definite total → excluded; the result is then
    re-normalized over the exact mass (spec §3: crs→ttg 聚合近似).
    """
    ttg = {bucket: 0.0 for bucket in TTG_BUCKETS}
    for (home_goals, away_goals), prob in exact.items():
        total = min(home_goals + away_goals, 7)
        ttg[f"total_{total}"] += prob
    return _renormalize(ttg)


def aggregate_crs_to_hhad(
    exact: dict[tuple[int, int], float], line: float
) -> dict[str, float]:
    """Aggregate exact crs scorelines into 让球胜平负 probabilities at ``line``.

    ``line`` is the home handicap in goals (negative when home gives goals, e.g.
    ``-1.0``). A scoreline covers 让胜 when ``home + line > away``, 让平 when
    equal, 让负 when less. 其他 buckets excluded; re-normalized over exact mass.
    """
    hhad = {"home": 0.0, "draw": 0.0, "away": 0.0}
    for (home_goals, away_goals), prob in exact.items():
        adjusted = home_goals + line
        if adjusted > away_goals:
            hhad["home"] += prob
        elif adjusted == away_goals:
            hhad["draw"] += prob
        else:
            hhad["away"] += prob
    return _renormalize(hhad)


def aggregate_ttg_to_over_under(
    ttg_fair: dict[str, float], line: float
) -> dict[str, float]:
    """Collapse a 总进球 distribution onto an over/under ``line``.

    ``ttg_fair`` maps total_0..total_7 → probability. A bucket's goal count
    above ``line`` is 大球, otherwise 小球 (total_7 counts as 7). Used to compare
    the 体彩 总进球 board against the international 大小球 board (spec §3 外部冲突).
    """
    over = 0.0
    under = 0.0
    for bucket, prob in ttg_fair.items():
        count = int(bucket.removeprefix("total_"))
        if count > line:
            over += prob
        else:
            under += prob
    return {"over": over, "under": under}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_jczq_bold_markets.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/jczq_bold_markets.py tests/test_jczq_bold_markets.py
git commit -m "feat(bold-markets): crs→总进球/让球 + 总进球→大小球 aggregation"
```

## Task 5: Market vocabulary + `BoldMatch`/`BoldLeg` multi-market fields

**Files:** Modify `nutmeg/services/jczq_bold_combos.py`; Test `tests/test_jczq_bold_combos.py`

Add the market vocabulary and extend the dataclasses. **Every new field defaults empty/`"had"`** — a v1 had-only `BoldMatch` stays valid and scores exactly as before (the v1 39 tests must stay green).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_jczq_bold_combos.py`:

```python
def test_market_vocabulary_constants() -> None:
    from nutmeg.services.jczq_bold_combos import (
        MARKET_LABELS,
        MARKET_SIGNALS,
        MARKETS,
    )

    assert MARKETS == ("had", "hhad", "ttg", "crs")
    # had has all five signals; hhad/crs three; ttg four (大小球 dispersion).
    assert set(MARKET_SIGNALS["had"]) == {
        "conflict", "contrarian", "drift", "dispersion", "heat",
    }
    assert set(MARKET_SIGNALS["hhad"]) == {"conflict", "contrarian", "heat"}
    assert set(MARKET_SIGNALS["ttg"]) == {
        "conflict", "contrarian", "dispersion", "heat",
    }
    assert set(MARKET_SIGNALS["crs"]) == {"conflict", "contrarian", "heat"}
    assert MARKET_LABELS == {
        "had": "胜平负", "hhad": "让球", "ttg": "总进球", "crs": "比分",
    }


def test_bold_match_multi_market_fields_default_empty() -> None:
    from nutmeg.services.jczq_bold_combos import BoldMatch

    # A v1-style had-only BoldMatch — multi-market fields default empty.
    match = BoldMatch(
        match_no="周一001", league="芬超", home="A", away="B",
        tc_odds={"home": 2.0, "draw": 3.2, "away": 3.5},
    )
    assert match.hhad_odds == {}
    assert match.ttg_odds == {}
    assert match.crs_odds == {}
    assert match.ou_odds == {}
    assert match.hhad_line == 0.0


def test_bold_leg_carries_market_and_label() -> None:
    from nutmeg.services.jczq_bold_combos import BoldLeg

    leg = BoldLeg(
        match_no="周一001", league="芬超", home="A", away="B",
        market="crs", pick="2:1", pick_label="2:1",
        tc_odds=7.5, boldness=0.4, reason="x",
    )
    assert leg.market == "crs"
    assert leg.pick_label == "2:1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_jczq_bold_combos.py::test_market_vocabulary_constants -v`
Expected: FAIL — `ImportError: cannot import name 'MARKETS'`.

- [ ] **Step 3: Write minimal implementation**

In `nutmeg/services/jczq_bold_combos.py`, after the `OUTCOMES` constant add:

```python
# --- Multi-market vocabulary (spec: bold-combo multi-market extension) ------
# The four 体彩 markets the engine scores.
MARKETS: tuple[str, ...] = ("had", "hhad", "ttg", "crs")

# Per market, the signals that are ACTIVE. The rest contribute 0 and take no
# weight (per-market weight normalization, spec §3 跨市场可比性). had has all
# five; hhad/crs have three; ttg has four (dispersion from the 大小球 books).
MARKET_SIGNALS: dict[str, tuple[str, ...]] = {
    "had": ("conflict", "contrarian", "drift", "dispersion", "heat"),
    "hhad": ("conflict", "contrarian", "heat"),
    "ttg": ("conflict", "contrarian", "dispersion", "heat"),
    "crs": ("conflict", "contrarian", "heat"),
}

# Human-readable market labels for the renderer.
MARKET_LABELS: dict[str, str] = {
    "had": "胜平负", "hhad": "让球", "ttg": "总进球", "crs": "比分",
}
```

In the `BoldMatch` dataclass, after the existing `vig` field add:

```python
    # --- multi-market 体彩 odds (default empty → engine scores 胜平负 only) ---
    hhad_odds: dict[str, float] = field(default_factory=dict)   # home/draw/away
    hhad_line: float = 0.0                                       # home handicap, goals
    ttg_odds: dict[str, float] = field(default_factory=dict)     # total_0..total_7
    crs_odds: dict[str, float] = field(default_factory=dict)     # raw sHHsAA / s1sX keys
    ou_odds: dict[str, float] = field(default_factory=dict)      # 国际大小球 over/under
    ou_line: float = 0.0
    ou_per_book: dict[str, list[float]] = field(default_factory=dict)
```

Replace the `BoldLeg` dataclass with:

```python
@dataclass(slots=True, frozen=True)
class BoldLeg:
    """One bold pick for one match in one market — the unit a parlay is built from.

    ``boldness`` is a heuristic salience score, NOT a probability. ``market`` is
    one of ``MARKETS``; ``pick`` is the internal outcome key; ``pick_label`` is
    the display string (胜 / 让平 / 3球 / 2:1). ``reason`` names the dominant
    board signal.
    """

    match_no: str
    league: str
    home: str
    away: str
    pick: str
    tc_odds: float
    boldness: float
    reason: str
    market: str = "had"
    pick_label: str = ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_jczq_bold_combos.py -v`
Expected: PASS — the 3 new tests + all 39 v1 tests (the v1 `bold_leg`/`anchor_ticket` still construct `BoldLeg` with the old positional args; `market`/`pick_label` default).

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/jczq_bold_combos.py tests/test_jczq_bold_combos.py
git commit -m "feat(bold-combos): market vocabulary + multi-market BoldMatch/BoldLeg fields"
```

## Task 6: Internal-consistency + external 总进球 conflict signals

**Files:** Modify `nutmeg/services/jczq_bold_combos.py`; Test `tests/test_jczq_bold_combos.py`

`internal_conflict(match, market)` compares the 体彩 board's **direct** quote against the value **derived by aggregating its own crs board** — the 体彩 disagreeing with itself. `external_conflict_ttg(match)` compares the 体彩 总进球 board against the international 大小球 board.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_jczq_bold_combos.py`:

```python
def test_internal_conflict_had_flags_crs_vs_had_disagreement() -> None:
    from nutmeg.services.jczq_bold_combos import BoldMatch, internal_conflict

    # 体彩 had board: home favorite (~0.5). 体彩 crs board: equal exact mass on
    # 1:0 / 0:0 / 0:1 → aggregates to home 1/3. The board contradicts itself.
    match = BoldMatch(
        match_no="周一001", league="芬超", home="A", away="B",
        tc_odds={"home": 1.9, "draw": 3.4, "away": 4.5},
        crs_odds={"s01s00": 3.0, "s00s00": 3.0, "s00s01": 3.0},
    )
    conflict = internal_conflict(match, "had")
    assert conflict["home"] > 0.05          # direct ~0.5 vs derived ~0.33
    assert set(conflict) == {"home", "draw", "away"}


def test_internal_conflict_is_zero_without_crs() -> None:
    from nutmeg.services.jczq_bold_combos import BoldMatch, internal_conflict

    match = BoldMatch(
        match_no="周一001", league="芬超", home="A", away="B",
        tc_odds={"home": 2.0, "draw": 3.2, "away": 3.5},
    )
    assert internal_conflict(match, "had") == {"home": 0.0, "draw": 0.0, "away": 0.0}


def test_external_conflict_ttg_compares_体彩_vs_国际大小球() -> None:
    from nutmeg.services.jczq_bold_combos import BoldMatch, external_conflict_ttg

    # 体彩 ttg leans under (total_1 cheap); 国际大小球 leans over → a real gap.
    match = BoldMatch(
        match_no="周一001", league="芬超", home="A", away="B",
        tc_odds={"home": 2.0, "draw": 3.2, "away": 3.5},
        ttg_odds={f"total_{k}": v for k, v in {
            0: 9.0, 1: 2.0, 2: 3.0, 3: 6.0, 4: 12.0, 5: 25.0, 6: 50.0, 7: 90.0,
        }.items()},
        ou_odds={"over": 1.6, "under": 2.4}, ou_line=2.5,
    )
    assert external_conflict_ttg(match) > 0.05


def test_external_conflict_ttg_zero_without_overunder() -> None:
    from nutmeg.services.jczq_bold_combos import BoldMatch, external_conflict_ttg

    match = BoldMatch(
        match_no="周一001", league="芬超", home="A", away="B",
        tc_odds={"home": 2.0, "draw": 3.2, "away": 3.5},
        ttg_odds={f"total_{k}": 5.0 for k in range(8)},
    )
    assert external_conflict_ttg(match) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_jczq_bold_combos.py::test_internal_conflict_had_flags_crs_vs_had_disagreement -v`
Expected: FAIL — `ImportError: cannot import name 'internal_conflict'`.

- [ ] **Step 3: Write minimal implementation**

In `nutmeg/services/jczq_bold_combos.py`, add the import near the top (after `import statistics`):

```python
from nutmeg.services.jczq_bold_markets import (
    aggregate_crs_to_had,
    aggregate_crs_to_hhad,
    aggregate_crs_to_ttg,
    aggregate_ttg_to_over_under,
    crs_scoreline_distribution,
)
```

After `heat_score` add:

```python
def _devig_map(odds: dict[str, float]) -> dict[str, float]:
    """De-vig an arbitrary-keyed odds map to fair probabilities summing to ~1.

    Generalizes ``_fair_from_odds`` (which is hard-coded to ``OUTCOMES``) to the
    总进球 / 让球 keyspaces. Empty / unusable input → empty dict.
    """
    inverse = {k: 1.0 / v for k, v in odds.items() if v and v > 0}
    total = sum(inverse.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in inverse.items()}


def internal_conflict(match: BoldMatch, market: str) -> dict[str, float]:
    """Per-outcome 盘口内部一致性冲突 for ``market`` — the 体彩 board's direct
    quote vs the value derived by aggregating its own crs board.

    ``market`` ∈ {"had", "hhad", "ttg"}. Returns ``{outcome_key: conflict}``,
    each ``abs(direct_fair - crs_derived_fair)`` clipped to [0, 1]. No crs board,
    or no direct quote → all-zero (graceful degradation). The crs market's own
    internal conflict is handled separately in ``_crs_internal_conflict``.
    """
    exact, other = crs_scoreline_distribution(match.crs_odds)
    if not exact and not other:
        outcomes = TTG_BUCKETS if market == "ttg" else OUTCOMES
        return {o: 0.0 for o in outcomes}
    if market == "had":
        derived = aggregate_crs_to_had(exact, other)
        direct = _fair_from_odds(match.had_odds_or_tc())
        keys = OUTCOMES
    elif market == "hhad":
        derived = aggregate_crs_to_hhad(exact, match.hhad_line)
        direct = _fair_from_odds(match.hhad_odds)
        keys = OUTCOMES
    elif market == "ttg":
        derived = aggregate_crs_to_ttg(exact)
        direct = _devig_map(match.ttg_odds)
        keys = TTG_BUCKETS
    else:  # pragma: no cover - defensive
        return {}
    if not direct:
        return {o: 0.0 for o in keys}
    return {
        o: _clip01(abs(direct.get(o, 0.0) - derived.get(o, 0.0))) for o in keys
    }


def external_conflict_ttg(match: BoldMatch) -> float:
    """Scalar 外部冲突 for 总进球 — the 体彩 总进球 board collapsed onto the 大小球
    line vs the international 大小球 board.

    Returns ``abs(体彩 P(over) - 国际 P(over))`` clipped to [0, 1]. No 体彩 ttg
    board, or no 国际大小球 → 0.0 (graceful degradation).
    """
    tc_ttg = _devig_map(match.ttg_odds)
    ou_fair = _devig_map(match.ou_odds)
    if not tc_ttg or not ou_fair or not match.ou_line:
        return 0.0
    tc_over_under = aggregate_ttg_to_over_under(tc_ttg, match.ou_line)
    return _clip01(abs(tc_over_under.get("over", 0.0) - ou_fair.get("over", 0.0)))
```

The `TTG_BUCKETS` name must be importable — add it to the `jczq_bold_markets` import line. And `BoldMatch` needs a `had_odds_or_tc()` helper so `tc_odds` (the v1 had field) is the had source. Add this method to the `BoldMatch` dataclass:

```python
    def had_odds_or_tc(self) -> dict[str, float]:
        """The 胜平负 体彩 odds — ``tc_odds`` IS the had market (v1 naming kept)."""
        return self.tc_odds
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_jczq_bold_combos.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/jczq_bold_combos.py tests/test_jczq_bold_combos.py
git commit -m "feat(bold-combos): 盘口内部一致性 + 外部总进球 conflict signals"
```

## Task 7: Per-market boldness composition + per-market bold leg

**Files:** Modify `nutmeg/services/jczq_bold_combos.py`; Test `tests/test_jczq_bold_combos.py`

`market_boldness(match, market)` composes that market's active signals with **per-market weight normalization** (active-signal weights sum to 1 — so had/hhad/ttg/crs boldness scores are same-scale comparable). `bold_leg_for_market` picks the boldest outcome in one market.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_jczq_bold_combos.py`:

```python
def test_market_boldness_weights_normalize_per_market() -> None:
    from nutmeg.services.jczq_bold_combos import BoldMatch, market_boldness

    # hhad has 3 active signals; with the heat term maxed and others 0 the
    # normalized heat weight is 1/3, so a heat of 1.0 → boldness 1/3.
    match = BoldMatch(
        match_no="周一001", league="芬超", home="A", away="B",
        tc_odds={"home": 2.0, "draw": 3.2, "away": 3.5},
        hhad_odds={"home": 2.5, "draw": 3.3, "away": 2.6}, hhad_line=-1.0,
        tags={"强胆场", "舒服盘", "coinflip", "draw_friendly"}, vig=0.20,
    )
    scores = market_boldness(match, "hhad")
    # heat clips to 1.0 (4 tags × 0.25); normalized hhad weight for heat = 1/3.
    assert all(abs(v - 1 / 3) < 0.34 for v in scores.values())
    assert set(scores) == {"home", "draw", "away"}


def test_bold_leg_for_market_picks_market_argmax() -> None:
    from nutmeg.services.jczq_bold_combos import BoldMatch, bold_leg_for_market

    # A 比分 leg — the coldest scoreline (longest odds) is the boldest pick.
    match = BoldMatch(
        match_no="周一001", league="芬超", home="拉赫蒂", away="瓦萨",
        tc_odds={"home": 2.0, "draw": 3.2, "away": 3.5},
        crs_odds={"s01s00": 6.0, "s00s00": 9.0, "s03s02": 41.0},
    )
    leg = bold_leg_for_market(match, "crs")
    assert leg is not None
    assert leg.market == "crs"
    assert leg.pick_label == "3:2"          # the coldest scoreline
    assert leg.tc_odds == 41.0


def test_bold_leg_for_market_returns_none_without_market_odds() -> None:
    from nutmeg.services.jczq_bold_combos import BoldMatch, bold_leg_for_market

    match = BoldMatch(
        match_no="周一001", league="芬超", home="A", away="B",
        tc_odds={"home": 2.0, "draw": 3.2, "away": 3.5},
    )
    assert bold_leg_for_market(match, "crs") is None    # no crs odds
    assert bold_leg_for_market(match, "had") is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_jczq_bold_combos.py::test_bold_leg_for_market_picks_market_argmax -v`
Expected: FAIL — `ImportError: cannot import name 'bold_leg_for_market'`.

- [ ] **Step 3: Write minimal implementation**

In `nutmeg/services/jczq_bold_combos.py`, after `bold_leg` add:

```python
# Weight lookup by signal name — for per-market normalization.
_SIGNAL_WEIGHTS: dict[str, float] = {
    "conflict": WEIGHT_CONFLICT,
    "contrarian": WEIGHT_CONTRARIAN,
    "drift": WEIGHT_DRIFT,
    "dispersion": WEIGHT_DISPERSION,
    "heat": WEIGHT_HEAT,
}

# crs pick label "H:A" from a raw sHHsAA key, and the 其他 buckets.
_CRS_OTHER_LABELS: dict[str, str] = {"s1sh": "胜其他", "s1sd": "平其他", "s1sa": "负其他"}
# ttg pick label from a total_K key.
_TTG_LABELS: dict[str, str] = {f"total_{k}": f"{k}球" for k in range(7)}
_TTG_LABELS["total_7"] = "7+球"
# hhad pick label.
_HHAD_LABELS: dict[str, str] = {"home": "让胜", "draw": "让平", "away": "让负"}


def _crs_pick_label(key: str) -> str:
    """Display label for a raw crs key: ``s02s01`` → ``2:1``, ``s1sh`` → 胜其他."""
    if key in _CRS_OTHER_LABELS:
        return _CRS_OTHER_LABELS[key]
    return f"{int(key[1:3])}:{int(key[4:6])}"


def _market_outcomes(match: BoldMatch, market: str) -> dict[str, float]:
    """The 体彩 decimal odds for ``market`` — keyed by that market's outcome keys.

    had/hhad → home/draw/away; ttg → total_0..total_7; crs → raw sHHsAA / s1sX
    keys (the ``...f`` flag keys are already excluded by the loader)."""
    if market == "had":
        return match.tc_odds
    if market == "hhad":
        return match.hhad_odds
    if market == "ttg":
        return match.ttg_odds
    return match.crs_odds


def _market_signal_scores(
    match: BoldMatch, market: str
) -> tuple[dict[str, dict[str, float]], float]:
    """Return ``(per_outcome_signals, heat)`` for ``market``.

    ``per_outcome_signals`` maps signal name → {outcome_key: score}; ``heat`` is
    the per-match scalar. Only the signals active for ``market`` are populated.
    """
    outcomes = _market_outcomes(match, market)
    keys = list(outcomes)
    fair = _devig_map(outcomes)
    active = MARKET_SIGNALS[market]
    signals: dict[str, dict[str, float]] = {}

    if "conflict" in active:
        if market == "had":
            signals["conflict"] = conflict_score(fair, _fair_from_odds(match.euro_odds))
        elif market == "crs":
            signals["conflict"] = _crs_internal_conflict(match)
        elif market == "ttg":
            internal = internal_conflict(match, "ttg")
            external = external_conflict_ttg(match)
            signals["conflict"] = {
                o: _clip01(internal.get(o, 0.0) + external) for o in keys
            }
        else:  # hhad
            signals["conflict"] = internal_conflict(match, "hhad")
    if "contrarian" in active:
        signals["contrarian"] = _generic_contrarian(fair, keys)
    if "drift" in active:
        signals["drift"] = drift_score(match.euro_opening, match.euro_odds)
    if "dispersion" in active:
        if market == "had":
            signals["dispersion"] = dispersion_score(match.per_book_odds)
        else:  # ttg — dispersion from the 国际大小球 books, one scalar
            ou_disp = dispersion_score(match.ou_per_book)
            scalar = max(ou_disp.values(), default=0.0)
            signals["dispersion"] = {o: scalar for o in keys}
    heat = heat_score(match.tags, match.vig)
    return signals, heat


def _generic_contrarian(fair: dict[str, float], keys: list[str]) -> dict[str, float]:
    """Contrarian/长尾 score for an arbitrary keyspace — ``1 - fair`` for every
    non-favorite outcome, ``0.0`` for the 体彩 favorite (argmax of ``fair``)."""
    if not fair:
        return {k: 0.0 for k in keys}
    favorite = max(keys, key=lambda k: fair.get(k, 0.0))
    return {
        k: 0.0 if k == favorite else _clip01(1.0 - fair.get(k, 0.0)) for k in keys
    }


def market_boldness(match: BoldMatch, market: str) -> dict[str, float]:
    """Per-outcome boldness for one ``market`` — the active signals composed
    with per-market weight normalization (spec §3 跨市场可比性).

    The active-signal weights are renormalized to sum 1, so had (5 signals) and
    crs (3 signals) produce same-scale scores and the candidate pool is not
    structurally dominated by had.
    """
    signals, heat = _market_signal_scores(match, market)
    keys = list(_market_outcomes(match, market))
    active = MARKET_SIGNALS[market]
    weight_total = sum(_SIGNAL_WEIGHTS[s] for s in active)
    if weight_total <= 0 or not keys:
        return {k: 0.0 for k in keys}
    scores: dict[str, float] = {}
    for key in keys:
        total = 0.0
        for signal in active:
            weight = _SIGNAL_WEIGHTS[signal] / weight_total
            value = heat if signal == "heat" else signals.get(signal, {}).get(key, 0.0)
            total += weight * value
        scores[key] = total
    return scores


def _crs_internal_conflict(match: BoldMatch) -> dict[str, float]:
    """crs market's own internal conflict — each scoreline inherits the larger
    of its had-bucket and ttg-bucket internal conflict (spec §3).
    """
    keys = list(match.crs_odds)
    if not keys:
        return {}
    had_conflict = internal_conflict(match, "had")
    ttg_conflict = internal_conflict(match, "ttg")
    result: dict[str, float] = {}
    for key in keys:
        if key in _CRS_OTHER_LABELS:           # 其他 bucket — had sign only
            had_key = {"s1sh": "home", "s1sd": "draw", "s1sa": "away"}[key]
            result[key] = had_conflict.get(had_key, 0.0)
            continue
        home_goals, away_goals = int(key[1:3]), int(key[4:6])
        had_key = (
            "home" if home_goals > away_goals
            else "draw" if home_goals == away_goals
            else "away"
        )
        ttg_key = f"total_{min(home_goals + away_goals, 7)}"
        result[key] = max(
            had_conflict.get(had_key, 0.0), ttg_conflict.get(ttg_key, 0.0)
        )
    return result


def _market_pick_label(market: str, key: str) -> str:
    """Display label for an outcome ``key`` in ``market``."""
    if market == "crs":
        return _crs_pick_label(key)
    if market == "ttg":
        return _TTG_LABELS.get(key, key)
    if market == "hhad":
        return _HHAD_LABELS.get(key, key)
    return OUTCOME_LABELS.get(key, key)


def bold_leg_for_market(match: BoldMatch, market: str) -> BoldLeg | None:
    """Pick the boldest outcome for ``match`` in one ``market``.

    Returns ``None`` when the match has no 体彩 odds for that market (graceful
    degradation — that market simply contributes no leg).
    """
    outcomes = _market_outcomes(match, market)
    usable = {k: v for k, v in outcomes.items() if v and v > 1.0}
    if not usable:
        return None
    scores = market_boldness(match, market)
    pick = max(usable, key=lambda k: scores.get(k, 0.0))
    label = _market_pick_label(market, pick)
    reason = f"{MARKET_LABELS[market]} · {label} · 大胆腿"
    return BoldLeg(
        match_no=match.match_no,
        league=match.league,
        home=match.home,
        away=match.away,
        pick=pick,
        tc_odds=usable[pick],
        boldness=scores.get(pick, 0.0),
        reason=reason,
        market=market,
        pick_label=label,
    )
```

Note: `_crs_internal_conflict` is referenced by `_market_signal_scores` before its definition in source order — Python resolves it at call time, so placing it after is fine, but for readability place `_crs_internal_conflict` **before** `_market_signal_scores`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_jczq_bold_combos.py -v`
Expected: PASS — new tests + all v1 tests.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/jczq_bold_combos.py tests/test_jczq_bold_combos.py
git commit -m "feat(bold-combos): per-market boldness + normalized weights + bold leg"
```

## Task 8: Cross-market candidate pool + Rule-O combination generation

**Files:** Modify `nutmeg/services/jczq_bold_combos.py`; Test `tests/test_jczq_bold_combos.py`

The engine now builds candidate legs across all four markets. A ticket may use at most one leg per match (Rule O). The candidate pool caps legs-per-match so combos always have cross-match options.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_jczq_bold_combos.py`:

```python
def test_candidate_legs_spans_markets() -> None:
    from nutmeg.services.jczq_bold_combos import BoldMatch, candidate_legs

    match = BoldMatch(
        match_no="周一001", league="芬超", home="A", away="B",
        tc_odds={"home": 2.0, "draw": 3.2, "away": 3.5},
        hhad_odds={"home": 2.5, "draw": 3.3, "away": 2.6}, hhad_line=-1.0,
        ttg_odds={f"total_{k}": 4.0 for k in range(8)},
        crs_odds={"s01s00": 6.0, "s00s00": 9.0, "s03s02": 41.0},
    )
    legs = candidate_legs([match])
    # one match, four markets → up to MAX_LEGS_PER_MATCH legs kept.
    assert {lg.market for lg in legs} <= {"had", "hhad", "ttg", "crs"}
    assert len(legs) <= 2                       # MAX_LEGS_PER_MATCH cap
    assert all(lg.match_no == "周一001" for lg in legs)


def test_bold_combos_enforces_one_leg_per_match() -> None:
    from nutmeg.services.jczq_bold_combos import BoldLeg, bold_combos

    # Two legs share 周一001 (had + crs); a legal 3-fold cannot use both.
    legs = [
        BoldLeg("周一001", "L", "A", "B", "home", 3.0, 0.5, "x", market="had", pick_label="胜"),
        BoldLeg("周一001", "L", "A", "B", "s01s00", 7.0, 0.6, "x", market="crs", pick_label="1:0"),
        BoldLeg("周一002", "L", "C", "D", "away", 3.5, 0.5, "x", market="had", pick_label="负"),
        BoldLeg("周一003", "L", "E", "F", "draw", 3.2, 0.5, "x", market="had", pick_label="平"),
    ]
    tickets = bold_combos(legs, chaos=10)
    assert tickets
    for ticket in tickets:
        match_nos = [lg.match_no for lg in ticket.legs]
        assert len(match_nos) == len(set(match_nos))      # Rule O — distinct matches
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_jczq_bold_combos.py::test_candidate_legs_spans_markets -v`
Expected: FAIL — `ImportError: cannot import name 'candidate_legs'`.

- [ ] **Step 3: Write minimal implementation**

In `nutmeg/services/jczq_bold_combos.py`, near the other pool constants (`POOL_MIN`/`POOL_MAX`) add:

```python
# A match may put at most this many legs (its boldest markets) into the
# candidate pool — keeps cross-match options for the Rule-O combo generator.
MAX_LEGS_PER_MATCH: int = 2
```

After `bold_leg_for_market` add:

```python
def candidate_legs(matches: list[BoldMatch]) -> list[BoldLeg]:
    """Build the cross-market candidate-leg pool.

    For each match, one bold leg per market it has 体彩 odds for; only the
    ``MAX_LEGS_PER_MATCH`` boldest are kept per match so the Rule-O combo
    generator always has cross-match options. The list is sorted by boldness.
    """
    legs: list[BoldLeg] = []
    for match in matches:
        per_match = [
            leg
            for market in MARKETS
            if (leg := bold_leg_for_market(match, market)) is not None
        ]
        per_match.sort(key=lambda lg: lg.boldness, reverse=True)
        legs.extend(per_match[:MAX_LEGS_PER_MATCH])
    legs.sort(key=lambda lg: lg.boldness, reverse=True)
    return legs
```

In `bold_combos`, the combination loop must reject combos that reuse a match. Replace the `for combo in itertools.combinations(legs, fold):` block body with:

```python
        for combo in itertools.combinations(legs, fold):
            combo_legs = list(combo)
            # Rule O — one leg per match (distinct match_no makes the parlay
            # legal regardless of which markets the legs come from).
            if len({lg.match_no for lg in combo_legs}) != fold:
                continue
            total = _ticket_total_odds(combo_legs)
            avg = _ticket_avg_boldness(combo_legs)
            combos.append((total * avg, combo_legs))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_jczq_bold_combos.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/jczq_bold_combos.py tests/test_jczq_bold_combos.py
git commit -m "feat(bold-combos): cross-market candidate pool + Rule-O combos"
```

## Task 9: Sporttery loader + day snapshot + multi-market engine & renderer

**Files:** Modify `nutmeg/services/jczq_bold_combos.py`; Test `tests/test_jczq_bold_combos.py`

`bold_matches_from_sporttery` builds `BoldMatch` objects from the raw Sporttery `getMatchCalculatorV1` response + `collect_bold_odds`. A per-day snapshot makes `--replay` reproducible. `BoldComboEngine.generate` is rewired to the cross-market pool; the renderer prints market labels.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_jczq_bold_combos.py`:

```python
def _sporttery_value() -> dict:
    """A minimal Sporttery getMatchCalculatorV1 'value' dict — 2 matches."""
    def match(no: str, home: str) -> dict:
        return {
            "matchNumStr": no, "businessDate": "2026-05-18",
            "matchStatus": "Selling", "leagueAbbName": "芬超",
            "homeTeamAbbName": home, "awayTeamAbbName": "客",
            "had": {"h": "2.00", "d": "3.20", "a": "3.50"},
            "hhad": {"h": "3.10", "d": "3.30", "a": "2.10", "goalLine": "-1"},
            "ttg": {f"s{k}": str(4.0 + k) for k in range(8)},
            "crs": {"s01s00": "6.50", "s01s00f": "0", "s00s00": "9.00",
                    "s02s01": "7.50", "s1sh": "80.0"},
        }
    return {"matchInfoList": [
        {"businessDate": "2026-05-18",
         "subMatchList": [match("周一001", "拉赫蒂"), match("周一002", "佐加顿斯")]}
    ]}


def test_bold_matches_from_sporttery_loads_all_markets() -> None:
    from nutmeg.services.jczq_bold_combos import bold_matches_from_sporttery

    matches = bold_matches_from_sporttery(
        _sporttery_value(), run_date="2026-05-18", bold_odds={}
    )
    assert len(matches) == 2
    m = matches[0]
    assert m.tc_odds == {"home": 2.0, "draw": 3.2, "away": 3.5}
    assert m.hhad_odds == {"home": 3.1, "draw": 3.3, "away": 2.1}
    assert m.hhad_line == -1.0
    assert m.ttg_odds["total_0"] == 4.0 and m.ttg_odds["total_7"] == 11.0
    # crs: the ...f flag key is excluded; exact + 其他 keys kept.
    assert "s01s00f" not in m.crs_odds
    assert m.crs_odds["s02s01"] == 7.5 and m.crs_odds["s1sh"] == 80.0


def test_snapshot_round_trip(tmp_path) -> None:
    from nutmeg.services.jczq_bold_combos import (
        load_sporttery_snapshot,
        persist_sporttery_snapshot,
    )

    persist_sporttery_snapshot("2026-05-18", tmp_path, _sporttery_value())
    loaded = load_sporttery_snapshot("2026-05-18", tmp_path)
    assert loaded is not None
    assert loaded["matchInfoList"][0]["subMatchList"][0]["matchNumStr"] == "周一001"
    assert load_sporttery_snapshot("2025-01-01", tmp_path) is None   # absent → None


def test_engine_generate_produces_cross_market_legs() -> None:
    from nutmeg.services.jczq_bold_combos import (
        BoldComboEngine,
        bold_matches_from_sporttery,
    )

    matches = bold_matches_from_sporttery(
        _sporttery_value(), run_date="2026-05-18", bold_odds={}
    )
    # widen to 3 matches so a 3-fold is possible
    matches = matches + [matches[0].__class__(
        match_no="周一003", league="芬超", home="X", away="Y",
        tc_odds={"home": 2.1, "draw": 3.1, "away": 3.4},
        crs_odds={"s01s00": 6.0, "s00s00": 9.0, "s03s02": 41.0},
    )]
    plan = BoldComboEngine().generate("2026-05-18", matches)
    rendered_markets = {
        lg.market for t in plan.tickets for lg in t.legs
    }
    assert rendered_markets                       # at least one market present
    assert plan.label.startswith("🎲")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_jczq_bold_combos.py::test_bold_matches_from_sporttery_loads_all_markets -v`
Expected: FAIL — `ImportError: cannot import name 'bold_matches_from_sporttery'`.

- [ ] **Step 3: Write minimal implementation**

In `nutmeg/services/jczq_bold_combos.py`, after `euro_from_fcom500` add:

```python
def _f(value: object) -> float | None:
    """Parse a Sporttery odds string to float; ``None`` when unusable."""
    try:
        result = float(str(value))
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _had_from_pool(pool: dict) -> dict[str, float]:
    """Sporttery had/hhad pool ``{h,d,a}`` → ``{home,draw,away}`` odds."""
    out: dict[str, float] = {}
    for src, dst in (("h", "home"), ("d", "draw"), ("a", "away")):
        value = _f(pool.get(src))
        if value is not None:
            out[dst] = value
    return out


def _ttg_from_pool(pool: dict) -> dict[str, float]:
    """Sporttery ttg pool ``{s0..s7}`` → ``{total_0..total_7}`` odds."""
    out: dict[str, float] = {}
    for k in range(8):
        value = _f(pool.get(f"s{k}"))
        if value is not None:
            out[f"total_{k}"] = value
    return out


def _crs_from_pool(pool: dict) -> dict[str, float]:
    """Sporttery crs pool → ``{raw_key: odds}`` — the ``...f`` flag keys and any
    metadata keys (``goalLine`` …) are excluded; only ``sHHsAA`` / ``s1sX``."""
    out: dict[str, float] = {}
    for key, raw in pool.items():
        if not (_RE_CRS_KEY.match(key)):
            continue
        value = _f(raw)
        if value is not None:
            out[key] = value
    return out


def _strong_favorite_tags(had_odds: dict[str, float]) -> set[str]:
    """A 强胆场 heat tag when the 体彩 had favorite is priced ≤ 1.35."""
    usable = [v for v in had_odds.values() if v and v > 0]
    return {"强胆场"} if usable and min(usable) <= 1.35 else set()


def bold_matches_from_sporttery(
    value: dict, *, run_date: str, bold_odds: dict[str, dict]
) -> list[BoldMatch]:
    """Build ``BoldMatch`` objects from a Sporttery ``getMatchCalculatorV1``
    response + the ``collect_bold_odds`` result.

    ``value`` is the API ``value`` dict (``matchInfoList`` → ``subMatchList``);
    only ``Selling`` matches whose ``businessDate`` equals ``run_date`` are
    kept. ``bold_odds`` maps 竞彩号 → ``{"match_winner": MarketOdds,
    "over_under": MarketOdds}`` — a match absent from it gets empty 国际 fields
    and its 欧赔/大小球 signals degrade to 0. A match with no usable had odds is
    skipped (never a crash).
    """
    matches: list[BoldMatch] = []
    for day in value.get("matchInfoList") or []:
        for raw in day.get("subMatchList") or []:
            if str(raw.get("matchStatus") or "").casefold() != "selling":
                continue
            business_date = str(raw.get("businessDate") or day.get("businessDate") or "")
            if run_date and business_date and business_date != run_date:
                continue
            had_odds = _had_from_pool(raw.get("had") or {})
            if len(had_odds) < 3:
                continue
            hhad_pool = raw.get("hhad") or {}
            match_no = str(raw.get("matchNumStr") or "")
            euro = (bold_odds.get(match_no) or {}).get("match_winner")
            over_under = (bold_odds.get(match_no) or {}).get("over_under")
            matches.append(
                BoldMatch(
                    match_no=match_no,
                    league=str(raw.get("leagueAbbName") or ""),
                    home=str(raw.get("homeTeamAbbName") or ""),
                    away=str(raw.get("awayTeamAbbName") or ""),
                    tc_odds=had_odds,
                    euro_odds=dict(euro.odds) if euro else {},
                    euro_opening=dict(euro.opening_odds) if euro else {},
                    per_book_odds=(
                        {k: list(v) for k, v in euro.per_book_odds.items()}
                        if euro else {}
                    ),
                    tags=_strong_favorite_tags(had_odds),
                    vig=_tc_vig(had_odds),
                    hhad_odds=_had_from_pool(hhad_pool),
                    hhad_line=_f(hhad_pool.get("goalLineValue"))
                    or _f(hhad_pool.get("goalLine")) or 0.0,
                    ttg_odds=_ttg_from_pool(raw.get("ttg") or {}),
                    crs_odds=_crs_from_pool(raw.get("crs") or {}),
                    ou_odds=dict(over_under.odds) if over_under else {},
                    ou_line=float(over_under.line)
                    if over_under and over_under.line else 0.0,
                    ou_per_book=(
                        {k: list(v) for k, v in over_under.per_book_odds.items()}
                        if over_under else {}
                    ),
                )
            )
    return matches


def persist_sporttery_snapshot(run_date: str, output_dir, value: dict) -> None:
    """Write the Sporttery response to ``<output_dir>/daily/<run_date>/
    sporttery_markets.json`` so ``--replay`` is reproducible."""
    import json
    from pathlib import Path

    path = Path(output_dir) / "daily" / run_date / "sporttery_markets.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def load_sporttery_snapshot(run_date: str, output_dir) -> dict | None:
    """Read a persisted Sporttery snapshot; ``None`` when absent."""
    import json
    from pathlib import Path

    path = Path(output_dir) / "daily" / run_date / "sporttery_markets.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
```

Add the crs-key regex near the top-of-module constants (it accepts both exact and 其他 keys):

```python
import re

# A raw Sporttery crs odds key — exact scoreline sHHsAA or an 其他 bucket s1sX.
_RE_CRS_KEY = re.compile(r"^s\d{2}s\d{2}$|^s1s[hda]$")
```

Rewrite `BoldComboEngine.generate` to use the cross-market pool:

```python
    def generate(self, run_date: str, matches: list[BoldMatch]) -> BoldComboPlan:
        """Build the day's plan from the supplied 体彩+国际 ``matches``."""
        chaos = day_chaos(matches)
        band = chaos_band(chaos)

        legs = candidate_legs(matches)          # cross-market, boldness-sorted
        pool_n = chaos_pool_size(chaos)
        candidate_pool = legs[:pool_n]

        tickets = bold_combos(candidate_pool, chaos)
        anchor = anchor_ticket(matches)

        return BoldComboPlan(
            run_date=run_date,
            day_chaos=chaos,
            chaos_band=band,
            anchor=anchor,
            tickets=tickets,
        )
```

Update `anchor_ticket` — when it builds its `BoldLeg`, set `market="had"` and `pick_label=OUTCOME_LABELS[favorite]`. Find the `BoldLeg(` constructor inside `anchor_ticket` and add those two keyword args.

Update `_render_leg` to use the market label + `pick_label`:

```python
def _render_leg(leg: BoldLeg) -> str:
    """One bold leg as a markdown bullet: 编号 / 市场 / 选项 / 体彩赔率 / 理由."""
    label = leg.pick_label or OUTCOME_LABELS.get(leg.pick, leg.pick)
    market = MARKET_LABELS.get(leg.market, leg.market)
    return (
        f"  - {leg.match_no} {leg.home} vs {leg.away} ｜ [{market}] "
        f"选 **{label}** @ {leg.tc_odds:.2f} ｜ {leg.reason}"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_jczq_bold_combos.py -v`
Expected: PASS — new tests + all v1 tests (v1 `_render_leg` tests still pass: a v1 had leg has `pick_label=""` so the renderer falls back to `OUTCOME_LABELS`; v1 `bold_leg` legs now also carry `market="had"`).

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/jczq_bold_combos.py tests/test_jczq_bold_combos.py
git commit -m "feat(bold-combos): Sporttery multi-market loader + snapshot + engine wiring"
```

## Task 10: CLI multi-market wiring + acceptance

**Files:** Modify `nutmeg/interfaces/cli/jczq.py`, `nutmeg/services/jczq_bold_combos.py`; Test `tests/test_cli.py`

The `jczq-bold-combos` command: a live `--date` run fetches the Sporttery full market + 500.com 国际 odds, persists the snapshot, and renders; `--replay` reads the persisted snapshot.

- [ ] **Step 1: Write the failing test**

First inspect the current command — run `grep -n "bold-combos\|bold_combos\|replay_bold" nutmeg/interfaces/cli/jczq.py` to find the existing `jczq-bold-combos` command and its `replay_bold_combos` call.

Add to `tests/test_cli.py` (mirror the existing `jczq-bold-combos` smoke test's style — find it with `grep -n "bold-combos" tests/test_cli.py`):

```python
def test_jczq_bold_combos_replay_renders_multi_market(tmp_path, monkeypatch) -> None:
    """A --replay run off a persisted Sporttery snapshot renders the welded
    label and contains no advantage wording."""
    import json
    from nutmeg.services.jczq_bold_combos import HARD_LABEL

    # persist a 3-match snapshot so the engine can build a 3-fold
    def m(no: str, home: str) -> dict:
        return {
            "matchNumStr": no, "businessDate": "2026-05-18",
            "matchStatus": "Selling", "leagueAbbName": "芬超",
            "homeTeamAbbName": home, "awayTeamAbbName": "客",
            "had": {"h": "2.00", "d": "3.20", "a": "3.50"},
            "hhad": {"h": "3.10", "d": "3.30", "a": "2.10", "goalLine": "-1"},
            "ttg": {f"s{k}": str(4.0 + k) for k in range(8)},
            "crs": {"s01s00": "6.50", "s00s00": "9.00", "s03s02": "41.0"},
        }
    snap_dir = tmp_path / "daily" / "2026-05-18"
    snap_dir.mkdir(parents=True)
    (snap_dir / "sporttery_markets.json").write_text(
        json.dumps({"matchInfoList": [{"businessDate": "2026-05-18",
            "subMatchList": [m("周一001", "A"), m("周一002", "B"), m("周一003", "C")]}]}),
        encoding="utf-8",
    )

    result = runner.invoke(app, [
        "jczq-bold-combos", "--replay", "2026-05-18",
        "--output-dir", str(tmp_path),
    ])

    assert result.exit_code == 0, result.output
    assert result.output.startswith(HARD_LABEL)
    for banned in ("胜率", "edge", "+EV", "正期望", "推荐下注", "重仓"):
        # the label's own legitimate "非 edge" negation is on the first line
        body = "\n".join(result.output.splitlines()[1:])
        assert banned not in body, f"banned word leaked: {banned}"
```

Use whatever `runner` / `app` import the existing `tests/test_cli.py` uses.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py::test_jczq_bold_combos_replay_renders_multi_market -v`
Expected: FAIL — the `--replay` path still uses the v1 `replay_bold_combos` (context.json), not the snapshot.

- [ ] **Step 3: Write minimal implementation**

In `nutmeg/services/jczq_bold_combos.py`, add a multi-market replay/live orchestrator after `replay_bold_combos`:

```python
def run_bold_combos_multimarket(
    run_date: str,
    output_dir,
    *,
    replay: bool,
) -> str:
    """Run the multi-market bold engine for ``run_date``.

    ``replay=True``: read the persisted Sporttery snapshot (degrade to the v1
    context.json had-only path when absent). ``replay=False``: fetch the
    Sporttery full market live, persist the snapshot, enrich with 500.com 国际
    odds. Returns the honest-labelled markdown.
    """
    import logging

    logger = logging.getLogger(__name__)

    value: dict | None = None
    if replay:
        value = load_sporttery_snapshot(run_date, output_dir)
        if value is None:
            logger.warning(
                "bold-combos: no snapshot for %s — falling back to v1 context.json",
                run_date,
            )
            return replay_bold_combos(run_date, output_dir)
    else:
        from nutmeg.services.jczq import SportteryJczqCalculatorProvider

        fetched = SportteryJczqCalculatorProvider().fetch()
        value = fetched.get("value") if "value" in fetched else fetched
        persist_sporttery_snapshot(run_date, output_dir, value)

    bold_odds: dict[str, dict] = {}
    if not replay:
        try:
            from nutmeg.data.fcom500 import Fcom500Client, collect_bold_odds

            with Fcom500Client() as client:
                bold_odds = collect_bold_odds(client)
        except Exception:  # noqa: BLE001 — 国际 odds optional; degrade
            logger.warning("bold-combos: 国际 odds enrichment failed", exc_info=True)

    matches = bold_matches_from_sporttery(
        value or {}, run_date=run_date, bold_odds=bold_odds
    )
    plan = BoldComboEngine().generate(run_date, matches)
    return render_bold_plan(plan)
```

In `nutmeg/interfaces/cli/jczq.py`, the existing `jczq-bold-combos` command calls `replay_bold_combos`. Rewire it: for `--replay` and live runs alike, call `run_bold_combos_multimarket(date, output_dir, replay=is_replay)`. Keep the existing `--date` / `--replay` / `--write` / `--output-dir` options. Concretely — locate the command body and replace its `replay_bold_combos(...)` call:

```python
    from nutmeg.services.jczq_bold_combos import run_bold_combos_multimarket

    markdown = run_bold_combos_multimarket(
        run_date, output_dir, replay=replay_date is not None
    )
```

Use the command's existing variable names for the resolved date / output dir / replay flag (read them off the current command body — do not invent new option names).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Acceptance — full suite + ruff + real replay, then commit**

Run all three:

```bash
uv run pytest tests/ -q
uv run ruff check nutmeg/data/fcom500.py nutmeg/services/jczq_bold_combos.py nutmeg/services/jczq_bold_markets.py nutmeg/interfaces/cli/jczq.py
uv run nutmeg jczq-bold-combos --replay 2026-05-18
```

Expected: pytest fully green (v1's 39 bold-combo tests + all new tests + the rest of the suite); ruff clean; the replay renders the welded 🎲 label, the chaos line, 稳健底仓 + 大胆票 with `[市场]` tags, and no banned words. Verify the three v1 hard-constraint tests still pass:

```bash
uv run pytest tests/test_jczq_bold_combos.py -k "hard_label or advantage or import" -v
```

Then commit:

```bash
git add -A
git commit -m "feat(cli): jczq-bold-combos multi-market — Sporttery snapshot + 国际 odds"
```

---

## Self-Review

**Spec coverage:**
- §2 四市场 + 三数据源 → Tasks 1-2 (大小球 parser + collector), Task 9 (Sporttery loader). ✓
- §3 内部一致性冲突 → Tasks 3-4 (crs aggregation), Task 6 (`internal_conflict`). ✓
- §3 外部总进球冲突 → Task 6 (`external_conflict_ttg`). ✓
- §3 跨市场归一化 → Task 7 (`market_boldness` normalized weights). ✓
- §3.5 混乱值 → unchanged v1 `day_chaos` (consumes the same `BoldMatch`). ✓
- §4 跨市场组合 + Rule O → Task 8. ✓
- §5 输出 + 市场标签 → Task 9 (`_render_leg`). 稳健底仓 胜平负-only → `anchor_ticket` unchanged (had-only). ✓
- §6 落地: 完整盘持久化 → Task 9 snapshot; CLI → Task 10. ✓
- §7 验收: hard constraints → Task 10 Step 5; `parse_over_under` TDD → Task 1; aggregation determinism → Tasks 3-4; Rule O → Task 8; degradation → Task 9 (`load_sporttery_snapshot` → None fallback). ✓
- §8 范围外: no 比分/进球 国际欧赔, no API-Football, no hafu — nothing in the plan adds them. ✓

**Placeholder scan:** No TBD/TODO. Every code step has complete code. Task 10 Step 3 references "the command's existing variable names" — this is a deliberate instruction to read the current CLI body (its option names are not invented here), not a placeholder.

**Type consistency:** `BoldMatch` (Task 5 fields), `BoldLeg` (Task 5 — `market`/`pick_label`), `internal_conflict(match, market)` / `external_conflict_ttg(match)` (Task 6, used in Task 7), `market_boldness`/`bold_leg_for_market` (Task 7, used in Task 8 `candidate_legs`), `candidate_legs`/`bold_combos` (Task 8, used in Task 9 `generate`), `bold_matches_from_sporttery`/`persist`/`load_sporttery_snapshot` (Task 9, used in Task 10). `crs_scoreline_distribution`/`aggregate_crs_to_had` (Task 3) and `aggregate_crs_to_ttg`/`aggregate_crs_to_hhad`/`aggregate_ttg_to_over_under` (Task 4) all imported in Task 6. `TTG_BUCKETS` defined in Task 3, imported in Task 6. Consistent.
