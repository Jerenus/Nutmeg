"""JCZQ tiered-plan v2 review — spec §6.

The next-day backtest: replays the v2 plan from snapshots, grades each tier
independently against okooo results, appends to history. Cross-version §24:
``retired_themes`` accumulator reads BOTH ``bold-review-history`` (v1) and
``tiered-plan-history`` (v2)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from nutmeg.services.jczq_bold_combos import (
    HARD_LABEL,
    MARKET_LABELS,
    BoldLeg,
    RetiredTheme,
    bold_matches_from_sporttery,
    load_bold_odds_snapshot,
    load_sporttery_snapshot,
    retired_themes_with_stats,
    ticket_theme,
)
from nutmeg.services.jczq_bold_review import grade_leg
from nutmeg.services.jczq_tiered import (
    DEFAULT_TIER_A,
    DEFAULT_TIER_B,
    DEFAULT_TIER_D,
    DEFAULT_TIER_E,
    LegReason,
    Tier,
    TieredLeg,
    TieredPlan,
    TierProfile,
    confidence_tag_for_code,
    select_tiered_plan,
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


def _history_before(history: list[dict], before_date: Optional[str]) -> list[dict]:
    if not before_date:
        return history
    return [
        rec for rec in history
        if (rec.get("date") or "") < before_date
    ]


def _cumulative_by_theme(history: list[dict], key: str) -> dict[str, dict]:
    """Walk history records, sum by_theme slots from the given key."""
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


def load_cross_version_retired_themes(
    output_dir, *, before_date: Optional[str] = None
) -> tuple[RetiredTheme, ...]:
    """spec §6.3 — read v1 ``bold-review-history.json`` + v2
    ``tiered-plan-history.json`` histories, sum by_theme, return the
    retired-themes set passed to the new engine. Missing files / parse
    errors / no themes past the 30-leg gate → empty tuple."""
    output = Path(output_dir)
    v1_hist = _history_before(
        _load_history(output / "bold-review-history.json"), before_date
    )
    v2_hist = _history_before(
        _load_history(output / "tiered-plan-history.json"), before_date
    )
    v1_by_theme = _cumulative_by_theme(v1_hist, "by_theme")
    v2_by_theme = _cumulative_by_theme(v2_hist, "by_theme")
    merged = _merge_cross_version_by_theme(v1_by_theme, v2_by_theme)
    return retired_themes_with_stats(merged)


def load_cross_version_history_dict(
    output_dir, *, before_date: Optional[str] = None
) -> dict:
    """Convenience for the CLI: returns the dict shape expected by
    ``select_tiered_plan(history=…)``.

    Includes ``records`` (raw v2 records, sorted by date) so the orchestrator
    can compute spec §25.3 rolling hhad market health.
    """
    output = Path(output_dir)
    v1_hist = _history_before(
        _load_history(output / "bold-review-history.json"), before_date
    )
    v2_hist = _history_before(
        _load_history(output / "tiered-plan-history.json"), before_date
    )
    merged = _merge_cross_version_by_theme(
        _cumulative_by_theme(v1_hist, "by_theme"),
        _cumulative_by_theme(v2_hist, "by_theme"),
    )
    return {
        "by_theme": merged,
        "records": sorted(v2_hist, key=lambda r: r.get("date") or ""),
    }


# ---------------------------------------------------------------------------
# Daily review — spec §6: replay + grade + render + history append
# ---------------------------------------------------------------------------


_TIER_NAMES: dict[str, str] = {
    "A": "稳健底仓", "B": "主方案", "D": "反大众", "E": "极限娱乐",
}
_TIER_PROFILES: dict[str, TierProfile] = {
    "A": DEFAULT_TIER_A,
    "B": DEFAULT_TIER_B,
    "D": DEFAULT_TIER_D,
    "E": DEFAULT_TIER_E,
}
_MARKET_CODES: dict[str, str] = {v: k for k, v in MARKET_LABELS.items()}
_HAD_PICK_CODES: dict[str, str] = {"胜": "home", "平": "draw", "负": "away"}
_HHAD_PICK_CODES: dict[str, str] = {
    "让胜": "home", "让平": "draw", "让负": "away",
}
_TIER_HEADER_RE = re.compile(
    r"^### (?P<code>[ABDE]) (?P<name>[^（\n]+)"
    r"(?:（(?P<fold>\d+)串1 · 合计赔率 (?P<odds>[0-9.]+) · "
    r"¥(?P<stake>\d+) · (?P<stars>[^）]+)）)?"
)
_TIER_LEG_RE = re.compile(
    r"^- (?P<match_no>\S+) (?P<home>.+?) vs (?P<away>.+?) ｜ "
    r"\[(?P<market>[^\]]+)\] \*\*(?P<pick>.+?)\*\* @ (?P<odds>[0-9.]+)"
)
_TIER_TOPLINE_RE = re.compile(
    r"multiplier=(?P<multiplier>[0-9.]+)×.*首推一张 = (?P<rec>\S+)"
)
_TIER_CHAOS_RE = re.compile(
    r"混乱值：(?P<chaos>\d+)/100（(?P<band>[^）]+)）.*(?P<date>\d{4}-\d{2}-\d{2})"
)


def _pick_code(market: str, pick_label: str) -> str:
    if market == "had":
        return _HAD_PICK_CODES.get(pick_label, pick_label)
    if market == "hhad":
        return _HHAD_PICK_CODES.get(pick_label, pick_label)
    if market == "ttg" and pick_label.endswith("球"):
        return f"total_{pick_label[:-1]}"
    if market == "crs" and ":" in pick_label:
        home, away = pick_label.split(":", 1)
        if home.isdigit() and away.isdigit():
            return f"s{int(home):02d}s{int(away):02d}"
    return pick_label


def _load_saved_markdown_plan(run_date: str, output_dir) -> Optional[TieredPlan]:
    """Load the dispatched tiered-plan markdown when no JSON snapshot exists.

    Review must grade the exact ticket shown to the operator, not a replay under
    newer selection rules.
    """
    path = Path(output_dir) / "daily" / run_date / "tiered-plan.md"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if "tiered-plan" not in path.name:
        return None

    multiplier = 1.0
    recommended_single: Optional[str] = None
    day_chaos = 0
    band = ""
    for line in lines:
        if match := _TIER_TOPLINE_RE.search(line):
            multiplier = float(match.group("multiplier"))
            rec = match.group("rec")
            recommended_single = None if rec == "—" else rec
        if match := _TIER_CHAOS_RE.search(line):
            day_chaos = int(match.group("chaos"))
            band = match.group("band")

    tier_map: dict[str, Optional[Tier]] = {code: None for code in _TIER_NAMES}
    current: Optional[dict] = None
    for line in lines:
        if header := _TIER_HEADER_RE.match(line):
            code = header.group("code")
            current = {
                "code": code,
                "total_odds": (
                    float(header.group("odds"))
                    if header.group("odds") is not None else None
                ),
                "stake": (
                    int(header.group("stake"))
                    if header.group("stake") is not None else None
                ),
                "legs": [],
            }
            if current["total_odds"] is not None:
                profile = _TIER_PROFILES[code]
                tier_map[code] = Tier(
                    profile=profile,
                    legs=current["legs"],
                    total_odds=current["total_odds"],
                    stake_yuan=current["stake"] or profile.base_stake_yuan,
                    confidence_tag=confidence_tag_for_code(code),
                )
            continue
        if current is None or current["total_odds"] is None:
            continue
        if leg_match := _TIER_LEG_RE.match(line):
            market = _MARKET_CODES.get(leg_match.group("market"))
            if market is None:
                continue
            pick_label = leg_match.group("pick")
            leg = BoldLeg(
                match_no=leg_match.group("match_no"),
                league="",
                home=leg_match.group("home"),
                away=leg_match.group("away"),
                pick=_pick_code(market, pick_label),
                tc_odds=float(leg_match.group("odds")),
                boldness=0.0,
                reason="",
                market=market,
                pick_label=pick_label,
            )
            current["legs"].append(
                TieredLeg(leg=leg, reason=LegReason("", "", ""))
            )

    return TieredPlan(
        run_date=run_date,
        day_chaos=day_chaos,
        chaos_band=band,
        tiers=[tier_map[code] for code in ("A", "B", "D", "E")],
        recommended_single=recommended_single,
        multiplier=multiplier,
        # spec §27.4 — saved markdown was dispatched under an unknown prior
        # engine version; tag as "v2.x" rather than today's running version.
        version="v2.x",
    )


@dataclass(frozen=True, slots=True)
class GradedTierLeg:
    match_no: str
    market: str
    pick_label: str
    tc_odds: float
    actual: Optional[str]
    hit: Optional[bool]


@dataclass(frozen=True, slots=True)
class GradedTier:
    """One tier graded against okooo results."""
    code: str
    name: str
    fold: int
    total_odds: float
    stake: int
    legs: list[GradedTierLeg]
    hits: int
    graded: int
    all_hit: bool
    pending: bool
    theme: str
    stake_returned: Optional[int]   # None when pending


@dataclass(frozen=True, slots=True)
class TieredReviewResult:
    run_date: str
    status: str
    day_chaos: int
    multiplier: float
    recommended_single: Optional[str]
    tiers: list[Optional[GradedTier]]
    results: dict[str, dict[str, str]]
    message: str
    day_record: dict = field(default_factory=dict)
    cumulative: dict = field(default_factory=dict)


def _try_load_match_hhad_lines(
    run_date: str, output_dir
) -> Optional[dict[str, float]]:
    """spec §27.6 — best-effort hhad goal_line lookup from the snapshot.

    Returns ``None`` when the snapshot is missing (eg historical backfills);
    callers should degrade by skipping the let-neg-one shadow field.
    """
    value = load_sporttery_snapshot(run_date, output_dir)
    if value is None:
        return None
    try:
        bold_odds = load_bold_odds_snapshot(run_date, output_dir)
        matches = bold_matches_from_sporttery(
            value, run_date=run_date, bold_odds=bold_odds,
        )
    except Exception:  # noqa: BLE001 — shadow field is non-load-bearing
        return None
    return {m.match_no: float(m.hhad_line or 0.0) for m in matches}


def replay_tiered_plan(run_date: str, output_dir) -> Optional[TieredPlan]:
    """spec §6 — re-run select_tiered_plan from yesterday's snapshots."""
    if saved_plan := _load_saved_markdown_plan(run_date, output_dir):
        return saved_plan
    value = load_sporttery_snapshot(run_date, output_dir)
    if value is None:
        return None
    bold_odds = load_bold_odds_snapshot(run_date, output_dir)
    matches = bold_matches_from_sporttery(
        value, run_date=run_date, bold_odds=bold_odds
    )
    history = load_cross_version_history_dict(output_dir, before_date=run_date)
    return select_tiered_plan(
        matches, history=history, multiplier=1.0, run_date=run_date
    )


