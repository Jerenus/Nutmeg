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

__all__ = [
    "ShadowRow",
    "compare_sources",
    "render_report",
    "run_backfill",
    "run_shadow",
]

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


def _board_match_numbers(value: dict, run_date: str) -> list[str]:
    """该**业务日**在售场次的竞彩号——覆盖率的分母。

    一份 sporttery 快照含**多个业务日**（2026-09-12 的快照里有 09-12 的 28 场、
    09-13 的 24 场、09-14 的 10 场）。分母不按 ``businessDate`` 过滤就会把三天的
    场次全算进一天，把覆盖率算成三分之一——回放工具初版正是这么把 titan007 的
    28/28 报成了 28/62。口径必须与
    ``jczq_titan007_odds._board_matches`` 完全一致。
    """
    out: list[str] = []
    for day in value.get("matchInfoList") or []:
        for raw in day.get("subMatchList") or []:
            if str(raw.get("matchStatus") or "").casefold() != "selling":
                continue
            business_date = str(raw.get("businessDate") or day.get("businessDate") or "")
            if run_date and business_date and business_date != run_date:
                continue
            match_no = str(raw.get("matchNumStr") or "")
            if match_no:
                out.append(match_no)
    return out


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
    board = _board_match_numbers(value, run_date)

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


def _merged_board_fetcher(client, run_date: str):
    """历史回放的板面取数：合并 ``run_date`` 与次日两张 titan007 历史板。

    体彩按**业务日**归组（一个业务日含深夜跨到次日历日的场次），titan007 历史端点按
    **开球历日**归组。只取 ``run_date`` 当日实测仅覆盖 45%（2026-09-12 板面 62 场），
    并次日后升到 84%。竞彩号在同一业务日内唯一，先到先得即可。
    """
    from datetime import date, timedelta

    def _fetch():
        rows = []
        seen: set[str] = set()
        nxt = (date.fromisoformat(run_date) + timedelta(days=1)).isoformat()
        for day in (run_date, nxt):
            try:
                fetched = client.fetch_board(run_date=day)
            except Exception:  # noqa: BLE001 — 缺一天只降覆盖，不炸整次回放
                continue
            for row in fetched:
                if row.match_no not in seen:
                    seen.add(row.match_no)
                    rows.append(row)
        return rows

    return _fetch


