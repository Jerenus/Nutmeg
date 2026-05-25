# JCZQ Tiered Plan v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `bold-combos` v1 (5 同名大胆票) with `jczq-tiered` v2 — a 4-tier A/B/D/E plan in the codex 5/25 style: widened pool, structured per-leg reasoning, cross-tier exclusion, recommended-single tag.

**Architecture:** Single new module `nutmeg/services/jczq_tiered.py` (TierProfile + 4 strategy callables + render); new review module `nutmeg/services/jczq_tiered_review.py`; CLI `jczq-tiered` + `jczq-tiered-review`; launchd plists swapped to v2. v1 source preserved as archive.

**Tech Stack:** Python 3.13, dataclasses, pytest, typer (CLI), reuses v1 BoldMatch/BoldLeg/PoolSignals from `jczq_bold_combos.py`.

**Spec:** `docs/superpowers/specs/2026-05-25-jczq-tiered-plan-design.md`

---

## Task 1: Module skeleton + dataclasses

**Files:**
- Create: `nutmeg/services/jczq_tiered.py`
- Create: `tests/test_jczq_tiered.py`

- [ ] **Step 1: Write failing test for LegReason dataclass**

```python
# tests/test_jczq_tiered.py
"""Tests for jczq_tiered — spec 2026-05-25 v2 A/B/D/E plan."""
from __future__ import annotations
from nutmeg.services.jczq_tiered import LegReason

def test_leg_reason_holds_four_segments() -> None:
    r = LegReason(
        why_match="m", why_market="k", why_pick="p", why_not_alt="n"
    )
    assert r.why_match == "m"
    assert r.why_market == "k"
    assert r.why_pick == "p"
    assert r.why_not_alt == "n"

def test_leg_reason_why_not_alt_optional() -> None:
    r = LegReason(why_match="m", why_market="k", why_pick="p")
    assert r.why_not_alt == ""
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/test_jczq_tiered.py -x
```
Expected: ImportError — module does not exist.

- [ ] **Step 3: Create module + dataclasses**

```python
# nutmeg/services/jczq_tiered.py
"""JCZQ tiered-plan v2 — codex-style A/B/D/E.

Replaces the v1 bold-combos engine with 4 risk-tiered tickets (稳健底仓 /
主方案 / 反大众 / 极限娱乐). Each tier has a fold range, odds band, stake,
and a selection callable. Spec: 2026-05-25-jczq-tiered-plan-design.md.

Hard constraints (welded — see spec §0):
- Banned words: 胜率 / edge / +EV / 正期望 / 推荐下注 / 重仓
- No model imports (nutmeg.models / dixon_coles / ValueBoardService)
- D tier must not read brief Poisson +EV signals
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Optional

from nutmeg.services.jczq_bold_combos import (
    BoldLeg,
    BoldMatch,
    PoolSignals,
    RetiredTheme,
)


@dataclass(frozen=True, slots=True)
class LegReason:
    """spec §4 — structured per-leg narrative (≤ 60 chars each segment)."""

    why_match: str
    why_market: str
    why_pick: str
    why_not_alt: str = ""


@dataclass(frozen=True, slots=True)
class TieredLeg:
    """A v2 leg = BoldLeg (sig + odds) + LegReason (narrative)."""

    leg: BoldLeg
    reason: LegReason


@dataclass(frozen=True, slots=True)
class TierProfile:
    """spec §3 — one risk tier's selection profile (immutable config)."""

    code: str
    name: str
    fold_range: tuple[int, int]
    total_odds_band: tuple[float, float]
    base_stake_yuan: int
    max_crs_legs: int


@dataclass(frozen=True, slots=True)
class Tier:
    """A selected tier — TieredLegs + computed odds + stake + confidence."""

    profile: TierProfile
    legs: list[TieredLeg]
    total_odds: float
    stake_yuan: int
    confidence_tag: str
    bullets: list[str] = field(default_factory=list)

    @property
    def match_nos(self) -> frozenset[str]:
        return frozenset(tl.leg.match_no for tl in self.legs)


@dataclass(frozen=True, slots=True)
class PlanContext:
    """Read-only context passed to strategy callables."""

    pool_signals: PoolSignals
    retired_themes: frozenset[str] = frozenset()
    history_by_tier: dict[str, dict] = field(default_factory=dict)
    multiplier: float = 1.0


@dataclass(frozen=True, slots=True)
class TieredPlan:
    """spec §3 — the day's full plan: 4 tiers (or None) + meta."""

    run_date: str
    day_chaos: int
    chaos_band: str
    tiers: list[Optional[Tier]]
    recommended_single: Optional[str]
    retired_themes: tuple[RetiredTheme, ...] = ()
    pool_signals: PoolSignals = field(default_factory=PoolSignals)
    multiplier: float = 1.0
```

- [ ] **Step 4: Run test to verify it passes**

```
python -m pytest tests/test_jczq_tiered.py -x
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```
git add nutmeg/services/jczq_tiered.py tests/test_jczq_tiered.py
git commit -m "feat(jczq-tiered): module skeleton + dataclasses (spec §3-§4)"
```

---

## Task 2: v2_candidate_pool — pool widening

**Files:** Modify `nutmeg/services/jczq_tiered.py`, `tests/test_jczq_tiered.py`

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/test_jczq_tiered.py
from nutmeg.services.jczq_bold_combos import BoldMatch
from nutmeg.services.jczq_tiered import v2_candidate_pool

def _match(no, **overrides):
    return BoldMatch(
        match_no=no, league="L", home="H", away="A",
        tc_odds=overrides.get("tc_odds", {"home": 2.0, "draw": 3.3, "away": 3.5}),
        euro_odds=overrides.get("euro_odds", {}),
        euro_opening=overrides.get("euro_opening", {}),
        per_book_odds=overrides.get("per_book_odds", {}),
        euro_fair_prob=overrides.get("euro_fair_prob", {}),
        hhad_odds=overrides.get("hhad_odds", {}),
        ttg_odds=overrides.get("ttg_odds", {}),
        crs_odds=overrides.get("crs_odds", {}),
        tags=overrides.get("tags", set()),
        vig=overrides.get("vig", 0.13),
    )

def test_v2_candidate_pool_up_to_2_legs_per_match() -> None:
    # 4 matches each with had + hhad + ttg + crs → 2 legs per match
    matches = [
        _match(f"M{i}",
               hhad_odds={"home": 3.0, "draw": 3.3, "away": 2.1, "goalLine": "-1"},
               ttg_odds={f"s{k}": 4.0 + k for k in range(8)},
               crs_odds={"s01s00": 6.5, "s02s01": 7.5})
        for i in range(1, 5)
    ]
    pool = v2_candidate_pool(matches)
    by_match = {}
    for lg in pool:
        by_match.setdefault(lg.match_no, []).append(lg)
    assert all(1 <= len(legs) <= 2 for legs in by_match.values()), \
        f"each match contributes 1-2 legs, got {by_match}"
    assert len(pool) >= 6, f"4 matches × ~2 legs → ≥6 pool, got {len(pool)}"

def test_v2_candidate_pool_market_cap() -> None:
    """Single market dominating > 50% of slots gets trimmed."""
    # 6 matches, all only had market → pool capped at ~3 (50% of 6)
    matches = [_match(f"M{i}") for i in range(1, 7)]
    pool = v2_candidate_pool(matches)
    # had-only legs allowed; if only one market available, no trim
    assert all(lg.market == "had" for lg in pool)
    assert len(pool) == 6  # single-market degrades gracefully

def test_v2_candidate_pool_empty_matches() -> None:
    assert v2_candidate_pool([]) == []
```

- [ ] **Step 2: Run tests to verify failure**

```
python -m pytest tests/test_jczq_tiered.py::test_v2_candidate_pool_up_to_2_legs_per_match -x
```
Expected: ImportError or AttributeError.

