"""因子生死机制的执行(反积累免疫落地):verdict → Factor 状态转换 + 持久化。"""
from nutmeg.decision.ontology import FactorVerdict


def _v(fid, rec, n=31):
    return FactorVerdict(factor_id=fid, as_of="2026-07-20", n_reads=n,
                         brier_delta_vs_prior=-0.01, clv_hit_rate=0.58,
                         direction_hit_rate=0.55, recommendation=rec)


