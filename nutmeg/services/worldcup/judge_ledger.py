"""评判员记分牌(judge spec §2)— 对账纯函数 + JSONL 读写 + 累计摘要。

幂等:append_day 整日替换(剔除同日旧条目后重写),重跑/补结安全。
评判员的牌子是打出来的:absent 也入账公示。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from .predictions import Predictions
from .results import WcResult

logger = logging.getLogger(__name__)

LEDGER_FILENAME = "judge-ledger.jsonl"
# 评判员层上线日(judge spec §2)——此前的日子不存在评判员,不计缺席。
LEDGER_START_DATE = "2026-06-12"


@dataclass(frozen=True, slots=True)
class LedgerSummary:
    n_picks: int
    judgment_rate: float | None
    score_rate: float | None
    baseline_rate: float | None
    upset_precision: float | None   # upset_hit / upset_flag 总数
    ticket_pnl: float
    ticket_n: int
    absent_days: int
    pending: int


def reconcile_day(pred: Predictions, results: list[WcResult]) -> list[dict]:
    """一天的判定 → ledger 条目(dict,直接可 JSONL)。赛果缺 → pending。"""
    by_id = {r.match_id: r for r in results}
    entries: list[dict] = []
    outcome_by_match_no: dict[str, str | None] = {}
    for p in pred.picks:
        r = by_id.get(p.match_id) if p.match_id else None
        e: dict = {
            "date": pred.date, "kind": "pick", "judge": pred.judge,
            "match_id": p.match_id, "fixture": p.fixture,
            "judgment": p.judgment, "confidence": p.confidence,
            "upset_flag": p.upset_flag, "pending": r is None,
        }
        if r is not None:
            jh = p.judgment == r.outcome_90
            sh = (
                None if r.goals_h_90 is None
                else p.score == f"{r.goals_h_90}-{r.goals_a_90}"
            )
            e.update({
                "judgment_hit": jh,
                "score_hit": sh,
                "baseline_hit": (
                    p.baseline_pick == r.outcome_90 if p.baseline_pick else None
                ),
                "upset_hit": bool(
                    p.upset_flag and jh and p.judgment != p.baseline_pick
                ),
            })
            if p.match_no:
                outcome_by_match_no[p.match_no] = r.outcome_90
        elif p.match_no:
            outcome_by_match_no[p.match_no] = None
        entries.append(e)

    t = pred.opinion_ticket
    if t is not None:
        outcome = outcome_by_match_no.get(t.match_no)
        te: dict = {
            "date": pred.date, "kind": "ticket", "judge": pred.judge,
            "match_no": t.match_no, "pick": t.pick, "odds": t.odds,
            "stake_yuan": t.stake_yuan, "pending": outcome is None,
        }
        if outcome is not None:
            if t.odds is None:
                te["pnl_yuan"] = None   # 赔率未存,人工补结(spec §5)
            elif t.pick == outcome:
                te["pnl_yuan"] = round(t.stake_yuan * (t.odds - 1.0), 2)
            else:
                te["pnl_yuan"] = float(-t.stake_yuan)
        entries.append(te)
    return entries


def absent_entry(date: str) -> dict:
    return {"date": date, "kind": "absent"}


def load_ledger(path: Path) -> list[dict]:
    if not path.exists():
        return []
    entries: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            logger.warning("ledger 损坏行已跳过: %r", line[:80])
    return entries


def append_day(path: Path, date: str, entries: list[dict]) -> None:
    """整日替换写入 — 重跑幂等、pending 补结安全。"""
    kept = [e for e in load_ledger(path) if e.get("date") != date]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for e in kept + entries:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")


def ledger_summary(entries: list[dict]) -> LedgerSummary:
    picks = [e for e in entries if e.get("kind") == "pick" and not e.get("pending")]
    tickets = [e for e in entries if e.get("kind") == "ticket" and not e.get("pending")]

    def _rate(key: str) -> float | None:
        vals = [e[key] for e in picks if e.get(key) is not None]
        return (sum(1 for v in vals if v) / len(vals)) if vals else None

    flagged = [e for e in picks if e.get("upset_flag")]
    return LedgerSummary(
        n_picks=len(picks),
        judgment_rate=_rate("judgment_hit"),
        score_rate=_rate("score_hit"),
        baseline_rate=_rate("baseline_hit"),
        upset_precision=(
            sum(1 for e in flagged if e.get("upset_hit")) / len(flagged)
            if flagged else None
        ),
        ticket_pnl=sum(e["pnl_yuan"] for e in tickets if e.get("pnl_yuan") is not None),
        ticket_n=len(tickets),
        absent_days=sum(1 for e in entries if e.get("kind") == "absent"),
        pending=sum(1 for e in entries if e.get("pending")),
    )


def reconcile_recent(output_dir: Path, *, today: str, days_back: int = 3) -> int:
    """对账最近 N 天(不含今天)— pending 自动补结;评判员缺席日记 absent。

    返回写入的条目数。jczq-report 两条路径(日报/复盘)都调它,幂等。
    """
    from datetime import date, timedelta

    from .predictions import load_predictions
    from .results import load_results

    wc_dir = output_dir / "wc2026"
    ledger_path = wc_dir / LEDGER_FILENAME
    results = load_results(wc_dir / "results.json")
    written = 0
    try:
        anchor = date.fromisoformat(today)
    except ValueError:
        return 0
    for back in range(1, days_back + 1):
        d = (anchor - timedelta(days=back)).isoformat()
        if d < LEDGER_START_DATE:
            continue  # 评判员层诞生之前的日子不算缺席
        pred = load_predictions(output_dir / "daily" / d)
        if pred is None:
            existing_dates = {e.get("date") for e in load_ledger(ledger_path)}
            if d not in existing_dates and (output_dir / "daily" / d).exists():
                append_day(ledger_path, d, [absent_entry(d)])
                written += 1
            continue
        entries = reconcile_day(pred, results)
        append_day(ledger_path, d, entries)
        written += len(entries)
    return written