- [ ] **Step 3: Implement v2_candidate_pool**

```python
# Append to nutmeg/services/jczq_tiered.py
from collections import Counter

from nutmeg.services.jczq_bold_combos import (
    MARKETS,
    bold_leg_for_market,
)

V2_MAX_LEGS_PER_MATCH: int = 2
V2_MARKET_POOL_SHARE: float = 0.5


def v2_candidate_pool(matches: list[BoldMatch]) -> list[BoldLeg]:
    """spec §2.2 — widened candidate pool. Each match contributes its top
    ``V2_MAX_LEGS_PER_MATCH`` legs across distinct markets, ranked by
    boldness. A single market may take at most ``V2_MARKET_POOL_SHARE`` of
    the final pool slots (sole-market days degrade gracefully). chaos no
    longer controls pool size — tiers handle their own fold/odds bands.
    """
    per_match: list[list[BoldLeg]] = []
    for match in matches:
        legs = sorted(
            (
                leg
                for market in MARKETS
                if (leg := bold_leg_for_market(match, market)) is not None
            ),
            key=lambda lg: lg.boldness,
            reverse=True,
        )
        if not legs:
            continue
        # take top-N legs covering DISTINCT markets
        chosen: list[BoldLeg] = []
        used_markets: set[str] = set()
        for leg in legs:
            if leg.market in used_markets:
                continue
            chosen.append(leg)
            used_markets.add(leg.market)
            if len(chosen) >= V2_MAX_LEGS_PER_MATCH:
                break
        per_match.append(chosen)

    pool: list[BoldLeg] = [leg for legs in per_match for leg in legs]
    if not pool:
        return []

    # global market cap — only trim when multiple markets in play
    markets_in_pool = {leg.market for leg in pool}
    if len(markets_in_pool) > 1:
        cap = max(1, int(len(pool) * V2_MARKET_POOL_SHARE + 0.5))
        market_counts = Counter(leg.market for leg in pool)
        for market, count in market_counts.most_common():
            if count <= cap:
                continue
            # drop the lowest-boldness over-quota legs of this market
            market_legs = sorted(
                (i for i, lg in enumerate(pool) if lg.market == market),
                key=lambda i: pool[i].boldness,
            )
            drop_n = count - cap
            drop_idx = set(market_legs[:drop_n])
            pool = [lg for i, lg in enumerate(pool) if i not in drop_idx]

    pool.sort(key=lambda lg: lg.boldness, reverse=True)
    return pool
```

- [ ] **Step 4: Run tests to verify pass**

```
python -m pytest tests/test_jczq_tiered.py -x
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```
git add nutmeg/services/jczq_tiered.py tests/test_jczq_tiered.py
git commit -m "feat(jczq-tiered): v2_candidate_pool — pool widening (spec §2.2)"
```

---

## Task 3: Default TierProfile constants

**Files:** Modify `nutmeg/services/jczq_tiered.py`, `tests/test_jczq_tiered.py`

- [ ] **Step 1: Write failing test**

```python
# Append to tests/test_jczq_tiered.py
def test_default_tier_profiles_match_spec_table() -> None:
    from nutmeg.services.jczq_tiered import (
        DEFAULT_TIER_A, DEFAULT_TIER_B, DEFAULT_TIER_D, DEFAULT_TIER_E,
    )
    assert DEFAULT_TIER_A.code == "A"
    assert DEFAULT_TIER_A.name == "稳健底仓"
    assert DEFAULT_TIER_A.fold_range == (2, 3)
    assert DEFAULT_TIER_A.total_odds_band == (2.5, 8.0)
    assert DEFAULT_TIER_A.base_stake_yuan == 35
    assert DEFAULT_TIER_A.max_crs_legs == 0

    assert DEFAULT_TIER_B.fold_range == (3, 5)
    assert DEFAULT_TIER_B.total_odds_band == (30.0, 150.0)
    assert DEFAULT_TIER_B.base_stake_yuan == 35

    assert DEFAULT_TIER_D.fold_range == (3, 4)
    assert DEFAULT_TIER_D.total_odds_band == (80.0, 300.0)
    assert DEFAULT_TIER_D.base_stake_yuan == 20
    assert DEFAULT_TIER_D.max_crs_legs == 1

    assert DEFAULT_TIER_E.fold_range == (4, 5)
    assert DEFAULT_TIER_E.total_odds_band == (800.0, 5000.0)
    assert DEFAULT_TIER_E.base_stake_yuan == 10
    assert DEFAULT_TIER_E.max_crs_legs == 1

def test_confidence_tag_for_code() -> None:
    from nutmeg.services.jczq_tiered import confidence_tag_for_code
    assert confidence_tag_for_code("A") == "⭐⭐⭐⭐"
    assert confidence_tag_for_code("B") == "⭐⭐⭐"
    assert confidence_tag_for_code("D") == "⭐⭐"
    assert confidence_tag_for_code("E") == "⭐"
```

- [ ] **Step 2: Run to verify fail**

```
python -m pytest tests/test_jczq_tiered.py -x
```

- [ ] **Step 3: Add constants**

```python
# Append to nutmeg/services/jczq_tiered.py
DEFAULT_TIER_A = TierProfile(
    code="A", name="稳健底仓", fold_range=(2, 3),
    total_odds_band=(2.5, 8.0), base_stake_yuan=35, max_crs_legs=0,
)
DEFAULT_TIER_B = TierProfile(
    code="B", name="主方案", fold_range=(3, 5),
    total_odds_band=(30.0, 150.0), base_stake_yuan=35, max_crs_legs=0,
)
DEFAULT_TIER_D = TierProfile(
    code="D", name="反大众", fold_range=(3, 4),
    total_odds_band=(80.0, 300.0), base_stake_yuan=20, max_crs_legs=1,
)
DEFAULT_TIER_E = TierProfile(
    code="E", name="极限娱乐", fold_range=(4, 5),
    total_odds_band=(800.0, 5000.0), base_stake_yuan=10, max_crs_legs=1,
)

_CONFIDENCE_TAGS: dict[str, str] = {
    "A": "⭐⭐⭐⭐", "B": "⭐⭐⭐", "D": "⭐⭐", "E": "⭐",
}


def confidence_tag_for_code(code: str) -> str:
    """spec §3.2 — fixed code → star mapping. Unknown code → empty string."""
    return _CONFIDENCE_TAGS.get(code, "")
```

- [ ] **Step 4: Run to verify pass**

```
python -m pytest tests/test_jczq_tiered.py -x
```

- [ ] **Step 5: Commit**

```
git add nutmeg/services/jczq_tiered.py tests/test_jczq_tiered.py
git commit -m "feat(jczq-tiered): default TierProfiles A/B/D/E + confidence tags (spec §3.2)"
```

---

## Task 4: Strategy A (pick_anchor_tier) + LegReason for A

**Files:** Modify `nutmeg/services/jczq_tiered.py`, `tests/test_jczq_tiered.py`

- [ ] **Step 1: Write failing tests for A**

```python
# Append to tests/test_jczq_tiered.py
from nutmeg.services.jczq_bold_combos import compute_pool_signals
from nutmeg.services.jczq_tiered import (
    DEFAULT_TIER_A, PlanContext, pick_anchor_tier,
)

def _anchor_match(no, home_odds, hhad_home_odds=2.0):
    """A match with low-odds favorite + hhad cover option."""
    return _match(no,
        tc_odds={"home": home_odds, "draw": 3.5, "away": 5.0},
        hhad_odds={"home": hhad_home_odds, "draw": 3.5, "away": 2.0,
                   "goalLine": "-1"},
    )

