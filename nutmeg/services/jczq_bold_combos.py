"""Bold-combo engine — an ENTERTAINMENT-purpose JCZQ parlay generator.

⚠️ HONEST FRAMING (spec §0 — welded into the product on purpose)

A 2026-05-18 188-match point-in-time backtest proved the predictive model
(Dixon-Coles) loses to the betting market (46.8% vs 56.4%) and the conflict
engine has no edge. 竞彩 takes roughly a 13% cut. **This engine is not a
money-making tool — it is an entertainment tool.** The user chose to build it
knowing those facts. It does NOT predict winners, does NOT claim an edge, and
its long-run expectation is negative.

What it does instead: from real *board* signals (体彩-vs-欧赔 conflict,
contrarian direction, market heat, odds drift, bookmaker dispersion) it picks a
bold 1X2 leg per match and assembles creative 3/4/5-fold parlays, modulated by
a day-level chaos value. Every output carries the welded 🎲 label and contains
NO advantage wording ("胜率 / edge / +EV / 正期望 / 推荐下注 / 重仓" are banned).

**This module deliberately imports NO predictive model** — not ``dixon_coles``,
not ``ValueBoardService``. It consumes only 体彩 odds + 欧赔. That is asserted
by a test (spec §7).

The "大胆分" (boldness score) is a heuristic *salience* score, NOT a
probability. It is never labelled "胜率 / 信心".
"""

from __future__ import annotations

import itertools
import statistics
from collections import Counter
from dataclasses import dataclass, field

# 市场数据内核已抽出到 jczq_market_kernel(Tier R1);本模块的 v1 组合 generator
# 仍复用这些底座符号,故 import 回来。
from nutmeg.services.jczq_market_kernel import (  # noqa: F401 — 供本模块 + 下游复用
    _CRS_OTHER_LABELS,
    _HHAD_LABELS,
    _MARKET_THEME,
    _RE_CRS_KEY,
    _SIGNAL_WEIGHTS,
    _THEME_SCRIPTS,
    _TTG_LABELS,
    ANCHOR_GAP_THRESHOLD,
    CHAOS_SCALE,
    DISPERSION_GAIN,
    DRIFT_GAIN,
    HARD_LABEL,
    HEAT_TAG,
    HEAT_TAGS,
    HEAT_VIG_GAIN,
    LEG_ODDS_MAX,
    LEG_ODDS_MIN,
    MARKET_LABELS,
    MARKET_SIGNALS,
    MARKETS,
    MIN_THEME_LEGS_FOR_RETIREMENT,
    OUTCOME_LABELS,
    OUTCOMES,
    THEME_DRAW,
    THEME_GOALS,
    THEME_HANDICAP,
    THEME_MIXED,
    THEME_SCORE,
    WEIGHT_CONFLICT,
    WEIGHT_CONTRARIAN,
    WEIGHT_DISPERSION,
    WEIGHT_DRIFT,
    WEIGHT_HEAT,
    BoldLeg,
    BoldMatch,
    MatchSignals,
    PoolSignals,
    RetiredTheme,
    _clip01,
    _crs_from_pool,
    _crs_internal_conflict,
    _crs_pick_label,
    _devig_map,
    _f,
    _fair_from_odds,
    _generic_contrarian,
    _had_from_pool,
    _is_draw_lean,
    _market_outcomes,
    _market_pick_label,
    _market_signal_scores,
    _match_uncertainty,
    _signed_float,
    _strong_favorite_tags,
    _tc_vig,
    _ttg_bucket_goals,
    _ttg_from_pool,
    bold_leg_for_market,
    bold_matches_from_sporttery,
    boldness,
    chaos_band,
    compute_pool_signals,
    conflict_score,
    contrarian_score,
    day_chaos,
    dispersion_score,
    drift_score,
    external_conflict_ttg,
    heat_score,
    internal_conflict,
    load_bold_odds_snapshot,
    load_sporttery_snapshot,
    market_boldness,
    retired_themes_with_stats,
    ticket_theme,
)

# The single outcome vocabulary used everywhere in this module — the 胜平负
# (1X2) market, the only market where 体彩 odds and 欧赔 both exist cleanly.

# --- Multi-market vocabulary (spec: bold-combo multi-market extension) ------
# The four 体彩 markets the engine scores.

# Per market, the signals that are ACTIVE. The rest contribute 0 and take no
# weight (per-market weight normalization, spec §3 跨市场可比性). had has all
# five; hhad/crs have three; ttg has four (dispersion from the 大小球 books).

# Human-readable market labels for the renderer.

# A raw Sporttery crs odds key — exact scoreline sHHsAA or an 其他 bucket s1sX.

# --- Named-constant signal gains (documented defaults — tunables) ----------
# Drift: an implied-probability move of ~0.10 (a sizeable shift) maps to ~0.6.
# Dispersion: a population stdev of 1/odds around ~0.05 across books maps high.
# Heat: each present board tag contributes this much.
# Heat: 体彩 vig above the ~0.12 baseline contributes this per unit of excess.

# Board tags from the brief's §1 table that read as "heat".




















# ---------------------------------------------------------------------------
# Task 3 — boldness composition + bold-leg selection
# ---------------------------------------------------------------------------

# Signal weights — documented defaults, all equal (0.2). Tunable knobs: raising
# WEIGHT_CONTRARIAN biases the engine toward colder, wilder legs.

# Human-readable Chinese labels for each signal — used in the 大胆理由 string.
_SIGNAL_LABELS: dict[str, str] = {
    "conflict": "盘口冲突",
    "contrarian": "反直觉冷门",
    "drift": "欧赔漂移",
    "dispersion": "博彩离散",
    "heat": "盘面热度",
}

# Outcome → Chinese 胜平负 label.










def _dominant_signal(match: BoldMatch, pick: str) -> str:
    """Return the Chinese label of the signal contributing most to ``pick``."""
    tc_fair = _fair_from_odds(match.tc_odds)
    euro_fair = _fair_from_odds(match.euro_odds)
    contributions = {
        "conflict": WEIGHT_CONFLICT * conflict_score(tc_fair, euro_fair)[pick],
        "contrarian": WEIGHT_CONTRARIAN * contrarian_score(tc_fair)[pick],
        "drift": WEIGHT_DRIFT * drift_score(match.euro_opening, match.euro_odds)[pick],
        "dispersion": WEIGHT_DISPERSION * dispersion_score(match.per_book_odds)[pick],
        "heat": WEIGHT_HEAT * heat_score(match.tags, match.vig),
    }
    top = max(contributions, key=lambda k: contributions[k])
    return _SIGNAL_LABELS[top]