def grade_tier(tier: Tier, results: dict[str, dict[str, str]]) -> GradedTier:
    """Grade one Tier's legs against okooo results. Pending if any leg
    has no result yet (跨日 / 未出)."""
    bold_legs: list[BoldLeg] = [tl.leg for tl in tier.legs]
    graded_legs = [grade_leg(lg, results) for lg in bold_legs]
    legs = [
        GradedTierLeg(
            match_no=gl.match_no, market=gl.market,
            pick_label=gl.pick_label, tc_odds=gl.tc_odds,
            actual=gl.actual, hit=gl.hit,
        )
        for gl in graded_legs
    ]
    hits = sum(1 for lg in legs if lg.hit is True)
    graded = sum(1 for lg in legs if lg.hit is not None)
    pending = any(lg.hit is None for lg in legs)
    all_hit = bool(legs) and all(lg.hit is True for lg in legs)
    theme = ticket_theme(bold_legs)[0] if bold_legs else ""
    stake_returned: Optional[int]
    if pending:
        stake_returned = None
    elif all_hit:
        stake_returned = round(tier.stake_yuan * tier.total_odds)
    else:
        stake_returned = 0
    return GradedTier(
        code=tier.profile.code, name=tier.profile.name,
        fold=len(legs), total_odds=tier.total_odds,
        stake=tier.stake_yuan, legs=legs,
        hits=hits, graded=graded,
        all_hit=all_hit, pending=pending,
        theme=theme, stake_returned=stake_returned,
    )