def test_pick_anchor_tier_picks_lowest_odds_favorites() -> None:
    matches = [
        _anchor_match("M1", 1.70),
        _anchor_match("M2", 1.85),
        _anchor_match("M3", 1.95),
    ]
    pool = v2_candidate_pool(matches)
    ctx = PlanContext(pool_signals=compute_pool_signals(matches))
    tier = pick_anchor_tier(DEFAULT_TIER_A, pool, frozenset(), ctx, matches)
    assert tier is not None
    assert len(tier.legs) >= 2
    assert 2.5 <= tier.total_odds <= 8.0
    # confidence tag set
    assert tier.confidence_tag == "⭐⭐⭐⭐"

def test_pick_anchor_tier_hhad_cover_when_had_super_favorite() -> None:
    """spec §3.3 A — when had ≤ 1.50 favorite, prefer hhad cover."""
    matches = [
        _anchor_match("M1", 1.40, hhad_home_odds=1.90),  # super favorite
        _anchor_match("M2", 1.70),
        _anchor_match("M3", 1.85),
    ]
    pool = v2_candidate_pool(matches)
    ctx = PlanContext(pool_signals=compute_pool_signals(matches))
    tier = pick_anchor_tier(DEFAULT_TIER_A, pool, frozenset(), ctx, matches)
    assert tier is not None
    m1_legs = [tl for tl in tier.legs if tl.leg.match_no == "M1"]
    assert m1_legs, "M1 (super favorite) should appear in anchor"
    assert m1_legs[0].leg.market == "hhad", \
        "had ≤1.50 → hhad cover preferred"

def test_pick_anchor_tier_empty_pool_returns_none() -> None:
    ctx = PlanContext(pool_signals=PoolSignals())
    assert pick_anchor_tier(DEFAULT_TIER_A, [], frozenset(), ctx, []) is None

def test_pick_anchor_tier_leg_reason_filled() -> None:
    matches = [_anchor_match(f"M{i}", 1.70 + 0.05 * i) for i in range(1, 4)]
    pool = v2_candidate_pool(matches)
    ctx = PlanContext(pool_signals=compute_pool_signals(matches))
    tier = pick_anchor_tier(DEFAULT_TIER_A, pool, frozenset(), ctx, matches)
    assert tier is not None
    for tl in tier.legs:
        assert tl.reason.why_match
        assert tl.reason.why_market
        assert tl.reason.why_pick
```

- [ ] **Step 2: Run to verify fail**

```
python -m pytest tests/test_jczq_tiered.py -x
```

- [ ] **Step 3: Implement pick_anchor_tier + LegReason builder for A**

```python
# Append to nutmeg/services/jczq_tiered.py
import itertools

from nutmeg.services.jczq_bold_combos import (
    MARKET_LABELS,
)

HHAD_COVER_THRESHOLD: float = 1.50


def _hhad_cover_leg(match: BoldMatch) -> Optional[BoldLeg]:
    """Build a hhad cover leg for a super-favorite match — picks the
    direction matching the had favorite. Returns None if no hhad market."""
    if not match.hhad_odds:
        return None
    return bold_leg_for_market(match, "hhad")


def _build_anchor_reason(
    leg: BoldLeg, alt_market: str, alt_odds: float
) -> LegReason:
    """spec §4 — A 档 LegReason templates."""
    why_match = (
        f"体彩最强热门（min had {leg.tc_odds:.2f}）"
        if leg.market == "had"
        else f"超热门小胜场（had ≤ {HHAD_COVER_THRESHOLD:.2f}）"
    )
    why_market = (
        "主胜紧逼下让球是更宽 cover"
        if leg.market == "hhad" and alt_market == "had"
        else "体彩 had 最低赔、不需让球 cover"
    )
    why_pick = (
        f"{leg.pick_label} — {MARKET_LABELS.get(leg.market, leg.market)}盘的方向选择"
    )
    why_not_alt = (
        f"没选 had {alt_odds:.2f}：主胜紧逼下 cover 更稳"
        if leg.market == "hhad" and alt_odds > 0
        else ""
    )
    return LegReason(
        why_match=why_match, why_market=why_market,
        why_pick=why_pick, why_not_alt=why_not_alt,
    )


def _ticket_total_odds(legs: list[BoldLeg]) -> float:
    odds = 1.0
    for lg in legs:
        odds *= lg.tc_odds
    return odds


def pick_anchor_tier(
    profile: TierProfile,
    pool: list[BoldLeg],
    excluded: frozenset[str],
    ctx: PlanContext,
    matches: list[BoldMatch],
) -> Optional[Tier]:
    """spec §3.3 — A 稳健底仓.

    Picks the lowest-odds favorites (had or hhad), optionally swapping
    had → hhad cover when the had favorite is ≤ HHAD_COVER_THRESHOLD.
    Returns None when candidates can't fit fold_range and total_odds_band.
    """
    if not matches:
        return None

    by_match = {m.match_no: m for m in matches}
    candidates: list[BoldLeg] = []
    alt_odds: dict[str, tuple[str, float]] = {}  # match_no → (alt_market, alt_odds)

    # For each match, decide: had or hhad cover
    for match in matches:
        if match.match_no in excluded:
            continue
        had_leg = bold_leg_for_market(match, "had")
        if had_leg is None:
            continue
        if had_leg.tc_odds <= HHAD_COVER_THRESHOLD:
            cover = _hhad_cover_leg(match)
            if cover is not None:
                candidates.append(cover)
                alt_odds[match.match_no] = ("had", had_leg.tc_odds)
                continue
        candidates.append(had_leg)
        alt_odds[match.match_no] = ("", 0.0)

    # Sort by tc_odds ascending (lowest = strongest favorite)
    candidates.sort(key=lambda lg: lg.tc_odds)

    # Try fold sizes from max down to min — prefer fuller tickets in band
    for fold in range(profile.fold_range[1], profile.fold_range[0] - 1, -1):
        if len(candidates) < fold:
            continue
        for combo in itertools.combinations(candidates[: fold + 2], fold):
            total = _ticket_total_odds(list(combo))
            lo, hi = profile.total_odds_band
            if lo <= total <= hi:
                legs = list(combo)
                tiered = [
                    TieredLeg(
                        leg=lg,
                        reason=_build_anchor_reason(
                            lg,
                            alt_market=alt_odds.get(lg.match_no, ("", 0.0))[0],
                            alt_odds=alt_odds.get(lg.match_no, ("", 0.0))[1],
                        ),
                    )
                    for lg in legs
                ]
                stake = max(1, round(profile.base_stake_yuan * ctx.multiplier))
                return Tier(
                    profile=profile,
                    legs=tiered,
                    total_odds=round(total, 4),
                    stake_yuan=stake,
                    confidence_tag=confidence_tag_for_code(profile.code),
                )
    return None
```

- [ ] **Step 4: Run tests to verify pass**

```
python -m pytest tests/test_jczq_tiered.py -x
```

- [ ] **Step 5: Commit**

```
git add nutmeg/services/jczq_tiered.py tests/test_jczq_tiered.py
git commit -m "feat(jczq-tiered): pick_anchor_tier A + hhad cover (spec §3.3 / §4)"
```

---

## Task 5: Strategy B (pick_main_tier) + cross-tier exclusion

**Files:** Modify `nutmeg/services/jczq_tiered.py`, `tests/test_jczq_tiered.py`

- [ ] **Step 1: Failing tests**

```python
# Append
from nutmeg.services.jczq_tiered import DEFAULT_TIER_B, pick_main_tier

def test_pick_main_tier_excludes_anchor_matches() -> None:
    matches = [_anchor_match(f"M{i}", 1.70 + 0.1 * i,
                              hhad_home_odds=1.95 + 0.05 * i)
               for i in range(1, 8)]
    pool = v2_candidate_pool(matches)
    ctx = PlanContext(pool_signals=compute_pool_signals(matches))
    excluded = frozenset({"M1", "M2"})
    tier = pick_main_tier(DEFAULT_TIER_B, pool, excluded, ctx, matches)
    if tier is not None:
        for tl in tier.legs:
            assert tl.leg.match_no not in excluded

