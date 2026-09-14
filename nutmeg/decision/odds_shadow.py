"""国际欧赔换源影子期 —— 双源同抓、逐场比 fair、出证据，**判断层一行不动**。

按 SOP，换数据源改变判断层输入的分布，属判据变更，须先跑影子期出证据再由用户裁定。
本模块只回答三个问题：

1. 覆盖率各是多少（API-Football 受配额所限实测 6/10）。
2. 同一场两源去水 fair 差多少 pp（决定切源是否会翻动既有判读）。
3. 新源的初赔带来多大 drift（这条信号在旧源上恒为 0）。

不写任何 ``bold_odds.json``，不进 sense/构票链路。
"""

from __future__ import annotations

from dataclasses import dataclass

from nutmeg.data.fcom500 import MarketOdds

__all__ = ["ShadowRow", "compare_sources", "render_report", "run_shadow"]

_OUTCOME_KEYS = ("home", "draw", "away")


@dataclass(frozen=True, slots=True)
class ShadowRow:
    """一场在两源下的对照。``None`` 表示该源没盖到这场。"""

    match_no: str
    baseline_fair: dict[str, float] | None
    candidate_fair: dict[str, float] | None
    max_delta_pp: float | None
    candidate_drift_pp: float | None
    candidate_books: int | None


def _fair(markets: dict[str, MarketOdds] | None) -> dict[str, float] | None:
    if not markets:
        return None
    market = markets.get("match_winner")
    if market is None or not market.fair_probability:
        return None
    return dict(market.fair_probability)


def _devig_local(odds: dict[str, float]) -> dict[str, float]:
    inverse = {k: 1.0 / v for k, v in odds.items() if v and v > 0}
    total = sum(inverse.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in inverse.items()}


def _drift_pp(markets: dict[str, MarketOdds] | None) -> float | None:
    """初赔 fair → 即时 fair 的最大单路位移（pp）。无初赔返回 ``None``。"""
    if not markets:
        return None
    market = markets.get("match_winner")
    if market is None or not market.opening_odds or not market.fair_probability:
        return None
    opening_fair = _devig_local(market.opening_odds)
    if not opening_fair:
        return None
    return round(
        max(
            abs(market.fair_probability.get(k, 0.0) - opening_fair.get(k, 0.0))
            for k in _OUTCOME_KEYS
        )
        * 100,
        2,
    )


def compare_sources(
    board: list[str],
    baseline: dict[str, dict[str, MarketOdds]],
    candidate: dict[str, dict[str, MarketOdds]],
) -> list[ShadowRow]:
    """按体彩板面顺序逐场对照两源。``board`` 是竞彩号全集（覆盖率的分母）。"""
    rows: list[ShadowRow] = []
    for match_no in board:
        base_fair = _fair(baseline.get(match_no))
        cand_markets = candidate.get(match_no)
        cand_fair = _fair(cand_markets)
        max_delta = None
        if base_fair and cand_fair:
            max_delta = round(
                max(
                    abs(base_fair.get(k, 0.0) - cand_fair.get(k, 0.0))
                    for k in _OUTCOME_KEYS
                )
                * 100,
                2,
            )
        books = None
        if cand_markets and cand_markets.get("match_winner") is not None:
            books = cand_markets["match_winner"].bookmaker_count
        rows.append(
            ShadowRow(
                match_no=match_no,
                baseline_fair=base_fair,
                candidate_fair=cand_fair,
                max_delta_pp=max_delta,
                candidate_drift_pp=_drift_pp(cand_markets),
                candidate_books=books,
            )
        )
    return rows


def render_report(run_date: str, rows: list[ShadowRow]) -> str:
    """出人读的 Markdown 报告。"""
    total = len(rows)
    base_n = sum(1 for r in rows if r.baseline_fair)
    cand_n = sum(1 for r in rows if r.candidate_fair)
    both = [r for r in rows if r.max_delta_pp is not None]
    drifts = [r.candidate_drift_pp for r in rows if r.candidate_drift_pp is not None]

    lines = [
        f"# 国际欧赔换源影子期 · {run_date}",
        "",
        f"- 板面场数：**{total}**",
        f"- API-Football 覆盖：**{base_n}/{total}**",
        f"- titan007 覆盖：**{cand_n}/{total}**",
    ]
    if both:
        deltas = sorted(r.max_delta_pp for r in both)
        median = deltas[len(deltas) // 2]
        lines.append(
            f"- 双源同覆盖 {len(both)} 场，fair 最大单路差：中位 **{median}pp**，"
            f"最大 **{max(deltas)}pp**"
        )
    else:
        lines.append("- 双源无共同覆盖场次，无法比 fair")
    if drifts:
        lines.append(
            f"- titan007 **初赔→即时 drift**：中位 **{sorted(drifts)[len(drifts) // 2]}pp**，"
            f"最大 **{max(drifts)}pp**（此信号在 API-Football 上恒为 0）"
        )
    else:
        lines.append("- titan007 无初赔数据（异常，应排查）")

    lines += [
        "",
        "| 竞彩号 | AF fair (主/平/客) | 007 fair (主/平/客) "
        "| 最大差 pp | 007 drift pp | 007 家数 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]

    def _fmt(fair: dict[str, float] | None) -> str:
        if not fair:
            return "—"
        return "/".join(f"{fair.get(k, 0.0) * 100:.1f}" for k in _OUTCOME_KEYS)

    for row in rows:
        lines.append(
            f"| {row.match_no} | {_fmt(row.baseline_fair)} | {_fmt(row.candidate_fair)} "
            f"| {row.max_delta_pp if row.max_delta_pp is not None else '—'} "
            f"| {row.candidate_drift_pp if row.candidate_drift_pp is not None else '—'} "
            f"| {row.candidate_books if row.candidate_books is not None else '—'} |"
        )
    return "\n".join(lines) + "\n"


def run_shadow(run_date: str, output_dir) -> str:
    """生产入口：抓体彩板面 → 两源各采一次 → 写报告。返回报告路径。"""
    from pathlib import Path

    from nutmeg.decision.market_data import fetch_sporttery_value_with_fallback
    from nutmeg.services.jczq_apifootball_odds import (
        collect_bold_odds_apifootball_live,
    )
    from nutmeg.services.jczq_titan007_odds import (
        ALL_BOOKS,
        SHARP_BOOKS,
        collect_bold_odds_titan007_live,
    )

    value, _ = fetch_sporttery_value_with_fallback()
    board = [
        str(raw.get("matchNumStr") or "")
        for day in (value.get("matchInfoList") or [])
        for raw in (day.get("subMatchList") or [])
        if str(raw.get("matchStatus") or "").casefold() == "selling"
        and str(raw.get("businessDate") or day.get("businessDate") or "") == run_date
    ]
    board = [no for no in board if no]

    baseline = collect_bold_odds_apifootball_live(value, run_date=run_date)
    sharp = collect_bold_odds_titan007_live(value, run_date=run_date, books=SHARP_BOOKS)
    every = collect_bold_odds_titan007_live(value, run_date=run_date, books=ALL_BOOKS)

    report = render_report(run_date, compare_sources(board, baseline, sharp))
    report += "\n## 口径对照：sharp(左) vs all(右)\n\n"
    report += render_report(run_date, compare_sources(board, sharp, every)).split("\n", 2)[2]

    path = Path(output_dir) / "daily" / run_date / "odds_shadow.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")
    return str(path)