def _day_record(
    run_date: str,
    plan: TieredPlan,
    graded: list[Optional[GradedTier]],
    *,
    match_hhad_lines: Optional[dict[str, float]] = None,
) -> dict:
    """Build the persistable day record. by_theme aggregated like v1 §24.

    spec §25.3 — also accumulates ``by_hhad_actual`` (counts of actual
    let-球 direction across all graded hhad legs) for rolling 14-day
    market-health gating.

    spec §27.4 — record ``version`` from ``plan.version`` so cumulative
    trends can be partitioned by engine version.

    spec §27.6 — when ``match_hhad_lines`` (mapping ``match_no → hhad_line``)
    is provided, accumulate ``by_hhad_actual_let_neg_one`` (counts of actual
    hhad direction restricted to matches with goal_line == -1.0) as a shadow
    field for 14-day analysis of "main fav minimal-win" patterns.
    """
    by_theme: dict[str, dict[str, int]] = {}
    by_tier: dict[str, dict[str, int]] = {}
    by_hhad_actual: dict[str, int] = {}  # spec §25.3
    by_hhad_actual_let_neg_one: dict[str, int] = {}  # spec §27.6 shadow
    # Dedupe at (match_no, market) level — same match in two tiers counts once.
    seen_hhad: set[str] = set()
    seen_let_neg_one: set[str] = set()
    for gt in graded:
        if gt is None:
            continue
        # by_theme — spec §24-compatible
        slot = by_theme.setdefault(
            gt.theme,
            {"tickets": 0, "ticket_hits": 0, "legs": 0, "leg_hits": 0},
        )
        slot["tickets"] += 1
        if gt.all_hit:
            slot["ticket_hits"] += 1
        slot["legs"] += gt.graded
        slot["leg_hits"] += gt.hits
        # by_tier — v2's new per-tier accumulator
        tslot = by_tier.setdefault(
            gt.code,
            {
                "tickets": 0, "ticket_hits": 0,
                "legs": 0, "leg_hits": 0,
                "stake_total": 0, "stake_returned": 0,
            },
        )
        tslot["tickets"] += 1
        if gt.all_hit:
            tslot["ticket_hits"] += 1
        tslot["legs"] += gt.graded
        tslot["leg_hits"] += gt.hits
        if not gt.pending:
            tslot["stake_total"] += gt.stake
            tslot["stake_returned"] += int(gt.stake_returned or 0)
        # spec §25.3 — count actual hhad direction once per match
        for lg in gt.legs:
            if lg.market != "hhad" or not lg.actual:
                continue
            if lg.match_no not in seen_hhad:
                seen_hhad.add(lg.match_no)
                by_hhad_actual[lg.actual] = by_hhad_actual.get(lg.actual, 0) + 1
            # spec §27.6 — partition by goal_line == -1.0
            if (
                match_hhad_lines is not None
                and lg.match_no not in seen_let_neg_one
                and match_hhad_lines.get(lg.match_no) == -1.0
            ):
                seen_let_neg_one.add(lg.match_no)
                by_hhad_actual_let_neg_one[lg.actual] = (
                    by_hhad_actual_let_neg_one.get(lg.actual, 0) + 1
                )
    record = {
        "date": run_date,
        "chaos": plan.day_chaos,
        "multiplier": plan.multiplier,
        "recommended_single": plan.recommended_single,
        "version": getattr(plan, "version", "v2.x"),  # spec §27.4
        "by_theme": by_theme,
        "by_tier": by_tier,
        "by_hhad_actual": by_hhad_actual,
    }
    if match_hhad_lines is not None:
        record["by_hhad_actual_let_neg_one"] = by_hhad_actual_let_neg_one
    return record