def bold_leg(match: BoldMatch) -> BoldLeg:
    """Pick the highest-boldness outcome for ``match`` as its bold leg.

    The ``reason`` names the dominant board signal — a human-readable hook for
    the entertainment narrative, never a claim of advantage.
    """
    scores = boldness(match)
    pick = max(OUTCOMES, key=lambda o: scores[o])
    signal = _dominant_signal(match, pick)
    outcome_label = OUTCOME_LABELS[pick]
    reason = f"{outcome_label}向 · 主导信号「{signal}」"
    return BoldLeg(
        match_no=match.match_no,
        league=match.league,
        home=match.home,
        away=match.away,
        pick=pick,
        tc_odds=match.tc_odds.get(pick, 0.0),
        boldness=scores[pick],
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Multi-market — per-market boldness composition + per-market bold leg
# ---------------------------------------------------------------------------

# Weight lookup by signal name — for per-market normalization.

# crs pick label "H:A" from a raw sHHsAA key, and the 其他 buckets.
# ttg pick label from a total_K key.
_TTG_LABELS["total_7"] = "7+球"
# hhad pick label.


















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


# ---------------------------------------------------------------------------
# Task 4 — day-level chaos value (spec §3.5)
# ---------------------------------------------------------------------------

# CHAOS_SCALE maps a per-match uncertainty (mean dispersion + mean conflict,
# roughly [0, 2]) onto the 0-100 chaos scale. Documented default.
# The candidate-pool size bounds — documented defaults (spec / plan §4).
POOL_MIN: int = 4
POOL_MAX: int = 10
# A match may put at most this many legs (its boldest markets) into the
# candidate pool — keeps cross-match options for the Rule-O combo generator.
MAX_LEGS_PER_MATCH: int = 2






def chaos_pool_size(chaos: int) -> int:
    """Map the day chaos value to the candidate-pool size ``N``.

    Linear from ``POOL_MIN`` at chaos 0 to ``POOL_MAX`` at chaos 100 — a calm
    day picks from a small, restrained pool; a chaotic day from a big, wild one.
    """
    chaos = max(0, min(100, chaos))
    span = POOL_MAX - POOL_MIN
    return POOL_MIN + round(span * chaos / 100)




# ---------------------------------------------------------------------------
# Task 5 — combination generation + 稳健底仓 (spec §4, §5)
# ---------------------------------------------------------------------------

# How many ranked tickets the bold output carries — documented default.
BOLD_TICKET_COUNT: int = 5
# The anchor ticket's leg count cap — a short 2-3 leg 稳健底仓 (spec §5).
ANCHOR_MAX_LEGS: int = 3

# 竞彩 single-ticket (一张彩票) payout cap — 返奖封顶, 500 万元 (spec §10.1,
# user-confirmed; a named, tunable constant).
JCZQ_PAYOUT_CAP_YUAN: float = 5_000_000.0
# Reference stake — 竞彩 base is 2 元/注; payout = stake × total_odds. Combined
# odds beyond JCZQ_PAYOUT_CAP_YUAN / REFERENCE_STAKE_YUAN pay nothing extra.
REFERENCE_STAKE_YUAN: float = 2.0
# A bold ticket may use at most this many legs from one market (spec §10.2) —
# forces cross-market mix. Enforced ONLY when the candidate pool spans ≥2
# markets (a single-market day would otherwise have every ticket filtered out).
MAX_LEGS_PER_MARKET_PER_TICKET: int = 2
# Diversity penalty for cross-ticket concentration (spec §11.2) — a combo's
# rank score is divided by ``1 + CONCENTRATION_PENALTY × (reuse count)`` so
# ticket selection spreads across matches when the pool allows.
CONCENTRATION_PENALTY: float = 0.35
# A match appearing in more than this fraction of the bold tickets triggers the
# 🟦 cross-ticket concentration warning in the renderer (spec §11.2).
CONCENTRATION_WARN_FRACTION: float = 0.6
# spec §17.1 — 体彩 implied probability minus 欧赔 fair probability ≥ this
# threshold (8pp) drops the leg from the anchor's 稳健底仓. The wall says
# "the 国内 pool has priced this leg ≥ 8pp more bullish than the de-vigged
# international market" — a structural slow-bleed signal, not an edge claim.
# 5/19 backtest case: 周三010 favorite implied 0.855 vs 欧赔 fair 0.715 → 0.140.
# spec §17.4 — equivalent-independent-ticket count below this floor appends
# the （高度共享场次） suffix to the chaos line, so the user reads "5 tickets
# but actually ≈ N independent bets" and can pick fewer.
EQUIV_INDEPENDENT_LOW_THRESHOLD: float = 1.5

# spec §20 — verdict boundaries for the day pool's heaviest-favorite tilt: the
# median of per-match minimum had odds. ≤ 大热门日 means "every match's
# favorite is heavily priced" — bold's cold-longshot picks are then betting
# against the pool's own consensus, which §22 surfaces.
HEAVY_FAVORITE_DAY_MAX: float = 1.80
BALANCED_DAY_MAX: float = 2.50

# spec §21 — theme resonance thresholds. The max picked-leg-match's 体彩
# implied probability for the theme's direction must reach the threshold or
# the engine is picking cold longshots, not riding consensus. Below threshold
# fires a 主题失谐 fact-only notice — descriptive, not prescriptive.
THEME_DRAW_RESONANCE: float = 0.30          # max draw implied across picked draw-lean legs
THEME_HIGH_GOALS_RESONANCE: float = 0.45    # max P(ttg≥3) across picked ttg legs

# spec §22 — descriptive flip-reading hint trigger: heavy-favorite-day
# consensus + low chaos + ≥1 theme dissonant → render a creative aid at
# the bottom that names the consensus direction. Strictly observational.
FLIP_READING_CHAOS_MAX: int = 20

# spec §13 — bold tickets target a realistic combined-odds band rather than the
# maximum. The band is for a 3-fold; longer parlays scale it geometrically.
TARGET_ODDS_3FOLD_LOW: float = 80.0
TARGET_ODDS_3FOLD_HIGH: float = 400.0
# A bold leg's 体彩 odds are kept in this realistic underdog range — a clear
# cold pick, not a freak scoreline (spec §13).


def _effective_odds(total_odds: float) -> float:
    """Combined odds capped at the 竞彩 payout limit (spec §10.1).

    Real combined odds beyond ``JCZQ_PAYOUT_CAP_YUAN / REFERENCE_STAKE_YUAN``
    pay nothing extra — the engine ranks combos by this capped value so it
    stops chasing un-collectable million-fold parlays. The ticket's stored
    ``total_odds`` keeps the true (uncapped) product; only ranking uses this.
    """
    return min(total_odds, JCZQ_PAYOUT_CAP_YUAN / REFERENCE_STAKE_YUAN)


@dataclass(slots=True, frozen=True)
class BoldTicket:
    """A parlay ticket — a set of distinct-match legs + its combined odds.

    There is NO win-probability / EV field — the engine has no probabilities
    (spec §5). ``avg_boldness`` is a heuristic salience average, labelled
    "大胆分" in every renderer, NEVER "胜率 / 信心".
    """

    id: str
    kind: str
    legs: list[BoldLeg]
    fold: int
    total_odds: float
    avg_boldness: float
    note: str = ""


def _ticket_total_odds(legs: list[BoldLeg]) -> float:
    """Product of the legs' 体彩 odds — the parlay's combined decimal odds."""
    product = 1.0
    for leg in legs:
        product *= leg.tc_odds
    return product


def _ticket_avg_boldness(legs: list[BoldLeg]) -> float:
    """Mean boldness across a ticket's legs — a salience average, not a rate."""
    return sum(leg.boldness for leg in legs) / len(legs) if legs else 0.0


def _band_fit(total_odds: float, fold: int) -> float:
    """How well a ticket's combined odds fits the realistic target band (spec §13).

    The 80-400× band for a 3-fold scales geometrically with ``fold`` (so per-leg
    odds stay realistic — a longer parlay is naturally higher). Returns 1.0
    inside the band and a ratio-based decay outside, so a moonshot combo ranks
    far below a realistic one.
    """
    exponent = fold / 3.0
    low = TARGET_ODDS_3FOLD_LOW**exponent
    high = TARGET_ODDS_3FOLD_HIGH**exponent
    if total_odds <= 0:
        return 0.0
    if total_odds < low:
        return total_odds / low
    if total_odds > high:
        return high / total_odds
    return 1.0


def _ticket_rank_score(legs: list[BoldLeg]) -> float:
    """A ticket's ranking score — ``band_fit × avg_boldness`` (spec §13).

    Ranks combos by how well they fit the realistic target odds band, NOT by
    raw odds — so the engine assembles bold-but-plausible parlays instead of
    chasing un-collectable million-fold moonshots.
    """
    return _band_fit(
        _ticket_total_odds(legs), len(legs)
    ) * _ticket_avg_boldness(legs)


def _over_cap_note(total_odds: float) -> str:
    """Honest cap annotation when a ticket's payout exceeds the 竞彩 limit, else ''."""
    cap_odds = JCZQ_PAYOUT_CAP_YUAN / REFERENCE_STAKE_YUAN
    if total_odds <= cap_odds:
        return ""
    payout = total_odds * REFERENCE_STAKE_YUAN
    return (
        f" · ⚠️本票 {REFERENCE_STAKE_YUAN:g} 元理论赔付 {payout:,.0f} 元，"
        f"超竞彩 {JCZQ_PAYOUT_CAP_YUAN:,.0f} 元单票封顶 — 实际只兑至 "
        f"{JCZQ_PAYOUT_CAP_YUAN:,.0f} 元"
    )


# spec §15 — bold-ticket 剧本 (storyline) archetypes. Descriptive, post-hoc
# classification of a ticket by its leg composition — it labels what the ticket
# already is, NEVER changes leg selection, so it cannot conflict with §10.2.

# Fixed selection order — Phase A picks one ticket per theme in this order.
THEME_ORDER: tuple[str, ...] = (
    THEME_DRAW, THEME_SCORE, THEME_HANDICAP, THEME_GOALS, THEME_MIXED,
)

# spec §17.3 / §24 — the 30-leg gate. by_theme accumulation below this number
# of GRADED legs blocks any retirement/weighting decision (§17.3 first half).
# At or above this number AND ticket_hits == 0, the theme is soft-retired:
# Phase A skips it; Phase B still considers its combos (§24 second half).




def retired_themes_from_history(
    by_theme: dict[str, dict[str, int]] | None,
) -> frozenset[str]:
    """spec §24 — themes past the 30-leg gate with zero whole-ticket hits.

    ``by_theme`` is the cumulative slot dict from
    ``bold-review-history.json`` (``_cumulative(...)['by_theme']``). A theme is
    retired ⟺ ``legs >= MIN_THEME_LEGS_FOR_RETIREMENT`` AND ``ticket_hits == 0``.

    The strict ``ticket_hits == 0`` gate is deliberate: ``ticket_hits > 0``
    keeps the theme in rotation even past 30 legs — the engine is entertainment
    and the user prefers "在困难中找落足点" over wholesale theme deletion.

    Legacy slots without the ``legs`` field default to 0 (never trigger), so
    retirement only fires after history.json is backfilled / new days accrue.
    """
    if not by_theme:
        return frozenset()
    retired = {
        theme
        for theme, slot in by_theme.items()
        if int(slot.get("legs", 0)) >= MIN_THEME_LEGS_FOR_RETIREMENT
        and int(slot.get("ticket_hits", 0)) == 0
    }
    return frozenset(retired)



# A market holding the majority of a ticket's legs → that market's theme. had
# has no theme of its own — a had-majority ticket falls through to 全市场混搭.

# One-line 剧本 narrative per theme — pure entertainment flavour. Contains NO
# advantage wording (胜率 / edge / +EV / 正期望 / 推荐下注 / 重仓) — §7 asserts it.






def bold_combos(
    legs: list[BoldLeg],
    chaos: int,
    *,
    retired_themes: frozenset[str] = frozenset(),
) -> list[BoldTicket]:
    """Assemble creative cross-market 3/4/5-fold parlays from the candidate ``legs``.

    Each ticket's legs are distinct matches (Rule O). When the candidate pool
    spans ≥2 markets a ticket may use at most ``MAX_LEGS_PER_MARKET_PER_TICKET``
    legs from any one market (spec §10.2 — forces cross-market mix; skipped on a
    single-market pool so v1 had-only days still produce tickets).

    Ticket *selection* is theme-driven (spec §15): every legal combo is scored
    by ``band_fit × avg_boldness`` (spec §13) and classified into a 剧本 theme.
    **Phase A** picks the best-ranked combo of each theme, so the bold tickets
    carry distinct characters instead of being the same legs permuted.
    **Phase B** fills toward ``BOLD_TICKET_COUNT`` with the next-best DISTINCT
    combos (diversity-penalized — single-market days have one theme, so Phase B
    does the spreading). A thin pool simply yields fewer tickets. ``chaos``
    already sized the candidate pool upstream (``chaos_pool_size``) and is not
    re-used here. Fewer than 3 candidate legs → an empty list (never a crash).

    spec §24 — ``retired_themes`` drops the Phase A guaranteed slot for any
    theme that hit the 30-leg gate with zero ticket hits. Phase B still
    considers retired-theme combos (they compete on score+penalty); the change
    is purely the loss of the saved seat. Default is empty → pre-§24 behaviour.
    """
    _ = chaos  # the pool was already chaos-sized; selection is theme-driven
    if len(legs) < 3:
        return []

    # The per-ticket market cap only makes sense — and is only safe — when the
    # pool actually has ≥2 markets to mix (spec §10.2).
    enforce_market_cap = len({lg.market for lg in legs}) >= 2

    # Every legal 3/4/5-fold combo, scored by band-fit × boldness (spec §13).
    scored: list[tuple[float, list[BoldLeg]]] = []
    for fold in (3, 4, 5):
        if fold > len(legs):
            continue
        for combo in itertools.combinations(legs, fold):
            combo_legs = list(combo)
            # Rule O — one leg per match (distinct match_no makes the parlay
            # legal regardless of which markets the legs come from).
            if len({lg.match_no for lg in combo_legs}) != fold:
                continue
            # spec §10.2 — no single market may dominate a ticket.
            if enforce_market_cap:
                market_counts = Counter(lg.market for lg in combo_legs)
                if max(market_counts.values()) > MAX_LEGS_PER_MARKET_PER_TICKET:
                    continue
            scored.append((_ticket_rank_score(combo_legs), combo_legs))
    if not scored:
        return []

    # spec §11.2 — running count of how many chosen tickets each match is in,
    # so both selection phases spread the ticket set across matches.
    appearance: Counter[str] = Counter()

    def _penalized(index: int) -> float:
        score, combo_legs = scored[index]
        reuse = sum(appearance[lg.match_no] for lg in combo_legs)
        return score / (1.0 + CONCENTRATION_PENALTY * reuse)

    used: set[int] = set()
    selected: list[list[BoldLeg]] = []

    def _take(index: int) -> None:
        used.add(index)
        combo_legs = scored[index][1]
        selected.append(combo_legs)
        for leg in combo_legs:
            appearance[leg.match_no] += 1

    # spec §15 Phase A — one ticket per theme, in fixed order; each theme picks
    # its best-ranked combo (concentration-penalized for same-score tie-breaks).
    by_theme: dict[str, list[int]] = {}
    for index, (_score, combo_legs) in enumerate(scored):
        theme, _script = ticket_theme(combo_legs)
        by_theme.setdefault(theme, []).append(index)
    for theme in THEME_ORDER:
        # spec §24 — soft-retired themes lose their Phase A saved seat. The
        # combos remain in ``scored`` and Phase B can still pick them on merit.
        if theme in retired_themes:
            continue
        candidates = [i for i in by_theme.get(theme, []) if i not in used]
        if candidates:
            _take(max(candidates, key=_penalized))

    # spec §15 Phase B — fill toward BOLD_TICKET_COUNT with the next-best
    # DISTINCT combos. A single-market day has one theme → Phase B does the
    # diversifying; a genuinely thin pool just runs out → fewer tickets.
    while len(selected) < BOLD_TICKET_COUNT:
        candidates = [i for i in range(len(scored)) if i not in used]
        if not candidates:
            break
        _take(max(candidates, key=_penalized))

    tickets: list[BoldTicket] = []
    for index, combo_legs in enumerate(
        sorted(selected, key=_ticket_rank_score, reverse=True),
        start=1,
    ):
        total_odds = _ticket_total_odds(combo_legs)
        note = "娱乐串 · 大胆分越高仅代表盘面越「有戏可挖」，不是命中概率"
        note += _over_cap_note(total_odds)
        tickets.append(
            BoldTicket(
                id=f"大胆票{index}",
                kind="大胆票",
                legs=combo_legs,
                fold=len(combo_legs),
                total_odds=round(total_odds, 4),
                avg_boldness=round(_ticket_avg_boldness(combo_legs), 4),
                note=note,
            )
        )
    return tickets


def anchor_ticket(matches: list[BoldMatch]) -> BoldTicket:
    """Build the 稳健底仓 — a short 2-3 leg parlay on the strongest 体彩 hot
    favorites (lowest-odds outcome per match).

    It is the hedge ballast for the bold tickets — NOT a "safe" bet, NOT
    +EV: the ``note`` says so honestly. High implied-hit-rate favorites still
    sit inside the same ~13% 竞彩 cut.

    spec §17.1 — for each candidate favorite, if the 体彩 implied probability
    exceeds the de-vigged 欧赔 fair probability by ≥ ``ANCHOR_GAP_THRESHOLD``,
    drop the leg (国内 pool priced it more bullish than the international
    market). When ``euro_fair_prob`` is empty (no snapshot) the guard skips
    and v1 lowest-odds-favorite behaviour is preserved — never a crash.
    """
    rated: list[tuple[float, BoldMatch, str]] = []
    for match in matches:
        usable = {o: v for o in OUTCOMES if (v := match.tc_odds.get(o)) and v > 0}
        if not usable:
            continue
        favorite = min(usable, key=lambda o: usable[o])
        fav_odds = usable[favorite]
        # §17.1 体彩-vs-欧赔 implied gap guard — applied only when 欧赔 fair
        # probability is available for this favorite outcome.
        fair = match.euro_fair_prob.get(favorite)
        if fair is not None and fair > 0.0:
            gap = (1.0 / fav_odds) - fair
            if gap >= ANCHOR_GAP_THRESHOLD:
                continue
        rated.append((fav_odds, match, favorite))
    rated.sort(key=lambda item: item[0])

    fold = min(ANCHOR_MAX_LEGS, len(rated))
    legs: list[BoldLeg] = []
    for fav_odds, match, favorite in rated[:fold]:
        legs.append(
            BoldLeg(
                match_no=match.match_no,
                league=match.league,
                home=match.home,
                away=match.away,
                pick=favorite,
                tc_odds=fav_odds,
                boldness=0.0,
                reason=f"{OUTCOME_LABELS[favorite]}向 · 体彩最强热门（最低赔）",
                market="had",
                pick_label=OUTCOME_LABELS[favorite],
            )
        )
    return BoldTicket(
        id="稳健底仓",
        kind="稳健底仓",
        legs=legs,
        fold=len(legs),
        total_odds=round(_ticket_total_odds(legs), 4) if legs else 0.0,
        avg_boldness=0.0,
        note=(
            "高命中倾向 ≠ 长期赚钱 — 它同样在 13% 抽水内，"
            "是大胆票的对冲压舱，不是「安全」、也不是赚钱腿"
        ),
    )


# ---------------------------------------------------------------------------
# Task 6 — engine assembly + welded honest label (spec §0, §5, §7)
# ---------------------------------------------------------------------------

# The welded honest label. EXACT text — asserted by a test (spec §7). The
# "−" is U+2212 (a real minus sign). This string is the first thing in every
# output (stdout / file / PDF / bot) — it must never be edited away.






@dataclass(slots=True, frozen=True)
class BoldComboPlan:
    """The day's full bold-combo output — anchor + bold tickets + chaos value.

    ``label`` is always ``HARD_LABEL``. There is NO win-probability / EV field
    anywhere in this plan or its tickets — the engine has no probabilities.
    ``pool_signals`` carries the per-match implied signals (§20-§22) so the
    renderer can expose pool-vs-theme honesty without re-loading 体彩 boards.
    Legacy callers that construct the plan without ``pool_signals`` get an
    empty default; render helpers degrade silently.
    """

    run_date: str
    day_chaos: int
    chaos_band: str
    anchor: BoldTicket
    tickets: list[BoldTicket]
    label: str = HARD_LABEL
    pool_signals: PoolSignals = field(default_factory=PoolSignals)
    # spec §24 — themes past the 30-leg gate at 0 ticket_hits; captured at
    # plan-build time so the renderer prints the exact 0/N + leg count.
    retired_themes: tuple[RetiredTheme, ...] = ()


# A market may fill at most this fraction of the candidate pool (spec §12) —
# guarantees the pool spans ≥2 markets when ≥2 markets exist, so the §10.2
# per-ticket market cap actually engages.
MARKET_POOL_SHARE: float = 0.5


def _balanced_pool(matches: list[BoldMatch], pool_n: int) -> list[BoldLeg]:
    """Build a match- AND market-balanced candidate pool of up to ``pool_n`` legs.

    比分 legs structurally dominate boldness (cold scorelines score ~1.0 on the
    contrarian/long-tail signal), so a plain boldness pool fills with 比分 and
    defeats the §10.2 per-ticket market cap. This builder caps any one market at
    ``pool_n * MARKET_POOL_SHARE`` slots: pass 1 seeds one leg per match (its
    boldest leg whose market is not yet full — match coverage + market
    coverage), pass 2 fills remaining slots by global boldness (still
    market-capped). A genuinely single-market day degrades to a single-market
    pool via the pass-1 fallback and §10.2 simply does not engage. The result
    is boldness-sorted.
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
        if legs:
            per_match.append(legs)
    if not per_match:
        return []

    # boldest matches first — they get first pick of the scarce market slots.
    per_match.sort(key=lambda legs: legs[0].boldness, reverse=True)
    market_cap = max(1, int(pool_n * MARKET_POOL_SHARE))
    pool: list[BoldLeg] = []
    market_count: Counter[str] = Counter()

    # pass 1 — one leg per match, preferring a market that is not yet full.
    for legs in per_match:
        if len(pool) >= pool_n:
            break
        choice = next(
            (lg for lg in legs if market_count[lg.market] < market_cap),
            legs[0],
        )
        pool.append(choice)
        market_count[choice.market] += 1

    # pass 2 — fill remaining slots with the next-boldest legs, market-capped.
    if len(pool) < pool_n:
        used = {id(lg) for lg in pool}
        rest = sorted(
            (lg for legs in per_match for lg in legs if id(lg) not in used),
            key=lambda lg: lg.boldness,
            reverse=True,
        )
        for leg in rest:
            if len(pool) >= pool_n:
                break
            if market_count[leg.market] < market_cap:
                pool.append(leg)
                market_count[leg.market] += 1

    pool.sort(key=lambda lg: lg.boldness, reverse=True)
    return pool


class BoldComboEngine:
    """Orchestrates the bold-combo pipeline (Tasks 2-5) into a ``BoldComboPlan``.

    per-match boldness → one bold leg per match → day chaos value → a
    chaos-sized candidate pool of the top-N bold legs → ranked 3/4/5-fold bold
    tickets + a 稳健底仓 anchor. No predictive model is touched.
    """

    def generate(
        self,
        run_date: str,
        matches: list[BoldMatch],
        *,
        retired_themes: tuple[RetiredTheme, ...] = (),
    ) -> BoldComboPlan:
        """Build the day's plan from the supplied 体彩+国际 ``matches``.

        spec §24 — ``retired_themes`` (from the cumulative review history) is
        passed through to ``bold_combos`` so Phase A skips the retired theme's
        saved seat, and rendered as a fact-only notice at the top of the plan.
        Default empty tuple keeps the pre-§24 behavior — tests + replays that
        construct an engine without history continue to work.
        """
        chaos = day_chaos(matches)
        band = chaos_band(chaos)

        pool_n = chaos_pool_size(chaos)
        # spec §12 — a market-balanced pool: caps any one market at half the
        # slots so 比分 cannot fill the pool and defeat the §10.2 per-ticket
        # market cap. Also seeds one leg per match for Rule-O reachability.
        candidate_pool = _balanced_pool(matches, pool_n)

        retired_set = frozenset(rt.theme for rt in retired_themes)
        tickets = bold_combos(
            candidate_pool, chaos, retired_themes=retired_set
        )
        anchor = anchor_ticket(matches)
        pool_signals = compute_pool_signals(matches)

        return BoldComboPlan(
            run_date=run_date,
            day_chaos=chaos,
            chaos_band=band,
            anchor=anchor,
            tickets=tickets,
            pool_signals=pool_signals,
            retired_themes=retired_themes,
        )


def _render_leg(leg: BoldLeg) -> str:
    """One bold leg as a markdown bullet: 编号 / 市场 / 选项 / 体彩赔率 / 理由."""
    label = leg.pick_label or OUTCOME_LABELS.get(leg.pick, leg.pick)
    market = MARKET_LABELS.get(leg.market, leg.market)
    return (
        f"  - {leg.match_no} {leg.home} vs {leg.away} ｜ [{market}] "
        f"选 **{label}** @ {leg.tc_odds:.2f} ｜ {leg.reason}"
    )


def _render_ticket(ticket: BoldTicket) -> list[str]:
    """One ticket as markdown lines — odds + 大胆分, never a probability/EV.

    A 大胆票 carries its 剧本 archetype in the header and a one-line 剧本
    narrative below the legs (spec §15)."""
    header = f"### {ticket.id}"
    script = ""
    if ticket.kind == "大胆票":
        theme, script = ticket_theme(ticket.legs)
        if theme:
            header += f" · {theme}"
    header += f"（{ticket.fold}串1 · 合计赔率 {ticket.total_odds:.2f}"
    if ticket.kind == "大胆票":
        header += f" · 平均大胆分 {ticket.avg_boldness:.3f}）"
    else:
        header += "）"
    lines = [header]
    for leg in ticket.legs:
        lines.append(_render_leg(leg))
    if script:
        lines.append(f"  > 剧本：{script}")
    if ticket.note:
        lines.append(f"  > {ticket.note}")
    return lines


def degenerate_pool_notice(tickets: list[BoldTicket]) -> str:
    """spec §18 — when every match in the bold pool contributes exactly one
    distinct leg, the "5 themed tickets" output is mathematically the
    enumeration ``C(U_m, k)`` of all ≥k-leg subsets of the U_m-match pool.
    Theme grouping (§15) and diversity penalty (§11.2) degrade to
    ``itertools.combinations`` — the 5 tickets are permutations, not choices.

    Returns a one-line notice when degenerate (≥2 tickets, every match
    contributing one distinct leg), empty string otherwise. The notice is
    fact-only (counts + folds + combinatorial totals); banned-word safe.
    """
    import math

    if len(tickets) < 2:
        return ""
    unique_matches = {leg.match_no for ticket in tickets for leg in ticket.legs}
    unique_legs = {
        (leg.match_no, leg.market, leg.pick_label)
        for ticket in tickets
        for leg in ticket.legs
    }
    if len(unique_legs) != len(unique_matches) or not unique_matches:
        return ""
    folds_used = sorted({ticket.fold for ticket in tickets if ticket.fold > 0})
    if not folds_used:
        return ""
    u_m = len(unique_matches)
    enumeration_total = sum(math.comb(u_m, k) for k in folds_used)
    comb_terms = "+".join(f"C({u_m},{k})" for k in folds_used)
    n_tickets = len(tickets)
    if n_tickets == enumeration_total:
        coverage = f"共 {enumeration_total} 种"
    else:
        coverage = f"共 {n_tickets}/{enumeration_total} 种"
    return (
        f"⚠️ 腿池退化：{u_m} 场池 × 单腿，{n_tickets} 张大胆票 = "
        f"{comb_terms} 枚举（{coverage}）—— 主题剧本只是排列，不是选择。"
    )


def equivalent_independent_tickets(tickets: list[BoldTicket]) -> float:
    """spec §17.4 — exposes the "5 tickets ≠ 5 independent bets" illusion.

    Equals ``unique_match_count / mean_legs_per_ticket``. With fully disjoint
    tickets it returns the ticket count (true independence); with heavy
    shared matches it collapses toward 1 — the tickets win/lose together.
    Returns 0.0 for an empty list (renderer then skips the line).

    5/19 case: 5 tickets × 16 legs / 4 unique matches → 4 / (16/5) = 1.25.
    """
    if not tickets:
        return 0.0
    unique_matches = {leg.match_no for ticket in tickets for leg in ticket.legs}
    total_legs = sum(len(ticket.legs) for ticket in tickets)
    if total_legs == 0:
        return 0.0
    mean_legs = total_legs / len(tickets)
    return len(unique_matches) / mean_legs






def pool_consensus(pool_signals: PoolSignals) -> str:
    """spec §20 — one-line summary of the day pool's heaviest-favorite tilt.

    Median of each match's minimum had odds → 大热门日 (≤
    ``HEAVY_FAVORITE_DAY_MAX``), 平衡日 (≤ ``BALANCED_DAY_MAX``), 上盘日
    otherwise. Empty pool / no had odds → ``""`` (renderer omits the line).
    Fact-only phrasing; no advantage wording.
    """
    odds = sorted(
        ms.min_had_odds for ms in pool_signals.by_match.values()
        if ms.min_had_odds > 0
    )
    if not odds:
        return ""
    median = statistics.median(odds)
    if median <= HEAVY_FAVORITE_DAY_MAX:
        verdict = "大热门日"
    elif median <= BALANCED_DAY_MAX:
        verdict = "平衡日"
    else:
        verdict = "上盘日"
    return (
        f"🟦 盘面共识：{len(odds)} 场池最低 had 中位赔 = {median:.2f} —— {verdict}。"
    )


def _bold_pick_direction(leg: BoldLeg) -> str:
    """Reduce a bold leg to ``home``/``draw``/``away``/``''``.

    had/hhad: the pick key is already a directional outcome. crs: parse the
    scoreline (sHHsAA) or 其他 buckets (s1sh/s1sd/s1sa). ttg: total-goals is
    orthogonal to the H/D/A axis — returns ``''`` so it never registers as a
    direction conflict. Unknown crs keys → ``''`` (skipped by callers).
    """
    if leg.market in ("had", "hhad"):
        if leg.pick in ("home", "draw", "away"):
            return leg.pick
        return ""
    if leg.market == "crs":
        key = leg.pick
        if key == "s1sh":
            return "home"
        if key == "s1sd":
            return "draw"
        if key == "s1sa":
            return "away"
        if len(key) == 6 and key[0] == "s" and key[3] == "s":
            try:
                h, a = int(key[1:3]), int(key[4:6])
            except ValueError:
                return ""
            if h > a:
                return "home"
            if h < a:
                return "away"
            return "draw"
    return ""


def same_match_contradictions(plan: BoldComboPlan) -> list[str]:
    """spec §19 — flag anchor ↔ bold same-match directional conflict.

    Anchor is had-only (hold one of home/draw/away per leg). Bold legs are
    multi-market: had/hhad/crs reduce to a directional vote, ttg is orthogonal
    (never a conflict). When the same ``match_no`` appears in BOTH anchor and
    ≥1 bold ticket with opposing directions, surface a fact-only ⚠️ line per
    conflicting (market, pick) pair (de-duped — multiple tickets sharing the
    same bold leg produce one notice). No banned words.

    5/20 case: anchor 003 胜 vs bold tickets' 003 比分 1:1 → 同场反向 fires.
    """
    if not plan.anchor.legs or not plan.tickets:
        return []
    anchor_by_match: dict[str, BoldLeg] = {
        leg.match_no: leg for leg in plan.anchor.legs
    }
    notices: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for ticket in plan.tickets:
        for leg in ticket.legs:
            anchor_leg = anchor_by_match.get(leg.match_no)
            if anchor_leg is None:
                continue
            bold_dir = _bold_pick_direction(leg)
            if not bold_dir:
                continue
            anchor_dir = _bold_pick_direction(anchor_leg)
            if not anchor_dir or anchor_dir == bold_dir:
                continue
            key = (leg.match_no, leg.market, leg.pick_label)
            if key in seen:
                continue
            seen.add(key)
            market = MARKET_LABELS.get(leg.market, leg.market)
            notices.append(
                f"⚠️ 同场反向：{leg.match_no} {leg.home} vs {leg.away} — "
                f"底仓 [{anchor_leg.pick_label}] @{anchor_leg.tc_odds:.2f}，"
                f"大胆票 [{market} {leg.pick_label}] @{leg.tc_odds:.2f}，方向相反。"
            )
    return notices


def theme_dissonance_notices(
    tickets: list[BoldTicket], pool_signals: PoolSignals
) -> list[str]:
    """spec §21 — flag bold themes that the pool itself doesn't support.

    For each theme used by the bold tickets, check the picked-leg matches
    against a theme-specific resonance threshold on the pool's 体彩-implied
    direction. Currently covers the two themes most prone to reaching for
    cold longshots:

    - 平局收割: max draw_implied across draw-lean picked-leg matches
      ≥ THEME_DRAW_RESONANCE → resonant. Below → fact-only ⚠️ notice.
    - 进球狂欢: max high_goals_implied across ttg picked-leg matches
      ≥ THEME_HIGH_GOALS_RESONANCE → resonant. Below → notice.

    冷门比分梦 / 黑马让球 / 全市场混搭 — descriptive, always treated as
    resonant (the first two ARE the cold/contrarian themes by definition;
    the last is the cross-market mixed bucket). spec §17.3 30-leg meta-rule
    is unaffected: this notice is per-day pool reading, not theme weighting.
    """
    if not tickets or not pool_signals.by_match:
        return []
    themes_in_use = {ticket_theme(t.legs)[0] for t in tickets}
    notices: list[str] = []

    if THEME_DRAW in themes_in_use:
        draw_match_nos = {
            lg.match_no
            for t in tickets for lg in t.legs
            if _is_draw_lean(lg)
        }
        max_draw = max(
            (pool_signals.by_match[m].draw_implied
             for m in draw_match_nos
             if m in pool_signals.by_match),
            default=0.0,
        )
        if 0.0 < max_draw < THEME_DRAW_RESONANCE:
            notices.append(
                f"⚠️ 主题失谐：「{THEME_DRAW}」今晚池内最高 draw 隐含 "
                f"{max_draw * 100:.0f}%，没有一场把平局定得偏强"
                f"（≥{int(THEME_DRAW_RESONANCE * 100)}%）—— 主题=反盘面挑冷。"
            )

    if THEME_GOALS in themes_in_use:
        ttg_match_nos = {
            lg.match_no
            for t in tickets for lg in t.legs
            if lg.market == "ttg"
        }
        max_high = max(
            (pool_signals.by_match[m].high_goals_implied
             for m in ttg_match_nos
             if m in pool_signals.by_match),
            default=0.0,
        )
        if 0.0 < max_high < THEME_HIGH_GOALS_RESONANCE:
            notices.append(
                f"⚠️ 主题失谐：「{THEME_GOALS}」今晚池内最高「≥3 球」隐含 "
                f"{max_high * 100:.0f}%，没有一场把高进球定得偏强"
                f"（≥{int(THEME_HIGH_GOALS_RESONANCE * 100)}%）—— 主题=反盘面挑冷。"
            )
    return notices


def flip_reading_hint(plan: BoldComboPlan) -> str:
    """spec §22 — descriptive flip-reading hint at the bottom of the plan.

    Trigger: bold tickets exist + day chaos ≤ FLIP_READING_CHAOS_MAX + pool
    consensus is 大热门日 + ≥1 theme in use is dissonant (§21). Then the
    engine is structurally picking against the pool's own consensus — surface
    the consensus direction so the user can read the bold tickets in context.

    Strictly observational. No buy/sell directive; no 推荐 / +EV / edge wording.
    """
    if not plan.tickets or not plan.pool_signals.by_match:
        return ""
    if plan.day_chaos > FLIP_READING_CHAOS_MAX:
        return ""
    consensus = pool_consensus(plan.pool_signals)
    if "大热门日" not in consensus:
        return ""
    dissonance = theme_dissonance_notices(plan.tickets, plan.pool_signals)
    if not dissonance:
        return ""
    themes_in_use = sorted({ticket_theme(t.legs)[0] for t in plan.tickets} - {""})
    theme_str = "/".join(themes_in_use) if themes_in_use else "—"
    return (
        f"🎨 翻面读法：盘面共识=大热门日 + 大盘混乱值 {plan.day_chaos}/100 + 主题"
        f"「{theme_str}」失谐 —— 顺着读 = 热门兑现 / 高进球。纯观察、不替你切换。"
    )


def _concentration_warning(tickets: list[BoldTicket]) -> str:
    """A 🟦 note when one match dominates the bold tickets (spec §11.2).

    Returns '' unless ≥2 tickets exist and some match appears in more than
    ``CONCENTRATION_WARN_FRACTION`` of them — surfaced honestly so the user
    sees the tickets are NOT really diversified (they win/lose together).
    """
    if len(tickets) < 2:
        return ""
    appearance: Counter[str] = Counter()
    for ticket in tickets:
        for match_no in {lg.match_no for lg in ticket.legs}:
            appearance[match_no] += 1
    hot = [
        (m, c)
        for m, c in appearance.items()
        if c > CONCENTRATION_WARN_FRACTION * len(tickets)
    ]
    if not hot:
        return ""
    names = "、".join(
        f"{m}（{c}/{len(tickets)} 张）"
        for m, c in sorted(hot, key=lambda item: -item[1])
    )
    return (
        f"🟦 集中度提示：{names} 出现在多数大胆票里 —— "
        "这些票会一起赢一起输，并非真正分散风险。"
    )


def _retirement_notice_lines(
    retired: tuple[RetiredTheme, ...],
) -> list[str]:
    """spec §24 — fact-only retirement notice; one line per retired theme.

    Phrasing uses only counted nouns (累计 / 张 / 腿 / 门槛 / 跳过保送); none
    of the §7 banned advantage words. Empty input → empty list (no clean-day
    pollution).
    """
    return [
        f"⚠️ 主题汰留：「{rt.theme}」累计 {rt.ticket_hits}/{rt.tickets} 张"
        f"（{rt.legs} 腿 ≥ {MIN_THEME_LEGS_FOR_RETIREMENT} 门槛）"
        f"今晚 Phase A 跳过保送。"
        for rt in retired
    ]


def render_bold_plan(plan: BoldComboPlan) -> str:
    """Render a ``BoldComboPlan`` to honest-labelled markdown.

    The output STARTS with ``HARD_LABEL`` and the day chaos line — welded at
    the top of every output (spec §5). It carries NO advantage wording
    (胜率 / edge / +EV / 正期望 / 推荐下注 / 重仓) and NO probability/EV column:
    the boldness number is labelled "大胆分" only.
    """
    equiv_independent = equivalent_independent_tickets(plan.tickets)
    # §17.4 — append （高度共享场次） when tickets are highly correlated.
    chaos_suffix = (
        "（高度共享场次）"
        if 0.0 < equiv_independent < EQUIV_INDEPENDENT_LOW_THRESHOLD
        else ""
    )
    lines: list[str] = [HARD_LABEL, ""]
    lines.append(
        f"**当天大盘面混乱值：{plan.day_chaos}/100（{plan.chaos_band}）** "
        f"· {plan.run_date}{chaos_suffix}"
    )
    lines.append(
        "> 混乱值越高 = 盘面越吵、组合越长越野；它只是娱乐抖动旋钮，不是优势信号。"
    )
    # §20 — pool-consensus tilt: a fact-only line on the day's heaviest-favorite
    # median had odds. Empty when the pool has no had odds (legacy / replay).
    consensus_line = pool_consensus(plan.pool_signals)
    if consensus_line:
        lines.append(consensus_line)
    concentration = _concentration_warning(plan.tickets)
    if concentration:
        lines.append(concentration)
    if equiv_independent > 0.0:
        # §17.4 — fact-only line: unique_match_count / mean_legs_per_ticket.
        # Phrasing carries no advantage wording (banned-word check in tests).
        lines.append(
            f"🟦 等效独立票数 ≈ {equiv_independent:.2f} 张 —— "
            "这些票实际共享场次，分散是错觉。"
        )
    # §18 — degenerate pool: 5 themed tickets are really C(N,k) enumeration.
    pool_notice = degenerate_pool_notice(plan.tickets)
    if pool_notice:
        lines.append(pool_notice)
    # §19 — anchor ↔ bold same-match directional conflicts (one line each).
    lines.extend(same_match_contradictions(plan))
    # §21 — bold-theme pick vs pool consensus on the theme's direction.
    lines.extend(theme_dissonance_notices(plan.tickets, plan.pool_signals))
    # §24 — soft-retired themes (30-leg gate met, 0 ticket hits): one fact
    # line per theme, between §21 dissonance and the blank-line separator.
    lines.extend(_retirement_notice_lines(plan.retired_themes))
    lines.append("")

    lines.append("## 稳健底仓（对冲压舱）")
    if plan.anchor.legs:
        lines.extend(_render_ticket(plan.anchor))
    else:
        lines.append("  - （当天无可用 体彩 赔率，底仓略过）")
    lines.append("")

    lines.append("## 大胆票")
    if plan.tickets:
        for ticket in plan.tickets:
            lines.extend(_render_ticket(ticket))
            lines.append("")
    else:
        lines.append("  - （候选腿不足 3 条，今天不出大胆串）")
        lines.append("")

    lines.append(
        "_「大胆分」是盘面启发式显著性分，不是命中概率；本引擎不预测胜负、"
        "长期为负，仅供娱乐。注金请只用娱乐预算的小额。_"
    )
    lines.append(
        "_注金提示：上面多张票相互独立 ≠ 风险分散 —— 它们常共享同几场、"
        "会一起赢一起输。你完全可以只挑一张、或一张都不买。_"
    )
    # §22 — flip-reading creative aid at the bottom (descriptive, not advice).
    # Only fires when the engine's tickets are reading against pool consensus.
    flip = flip_reading_hint(plan)
    if flip:
        lines.append(flip)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Task 7 — context.json → BoldMatch loader (体彩 odds + optional 欧赔)
# ---------------------------------------------------------------------------

# 体彩 had 选项 → the engine's OUTCOMES vocabulary.
_HAD_PICK_TO_OUTCOME: dict[str, str] = {"胜": "home", "平": "draw", "负": "away"}

# A context.json match's ``role`` string → the heat tag it reads as.
_ROLE_TO_TAG: dict[str, str] = {"强胆场": "强胆场"}


def _had_odds(candidates: list[dict]) -> dict[str, float]:
    """Pull the 胜平负 (had) decimal odds out of a context.json match's
    ``candidates`` list. Returns an empty dict when the had pool is absent."""
    odds: dict[str, float] = {}
    for cand in candidates:
        if cand.get("pool") != "had":
            continue
        outcome = _HAD_PICK_TO_OUTCOME.get(str(cand.get("pick", "")))
        value = cand.get("odds")
        if outcome and isinstance(value, int | float) and value > 1.0:
            odds[outcome] = float(value)
    return odds




def _match_tags(role: str) -> set[str]:
    """Map a context.json ``role`` to the engine's heat tags."""
    tag = _ROLE_TO_TAG.get(role.strip())
    return {tag} if tag else set()


