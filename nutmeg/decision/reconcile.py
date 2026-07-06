"""reconcile — Read/Ticket + 赛果 + 收盘快照 → Settlement(双轴)。

演进 judge_ledger 对账纪律。赛果缺 → pending(brier/outcome=None);
收盘快照缺 → clv_pp=None(缺数据绝不伪造,spec §4 多源纪律)。
"""
from __future__ import annotations

from nutmeg.decision.ontology import Settlement
from nutmeg.decision.scoring import brier, clv_pp


def settle_read(read, *, outcome_90, score, closing) -> Settlement:
    b = None if outcome_90 is None else brier(read.belief, outcome_90)
    clv = None
    if closing is not None and not read.shadow:
        closing_fair = (closing.fair or {}).get(read.market, {})
        if closing_fair:
            clv = clv_pp(read.belief, read.prior, closing_fair)
    return Settlement(
        settlement_id=f"SET-read-{read.read_id}",
        ref_type="read", ref_id=read.read_id,
        settled_at=read.made_at,          # 占位;编排层用真实结算时刻覆盖
        outcome_90=outcome_90, score=score,
        closing_snapshot_id=(closing.snapshot_id if closing else None),
        brier=b, clv_pp=clv, hit=None, pnl_yuan=None,
    )


def settle_ticket_leg(*, market: str, pick: str, line: float | None,
                      outcome_90: str | None, goals_h: int | None,
                      goals_a: int | None) -> str | None:
    """票面口径 3 路结果(继承 judge_ledger._grade_ticket_outcome 全部 7/06 修复)。

    had=胜平负;hhad=90' 净胜球+让球线。line=None 且 hhad → None(pending)。
    AET/PEN 90'=平 margin 0。pick 无法规约成 home/draw/away → None(pending,不误判输)。
    赛果缺(outcome_90=None)→ None。
    """
    if pick not in ("home", "draw", "away"):
        return None
    if outcome_90 is None:
        return None
    if market == "had":
        return outcome_90
    if market == "hhad":
        if line is None:
            return None
        if outcome_90 == "draw":
            margin = 0
        elif goals_h is None:
            return None
        else:
            margin = goals_h - goals_a
        adj = margin + line
        return "home" if adj > 0 else "away" if adj < 0 else "draw"
    return None
