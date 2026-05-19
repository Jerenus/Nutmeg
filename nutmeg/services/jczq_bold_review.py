"""Bold-combo backtest — the next-day review of the entertainment bold engine.

The daily launchd job switched to the bold engine (``jczq-bold-combos``); the
old advisor-review grades plans the advisor records in the betting DB and now
has no data. This module is the bold engine's OWN review (spec §16): it replays
the plan from the §14 snapshots, grades it against the okooo results, and emits
an honest backtest report + a cumulative theme history.

It is a REVIEW, not a tuner — it never writes back a decision policy or adjusts
engine weights (the bold engine has no rules treadmill). The output keeps the
welded 🎲 honest framing: factual hit / miss only, NO advantage wording.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from pathlib import Path

from nutmeg.services.jczq_bold_combos import (
    HARD_LABEL,
    MARKET_LABELS,
    THEME_ORDER,
    BoldComboEngine,
    BoldComboPlan,
    BoldLeg,
    BoldTicket,
    bold_matches_from_sporttery,
    load_bold_odds_snapshot,
    load_sporttery_snapshot,
    ticket_theme,
)

# The four 体彩 markets okooo reports per match — keyed exactly as the engine's
# ``BoldLeg.market``, so a leg grades against ``results[match_no][leg.market]``.
_REVIEW_MARKETS: tuple[str, ...] = ("had", "hhad", "ttg", "crs")


@dataclass(slots=True, frozen=True)
class GradedLeg:
    """One bold leg graded against the actual result.

    ``hit`` is ``None`` when the match has no result yet (待定) — a pending leg
    never counts toward a hit rate's denominator (spec §16)."""

    match_no: str
    market: str
    pick_label: str
    tc_odds: float
    actual: str | None
    hit: bool | None


@dataclass(slots=True, frozen=True)
class GradedTicket:
    """A bold ticket graded — per-leg hits + the whole-ticket verdict."""

    ticket_id: str
    kind: str
    theme: str
    fold: int
    total_odds: float
    legs: list[GradedLeg]
    hits: int       # legs that hit
    graded: int     # legs with a result (hit is not None)
    all_hit: bool   # every leg hit (and none pending)
    pending: bool   # at least one leg has no result yet


@dataclass(slots=True, frozen=True)
class BoldReviewResult:
    """The day's bold review — graded tickets, the rendered report, history."""

    run_date: str
    status: str                       # "reviewed" | "no_snapshot"
    day_chaos: int
    anchor: GradedTicket | None
    bold_tickets: list[GradedTicket]
    results: dict[str, dict[str, str]]
    message: str
    day_record: dict = field(default_factory=dict)
    cumulative: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Replay + grading
# ---------------------------------------------------------------------------


def replay_bold_plan(run_date: str, output_dir) -> BoldComboPlan | None:
    """Rebuild the day's ``BoldComboPlan`` from the §14 snapshots.

    Reads ``sporttery_markets.json`` + ``bold_odds.json`` and re-runs the
    engine — §14 guarantees this reproduces the plan that was dispatched.
    Returns ``None`` when there is no Sporttery snapshot (the bold engine did
    not run that day) — never a crash.
    """
    value = load_sporttery_snapshot(run_date, output_dir)
    if value is None:
        return None
    bold_odds = load_bold_odds_snapshot(run_date, output_dir)
    matches = bold_matches_from_sporttery(
        value, run_date=run_date, bold_odds=bold_odds
    )
    return BoldComboEngine().generate(run_date, matches)


def grade_leg(leg: BoldLeg, results: dict[str, dict[str, str]]) -> GradedLeg:
    """Grade one leg — ``hit`` is ``actual == leg.pick_label`` (pick_label is the
    human form: 胜 / 让平 / 2球 / 2:1, matching okooo's winning-option string).

    No result for that match+market → ``actual=None``, ``hit=None`` (待定)."""
    actual = (results.get(leg.match_no) or {}).get(leg.market) or None
    hit = None if actual is None else (actual == leg.pick_label)
    return GradedLeg(
        match_no=leg.match_no,
        market=leg.market,
        pick_label=leg.pick_label,
        tc_odds=leg.tc_odds,
        actual=actual,
        hit=hit,
    )


