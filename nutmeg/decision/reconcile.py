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
