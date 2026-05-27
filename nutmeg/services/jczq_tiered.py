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

import itertools
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Optional

from nutmeg.services.jczq_bold_combos import (
    ANCHOR_GAP_THRESHOLD,
    HARD_LABEL,
    MARKET_LABELS,
    MARKETS,
    OUTCOME_LABELS,
    OUTCOMES,
    BoldLeg,
    BoldMatch,
    PoolSignals,
    RetiredTheme,
    bold_leg_for_market,
    chaos_band,
    compute_pool_signals,
    day_chaos,
    retired_themes_with_stats,
    ticket_theme,
)

# ---------------------------------------------------------------------------
# Dataclasses — spec §3-§4
# ---------------------------------------------------------------------------


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
    # spec §25.3 — rolling hhad market health (output of
    # ``recent_hhad_market_health``); empty dict = disabled / no gating.
    hhad_health: dict = field(default_factory=dict)


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
    # spec §25.3 — rolling hhad health snapshot for the brief top-line.
    hhad_health: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# v2 candidate pool — spec §2.2
# ---------------------------------------------------------------------------

V2_MAX_LEGS_PER_MATCH: int = 2
V2_MARKET_POOL_SHARE: float = 0.5


def _match_has_usable_had(match: BoldMatch) -> bool:
    """spec §26.1 — a match without usable 胜平负 odds is unopened/cancelled
    and must not contribute legs to B/D/E pools (5/26 005 弗拉门戈 leaked into
    B via its hhad leg because the per-market check passed even though had
    was None). Mirrors ``bold_leg_for_market`` usability criterion."""
    return any(v and v > 1.0 for v in match.tc_odds.values())


def v2_candidate_pool(matches: list[BoldMatch]) -> list[BoldLeg]:
    """spec §2.2 — widened candidate pool. Each match contributes its top
    ``V2_MAX_LEGS_PER_MATCH`` legs across distinct markets, ranked by
    boldness. A single market may take at most ``V2_MARKET_POOL_SHARE`` of
    the final pool slots (sole-market days degrade gracefully). chaos no
    longer controls pool size — tiers handle their own fold/odds bands.

    spec §26.1 — matches with no usable 胜平负 odds (unopened/cancelled)
    are rejected at the pool source so B/D/E can never pick them.
    """
    matches = [m for m in matches if _match_has_usable_had(m)]
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

    markets_in_pool = {leg.market for leg in pool}
    if len(markets_in_pool) > 1:
        cap = max(1, int(len(pool) * V2_MARKET_POOL_SHARE + 0.5))
        market_counts = Counter(leg.market for leg in pool)
        for market, count in market_counts.most_common():
            if count <= cap:
                continue
            market_legs = sorted(
                (i for i, lg in enumerate(pool) if lg.market == market),
                key=lambda i: pool[i].boldness,
            )
            drop_n = count - cap
            drop_idx = set(market_legs[:drop_n])
            pool = [lg for i, lg in enumerate(pool) if i not in drop_idx]

    pool.sort(key=lambda lg: lg.boldness, reverse=True)
    return pool


# ---------------------------------------------------------------------------
# Default TierProfiles — spec §3.2
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ticket_total_odds(legs: list[BoldLeg]) -> float:
    odds = 1.0
    for lg in legs:
        odds *= lg.tc_odds
    return odds


def _hhad_count(legs: list[BoldLeg]) -> int:
    return sum(1 for lg in legs if lg.market == "hhad")


def _max_hhad_legs(profile: TierProfile) -> Optional[int]:
    if profile.code == "B":
        return MAIN_MAX_HHAD_LEGS
    if profile.code == "D":
        return CONTRA_MAX_HHAD_LEGS
    return None


def _violates_hhad_concentration(
    profile: TierProfile, legs: list[BoldLeg]
) -> bool:
    cap = _max_hhad_legs(profile)
    return cap is not None and _hhad_count(legs) > cap


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