def grade_ticket(
    ticket: BoldTicket, results: dict[str, dict[str, str]]
) -> GradedTicket:
    """Grade a whole ticket — per-leg + the all-hit / pending verdict."""
    legs = [grade_leg(leg, results) for leg in ticket.legs]
    hits = sum(1 for leg in legs if leg.hit is True)
    graded = sum(1 for leg in legs if leg.hit is not None)
    pending = any(leg.hit is None for leg in legs)
    all_hit = bool(legs) and all(leg.hit is True for leg in legs)
    theme = ticket_theme(ticket.legs)[0] if ticket.kind == "大胆票" else ""
    return GradedTicket(
        ticket_id=ticket.id,
        kind=ticket.kind,
        theme=theme,
        fold=ticket.fold,
        total_odds=ticket.total_odds,
        legs=legs,
        hits=hits,
        graded=graded,
        all_hit=all_hit,
        pending=pending,
    )


# ---------------------------------------------------------------------------
# Per-day record + append-only cumulative history (spec §16)
# ---------------------------------------------------------------------------


def _history_path(output_dir) -> Path:
    return Path(output_dir) / "bold-review-history.json"


def _load_history(output_dir) -> list[dict]:
    """Read the append-only review history; ``[]`` when absent/corrupt."""
    path = _history_path(output_dir)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def _day_record(
    run_date: str,
    chaos: int,
    anchor: GradedTicket | None,
    bold: list[GradedTicket],
) -> dict:
    """One day's compact review record — the unit appended to the history."""
    by_theme: dict[str, dict[str, int]] = {}
    for gt in bold:
        slot = by_theme.setdefault(gt.theme, {"tickets": 0, "ticket_hits": 0})
        slot["tickets"] += 1
        if gt.all_hit:
            slot["ticket_hits"] += 1
    return {
        "date": run_date,
        "chaos": chaos,
        "anchor": None
        if anchor is None
        else {
            "all_hit": anchor.all_hit,
            "pending": anchor.pending,
            "hits": anchor.hits,
            "graded": anchor.graded,
        },
        "bold": {
            "tickets": len(bold),
            "ticket_hits": sum(1 for gt in bold if gt.all_hit),
            "ticket_graded": sum(1 for gt in bold if not gt.pending),
            "leg_hits": sum(gt.hits for gt in bold),
            "leg_graded": sum(gt.graded for gt in bold),
        },
        "by_theme": by_theme,
    }


def _append_history(output_dir, day_record: dict) -> list[dict]:
    """Append today's record to the history — idempotent: re-reviewing the same
    date REPLACES its entry rather than duplicating it (spec §16)."""
    history = [
        rec
        for rec in _load_history(output_dir)
        if rec.get("date") != day_record["date"]
    ]
    history.append(day_record)
    history.sort(key=lambda rec: rec.get("date") or "")
    path = _history_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return history


def _cumulative(history: list[dict]) -> dict:
    """Sum the history into running totals — the structural-signal view that
    makes "冷门比分梦 14 天 0/14" surface on its own (spec §16)."""
    anchor_hits = anchor_total = 0
    ticket_hits = ticket_total = leg_hits = leg_total = 0
    by_theme: dict[str, dict[str, int]] = {}
    for rec in history:
        anchor = rec.get("anchor")
        if anchor and not anchor.get("pending"):
            anchor_total += 1
            anchor_hits += 1 if anchor.get("all_hit") else 0
        bold = rec.get("bold") or {}
        ticket_hits += int(bold.get("ticket_hits", 0))
        ticket_total += int(bold.get("ticket_graded", 0))
        leg_hits += int(bold.get("leg_hits", 0))
        leg_total += int(bold.get("leg_graded", 0))
        for theme, slot in (rec.get("by_theme") or {}).items():
            agg = by_theme.setdefault(theme, {"tickets": 0, "ticket_hits": 0})
            agg["tickets"] += int(slot.get("tickets", 0))
            agg["ticket_hits"] += int(slot.get("ticket_hits", 0))
    return {
        "days": len(history),
        "first_date": history[0]["date"] if history else "",
        "last_date": history[-1]["date"] if history else "",
        "anchor": {"hits": anchor_hits, "total": anchor_total},
        "bold_tickets": {"hits": ticket_hits, "total": ticket_total},
        "bold_legs": {"hits": leg_hits, "total": leg_total},
        "by_theme": by_theme,
    }


# ---------------------------------------------------------------------------
# Rendering — honest, welded 🎲 label, factual hit/miss only (spec §16)
# ---------------------------------------------------------------------------