def bold_matches_from_context(
    context: dict, *, euro_by_match_no: dict[str, dict]
) -> list[BoldMatch]:
    """Build ``BoldMatch`` objects from a daily ``context.json`` + optional 欧赔.

    Each context match must carry a 胜平负 (``had``) pool — that is the only
    market the engine scores. ``euro_by_match_no`` maps 竞彩号 →
    ``{"odds": .., "opening": .., "per_book": ..}`` (the 欧赔 collected from
    500.com); a match absent from it simply gets empty 欧赔 fields, and its
    conflict/drift/dispersion signals degrade to 0 — heat + contrarian still
    work. A match with no usable ``had`` odds is skipped (never a crash).
    """
    matches: list[BoldMatch] = []
    for raw in context.get("matches") or []:
        tc_odds = _had_odds(raw.get("candidates") or [])
        if len(tc_odds) < 3:
            continue
        euro = euro_by_match_no.get(str(raw.get("match_no", "")), {})
        matches.append(
            BoldMatch(
                match_no=str(raw.get("match_no", "")),
                league=str(raw.get("league", "")),
                home=str(raw.get("home_team", "")),
                away=str(raw.get("away_team", "")),
                tc_odds=tc_odds,
                euro_odds=dict(euro.get("odds") or {}),
                euro_opening=dict(euro.get("opening") or {}),
                per_book_odds={
                    k: list(v) for k, v in (euro.get("per_book") or {}).items()
                },
                tags=_match_tags(str(raw.get("role", ""))),
                vig=_tc_vig(tc_odds),
            )
        )
    return matches