# ---------------------------------------------------------------------------
# Strategy A — spec §3.3 / §4
# ---------------------------------------------------------------------------

HHAD_COVER_THRESHOLD: float = 1.50

# spec §25.1 — A 真稳健化阈值
ANCHOR_REQUIRE_HOT_THRESHOLD: float = 1.65
A_3FOLD_TOTAL_ODDS_HARD_CAP: float = 5.5
A_2FOLD_TOTAL_ODDS_HARD_CAP: float = 4.0

# 2026-05-26 review gate — prevent B/D from collapsing into the same all-hhad
# longshot structure that missed on 2026-05-25.
MAIN_HHAD_HIGH_ODDS_CUTOFF: float = 5.0
MAIN_MAX_HHAD_LEGS: int = 2
CONTRA_MAX_HHAD_LEGS: int = 2

# Calm-day single-ticket recommendation gate. D may still render as an
# entertainment ticket, but not as "首推" when it is too leveraged.
SINGLE_RECOMMEND_CALM_CHAOS_MAX: int = 20
D_SINGLE_RECOMMEND_MAX_ODDS_CALM: float = 180.0
D_SINGLE_RECOMMEND_MAX_FOLD_CALM: int = 3

# spec §25.3 — hhad 健康度门控
HHAD_HEALTH_WINDOW_DAYS: int = 14
HHAD_HEALTH_MIN_LEGS: int = 30
HHAD_HEALTH_DOMINANCE_RATE: float = 0.55
_HHAD_DIRECTIONS: tuple[str, ...] = ("让胜", "让平", "让负")


def recent_hhad_market_health(
    records: list[dict],
    *,
    window_days: int = HHAD_HEALTH_WINDOW_DAYS,
    min_legs: int = HHAD_HEALTH_MIN_LEGS,
    dominance_rate: float = HHAD_HEALTH_DOMINANCE_RATE,
) -> dict:
    """spec §25.3 — compute hhad direction hit-rates over the most recent
    ``window_days`` review records and decide which D/E picks to block.

    Returns a dict with keys:
      - ``enabled`` (bool): True iff total legs ≥ ``min_legs``
      - ``totals`` (dict[str, int]): per-direction leg counts (incl. zero)
      - ``rates`` (dict[str, float]): per-direction fractions (sum to 1.0)
      - ``total_legs`` (int)
      - ``blocked_picks`` (frozenset[str]): pick labels D/E must reject
      - ``dominant`` (str | ""): direction crossing ``dominance_rate``
    """
    totals: dict[str, int] = {d: 0 for d in _HHAD_DIRECTIONS}
    recent = sorted(records, key=lambda r: r.get("date") or "", reverse=True)
    recent = recent[:window_days]
    for rec in recent:
        for direction, count in (rec.get("by_hhad_actual") or {}).items():
            if direction in totals:
                totals[direction] += int(count)
    total_legs = sum(totals.values())
    if total_legs < min_legs:
        return {
            "enabled": False, "totals": totals, "rates": {},
            "total_legs": total_legs, "blocked_picks": frozenset(),
            "dominant": "",
        }
    rates = {d: totals[d] / total_legs for d in _HHAD_DIRECTIONS}
    dominant = ""
    blocked: frozenset[str] = frozenset()
    for direction in _HHAD_DIRECTIONS:
        if rates[direction] >= dominance_rate:
            dominant = direction
            blocked = frozenset(
                d for d in _HHAD_DIRECTIONS if d != direction
            )
            break
    return {
        "enabled": True, "totals": totals, "rates": rates,
        "total_legs": total_legs, "blocked_picks": blocked,
        "dominant": dominant,
    }

# hhad direction key → 让球 pick label. With negative goalLine (e.g. -1, home
# favoured), "home" means home covers the handicap; "away" means away wins
# straight up or covers in the underdog direction. The cover pick that
# matches the had favourite direction is the one whose key equals the had
# favourite key.
_HHAD_PICK_LABEL: dict[str, str] = {
    "home": "让胜", "draw": "让平", "away": "让负",
}