def _matches_in_plan(plan: BoldComboPlan) -> dict[str, tuple[str, str]]:
    """Distinct matches across the plan's tickets — ``match_no → (home, away)``."""
    out: dict[str, tuple[str, str]] = {}
    tickets = ([plan.anchor] if plan.anchor.legs else []) + list(plan.tickets)
    for ticket in tickets:
        for leg in ticket.legs:
            out.setdefault(leg.match_no, (leg.home, leg.away))
    return dict(sorted(out.items()))


def _mark(hit: bool | None) -> str:
    return {True: "✅", False: "✗", None: "待定"}[hit]


def _render_graded_ticket(gt: GradedTicket) -> list[str]:
    """A graded ticket — a header line + one line per leg with its result."""
    name = f"{gt.ticket_id} · {gt.theme}" if gt.theme else gt.ticket_id
    verdict = "待定" if gt.pending else ("整票命中 ✅" if gt.all_hit else "整票未中")
    lines = [
        f"- {name}（{gt.fold}串1 @{gt.total_odds:.2f}）："
        f"命中 {gt.hits}/{len(gt.legs)} · {verdict}"
    ]
    for leg in gt.legs:
        market = MARKET_LABELS.get(leg.market, leg.market)
        actual = leg.actual or "未出"
        lines.append(
            f"    {leg.match_no} {market} {leg.pick_label} "
            f"→ 实际 {actual} {_mark(leg.hit)}"
        )
    return lines


def _render_no_snapshot(run_date: str) -> str:
    return "\n".join(
        [
            HARD_LABEL,
            "",
            f"【Nutmeg｜{run_date} bold 大胆票复盘】",
            f"无 {run_date} 的盘口快照 —— 当天 bold 引擎未跑，跳过复盘。",
        ]
    )