def _append_history(output_dir, day_record: dict) -> list[dict]:
    path = Path(output_dir) / "tiered-plan-history.json"
    history = [
        rec for rec in _load_history(path)
        if rec.get("date") != day_record["date"]
    ]
    history.append(day_record)
    history.sort(key=lambda r: r.get("date") or "")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return history


def _cumulative(history: list[dict]) -> dict:
    """Sum across history records for the trend block.

    spec §27.4 — also computes per-version per-tier aggregates so the
    cumulative trend can be partitioned when multiple engine versions appear
    in history (v2/v2.1/v2.2/v2.3 ran on consecutive days during 5/25-5/28).
    """
    tier_agg: dict[str, dict[str, int]] = {}
    theme_agg: dict[str, dict[str, int]] = {}
    by_version: dict[str, dict[str, dict[str, int]]] = {}  # spec §27.4
    for rec in history:
        version = rec.get("version") or "v2.x"
        version_slot = by_version.setdefault(version, {})
        for code, slot in (rec.get("by_tier") or {}).items():
            a = tier_agg.setdefault(
                code,
                {
                    "tickets": 0, "ticket_hits": 0,
                    "legs": 0, "leg_hits": 0,
                    "stake_total": 0, "stake_returned": 0,
                },
            )
            v_tier = version_slot.setdefault(
                code,
                {
                    "tickets": 0, "ticket_hits": 0,
                    "legs": 0, "leg_hits": 0,
                    "stake_total": 0, "stake_returned": 0,
                },
            )
            for k in (
                "tickets", "ticket_hits", "legs", "leg_hits",
                "stake_total", "stake_returned",
            ):
                a[k] += int(slot.get(k, 0))
                v_tier[k] += int(slot.get(k, 0))
        for theme, slot in (rec.get("by_theme") or {}).items():
            a = theme_agg.setdefault(
                theme,
                {"tickets": 0, "ticket_hits": 0, "legs": 0, "leg_hits": 0},
            )
            for k in ("tickets", "ticket_hits", "legs", "leg_hits"):
                a[k] += int(slot.get(k, 0))
    return {
        "days": len(history),
        "first_date": history[0]["date"] if history else "",
        "last_date": history[-1]["date"] if history else "",
        "by_tier": tier_agg,
        "by_theme": theme_agg,
        "by_version": by_version,
    }