def euro_from_fcom500(collected: dict) -> dict[str, dict]:
    """Reshape a ``Fcom500OddsProvider.collect()`` result into the
    ``euro_by_match_no`` mapping ``bold_matches_from_context`` expects.

    Only the 胜平负 (``match_winner``) market is used — its parsed
    ``MarketOdds`` carries ``opening_odds`` + ``per_book_odds`` (Task 1).
    A match whose 欧赔 page failed to parse simply has no entry — graceful
    degradation. This reads the 500.com domain objects but imports NO
    predictive model.
    """
    euro: dict[str, dict] = {}
    for match_no, entry in collected.items():
        market = entry.odds.markets.get("match_winner")
        if market is None:
            continue
        odds = {o.outcome_key: o.average_odds for o in market.outcomes}
        euro[match_no] = {"odds": odds}
    return euro
















def fetch_sporttery_value_with_fallback() -> tuple[dict, str]:
    """体彩盘面抓取：sporttery 主源 → trade.500.com 备源（spec 2026-06-11）。

    返回 ``(value, source)``；``source`` ∈ {"sporttery", "fcom500-fallback"}。
    回退触发两种情形：主源抛 ``JczqProviderError``（403/网络/errorCode≠0），或
    返回的 value 无非空 ``matchInfoList``（2026-06-11 WAF 降级空壳形态）。备源
    只有 had/hhad 两池。备源也失败/解析 0 场 → 原样抛出主源错误——绝不静默
    出假空盘。
    """
    import logging

    import nutmeg.services.jczq as jczq_service

    logger = logging.getLogger(__name__)
    primary_error: Exception
    try:
        fetched = jczq_service.SportteryJczqCalculatorProvider().fetch()
        value = fetched.get("value") if "value" in fetched else fetched
        if value.get("matchInfoList"):
            return value, "sporttery"
        primary_error = jczq_service.JczqProviderError(
            "Sporttery returned no matchInfoList (degraded/WAF response)"
        )
        logger.warning("sporttery 主源返回空壳（无 matchInfoList），尝试 500.com 备源")
    except jczq_service.JczqProviderError as exc:
        primary_error = exc
        logger.warning("sporttery 主源失败（%s），尝试 500.com 备源", exc)

    try:
        import nutmeg.data.fcom500 as fcom500

        with fcom500.Fcom500Client() as client:
            html = client.get("https://trade.500.com/jczq/")
        board = fcom500.parse_jczq_list(html)
        value = fcom500.sporttery_value_from_jczq_board(board)
        if value.get("matchInfoList"):
            return value, "fcom500-fallback"
        logger.warning("500.com 备源解析 0 场在售比赛")
    except Exception:  # noqa: BLE001 — 备源失败不掩盖主源错误
        logger.warning("500.com 备源也失败", exc_info=True)
    raise primary_error