def _favourite_had_leg(match: BoldMatch) -> Optional[tuple[BoldLeg, str]]:
    """Build a had BoldLeg picking the lowest-odds outcome (favourite).

    Returns ``(leg, gap_status)`` where gap_status is "" (no §17.1 gap) or
    "gap" (drop). Returns None when no usable had odds.
    """
    usable = {
        o: v for o in OUTCOMES if (v := match.tc_odds.get(o)) and v > 0
    }
    if not usable:
        return None
    favourite = min(usable, key=lambda o: usable[o])
    fav_odds = usable[favourite]
    fair = match.euro_fair_prob.get(favourite)
    if fair is not None and fair > 0.0:
        gap = (1.0 / fav_odds) - fair
        if gap >= ANCHOR_GAP_THRESHOLD:
            return None
    leg = BoldLeg(
        match_no=match.match_no, league=match.league,
        home=match.home, away=match.away,
        pick=favourite, tc_odds=fav_odds, boldness=0.0,
        reason=f"{OUTCOME_LABELS[favourite]}向 · 体彩最强热门（最低赔）",
        market="had", pick_label=OUTCOME_LABELS[favourite],
    )
    return leg, ""


def _hhad_cover_for_favourite(match: BoldMatch, fav_direction: str) -> Optional[BoldLeg]:
    """Build an hhad cover BoldLeg matching the had favourite direction.

    ``fav_direction`` is "home" / "draw" / "away" from the had market.
    The hhad pick at the same direction key is the "cover" (e.g., a home
    favourite picks hhad['home'] which is the home-covers-handicap bet).
    """
    if not match.hhad_odds or fav_direction not in match.hhad_odds:
        return None
    odds = match.hhad_odds[fav_direction]
    if not odds or odds <= 0:
        return None
    return BoldLeg(
        match_no=match.match_no, league=match.league,
        home=match.home, away=match.away,
        pick=fav_direction, tc_odds=odds, boldness=0.0,
        reason="cover · 体彩 hhad 让球方向匹配 had 热门",
        market="hhad", pick_label=_HHAD_PICK_LABEL.get(fav_direction, "让平"),
    )


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
    market_label = MARKET_LABELS.get(leg.market, leg.market)
    why_pick = f"{leg.pick_label} — {market_label}盘的方向选择"
    why_not_alt = (
        f"没选 had {alt_odds:.2f}：主胜紧逼下 cover 更稳"
        if leg.market == "hhad" and alt_odds > 0
        else ""
    )
    return LegReason(
        why_match=why_match, why_market=why_market,
        why_pick=why_pick, why_not_alt=why_not_alt,
    )