def _mark(hit: Optional[bool]) -> str:
    return {True: "✅", False: "✗", None: "待定"}[hit]


def _render_graded_tier(gt: GradedTier) -> list[str]:
    """A graded tier block — header + per-leg result."""
    verdict = (
        "待定" if gt.pending
        else ("整票命中 ✅" if gt.all_hit else "整票未中")
    )
    header = (
        f"### {gt.code} {gt.name}（{gt.fold}串1 @{gt.total_odds:.2f} · ¥{gt.stake}）："
        f"命中 {gt.hits}/{len(gt.legs)} · {verdict}"
    )
    if not gt.pending:
        ret = gt.stake_returned or 0
        net = ret - gt.stake
        sign = "+" if net >= 0 else ""
        header += f" · 实际回款 ¥{ret}（净 {sign}¥{net}）"
    lines = [header]
    for lg in gt.legs:
        market = MARKET_LABELS.get(lg.market, lg.market)
        actual = lg.actual or "未出"
        lines.append(
            f"    {lg.match_no} {market} {lg.pick_label} "
            f"→ 实际 {actual} {_mark(lg.hit)}"
        )
    return lines


def _render_no_snapshot(run_date: str) -> str:
    return "\n".join([
        HARD_LABEL,
        "",
        f"【Nutmeg｜{run_date} tiered-plan 复盘】",
        f"无 {run_date} 的盘口快照 —— 当天 v2 引擎未跑，跳过复盘。",
    ])