def persist_sporttery_snapshot(run_date: str, output_dir, value: dict) -> None:
    """Write the Sporttery response to ``<output_dir>/daily/<run_date>/
    sporttery_markets.json`` so ``--replay`` is reproducible.

    守卫（spec 2026-06-11）：新 ``value`` 无非空 ``matchInfoList`` 且磁盘已有
    含非空 ``matchInfoList`` 的快照 → 拒绝覆盖。修 2026-06-11 数据丢失 bug——
    WAF 降级空壳把当天 12:00 的完好 20 场快照冲掉（与 v2.2 修过的 ``--replay``
    覆盖派发文件 bug 同族）。
    """
    import json
    import logging
    from pathlib import Path

    path = Path(output_dir) / "daily" / run_date / "sporttery_markets.json"
    if not value.get("matchInfoList") and path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            existing = {}
        if isinstance(existing, dict) and existing.get("matchInfoList"):
            logging.getLogger(__name__).warning(
                "sporttery snapshot guard: 拒绝用空盘响应覆盖 %s 的非空快照",
                run_date,
            )
            return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")




def persist_bold_odds_snapshot(run_date: str, output_dir, bold_odds: dict) -> None:
    """Write the ``collect_bold_odds`` result to ``<output_dir>/daily/<run_date>/
    bold_odds.json`` so ``--replay`` reproduces the 国际-odds-enriched engine
    (spec §14).

    Without this, ``--replay`` never re-fetches 国际 odds and degrades to
    体彩-only — the conflict / drift / dispersion signals collapse to 0 and the
    day chaos value falsely reads 0. ``bold_odds`` maps 竞彩号 →
    ``{market_name: MarketOdds}``; each ``MarketOdds`` is a plain fcom500
    dataclass (no predictive model) serialized via ``dataclasses.asdict``.
    """
    import dataclasses
    import json
    from pathlib import Path

    payload = {
        match_no: {
            market: dataclasses.asdict(odds) for market, odds in markets.items()
        }
        for match_no, markets in bold_odds.items()
    }
    path = Path(output_dir) / "daily" / run_date / "bold_odds.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")




