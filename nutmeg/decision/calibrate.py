"""calibrate — 聚合 Settlement → FactorVerdict + 词典上限强制(spec §5)。

生死规则(继承 spec §30 反 churn):
- n<30 只积累不判决(keep)。
- n≥30:CLV 命中>0.55 且 brier_delta<0 → keep(转正/维持 active);
        双轴皆平庸(CLV≤0.55 且 brier_delta≥0) → retire;
        一轴好一轴差 → watch。
- ACTIVE_CAP=12:超限强制退休最弱(CLV 最低)。
"""
from __future__ import annotations

from nutmeg.decision.factors import ACTIVE_CAP
from nutmeg.decision.ontology import FactorVerdict

_MIN_SAMPLE = 30
_CLV_BAR = 0.55


def factor_verdict(factor_id: str, settlements: list[dict], *,
                   as_of: str) -> FactorVerdict:
    """settlements: [{brier_delta, clv_hit(0/1)}, ...](已结,非 pending)。"""
    n = len(settlements)
    clv_rate = (sum(s["clv_hit"] for s in settlements) / n) if n else None
    brier_delta = (sum(s["brier_delta"] for s in settlements) / n) if n else None

    if n < _MIN_SAMPLE:
        rec = "keep"                               # 样本不足只积累
    else:
        clv_good = clv_rate > _CLV_BAR
        brier_good = brier_delta < 0
        if clv_good and brier_good:
            rec = "keep"
        elif not clv_good and not brier_good:
            rec = "retire"
        else:
            rec = "watch"
    return FactorVerdict(
        factor_id=factor_id, as_of=as_of, n_reads=n,
        brier_delta_vs_prior=brier_delta, clv_hit_rate=clv_rate,
        direction_hit_rate=None, recommendation=rec, next_review_at="",
    )


def enforce_active_cap(factors, verdicts) -> list[str]:
    """active 因子超 ACTIVE_CAP → 退休最弱(CLV 最低)者,返回被退休的 id 列表。"""
    active = [f for f in factors if f.status == "active"]
    if len(active) <= ACTIVE_CAP:
        return []
    clv_by_id = {v.factor_id: (v.clv_hit_rate or 0.0) for v in verdicts}
    ranked = sorted(active, key=lambda f: clv_by_id.get(f.factor_id, 0.0))
    n_retire = len(active) - ACTIVE_CAP
    return [f.factor_id for f in ranked[:n_retire]]