def render_tiered_review(
    run_date: str,
    plan: TieredPlan,
    graded: list[Optional[GradedTier]],
    cumulative: dict,
) -> str:
    """spec §6 — render the v2 next-day backtest report. Welded 🎲 label,
    factual hit/miss only, no advantage wording."""
    lines: list[str] = [HARD_LABEL, ""]
    lines.append(f"【Nutmeg｜{run_date} tiered-plan v2 复盘】")
    lines.append("赛后对照，非收益结论；娱乐工具长期为负、仅供参考。")
    lines.append("")

    lines.append("## 票面回测")
    code_order = ["A", "B", "D", "E"]
    has_any = False
    for tier_obj, code in zip(plan.tiers, code_order, strict=True):
        gt = next(
            (g for g in graded if g is not None and g.code == code), None
        )
        if gt is None and tier_obj is None:
            lines.append(f"### {code} {_TIER_NAMES[code]}：当日无票")
            continue
        if gt is not None:
            lines.extend(_render_graded_tier(gt))
            has_any = True
    if not has_any:
        lines.append("- （当天 4 档全为空）")
    lines.append("")

    lines.append("## 本期小结")
    ticket_hits = sum(
        1 for g in graded if g is not None and g.all_hit
    )
    ticket_total = sum(
        1 for g in graded if g is not None and not g.pending
    )
    leg_hits = sum(g.hits for g in graded if g is not None)
    leg_total = sum(g.graded for g in graded if g is not None)
    stake_total = sum(
        g.stake for g in graded if g is not None and not g.pending
    )
    stake_returned = sum(
        int(g.stake_returned or 0)
        for g in graded if g is not None and not g.pending
    )
    net = stake_returned - stake_total
    sign = "+" if net >= 0 else ""
    lines.append(
        f"- 整票 {ticket_hits}/{ticket_total} 命中 · 腿 {leg_hits}/{leg_total}"
    )
    lines.append(
        f"- 当日预算 ¥{stake_total} · 回款 ¥{stake_returned} · 净 {sign}¥{net}"
    )
    lines.append("")

    lines.append("## 累计趋势")
    days = cumulative.get("days", 0)
    span = (
        f"（{days} 天，{cumulative.get('first_date')}~{cumulative.get('last_date')}）"
        if days else ""
    )
    lines.append(f"最近累计{span}：")
    tier_cum = cumulative.get("by_tier", {})
    for code in code_order:
        slot = tier_cum.get(code)
        if not slot:
            continue
        cum_stake_total = slot.get("stake_total", 0)
        cum_stake_returned = slot.get("stake_returned", 0)
        cum_net = cum_stake_returned - cum_stake_total
        cum_sign = "+" if cum_net >= 0 else ""
        lines.append(
            f"- {code} {_TIER_NAMES[code]}: "
            f"整票 {slot.get('ticket_hits', 0)}/{slot.get('tickets', 0)} · "
            f"腿 {slot.get('leg_hits', 0)}/{slot.get('legs', 0)} · "
            f"预算 ¥{cum_stake_total} 净 {cum_sign}¥{cum_net}"
        )
    # spec §27.4 — by_version breakdown when ≥2 engine versions present in history
    by_version = cumulative.get("by_version", {})
    if len(by_version) >= 2:
        lines.append("")
        lines.append("按引擎版本分组：")
        for ver in sorted(by_version):
            v_tiers = by_version[ver]
            parts = []
            for code in code_order:
                slot = v_tiers.get(code)
                if not slot:
                    continue
                v_stake = slot.get("stake_total", 0)
                v_ret = slot.get("stake_returned", 0)
                v_net = v_ret - v_stake
                v_sign = "+" if v_net >= 0 else ""
                parts.append(
                    f"{code} {slot.get('ticket_hits', 0)}/{slot.get('tickets', 0)}票 "
                    f"{slot.get('leg_hits', 0)}/{slot.get('legs', 0)}腿 "
                    f"净 {v_sign}¥{v_net}"
                )
            if parts:
                lines.append(f"- {ver}: {' · '.join(parts)}")
    lines.append("")
    lines.append(
        "_本复盘只做赛后对照，不预测、不号称优势；娱乐工具长期为负期望，仅供参考。_"
    )
    return "\n".join(lines)