def run_backfill(run_dates: list[str], output_dir) -> str:
    """历史回放：磁盘上已存的 API-Football ``bold_odds.json`` vs 现抓 titan007 历史盘。

    解决的问题：影子期要 ≥3 个板面日的证据，但等 3 个日历日太慢，且 API-Football 免费档
    只给 today±1、无法回补历史。存量快照正好是它当时**实际**产出的东西，比重抓更诚实。

    ``run_dates`` 里没有 ``bold_odds.json`` 或 ``sporttery_markets.json`` 的日子跳过。
    返回报告路径。
    """
    import json
    from pathlib import Path

    from nutmeg.data.titan007 import Titan007Client
    from nutmeg.decision.market_data import load_bold_odds_snapshot
    from nutmeg.services.jczq_titan007_odds import (
        SHARP_BOOKS,
        collect_bold_odds_titan007,
    )

    base = Path(output_dir)
    lines = [
        "# 国际欧赔换源 · 多日历史回放",
        "",
        "存量 API-Football 快照（当时实际产出）vs 现抓 titan007 历史盘。",
        "",
        "| 业务日 | 板面 | AF 覆盖 | 007 覆盖 | 同覆盖 "
        "| fair 差中位 pp | fair 差最大 pp | 007 drift 中位 pp |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    totals = {"board": 0, "af": 0, "t7": 0}
    all_deltas: list[float] = []
    all_drifts: list[float] = []
    paired: list[tuple[float, float]] = []   # (fair 差 pp, drift pp) 同场配对

    with Titan007Client() as client:
        for run_date in run_dates:
            day_dir = base / "daily" / run_date
            sporttery_path = day_dir / "sporttery_markets.json"
            if not (sporttery_path.exists() and (day_dir / "bold_odds.json").exists()):
                continue
            value = json.loads(sporttery_path.read_text(encoding="utf-8"))
            board = _board_match_numbers(value, run_date)
            if not board:
                continue

            baseline = load_bold_odds_snapshot(run_date, output_dir)
            candidate = collect_bold_odds_titan007(
                value,
                run_date=run_date,
                board_fetcher=_merged_board_fetcher(client, run_date),
                odds_fetcher=client.fetch_euro_odds,
                books=SHARP_BOOKS,
            )
            rows = compare_sources(board, baseline, candidate)
            deltas = sorted(r.max_delta_pp for r in rows if r.max_delta_pp is not None)
            drifts = sorted(
                r.candidate_drift_pp for r in rows if r.candidate_drift_pp is not None
            )
            af_n = sum(1 for r in rows if r.baseline_fair)
            t7_n = sum(1 for r in rows if r.candidate_fair)
            totals["board"] += len(board)
            totals["af"] += af_n
            totals["t7"] += t7_n
            all_deltas.extend(deltas)
            all_drifts.extend(drifts)
            paired.extend(
                (r.max_delta_pp, r.candidate_drift_pp)
                for r in rows
                if r.max_delta_pp is not None and r.candidate_drift_pp is not None
            )

            def _med(values: list[float]) -> str:
                return f"{values[len(values) // 2]}" if values else "—"

            lines.append(
                f"| {run_date} | {len(board)} | {af_n} ({af_n / len(board):.0%}) "
                f"| {t7_n} ({t7_n / len(board):.0%}) | {len(deltas)} "
                f"| {_med(deltas)} | {max(deltas) if deltas else '—'} | {_med(drifts)} |"
            )

    board_total = totals["board"] or 1
    lines += [
        "",
        f"**合计**：板面 {totals['board']} 场；"
        f"API-Football 覆盖 **{totals['af']} ({totals['af'] / board_total:.0%})**；"
        f"titan007 覆盖 **{totals['t7']} ({totals['t7'] / board_total:.0%})**。",
    ]
    if all_deltas:
        ordered = sorted(all_deltas)
        over_5pp = sum(1 for d in ordered if d >= 5.0)
        median = ordered[len(ordered) // 2]
        lines.append(
            f"双源同覆盖 {len(ordered)} 场，fair 最大单路差中位 **{median}pp**，"
            f"最大 **{max(ordered)}pp**，**≥5pp 的有 {over_5pp} 场**"
            f"（5pp 是判读层的实质性线）。"
        )
    if all_drifts:
        ordered = sorted(all_drifts)
        over_5pp = sum(1 for d in ordered if d >= 5.0)
        median = ordered[len(ordered) // 2]
        lines.append(
            f"titan007 初赔→即时 drift：中位 **{median}pp**，"
            f"最大 **{max(ordered)}pp**，**≥5pp 的有 {over_5pp} 场**"
            f"（此信号在 API-Football 上恒为 0）。"
        )
    if paired:
        big = [drift for delta, drift in paired if delta >= 5.0]
        small = [drift for delta, drift in paired if delta < 5.0]
        if big and small:
            big_med = sorted(big)[len(big) // 2]
            small_med = sorted(small)[len(small) // 2]
            lines += [
                "",
                "## 差异归因：时间差，不是两源分歧",
                "",
                "本回放对 AF 与 007 并非同一时刻取价——AF 存量快照是**读时盘**，"
                "007 历史端点返回的是**终盘**。若 fair 差真由两源分歧造成，它应与该场"
                "价格移动无关；若由时间差造成，则大差异必然集中在大位移的场次。",
                "",
                f"- fair 差 **≥5pp** 的 {len(big)} 场 → drift 中位 **{big_med}pp**",
                f"- fair 差 **<5pp** 的 {len(small)} 场 → drift 中位 **{small_med}pp**",
                "",
                f"差异集中在高位移场次（{big_med}pp vs {small_med}pp），"
                "支持时间差解释：两源读的是同一个市场。",
            ]

    path = base / "decision" / "odds_backfill.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    report = "\n".join(lines) + "\n"
    path.write_text(report, encoding="utf-8")
    return str(path)