def render_bold_review(
    run_date: str,
    plan: BoldComboPlan,
    anchor: GradedTicket | None,
    bold: list[GradedTicket],
    results: dict[str, dict[str, str]],
    cumulative: dict,
) -> str:
    """Render the honest bold-combo backtest report.

    Starts with the welded 🎲 ``HARD_LABEL``; reports factual 命中 / 未中 only —
    NO advantage wording (胜率 / edge / +EV / 正期望 / 推荐下注 / 重仓), no
    predicted probabilities. It is a 赛后对照, not a 收益结论 (spec §16)."""
    lines: list[str] = [HARD_LABEL, ""]
    lines.append(f"【Nutmeg｜{run_date} bold 大胆票复盘】")
    lines.append("赛后对照，非收益结论；大胆票本就长期为负、仅供娱乐。")
    lines.append("")

    lines.append("## 赛果")
    matches = _matches_in_plan(plan)
    if matches:
        for match_no, (home, away) in matches.items():
            row = results.get(match_no) or {}
            score = row.get("score") or "未出"
            cells = "、".join(
                f"{MARKET_LABELS[m]} {row[m]}"
                for m in _REVIEW_MARKETS
                if row.get(m)
            )
            lines.append(
                f"- {match_no} {home} vs {away}：{score}"
                + (f"　{cells}" if cells else "")
            )
    else:
        lines.append("- （当天票面无场次）")
    lines.append("")

    lines.append("## 票面回测")
    if anchor is not None:
        lines.extend(_render_graded_ticket(anchor))
    for gt in bold:
        lines.extend(_render_graded_ticket(gt))
    lines.append("")

    lines.append("## 本期小结")
    if anchor is not None:
        a_verdict = (
            "待定" if anchor.pending
            else ("命中" if anchor.all_hit else "未中")
        )
        lines.append(f"- 稳健底仓：{a_verdict}（命中腿 {anchor.hits}/{len(anchor.legs)}）")
    bold_ticket_hits = sum(1 for gt in bold if gt.all_hit)
    bold_leg_hits = sum(gt.hits for gt in bold)
    bold_leg_total = sum(len(gt.legs) for gt in bold)
    lines.append(
        f"- 大胆票：{bold_ticket_hits}/{len(bold)} 整票命中 · "
        f"大胆腿 {bold_leg_hits}/{bold_leg_total} 命中"
    )
    theme_today: dict[str, list[int]] = {}
    for gt in bold:
        slot = theme_today.setdefault(gt.theme, [0, 0])
        slot[0] += 1
        slot[1] += 1 if gt.all_hit else 0
    if theme_today:
        parts = "、".join(
            f"{theme} {slot[1]}/{slot[0]}"
            for theme in THEME_ORDER
            if (slot := theme_today.get(theme))
        )
        lines.append(f"- 主题：{parts}")
    lines.append("")

    lines.append("## 累计趋势")
    days = cumulative.get("days", 0)
    span = (
        f"（{days} 天，{cumulative.get('first_date')}~{cumulative.get('last_date')}）"
        if days
        else ""
    )
    lines.append(f"最近累计{span}：")
    anchor_cum = cumulative.get("anchor", {})
    ticket_cum = cumulative.get("bold_tickets", {})
    leg_cum = cumulative.get("bold_legs", {})
    lines.append(
        f"- 稳健底仓整票命中 {anchor_cum.get('hits', 0)}/{anchor_cum.get('total', 0)}"
    )
    lines.append(
        f"- 大胆票整票命中 {ticket_cum.get('hits', 0)}/{ticket_cum.get('total', 0)}"
        f" · 大胆腿命中 {leg_cum.get('hits', 0)}/{leg_cum.get('total', 0)}"
    )
    theme_cum = cumulative.get("by_theme", {})
    if theme_cum:
        parts = "、".join(
            f"{theme} {slot['ticket_hits']}/{slot['tickets']}"
            for theme in THEME_ORDER
            if (slot := theme_cum.get(theme))
        )
        if parts:
            lines.append(f"- 主题：{parts}")
    lines.append("")

    lines.append(
        "_本复盘只做赛后对照，不预测、不号称优势；大胆票长期为负期望，仅供娱乐。_"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def build_bold_review(
    run_date: str, output_dir, *, result_provider
) -> BoldReviewResult:
    """Replay, grade and render the bold review for ``run_date``.

    ``result_provider`` exposes ``fetch_results(run_date)`` (the okooo provider
    in production; a fake in tests). The okooo call is made ONLY when a snapshot
    exists — a no-snapshot date skips straight to an honest "跳过" report and
    never touches the network. Appends today's record to the cumulative history.
    """
    plan = replay_bold_plan(run_date, output_dir)
    if plan is None:
        return BoldReviewResult(
            run_date=run_date,
            status="no_snapshot",
            day_chaos=0,
            anchor=None,
            bold_tickets=[],
            results={},
            message=_render_no_snapshot(run_date),
        )

    results = result_provider.fetch_results(run_date)
    anchor = grade_ticket(plan.anchor, results) if plan.anchor.legs else None
    bold = [grade_ticket(ticket, results) for ticket in plan.tickets]

    day_record = _day_record(run_date, plan.day_chaos, anchor, bold)
    history = _append_history(output_dir, day_record)
    cumulative = _cumulative(history)
    message = render_bold_review(run_date, plan, anchor, bold, results, cumulative)

    return BoldReviewResult(
        run_date=run_date,
        status="reviewed",
        day_chaos=plan.day_chaos,
        anchor=anchor,
        bold_tickets=bold,
        results=results,
        message=message,
        day_record=day_record,
        cumulative=cumulative,
    )


def _review_to_dict(review: BoldReviewResult) -> dict:
    """Serialize a review to a JSON-native dict for the ``bold-review.json``
    artifact."""
    return {
        "run_date": review.run_date,
        "status": review.status,
        "day_chaos": review.day_chaos,
        "anchor": dataclasses.asdict(review.anchor) if review.anchor else None,
        "bold_tickets": [dataclasses.asdict(gt) for gt in review.bold_tickets],
        "results": review.results,
        "day_record": review.day_record,
        "cumulative": review.cumulative,
        "message": review.message,
    }


def run_bold_review(
    run_date: str, output_dir, *, result_provider=None
) -> BoldReviewResult:
    """Build the bold review and write the ``bold-review.md`` / ``.json``
    artifacts under ``daily/<run_date>/``. Telegram dispatch is the CLI's job.
    """
    if result_provider is None:
        from nutmeg.services.jczq_review import OkoooJczqResultProvider

        result_provider = OkoooJczqResultProvider()

    review = build_bold_review(
        run_date, output_dir, result_provider=result_provider
    )
    run_dir = Path(output_dir) / "daily" / run_date
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "bold-review.md").write_text(review.message, encoding="utf-8")
    (run_dir / "bold-review.json").write_text(
        json.dumps(_review_to_dict(review), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return review