def build_tiered_review(
    run_date: str, output_dir, *, result_provider=None
) -> TieredReviewResult:
    """Replay, grade, render, and append history for a tiered plan.

    ``result_provider`` defaults to ``OkoooJczqResultProvider`` (production),
    overridable for tests."""
    plan = replay_tiered_plan(run_date, output_dir)
    if plan is None:
        return TieredReviewResult(
            run_date=run_date,
            status="no_snapshot",
            day_chaos=0, multiplier=1.0,
            recommended_single=None,
            tiers=[None, None, None, None],
            results={},
            message=_render_no_snapshot(run_date),
        )

    if result_provider is None:
        from nutmeg.services.jczq_review import OkoooJczqResultProvider
        result_provider = OkoooJczqResultProvider()
    results = result_provider.fetch_results(run_date)

    graded: list[Optional[GradedTier]] = []
    for tier in plan.tiers:
        graded.append(grade_tier(tier, results) if tier is not None else None)

    # spec §27.6 — best-effort lookup of hhad goal_line per match from the
    # original sporttery snapshot (None when snapshot missing, eg historical
    # backfills without raw data).
    match_hhad_lines = _try_load_match_hhad_lines(run_date, output_dir)
    day_record = _day_record(
        run_date, plan, graded, match_hhad_lines=match_hhad_lines,
    )
    history = _append_history(output_dir, day_record)
    cumulative = _cumulative(history)
    message = render_tiered_review(run_date, plan, graded, cumulative)

    return TieredReviewResult(
        run_date=run_date,
        status="reviewed",
        day_chaos=plan.day_chaos,
        multiplier=plan.multiplier,
        recommended_single=plan.recommended_single,
        tiers=graded,
        results=results,
        message=message,
        day_record=day_record,
        cumulative=cumulative,
    )


def run_tiered_review(
    run_date: str, output_dir, *, result_provider=None
) -> TieredReviewResult:
    """Build the review + persist md/json to ``daily/<date>/``."""
    review = build_tiered_review(
        run_date, output_dir, result_provider=result_provider
    )
    daily_dir = Path(output_dir) / "daily" / run_date
    daily_dir.mkdir(parents=True, exist_ok=True)
    (daily_dir / "tiered-plan-review.md").write_text(
        review.message, encoding="utf-8"
    )
    payload = {
        "run_date": review.run_date,
        "status": review.status,
        "day_chaos": review.day_chaos,
        "multiplier": review.multiplier,
        "recommended_single": review.recommended_single,
        "tiers": [
            None if g is None else {
                "code": g.code, "name": g.name, "fold": g.fold,
                "total_odds": g.total_odds, "stake": g.stake,
                "theme": g.theme,
                "legs": [
                    {
                        "match_no": lg.match_no, "market": lg.market,
                        "pick_label": lg.pick_label, "tc_odds": lg.tc_odds,
                        "actual": lg.actual, "hit": lg.hit,
                    } for lg in g.legs
                ],
                "hits": g.hits, "graded": g.graded,
                "all_hit": g.all_hit, "pending": g.pending,
                "stake_returned": g.stake_returned,
            }
            for g in review.tiers
        ],
        "results": review.results,
        "day_record": review.day_record,
        "cumulative": review.cumulative,
        "message": review.message,
    }
    (daily_dir / "tiered-plan-review.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return review