def pick_anchor_tier(
    profile: TierProfile,
    pool: list[BoldLeg],
    excluded: frozenset[str],
    ctx: PlanContext,
    matches: list[BoldMatch],
) -> Optional[Tier]:
    """spec §3.3 — A 稳健底仓.

    Picks the lowest-odds favorites (had or hhad), optionally swapping
    had → hhad cover when the had favorite is ≤ ``HHAD_COVER_THRESHOLD``.
    Returns None when candidates can't fit fold_range and total_odds_band.
    """
    _ = pool  # anchor walks matches directly for favourite-direction picks
    if not matches:
        return None

    candidates: list[BoldLeg] = []
    alt_info: dict[str, tuple[str, float]] = {}

    for match in matches:
        if match.match_no in excluded:
            continue
        result = _favourite_had_leg(match)
        if result is None:
            continue
        had_leg, _gap_status = result
        # spec §3.3 A — hhad cover for super favourites
        if had_leg.tc_odds <= HHAD_COVER_THRESHOLD:
            cover = _hhad_cover_for_favourite(match, had_leg.pick)
            if cover is not None:
                candidates.append(cover)
                alt_info[match.match_no] = ("had", had_leg.tc_odds)
                continue
        candidates.append(had_leg)
        alt_info[match.match_no] = ("", 0.0)

    # spec §25.1 — A 真稳健化前置门槛：池中必须存在 ≥1 条 had ≤ 1.65 的"真热门"
    has_real_favourite = any(
        lg.market == "had" and lg.tc_odds <= ANCHOR_REQUIRE_HOT_THRESHOLD
        for lg in candidates
    ) or any(
        # hhad cover 触发时原 had 一定 ≤ 1.50，也算真热门池
        info[0] == "had" and info[1] <= HHAD_COVER_THRESHOLD
        for info in alt_info.values()
    )
    if not has_real_favourite:
        return None

    candidates.sort(key=lambda lg: lg.tc_odds)

    for fold in range(profile.fold_range[1], profile.fold_range[0] - 1, -1):
        if len(candidates) < fold:
            continue
        # spec §25.1 — per-fold 总赔率硬上限
        per_fold_cap = (
            A_3FOLD_TOTAL_ODDS_HARD_CAP if fold == 3
            else A_2FOLD_TOTAL_ODDS_HARD_CAP if fold == 2
            else profile.total_odds_band[1]
        )
        for combo in itertools.combinations(candidates[: fold + 2], fold):
            combo_list = list(combo)
            total = _ticket_total_odds(combo_list)
            lo, _hi_profile = profile.total_odds_band
            hi = min(_hi_profile, per_fold_cap)
            if lo <= total <= hi:
                tiered = [
                    TieredLeg(
                        leg=lg,
                        reason=_build_anchor_reason(
                            lg,
                            alt_market=alt_info.get(lg.match_no, ("", 0.0))[0],
                            alt_odds=alt_info.get(lg.match_no, ("", 0.0))[1],
                        ),
                    )
                    for lg in combo_list
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


# ---------------------------------------------------------------------------
# Strategy B — spec §3.3 / §4
# ---------------------------------------------------------------------------


def _build_main_reason(leg: BoldLeg) -> LegReason:
    """spec §4 — B 档 LegReason templates."""
    market_label = MARKET_LABELS.get(leg.market, leg.market)
    return LegReason(
        why_match=f"中段 boldness 候选（{leg.tc_odds:.2f}× · {leg.boldness:.2f}）",
        why_market=f"{market_label}盘 structural pick — 非 had 杠杆",
        why_pick=f"{leg.pick_label} — {leg.reason or '盘面信号'}",
    )


def pick_main_tier(
    profile: TierProfile,
    pool: list[BoldLeg],
    excluded: frozenset[str],
    ctx: PlanContext,
    matches: list[BoldMatch],
) -> Optional[Tier]:
    """spec §3.3 — B 主方案. Excludes A's matches; drops legs that violate
    crs cap upfront; prefers hhad/ttg structural legs; tries fold sizes
    until one combo lands in the odds band."""
    _ = matches
    candidates = [lg for lg in pool if lg.match_no not in excluded]
    if profile.max_crs_legs == 0:
        candidates = [lg for lg in candidates if lg.market != "crs"]
    candidates = [
        lg for lg in candidates
        if not (
            lg.market == "hhad"
            and lg.tc_odds >= MAIN_HHAD_HIGH_ODDS_CUTOFF
        )
    ]
    # spec §26.2 — ttg ranks above hhad above had in the sort key so that the
    # ``candidates[: fold + 4]`` search window always surfaces ttg legs when
    # they exist (root-cause of 5/25→5/26 all-hhad B regressions).
    candidates.sort(
        key=lambda lg: (
            0 if lg.market == "ttg"
            else (1 if lg.market == "hhad" else 2),
            -lg.boldness,
        )
    )
    if not candidates:
        return None

    ttg_in_pool = any(lg.market == "ttg" for lg in candidates)

    for fold in range(profile.fold_range[1], profile.fold_range[0] - 1, -1):
        if len(candidates) < fold:
            continue
        # Cap search breadth — first ``fold + 4`` candidates cover the
        # top by combined preference; combinations explode otherwise.
        for combo in itertools.combinations(candidates[: fold + 4], fold):
            combo_list = list(combo)
            if len({lg.match_no for lg in combo_list}) != fold:
                continue
            crs_count = sum(1 for lg in combo_list if lg.market == "crs")
            if crs_count > profile.max_crs_legs:
                continue
            if _violates_hhad_concentration(profile, combo_list):
                continue
            # spec §26.2 — B must include ≥1 ttg leg whenever ttg candidates
            # exist (ttg unavailable → constraint disabled, graceful degrade).
            if (
                ttg_in_pool
                and not any(lg.market == "ttg" for lg in combo_list)
            ):
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


# ---------------------------------------------------------------------------
# Strategy D — spec §3.3 / §4
# ---------------------------------------------------------------------------


def _build_contra_reason(leg: BoldLeg) -> LegReason:
    """spec §4 — D 档 LegReason templates."""
    market_label = MARKET_LABELS.get(leg.market, leg.market)
    return LegReason(
        why_match=f"反盘面候选（boldness {leg.boldness:.2f}）",
        why_market=f"{market_label}盘 contrarian 高分腿",
        why_pick=f"{leg.pick_label} — 大众最不敢站",
    )


def pick_contra_tier(
    profile: TierProfile,
    pool: list[BoldLeg],
    excluded: frozenset[str],
    ctx: PlanContext,
    matches: list[BoldMatch],
    b_hhad_picks: Optional[dict[str, str]] = None,
) -> Optional[Tier]:
    """spec §3.3 — D 反大众. Exclude A∪B matches; SKIP combos in retired
    themes. Combines top-boldness structural legs (hhad/ttg) with at most
    ``profile.max_crs_legs`` crs legs to satisfy the crs cap upfront.

    spec §25.2.b — ``b_hhad_picks`` maps ``match_no -> pick`` for any hhad
    legs B already picked; D filters out *same-match hhad-reverse* picks
    (would be "B let X, D let Y on same match" = double-direction punt).
    """
    _ = matches
    candidates = [lg for lg in pool if lg.match_no not in excluded]
    # spec §25.2.b — drop hhad legs that reverse B's hhad pick on same match.
    if b_hhad_picks:
        candidates = [
            lg for lg in candidates
            if not (
                lg.market == "hhad"
                and lg.match_no in b_hhad_picks
                and b_hhad_picks[lg.match_no] != lg.pick
            )
        ]
    # spec §25.3 — hhad health gating: reject hhad legs whose pick_label is
    # in blocked_picks (dominant direction's complement).
    blocked: frozenset[str] = ctx.hhad_health.get("blocked_picks") or frozenset()
    if blocked:
        candidates = [
            lg for lg in candidates
            if not (lg.market == "hhad" and lg.pick_label in blocked)
        ]
    # Split by market so we can pick the right mix.
    structural = sorted(
        (lg for lg in candidates if lg.market in ("hhad", "ttg", "had")),
        key=lambda lg: lg.boldness, reverse=True,
    )
    crs_legs = sorted(
        (lg for lg in candidates if lg.market == "crs"),
        key=lambda lg: lg.boldness, reverse=True,
    )

    for fold in range(profile.fold_range[1], profile.fold_range[0] - 1, -1):
        # Try increasing crs count from 0 to max_crs_legs.
        for crs_n in range(profile.max_crs_legs + 1):
            structural_n = fold - crs_n
            if structural_n < 0 or structural_n > len(structural):
                continue
            if crs_n > len(crs_legs):
                continue
            struct_cands = structural[: structural_n + 4]
            for struct_combo in itertools.combinations(
                struct_cands, structural_n
            ):
                crs_iter = (
                    itertools.combinations(crs_legs[: crs_n + 4], crs_n)
                    if crs_n > 0 else [()]
                )
                for crs_combo in crs_iter:
                    combo_list = list(struct_combo) + list(crs_combo)
                    if len({lg.match_no for lg in combo_list}) != fold:
                        continue
                    if _violates_hhad_concentration(profile, combo_list):
                        continue
                    if ticket_theme(combo_list)[0] in ctx.retired_themes:
                        continue
                    total = _ticket_total_odds(combo_list)
                    lo, hi = profile.total_odds_band
                    if lo <= total <= hi:
                        tiered = [
                            TieredLeg(leg=lg, reason=_build_contra_reason(lg))
                            for lg in combo_list
                        ]
                        stake = max(
                            1, round(profile.base_stake_yuan * ctx.multiplier)
                        )
                        return Tier(
                            profile=profile, legs=tiered,
                            total_odds=round(total, 4),
                            stake_yuan=stake,
                            confidence_tag=confidence_tag_for_code(
                                profile.code
                            ),
                        )
    return None


# ---------------------------------------------------------------------------
# Strategy E — spec §3.3 / §4
# ---------------------------------------------------------------------------


def _build_lottery_reason(leg: BoldLeg) -> LegReason:
    """spec §4 — E 档 LegReason templates."""
    market_label = MARKET_LABELS.get(leg.market, leg.market)
    return LegReason(
        why_match=f"长尾候选（{leg.tc_odds:.2f}×）",
        why_market=f"{market_label}盘最大想象空间",
        why_pick=f"{leg.pick_label} — 极冷门娱乐尾",
    )


def pick_lottery_tier(
    profile: TierProfile,
    pool: list[BoldLeg],
    excluded: frozenset[str],
    ctx: PlanContext,
    matches: list[BoldMatch],
) -> Optional[Tier]:
    """spec §3.3 / §25.2.a — E 极限娱乐.

    Now honours ``excluded`` (spec §25.2.a) so it no longer shares legs with
    A/B/D. If remaining candidate pool can't satisfy fold_range, returns
    None (¥10 → ¥0; Q2a).
    """
    _ = matches
    available = [lg for lg in pool if lg.match_no not in excluded]
    # spec §25.3 — hhad health gating applies to E too (long-tail lottery).
    blocked: frozenset[str] = ctx.hhad_health.get("blocked_picks") or frozenset()
    if blocked:
        available = [
            lg for lg in available
            if not (lg.market == "hhad" and lg.pick_label in blocked)
        ]
    structural = sorted(
        (lg for lg in available if lg.market in ("hhad", "ttg", "had")),
        key=lambda lg: lg.tc_odds, reverse=True,  # prefer high-odds tails
    )
    crs_legs = sorted(
        (lg for lg in available if lg.market == "crs"),
        key=lambda lg: lg.tc_odds, reverse=True,
    )

    for fold in range(profile.fold_range[1], profile.fold_range[0] - 1, -1):
        for crs_n in range(profile.max_crs_legs + 1):
            structural_n = fold - crs_n
            if structural_n < 0 or structural_n > len(structural):
                continue
            if crs_n > len(crs_legs):
                continue
            struct_cands = structural[: structural_n + 4]
            for struct_combo in itertools.combinations(
                struct_cands, structural_n
            ):
                crs_iter = (
                    itertools.combinations(crs_legs[: crs_n + 4], crs_n)
                    if crs_n > 0 else [()]
                )
                for crs_combo in crs_iter:
                    combo_list = list(struct_combo) + list(crs_combo)
                    if len({lg.match_no for lg in combo_list}) != fold:
                        continue
                    total = _ticket_total_odds(combo_list)
                    lo, hi = profile.total_odds_band
                    if lo <= total <= hi:
                        tiered = [
                            TieredLeg(
                                leg=lg, reason=_build_lottery_reason(lg)
                            )
                            for lg in combo_list
                        ]
                        stake = max(
                            1, round(profile.base_stake_yuan * ctx.multiplier)
                        )
                        return Tier(
                            profile=profile, legs=tiered,
                            total_odds=round(total, 4),
                            stake_yuan=stake,
                            confidence_tag=confidence_tag_for_code(
                                profile.code
                            ),
                        )
    return None


# ---------------------------------------------------------------------------
# Orchestrator — spec §3.4
# ---------------------------------------------------------------------------


def _too_risky_as_single(tier: Tier, chaos: int) -> bool:
    if tier.profile.code != "D" or chaos >= SINGLE_RECOMMEND_CALM_CHAOS_MAX:
        return False
    if len(tier.legs) > D_SINGLE_RECOMMEND_MAX_FOLD_CALM:
        return True
    if tier.total_odds > D_SINGLE_RECOMMEND_MAX_ODDS_CALM:
        return True
    return _hhad_count([tl.leg for tl in tier.legs]) == len(tier.legs)


def recommended_single_for_tiers(
    *,
    a: Optional[Tier],
    b: Optional[Tier],
    d: Optional[Tier],
    chaos: int,
) -> Optional[str]:
    """Choose the single ticket marker without promoting leveraged D tickets."""
    if a is not None:
        return "A"
    if d is not None:
        if _too_risky_as_single(d, chaos):
            return None
        return "D"
    if b is not None:
        return "B"
    return None


def select_tiered_plan(
    matches: list[BoldMatch],
    *,
    history: dict,
    multiplier: float = 1.0,
    run_date: str = "",
) -> TieredPlan:
    """spec §3 — full v2 plan. Build pool, run 4 strategies with cross-tier
    exclusion, decide recommended_single. ``history`` is the merged
    cumulative by_theme dict (spec §6.3 cross-version reader)."""
    chaos = day_chaos(matches)
    band = chaos_band(chaos)
    pool = v2_candidate_pool(matches)
    pool_signals = compute_pool_signals(matches)
    retired_stats = retired_themes_with_stats(history.get("by_theme") or {})
    retired_set = frozenset(rt.theme for rt in retired_stats)
    # spec §25.3 — compute rolling 14d hhad market health from v2 records.
    hhad_health = recent_hhad_market_health(history.get("records") or [])
    ctx = PlanContext(
        pool_signals=pool_signals,
        retired_themes=retired_set,
        history_by_tier=history.get("by_tier_cumulative") or {},
        multiplier=multiplier,
        hhad_health=hhad_health,
    )

    a = pick_anchor_tier(DEFAULT_TIER_A, pool, frozenset(), ctx, matches)
    a_excluded = a.match_nos if a else frozenset()
    b = pick_main_tier(DEFAULT_TIER_B, pool, a_excluded, ctx, matches)
    b_excluded = b.match_nos if b else frozenset()
    # spec §25.2.b — collect B's hhad picks for D's same-match-reverse check
    b_hhad_picks: dict[str, str] = (
        {tl.leg.match_no: tl.leg.pick for tl in b.legs if tl.leg.market == "hhad"}
        if b else {}
    )
    d = pick_contra_tier(
        DEFAULT_TIER_D, pool, a_excluded | b_excluded, ctx, matches,
        b_hhad_picks=b_hhad_picks,
    )
    d_excluded = d.match_nos if d else frozenset()
    # spec §25.2.a — E now honours excluded = A ∪ B ∪ D
    e = pick_lottery_tier(
        DEFAULT_TIER_E, pool,
        a_excluded | b_excluded | d_excluded,
        ctx, matches,
    )

    # spec §25.1 + 2026-05-26 review gate: A → D → B, but calm-day D only
    # receives "首推" when it is not an over-leveraged entertainment ticket.
    recommended = recommended_single_for_tiers(a=a, b=b, d=d, chaos=chaos)

    return TieredPlan(
        run_date=run_date,
        day_chaos=chaos,
        chaos_band=band,
        tiers=[a, b, d, e],
        recommended_single=recommended,
        retired_themes=retired_stats,
        pool_signals=pool_signals,
        multiplier=multiplier,
        hhad_health=hhad_health,
    )


# ---------------------------------------------------------------------------
# Render — spec §5
# ---------------------------------------------------------------------------


def render_tiered_plan(plan: TieredPlan) -> str:
    """spec §5 — render TieredPlan to honest-labelled markdown."""
    lines: list[str] = [HARD_LABEL, ""]

    stake_total = sum(t.stake_yuan for t in plan.tiers if t is not None)
    rec = plan.recommended_single or "—"
    mul_str = f"{plan.multiplier:.2f}×"
    lines.append(
        f"💰 今日方案 · 总建议金额 ¥{stake_total}（multiplier={mul_str}）· "
        f"首推一张 = {rec}"
    )
    lines.append(
        f"**当天大盘面混乱值：{plan.day_chaos}/100（{plan.chaos_band}）** · "
        f"{plan.run_date}"
    )

    for rt in plan.retired_themes:
        lines.append(
            f"⚠️ 主题汰留：「{rt.theme}」累计 {rt.ticket_hits}/{rt.tickets} 张"
            f"（{rt.legs} 腿 ≥ 30 门槛）今晚 Phase A 跳过保送。"
        )

    # spec §25.3 — hhad market health top-line
    h = plan.hhad_health or {}
    if h:
        if h.get("enabled"):
            r = h.get("rates", {})
            dom = h.get("dominant") or ""
            blocked = ", ".join(sorted(h.get("blocked_picks") or [])) or "无"
            lines.append(
                "📊 hhad 健康度 14d："
                f"让胜 {r.get('让胜', 0):.1%} / 让平 {r.get('让平', 0):.1%} / "
                f"让负 {r.get('让负', 0):.1%}（{h.get('total_legs', 0)} 腿） — "
                + (f"D/E 已剔除 {blocked} pick" if dom else "无方向超 55%，D/E contrarian 正常开")
            )
        else:
            lines.append(
                f"📊 hhad 健康度样本不足（{h.get('total_legs', 0)}<30 腿），"
                "D/E contrarian 正常开"
            )

    # spec §25.1 — A 不出时的明确公示
    a_tier = plan.tiers[0] if plan.tiers else None
    if a_tier is None:
        lines.append(
            "⚠️ A 档因无 ≤1.65 真热门、或总赔率超 5.5 上限，今晚不出。"
        )
    # spec §25.2.a — E 不出时的明确公示
    e_tier = plan.tiers[3] if len(plan.tiers) > 3 else None
    if e_tier is None:
        lines.append(
            "⚠️ E 档因跨档去重后剩余腿 < 4，今晚不出。"
        )
    lines.append("")

    code_order = ["A", "B", "D", "E"]
    name_order = ["稳健底仓", "主方案", "反大众", "极限娱乐"]
    for tier, code, name in zip(
        plan.tiers, code_order, name_order, strict=True
    ):
        if tier is None:
            lines.append(f"### {code} {name}")
            lines.append(f"> 今日 {code} 档：候选不足或赔率档命不中。")
            lines.append("")
            continue
        lines.extend(
            _render_tier_block(tier, recommended=plan.recommended_single)
        )
        lines.append("")

    if plan.recommended_single is None and all(t is None for t in plan.tiers):
        lines.append("> 今日无可用方案 —— 候选盘面无法满足任一档位。")
        lines.append("")

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
            "_首推一张标记只是引擎依据档位优先级给出的常识建议，"
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
        if p.code == "A":
            out.append("> 首推一张（若只玩一张选这张）")
        else:
            out.append(
                "> 首推一张（A 档不出，本档为今晚最高优先级娱乐票）"
            )
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


# Strategy signature alias for typing
Strategy = Callable[
    [TierProfile, list[BoldLeg], frozenset[str], PlanContext, list[BoldMatch]],
    Optional[Tier],
]