def replay_bold_combos(run_date: str, output_dir) -> str:
    """Replay a stored ``context.json`` through the bold-combo engine.

    Reads ``<output_dir>/daily/<run_date>/context.json`` for the 体彩 odds,
    attempts to enrich it with 500.com 欧赔 (degrading silently to 体彩-only on
    any failure), runs ``BoldComboEngine`` and returns the honest-labelled
    markdown. Raises ``FileNotFoundError`` when the context file is absent.
    """
    import json
    import logging
    from pathlib import Path

    logger = logging.getLogger(__name__)
    ctx_path = Path(output_dir) / "daily" / run_date / "context.json"
    if not ctx_path.exists():
        raise FileNotFoundError(f"context.json not found: {ctx_path}")
    context = json.loads(ctx_path.read_text(encoding="utf-8"))

    euro_by_match_no: dict[str, dict] = {}
    try:
        from nutmeg.data.fcom500 import Fcom500Client, Fcom500OddsProvider

        with Fcom500Client() as client:
            collected = Fcom500OddsProvider(client=client).collect(run_date)
        euro_by_match_no = euro_from_fcom500(collected)
    except Exception:  # noqa: BLE001 — 欧赔 is optional; degrade to 体彩-only
        logger.warning("bold-combos: 欧赔 enrichment failed — 体彩-only", exc_info=True)

    matches = bold_matches_from_context(
        context, euro_by_match_no=euro_by_match_no
    )
    plan = BoldComboEngine().generate(run_date, matches)
    return render_bold_plan(plan)


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

    # spec §14 — 国际 odds are snapshotted alongside the Sporttery markets so
    # --replay reproduces the full-signal engine instead of degrading to
    # 体彩-only (the silent chaos=0 bug a 2026-05-18 replay exposed).
    bold_odds: dict[str, dict] = {}
    if replay:
        bold_odds = load_bold_odds_snapshot(run_date, output_dir)
    else:
        try:
            from nutmeg.data.fcom500 import Fcom500Client, collect_bold_odds

            with Fcom500Client() as client:
                bold_odds = collect_bold_odds(client)
        except Exception:  # noqa: BLE001 — 国际 odds optional; degrade
            logger.warning("bold-combos: 国际 odds enrichment failed", exc_info=True)
        if bold_odds:
            persist_bold_odds_snapshot(run_date, output_dir, bold_odds)

    matches = bold_matches_from_sporttery(
        value or {}, run_date=run_date, bold_odds=bold_odds
    )
    # spec §24 — read the cumulative review history; themes past the 30-leg
    # gate at 0 ticket hits lose their Phase A saved seat and surface a fact
    # line at the top of the rendered plan. Missing/empty/corrupt history →
    # empty tuple, never a crash.
    retired = _load_retired_themes(output_dir)
    plan = BoldComboEngine().generate(run_date, matches, retired_themes=retired)
    return render_bold_plan(plan)


def _load_retired_themes(output_dir) -> tuple[RetiredTheme, ...]:
    """spec §24 — read bold-review-history.json and return the themes past
    the 30-leg gate with 0 ticket_hits. Lazy-imports from the review module
    to avoid a circular dependency. Missing file / parse error / no themes
    past the gate → empty tuple.
    """
    from nutmeg.services.jczq_bold_review import _cumulative, _load_history

    history = _load_history(output_dir)
    cumulative = _cumulative(history)
    return retired_themes_with_stats(cumulative.get("by_theme") or {})
