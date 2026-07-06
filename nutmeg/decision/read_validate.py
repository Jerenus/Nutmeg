"""Read 校验(代码职责)——概率归一/weight_pp 一致/因子在词典/证据非空/conf5 限方向。

判断(因子选择/幅度/场景/falsifier)是 Claude 运行时产出,永不在此。
继承判读层硬约束 a-f(CLAUDE.md):conf5 仅限 90' 方向市场(had/hhad)。
"""
from __future__ import annotations

_DIRECTION_MARKETS = ("had", "hhad")
_TOL = 1e-6


def validate_read(read, *, allowed_factors: set[str]) -> list[str]:
    errs: list[str] = []

    # 概率归一
    for name, probs in (("prior", read.prior), ("belief", read.belief)):
        total = sum(probs.values())
        if abs(total - 1.0) > _TOL:
            errs.append(f"{name} 概率未归一(和={total:.4f})")

    if read.shadow:
        # shadow: belief 必须 == prior 且无因子
        if read.factors:
            errs.append("shadow read 不得带因子")
        if any(abs(read.belief.get(k, 0.0) - v) > _TOL
               for k, v in read.prior.items()):
            errs.append("shadow read 的 belief 必须等于 prior")
    else:
        # 因子在词典 + 证据非空
        for f in read.factors:
            fid = f.get("factor_id")
            if fid not in allowed_factors:
                errs.append(f"因子 {fid!r} 不在词典或已退休")
            if not f.get("evidence"):
                errs.append(f"因子 {fid!r} 缺证据(非 shadow 必填)")
        # weight_pp 合计 ≈ belief−prior 的总偏移量(pp)
        moved = sum(abs(read.belief.get(k, 0.0) - read.prior.get(k, 0.0))
                    for k in read.prior) * 100 / 2
        declared = sum(abs(f.get("weight_pp", 0)) for f in read.factors)
        if read.factors and abs(moved - declared) > 1.0:
            errs.append(f"weight_pp 合计({declared})≠belief−prior 偏移({moved:.1f}pp)")

    # conf5 仅限 90' 方向市场
    if read.confidence >= 5 and read.market not in _DIRECTION_MARKETS:
        errs.append(f"conf5 仅限 90' 方向市场(had/hhad),得到 {read.market}")

    return errs