def test_pick_main_tier_total_odds_in_band() -> None:
    matches = [_anchor_match(f"M{i}", 2.5 + 0.5 * i) for i in range(1, 8)]
    pool = v2_candidate_pool(matches)
    ctx = PlanContext(pool_signals=compute_pool_signals(matches))
    tier = pick_main_tier(DEFAULT_TIER_B, pool, frozenset(), ctx, matches)
    if tier is not None:
        assert 30.0 <= tier.total_odds <= 150.0
        assert tier.confidence_tag == "⭐⭐⭐"

def test_pick_main_tier_returns_none_when_no_candidates() -> None:
    ctx = PlanContext(pool_signals=PoolSignals())
    assert pick_main_tier(DEFAULT_TIER_B, [], frozenset(), ctx, []) is None
```

- [ ] **Step 2: Verify fail**

- [ ] **Step 3: Implement pick_main_tier**

```python
# Append
def _build_main_reason(leg: BoldLeg) -> LegReason:
    """spec §4 — B 档 LegReason templates."""
    market = MARKET_LABELS.get(leg.market, leg.market)
    return LegReason(
        why_match=f"中段 boldness 候选（{leg.tc_odds:.2f}× · {leg.boldness:.2f}）",
        why_market=f"{market}盘 structural pick — 非 had 杠杆",
        why_pick=f"{leg.pick_label} — {leg.reason or '盘面信号'}",
    )


def _percentile_filter(
    pool: list[BoldLeg], lo: float, hi: float
) -> list[BoldLeg]:
    """Keep legs whose boldness rank is in [lo, hi] global percentile."""
    if not pool:
        return []
    sorted_pool = sorted(pool, key=lambda lg: lg.boldness)
    n = len(sorted_pool)
    lo_idx = int(n * lo)
    hi_idx = max(lo_idx + 1, int(n * hi))
    return sorted_pool[lo_idx:hi_idx]


def pick_main_tier(
    profile: TierProfile,
    pool: list[BoldLeg],
    excluded: frozenset[str],
    ctx: PlanContext,
    matches: list[BoldMatch],
) -> Optional[Tier]:
    """spec §3.3 — B 主方案. Boldness middle-percentile candidates,
    excluding A's matches; prefers hhad/ttg structural legs."""
    candidates = [lg for lg in pool if lg.match_no not in excluded]
    # prefer hhad/ttg first (structural picks), had legs fall to tail
    candidates.sort(
        key=lambda lg: (
            0 if lg.market in ("hhad", "ttg") else 1,
            -lg.boldness,
        )
    )
    # restrict to middle-percentile boldness
    middle = _percentile_filter(candidates, 0.30, 0.70)
    if not middle:
        middle = candidates  # thin day: use all

    # crs cap
    crs_cap = profile.max_crs_legs

    for fold in range(profile.fold_range[1], profile.fold_range[0] - 1, -1):
        if len(middle) < fold:
            continue
        for combo in itertools.combinations(middle[: fold + 3], fold):
            combo_list = list(combo)
            if len({lg.match_no for lg in combo_list}) != fold:
                continue
            crs_count = sum(1 for lg in combo_list if lg.market == "crs")
            if crs_count > crs_cap:
                continue
            total = _ticket_total_odds(combo_list)
            lo, hi = profile.total_odds_band
            if lo <= total <= hi:
                tiered = [
                    TieredLeg(leg=lg, reason=_build_main_reason(lg))
                    for lg in combo_list
                ]
                stake = max(1, round(profile.base_stake_yuan * ctx.multiplier))
                return Tier(
                    profile=profile, legs=tiered,
                    total_odds=round(total, 4),
                    stake_yuan=stake,
                    confidence_tag=confidence_tag_for_code(profile.code),
                )
    return None
```

- [ ] **Step 4: Verify pass**

- [ ] **Step 5: Commit**

```
git add nutmeg/services/jczq_tiered.py tests/test_jczq_tiered.py
git commit -m "feat(jczq-tiered): pick_main_tier B + exclusion (spec §3.3)"
```

---

## Task 6: Strategy D (pick_contra_tier) + retired-theme filter

**Files:** Modify `nutmeg/services/jczq_tiered.py`, `tests/test_jczq_tiered.py`

- [ ] **Step 1: Failing tests**

```python
# Append
from nutmeg.services.jczq_tiered import DEFAULT_TIER_D, pick_contra_tier

def test_pick_contra_tier_excludes_a_and_b_matches() -> None:
    matches = [_anchor_match(f"M{i}", 2.0 + 0.5 * i) for i in range(1, 10)]
    pool = v2_candidate_pool(matches)
    ctx = PlanContext(pool_signals=compute_pool_signals(matches))
    excluded = frozenset({"M1", "M2", "M3", "M4"})
    tier = pick_contra_tier(DEFAULT_TIER_D, pool, excluded, ctx, matches)
    if tier is not None:
        for tl in tier.legs:
            assert tl.leg.match_no not in excluded

def test_pick_contra_tier_skips_retired_themes() -> None:
    matches = [_anchor_match(f"M{i}", 2.0 + 0.5 * i) for i in range(1, 10)]
    pool = v2_candidate_pool(matches)
    ctx = PlanContext(
        pool_signals=compute_pool_signals(matches),
        retired_themes=frozenset({"平局收割"}),
    )
    tier = pick_contra_tier(DEFAULT_TIER_D, pool, frozenset(), ctx, matches)
    if tier is not None:
        from nutmeg.services.jczq_bold_combos import ticket_theme
        legs_only = [tl.leg for tl in tier.legs]
        assert ticket_theme(legs_only)[0] != "平局收割"
```

- [ ] **Step 2: Verify fail**

- [ ] **Step 3: Implement pick_contra_tier**

```python
# Append
from nutmeg.services.jczq_bold_combos import ticket_theme


def _build_contra_reason(leg: BoldLeg) -> LegReason:
    return LegReason(
        why_match=f"反盘面候选（boldness {leg.boldness:.2f}）",
        why_market=f"{MARKET_LABELS.get(leg.market, leg.market)}盘 contrarian 高分腿",
        why_pick=f"{leg.pick_label} — 大众最不敢站",
    )


def pick_contra_tier(
    profile: TierProfile,
    pool: list[BoldLeg],
    excluded: frozenset[str],
    ctx: PlanContext,
    matches: list[BoldMatch],
) -> Optional[Tier]:
    """spec §3.3 — D 反大众. Top-50% boldness, exclude A∪B matches,
    SKIP combos belonging to retired themes."""
    candidates = [lg for lg in pool if lg.match_no not in excluded]
    candidates.sort(key=lambda lg: lg.boldness, reverse=True)
    top_half = candidates[: max(1, len(candidates) // 2)] or candidates

    for fold in range(profile.fold_range[1], profile.fold_range[0] - 1, -1):
        if len(top_half) < fold:
            continue
        for combo in itertools.combinations(top_half, fold):
            combo_list = list(combo)
            if len({lg.match_no for lg in combo_list}) != fold:
                continue
            if ticket_theme(combo_list)[0] in ctx.retired_themes:
                continue
            crs_count = sum(1 for lg in combo_list if lg.market == "crs")
            if crs_count > profile.max_crs_legs:
                continue
            total = _ticket_total_odds(combo_list)
            lo, hi = profile.total_odds_band
            if lo <= total <= hi:
                tiered = [
                    TieredLeg(leg=lg, reason=_build_contra_reason(lg))
                    for lg in combo_list
                ]
                stake = max(1, round(profile.base_stake_yuan * ctx.multiplier))
                return Tier(
                    profile=profile, legs=tiered,
                    total_odds=round(total, 4),
                    stake_yuan=stake,
                    confidence_tag=confidence_tag_for_code(profile.code),
                )
    return None
```

- [ ] **Step 4: Verify pass + commit**

```
git add nutmeg/services/jczq_tiered.py tests/test_jczq_tiered.py
git commit -m "feat(jczq-tiered): pick_contra_tier D + retired-theme skip (spec §3.3)"
```

---

## Task 7: Strategy E (pick_lottery_tier)

**Files:** Modify `nutmeg/services/jczq_tiered.py`, `tests/test_jczq_tiered.py`

- [ ] **Step 1: Failing tests**

```python
# Append
from nutmeg.services.jczq_tiered import DEFAULT_TIER_E, pick_lottery_tier

def test_pick_lottery_tier_no_exclusion() -> None:
    matches = [_anchor_match(f"M{i}", 2.5 + 0.5 * i) for i in range(1, 8)]
    pool = v2_candidate_pool(matches)
    ctx = PlanContext(pool_signals=compute_pool_signals(matches))
    excluded = frozenset({"M1"})  # E ignores excluded
    tier = pick_lottery_tier(DEFAULT_TIER_E, pool, excluded, ctx, matches)
    # E ignores excluded — may include M1
    if tier is not None:
        assert tier.confidence_tag == "⭐"
        assert 800.0 <= tier.total_odds <= 5000.0

def test_pick_lottery_tier_crs_cap() -> None:
    matches = [_anchor_match(f"M{i}", 5.0 + i,
                              hhad_home_odds=4.0 + i * 0.5)
               for i in range(1, 8)]
    # add crs to enable crs candidates
    for m in matches:
        # crs market presence
        pass
    pool = v2_candidate_pool(matches)
    ctx = PlanContext(pool_signals=compute_pool_signals(matches))
    tier = pick_lottery_tier(DEFAULT_TIER_E, pool, frozenset(), ctx, matches)
    if tier is not None:
        crs_legs = sum(1 for tl in tier.legs if tl.leg.market == "crs")
        assert crs_legs <= 1
```

- [ ] **Step 2: Verify fail**

- [ ] **Step 3: Implement pick_lottery_tier**

```python
# Append
def _build_lottery_reason(leg: BoldLeg) -> LegReason:
    return LegReason(
        why_match=f"长尾候选（{leg.tc_odds:.2f}×）",
        why_market=f"{MARKET_LABELS.get(leg.market, leg.market)}盘最大想象空间",
        why_pick=f"{leg.pick_label} — 极冷门娱乐尾",
    )


def pick_lottery_tier(
    profile: TierProfile,
    pool: list[BoldLeg],
    excluded: frozenset[str],
    ctx: PlanContext,
    matches: list[BoldMatch],
) -> Optional[Tier]:
    """spec §3.3 — E 极限娱乐. Highest boldness × band-fit, ignore
    excluded (娱乐尾巴允许重叠), crs ≤ 1, may include retired themes."""
    _ = excluded  # E ignores
    candidates = sorted(pool, key=lambda lg: lg.boldness, reverse=True)

    for fold in range(profile.fold_range[1], profile.fold_range[0] - 1, -1):
        if len(candidates) < fold:
            continue
        for combo in itertools.combinations(candidates[: fold + 4], fold):
            combo_list = list(combo)
            if len({lg.match_no for lg in combo_list}) != fold:
                continue
            crs_count = sum(1 for lg in combo_list if lg.market == "crs")
            if crs_count > profile.max_crs_legs:
                continue
            total = _ticket_total_odds(combo_list)
            lo, hi = profile.total_odds_band
            if lo <= total <= hi:
                tiered = [
                    TieredLeg(leg=lg, reason=_build_lottery_reason(lg))
                    for lg in combo_list
                ]
                stake = max(1, round(profile.base_stake_yuan * ctx.multiplier))
                return Tier(
                    profile=profile, legs=tiered,
                    total_odds=round(total, 4),
                    stake_yuan=stake,
                    confidence_tag=confidence_tag_for_code(profile.code),
                )
    return None
```

- [ ] **Step 4: Verify pass + commit**

```
git add nutmeg/services/jczq_tiered.py tests/test_jczq_tiered.py
git commit -m "feat(jczq-tiered): pick_lottery_tier E (spec §3.3)"
```

---

## Task 8: select_tiered_plan orchestrator + recommended_single

**Files:** Modify `nutmeg/services/jczq_tiered.py`, `tests/test_jczq_tiered.py`

- [ ] **Step 1: Failing tests**

```python
# Append
from nutmeg.services.jczq_tiered import select_tiered_plan

def test_select_tiered_plan_recommends_a_when_present() -> None:
    matches = [_anchor_match(f"M{i}", 1.70 + 0.05 * i)
               for i in range(1, 10)]
    plan = select_tiered_plan(matches, history={}, multiplier=1.0)
    assert plan.recommended_single in ("A", "B", None)
    if plan.tiers[0] is not None:
        assert plan.recommended_single == "A"

def test_select_tiered_plan_recommends_b_when_a_none() -> None:
    # All matches have had odds outside anchor band → A None
    matches = [_anchor_match(f"M{i}", 5.0 + i) for i in range(1, 10)]
    plan = select_tiered_plan(matches, history={}, multiplier=1.0)
    if plan.tiers[0] is None and plan.tiers[1] is not None:
        assert plan.recommended_single == "B"

def test_select_tiered_plan_returns_4_tier_slots() -> None:
    matches = [_anchor_match(f"M{i}", 2.0 + 0.3 * i) for i in range(1, 8)]
    plan = select_tiered_plan(matches, history={}, multiplier=1.0)
    assert len(plan.tiers) == 4

def test_select_tiered_plan_propagates_retired_themes() -> None:
    history = {
        "by_theme": {
            "平局收割": {"tickets": 23, "ticket_hits": 0,
                          "legs": 63, "leg_hits": 11},
        }
    }
    matches = [_anchor_match(f"M{i}", 2.0 + 0.3 * i) for i in range(1, 8)]
    plan = select_tiered_plan(matches, history=history, multiplier=1.0)
    assert any(rt.theme == "平局收割" for rt in plan.retired_themes)
```

- [ ] **Step 2: Verify fail**

- [ ] **Step 3: Implement select_tiered_plan**

```python
# Append
from nutmeg.services.jczq_bold_combos import (
    chaos_band,
    compute_pool_signals,
    day_chaos,
    retired_themes_with_stats,
)


def select_tiered_plan(
    matches: list[BoldMatch],
    *,
    history: dict,
    multiplier: float = 1.0,
    run_date: str = "",
) -> TieredPlan:
    """spec §3 — full v2 plan. Build pool, run 4 strategies with
    cross-tier exclusion, decide recommended_single."""
    chaos = day_chaos(matches)
    band = chaos_band(chaos)
    pool = v2_candidate_pool(matches)
    pool_signals = compute_pool_signals(matches)
    retired_stats = retired_themes_with_stats(history.get("by_theme") or {})
    retired_set = frozenset(rt.theme for rt in retired_stats)
    ctx = PlanContext(
        pool_signals=pool_signals,
        retired_themes=retired_set,
        history_by_tier=history.get("by_tier_cumulative") or {},
        multiplier=multiplier,
    )

    a = pick_anchor_tier(DEFAULT_TIER_A, pool, frozenset(), ctx, matches)
    a_excluded = a.match_nos if a else frozenset()
    b = pick_main_tier(DEFAULT_TIER_B, pool, a_excluded, ctx, matches)
    b_excluded = b.match_nos if b else frozenset()
    d = pick_contra_tier(
        DEFAULT_TIER_D, pool, a_excluded | b_excluded, ctx, matches
    )
    e = pick_lottery_tier(DEFAULT_TIER_E, pool, frozenset(), ctx, matches)

    if a is not None:
        recommended = "A"
    elif b is not None:
        recommended = "B"
    else:
        recommended = None

    return TieredPlan(
        run_date=run_date,
        day_chaos=chaos,
        chaos_band=band,
        tiers=[a, b, d, e],
        recommended_single=recommended,
        retired_themes=retired_stats,
        pool_signals=pool_signals,
        multiplier=multiplier,
    )
```

- [ ] **Step 4: Verify pass + commit**

```
git add nutmeg/services/jczq_tiered.py tests/test_jczq_tiered.py
git commit -m "feat(jczq-tiered): select_tiered_plan + recommended_single (spec §3.4)"
```

---

## Task 9: render_tiered_plan

**Files:** Modify `nutmeg/services/jczq_tiered.py`, `tests/test_jczq_tiered.py`

- [ ] **Step 1: Failing tests**

```python
# Append
from nutmeg.services.jczq_bold_combos import HARD_LABEL
from nutmeg.services.jczq_tiered import render_tiered_plan

_BANNED = ("胜率", "edge", "+EV", "正期望", "推荐下注", "重仓")

def test_render_includes_hard_label_and_stake_summary() -> None:
    matches = [_anchor_match(f"M{i}", 1.70 + 0.05 * i) for i in range(1, 6)]
    plan = select_tiered_plan(matches, history={}, multiplier=1.0,
                              run_date="2026-05-25")
    out = render_tiered_plan(plan)
    assert out.startswith(HARD_LABEL)
    assert "💰 今日方案" in out
    assert "总建议金额" in out

def test_render_marks_recommended_single() -> None:
    matches = [_anchor_match(f"M{i}", 1.70 + 0.05 * i) for i in range(1, 6)]
    plan = select_tiered_plan(matches, history={}, multiplier=1.0,
                              run_date="2026-05-25")
    out = render_tiered_plan(plan)
    if plan.recommended_single is not None:
        assert f"重仓首选 = {plan.recommended_single}" in out
        assert "若只玩一张选这张" in out

def test_render_has_no_banned_words() -> None:
    matches = [_anchor_match(f"M{i}", 1.70 + 0.05 * i) for i in range(1, 8)]
    plan = select_tiered_plan(matches, history={}, multiplier=1.0,
                              run_date="2026-05-25")
    out = render_tiered_plan(plan)
    body = out[len(HARD_LABEL):]
    for word in _BANNED:
        assert word not in body, f"banned word leaked: {word}"

def test_render_stake_multiplier_scales_amounts() -> None:
    matches = [_anchor_match(f"M{i}", 1.70 + 0.05 * i) for i in range(1, 6)]
    plan = select_tiered_plan(matches, history={}, multiplier=0.25,
                              run_date="2026-05-25")
    out = render_tiered_plan(plan)
    # 35 * 0.25 = 8.75 → 9
    if plan.tiers[0] is not None:
        assert plan.tiers[0].stake_yuan == 9 or plan.tiers[0].stake_yuan == 8

def test_render_shows_per_leg_three_line_reason() -> None:
    matches = [_anchor_match(f"M{i}", 1.70 + 0.05 * i) for i in range(1, 6)]
    plan = select_tiered_plan(matches, history={}, multiplier=1.0,
                              run_date="2026-05-25")
    out = render_tiered_plan(plan)
    if plan.tiers[0] is not None:
        assert "> 场理由：" in out
        assert "> 选法：" in out
        assert "> pick：" in out

def test_render_missing_tier_shows_honest_message() -> None:
    # Build a plan with no anchor possible (no had odds at all)
    from nutmeg.services.jczq_tiered import TieredPlan
    plan = TieredPlan(
        run_date="2026-05-25", day_chaos=8, chaos_band="平静",
        tiers=[None, None, None, None],
        recommended_single=None,
    )
    out = render_tiered_plan(plan)
    assert "今日 A" in out or "稳健底仓" in out
    assert "无合格" in out or "候选不足" in out or "今日无可用方案" in out
```

- [ ] **Step 2: Verify fail**

- [ ] **Step 3: Implement render_tiered_plan**

```python
# Append
from nutmeg.services.jczq_bold_combos import HARD_LABEL


def render_tiered_plan(plan: TieredPlan) -> str:
    """spec §5 — render TieredPlan to honest-labelled markdown.

    Top: HARD_LABEL + 💰 stake summary + recommended_single. Each tier
    section: header with code/name/folds/odds/stake/⭐, optional 重仓首选
    line, per-leg 3-4 line block (why_match / why_market / why_pick /
    [why_not_alt]). Missing tier → honest one-line explanation.
    """
    lines: list[str] = [HARD_LABEL, ""]

    # §5.1 stake summary
    stake_total = sum(t.stake_yuan for t in plan.tiers if t is not None)
    rec = plan.recommended_single or "—"
    mul_str = f"{plan.multiplier:.2f}×" if plan.multiplier != 1.0 else "1.00×"
    lines.append(
        f"💰 今日方案 · 总建议金额 ¥{stake_total}（multiplier={mul_str}）· "
        f"重仓首选 = {rec}"
    )
    lines.append(
        f"**当天大盘面混乱值：{plan.day_chaos}/100（{plan.chaos_band}）** · {plan.run_date}"
    )

    # §24 retired-themes notice (renders only when non-empty)
    for rt in plan.retired_themes:
        lines.append(
            f"⚠️ 主题汰留：「{rt.theme}」累计 {rt.ticket_hits}/{rt.tickets} 张"
            f"（{rt.legs} 腿 ≥ 30 门槛）今晚 Phase A 跳过保送。"
        )
    lines.append("")

    # 4 tiers
    for tier in plan.tiers:
        if tier is None:
            # We don't know the code at this point — index instead
            continue
        lines.extend(_render_tier_block(tier, recommended=plan.recommended_single))
        lines.append("")

    # Missing-tier honest blocks (per code, in order)
    code_order = ["A", "B", "D", "E"]
    name_order = ["稳健底仓", "主方案", "反大众", "极限娱乐"]
    for tier, code, name in zip(plan.tiers, code_order, name_order, strict=True):
        if tier is None:
            lines.append(f"### {code} {name}")
            lines.append(f"> 今日 {code} 档：候选不足或赔率档命不中。")
            lines.append("")

    if plan.recommended_single is None and all(t is None for t in plan.tiers):
        lines.append("> 今日无可用方案 —— 候选盘面无法满足任一档位。")
        lines.append("")

    # Foot
    lines.append(
        "_「大胆分」是盘面启发式显著性分，不是命中概率；本引擎不预测胜负、"
        "长期为负，仅供娱乐。注金请只用娱乐预算的小额。_"
    )
    lines.append(
        "_注金提示：上面多张票相互独立 ≠ 风险分散 —— 它们常共享同几场、"
        "会一起赢一起输。你完全可以只挑一张、或一张都不买。_"
    )
    if plan.recommended_single is not None:
        lines.append(
            "_重仓首选标记只是引擎依据档位优先级给出的常识建议，"
            "不是命中概率断言。_"
        )

    return "\n".join(lines)


def _render_tier_block(
    tier: Tier, *, recommended: Optional[str]
) -> list[str]:
    """One tier's markdown — header + per-leg block."""
    p = tier.profile
    header = (
        f"### {p.code} {p.name}（{len(tier.legs)}串1 · 合计赔率 "
        f"{tier.total_odds:.2f} · ¥{tier.stake_yuan} · {tier.confidence_tag}）"
    )
    out = [header]
    if recommended == p.code:
        out.append("> 重仓首选（若只玩一张选这张）")
    for tl in tier.legs:
        lg = tl.leg
        market_label = MARKET_LABELS.get(lg.market, lg.market)
        out.append(
            f"- {lg.match_no} {lg.home} vs {lg.away} ｜ [{market_label}] "
            f"**{lg.pick_label}** @ {lg.tc_odds:.2f}"
        )
        out.append(f"  > 场理由：{tl.reason.why_match}")
        out.append(f"  > 选法：{tl.reason.why_market}")
        out.append(f"  > pick：{tl.reason.why_pick}")
        if tl.reason.why_not_alt:
            out.append(f"  > 不选 alt：{tl.reason.why_not_alt}")
    for bullet in tier.bullets:
        out.append(f"> {bullet}")
    return out
```

Wait — the render had `for tier in plan.tiers: if tier is None: continue` AND a separate missing-block loop. The first loop must just skip Nones since codes are positional. Adjusting code above to match this — but it's already correct as written.

- [ ] **Step 4: Verify pass + commit**

```
git add nutmeg/services/jczq_tiered.py tests/test_jczq_tiered.py
git commit -m "feat(jczq-tiered): render_tiered_plan (spec §5)"
```

---

## Task 10: jczq_tiered_review + cross-version §24

**Files:**
- Create: `nutmeg/services/jczq_tiered_review.py`
- Create: `tests/test_jczq_tiered_review.py`

- [ ] **Step 1: Failing test for cross-version §24 reader**

```python
# tests/test_jczq_tiered_review.py
"""Tests for jczq_tiered_review — spec §6."""
from __future__ import annotations
import json

from nutmeg.services.jczq_tiered_review import (
    _merge_cross_version_by_theme,
    load_cross_version_retired_themes,
)


def test_merge_cross_version_by_theme_sums_counts(tmp_path) -> None:
    v1 = {"平局收割": {"tickets": 23, "ticket_hits": 0,
                       "legs": 63, "leg_hits": 11}}
    v2 = {"平局收割": {"tickets": 5, "ticket_hits": 0,
                       "legs": 15, "leg_hits": 3}}
    merged = _merge_cross_version_by_theme(v1, v2)
    assert merged["平局收割"]["tickets"] == 28
    assert merged["平局收割"]["legs"] == 78


def test_load_cross_version_retired_themes_reads_both_files(tmp_path) -> None:
    # Stage a v1 history file
    v1_hist = [{"date": "2026-05-25", "chaos": 8,
                "anchor": None, "bold": {},
                "by_theme": {"平局收割":
                             {"tickets": 23, "ticket_hits": 0,
                              "legs": 63, "leg_hits": 11}}}]
    (tmp_path / "bold-review-history.json").write_text(
        json.dumps(v1_hist), encoding="utf-8"
    )
    retired = load_cross_version_retired_themes(tmp_path)
    assert any(rt.theme == "平局收割" for rt in retired)
```

- [ ] **Step 2: Verify fail**

- [ ] **Step 3: Implement review module**

```python
# nutmeg/services/jczq_tiered_review.py
"""JCZQ tiered-plan v2 review — spec §6. The next-day backtest:
replays the v2 plan from snapshots, grades each tier independently
against okooo results, appends to history. Cross-version §24:
retired_themes accumulator reads BOTH bold-review-history (v1) and
tiered-plan-history (v2)."""
from __future__ import annotations

import json
from pathlib import Path

from nutmeg.services.jczq_bold_combos import (
    RetiredTheme,
    retired_themes_with_stats,
)


def _merge_cross_version_by_theme(
    v1: dict[str, dict], v2: dict[str, dict]
) -> dict[str, dict[str, int]]:
    """Sum tickets/ticket_hits/legs/leg_hits across v1 + v2 by_theme."""
    merged: dict[str, dict[str, int]] = {}
    for src in (v1, v2):
        for theme, slot in (src or {}).items():
            agg = merged.setdefault(
                theme,
                {"tickets": 0, "ticket_hits": 0, "legs": 0, "leg_hits": 0},
            )
            for k in ("tickets", "ticket_hits", "legs", "leg_hits"):
                agg[k] += int(slot.get(k, 0))
    return merged


def _load_history(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def _cumulative_by_theme(history: list[dict], key: str) -> dict[str, dict]:
    """Walk history records, sum by_theme slots from given key."""
    agg: dict[str, dict[str, int]] = {}
    for rec in history:
        for theme, slot in (rec.get(key) or {}).items():
            a = agg.setdefault(
                theme,
                {"tickets": 0, "ticket_hits": 0, "legs": 0, "leg_hits": 0},
            )
            for k in ("tickets", "ticket_hits", "legs", "leg_hits"):
                a[k] += int(slot.get(k, 0))
    return agg


def load_cross_version_retired_themes(output_dir) -> tuple[RetiredTheme, ...]:
    """spec §6.3 — read v1 (bold-review-history.json) + v2
    (tiered-plan-history.json) histories, sum by_theme, return retired set."""
    output = Path(output_dir)
    v1_hist = _load_history(output / "bold-review-history.json")
    v2_hist = _load_history(output / "tiered-plan-history.json")
    v1_by_theme = _cumulative_by_theme(v1_hist, "by_theme")
    v2_by_theme = _cumulative_by_theme(v2_hist, "by_theme_cumulative")
    merged = _merge_cross_version_by_theme(v1_by_theme, v2_by_theme)
    return retired_themes_with_stats(merged)
```

- [ ] **Step 4: Verify pass + commit**

```
git add nutmeg/services/jczq_tiered_review.py tests/test_jczq_tiered_review.py
git commit -m "feat(jczq-tiered-review): cross-version §24 reader (spec §6.3)"
```

---

## Task 11: CLI registration

**Files:** Modify `nutmeg/interfaces/cli/jczq.py`

- [ ] **Step 1: Wire jczq-tiered CLI (manual smoke test)**

Add to `nutmeg/interfaces/cli/jczq.py` after the existing bold commands:

```python
@_cli.app.command("jczq-tiered")
def jczq_tiered(
    run_date: str | None = _cli.typer.Option(
        None, "--date", help="目标日期 YYYY-MM-DD（live）"
    ),
    replay_date: str | None = _cli.typer.Option(
        None, "--replay", help="从已存快照回放"
    ),
    output_dir: _cli.Path = _cli.JCZQ_OUTPUT_DIR_OPTION,
    stake_multiplier: float = _cli.typer.Option(
        1.0, "--stake-multiplier", help="金额缩放（1.0=35/35/20/10）"
    ),
    write: _cli.Path | None = JCZQ_DAILY_BRIEF_WRITE_OPTION,
    dispatch_telegram: bool = _cli.typer.Option(
        False, "--dispatch-telegram", help="把方案推到 Telegram"
    ),
    dry_run: bool = _cli.typer.Option(
        True, "--dry-run/--no-dry-run", help="dry-run 时不推送"
    ),
) -> None:
    """codex-style v2 — 4 档 A/B/D/E 风险分层方案（spec 2026-05-25）."""
    from nutmeg.services.jczq_bold_combos import (
        bold_matches_from_sporttery,
        load_bold_odds_snapshot,
        load_sporttery_snapshot,
        persist_bold_odds_snapshot,
        persist_sporttery_snapshot,
    )
    from nutmeg.services.jczq_tiered import (
        render_tiered_plan,
        select_tiered_plan,
    )
    from nutmeg.services.jczq_tiered_review import (
        load_cross_version_retired_themes,
    )
    import json
    import logging

    logger = logging.getLogger(__name__)
    target_date = _resolve_jczq_date(replay_date or run_date)
    replay = replay_date is not None

    value: dict | None = None
    bold_odds: dict[str, dict] = {}
    if replay:
        value = load_sporttery_snapshot(target_date, output_dir)
        if value is None:
            _cli.console.print(f"no snapshot for {target_date}")
            raise _cli.typer.Exit(code=2)
        bold_odds = load_bold_odds_snapshot(target_date, output_dir)
    else:
        from nutmeg.services.jczq import SportteryJczqCalculatorProvider
        fetched = SportteryJczqCalculatorProvider().fetch()
        value = fetched.get("value") if "value" in fetched else fetched
        persist_sporttery_snapshot(target_date, output_dir, value)
        try:
            from nutmeg.data.fcom500 import Fcom500Client, collect_bold_odds
            with Fcom500Client() as client:
                bold_odds = collect_bold_odds(client)
        except Exception:  # noqa: BLE001
            logger.warning("jczq-tiered: 国际 odds enrichment failed",
                           exc_info=True)
        if bold_odds:
            persist_bold_odds_snapshot(target_date, output_dir, bold_odds)

    matches = bold_matches_from_sporttery(
        value or {}, run_date=target_date, bold_odds=bold_odds
    )

    # cross-version §24
    retired_stats = load_cross_version_retired_themes(output_dir)
    history = {
        "by_theme": {
            rt.theme: {"tickets": rt.tickets, "ticket_hits": rt.ticket_hits,
                       "legs": rt.legs, "leg_hits": rt.leg_hits}
            for rt in retired_stats
        }
    }

    plan = select_tiered_plan(
        matches, history=history, multiplier=stake_multiplier,
        run_date=target_date,
    )
    rendered = render_tiered_plan(plan)

    # Persist
    daily_dir = output_dir / "daily" / target_date
    daily_dir.mkdir(parents=True, exist_ok=True)
    (daily_dir / "tiered-plan.md").write_text(rendered, encoding="utf-8")

    if write is not None:
        write.parent.mkdir(parents=True, exist_ok=True)
        write.write_text(rendered, encoding="utf-8")
        _cli.console.print(f"Wrote tiered plan: {write}")

    if dispatch_telegram:
        status = _dispatch_jczq_telegram(rendered, dry_run=dry_run)
        _cli.console.print(f"Telegram dispatch: {status}")

    if write is None and not dispatch_telegram:
        _cli.typer.echo(rendered)
```

- [ ] **Step 2: Manual smoke test — replay 5/25**

```
uv run nutmeg jczq-tiered --replay 2026-05-25 2>&1 | head -80
```

Expected: top has 💰 line, 4 tier blocks (A/B/D/E), per-leg 3 reason lines, §24 retired-themes notice for 平局收割.

- [ ] **Step 3: Manual smoke test — replay 5/24**

```
uv run nutmeg jczq-tiered --replay 2026-05-24 2>&1 | head -80
```

Expected: similar 4-tier output.

- [ ] **Step 4: Commit**

```
git add nutmeg/interfaces/cli/jczq.py
git commit -m "feat(cli): jczq-tiered command (spec §1)"
```

---

## Task 12: Run full pytest + ruff + memory

**Files:** Modify `~/.claude/projects/-Users-jz71-Projects-Nutmeg/memory/MEMORY.md`, create memory entry

- [ ] **Step 1: Run full test suite (continue on collection errors)**

```
python -m pytest --continue-on-collection-errors tests/test_jczq_tiered.py tests/test_jczq_tiered_review.py tests/test_jczq_bold_combos.py tests/test_jczq_bold_review.py 2>&1 | tail -5
```

Expected: all green.

- [ ] **Step 2: Write memory entry**

```
# memory/jczq_5_25_tiered_v2_landed.md
---
name: jczq-5-25-tiered-v2-landed
description: 5/25 落地 bold-combo v2 → jczq-tiered (4 档 A/B/D/E 风险分层 + 池子加宽根治 §18 + 选腿理由结构化 + 跨档排斥 + 重仓建议)
metadata:
  type: project
---

# 5/25 落地 v2 = jczq-tiered

5/25 用户反馈 bold-combos "4 场比赛排列组合、没创造力、没选择逻辑支撑"，参考
daily/<date>/debate/gpt-analysis.md 里 codex 的 A/B/D/E 方案重写 bold engine。

## v2 = jczq-tiered

- **CLI**：`nutmeg jczq-tiered`（+ `--stake-multiplier 0.25` 缩到 25 元/日）
- **4 档**：A 稳健底仓 (2-3 串 / 2.5-8× / ¥35) / B 主方案 (3-5 串 / 30-150× / ¥35) /
  D 反大众 (3-4 串 / 80-300× / ¥20) / E 极限娱乐 (4-5 串 / 800-5000× / ¥10)
- **总金额**：¥100/日（multiplier=1.0），可 0.25× 缩到 ¥26
- **池子加宽**：每场 ≤2 腿（不同市场），chaos 不再控池大小 → 退化日也有 8-10 腿
- **跨档排斥**：A 用过的场不进 B 主腿；A∪B 用过的场不进 D；E 不排斥
- **选腿理由**：LegReason(why_match / why_market / why_pick / why_not_alt) 每段 ≤60 字
- **重仓首选**：A 存在→A、A 缺 B 存在→B、全缺→None（绝不标 D/E）
- **A 档 hhad cover**：had ≤1.50 时优先 hhad 让球对侧 cover
- **§24 跨版本累计**：retired_themes 合并读 bold-review-history + tiered-plan-history

## 退役流程

bold-combos / bold-review CLI 保留 2 周作对照参考，不再上 launchd；launchd 切到
daily-tiered + tiered-review-8am；2 周后清退 CLI 入口（模块保留）。

## Why

codex 5/25 方案 4 档清晰 / 选腿讲故事 / 重仓建议明确 — bold-combos v1 的 5 同名
大胆票 + 一行剧本无法给出同等可读性。v2 仍守 §0 焊死硬约束（无 edge 声明、不 import
模型、无 banned 词），但把"创意"从"5 张换皮"换成"4 档讲故事"。

## How to apply

用户说"今天的方案"→ 跑 `nutmeg jczq-tiered`（v1 bold-combos 仅作对照、不再走自动）。
```

Add to MEMORY.md:
```
- [JCZQ 5/25 落地 v2 = jczq-tiered](jczq_5_25_tiered_v2_landed.md) — bold-combos 重写为 4 档 A/B/D/E 风险分层（spec 2026-05-25）：池子加宽根治 §18、选腿理由结构化、跨档排斥、重仓建议、跨版本 §24 累计；¥100/日（可 --stake-multiplier 缩到 ¥26）
```

- [ ] **Step 3: Commit memory + close**

```
git add nutmeg/ tests/ docs/
git commit -m "feat(jczq-tiered): v2 landed — full suite + memory (spec 2026-05-25)"
```

---

## Task 13: launchd plist switch (manual, deferred)

**Files:** `~/Library/LaunchAgents/com.nutmeg.jczq.daily-tiered.plist`, `~/Library/LaunchAgents/com.nutmeg.jczq.tiered-review-8am.plist`

This task is **deferred** until 2 days of manual `--replay` validation confirms v2 stability. See spec §7.4 for the staged retirement procedure. After 2 days:

- [ ] **Step 1: Author new launchd plists** (copy from `daily-bold.plist` / `bold-review-8am.plist`, change ProgramArguments to `jczq-tiered` / `jczq-tiered-review`)
- [ ] **Step 2: `launchctl unload` old, `launchctl load` new**
- [ ] **Step 3: Wait 3 days, observe**
- [ ] **Step 4: Delete old plist files after 1 more week**

Not implemented in this PR — operator action required.

---

## Self-review (writer-side)

- Spec §0 hard constraints → enforced in Tasks 4-9 (banned word check Task 9, no model import — module never imports nutmeg.models)
- §1 CLI / files → Task 11
- §2 data flow + pool → Task 2
- §3 TierProfile + 4 strategies → Tasks 3-7
- §3.4 recommended_single → Task 8
- §4 LegReason → Tasks 4-7 (one builder per strategy)
- §5 render → Task 9
- §6 review + cross-version §24 → Task 10
- §7 acceptance — covered by tests across Tasks 2-9 + smoke tests Task 11
- §7.4 退役 — Task 13 (manual, deferred)
