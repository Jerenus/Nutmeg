"""Rule O —— 单票同场合法性校验（国家体彩混合过关规则）。

spec §33（2026-06-04）：从退役的 ``jczq_diagnostics`` 模块剥离出来，作为引擎无关的
规范校验器保留。``jczq_parlay_constructor`` 的 ``as_plan()`` 适配器即为喂给本校验器
而设计。纯函数、无 I/O。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from nutmeg.domain.jczq_daily import JczqDailyPlan


@dataclass(frozen=True, slots=True)
class SameMatchPoolViolation:
    plan_kind: str
    plan_name: str
    match_no: str
    pools: tuple[str, ...]  # e.g. ("ttg", "hhad")
    picks: tuple[str, ...]  # parallel to pools
    severity: str  # "blocking" — these tickets cannot legally be placed.


def check_same_match_pool_legality(
    plans: Iterable[JczqDailyPlan],
) -> list[SameMatchPoolViolation]:
    """Detect plans that combine same-match different-pool legs in one ticket.

    Per 国家体彩 mixed-parlay rules a single ticket may NOT multiply legs from
    the same match across different pools (had/hhad/ttg/hafu/crs). Stacking two
    same-pool legs from the same match is also illegal in 单关 mode and pointless
    in mixed mode (only one outcome can win), so we treat any same-match
    repetition inside a plan as a blocking violation.

    Returns one violation per offending (plan, match) pair. An empty list means
    every plan is structurally legal.
    """

    violations: list[SameMatchPoolViolation] = []
    for plan in plans:
        if not plan.legs:
            continue
        by_match: dict[str, list] = {}
        for leg in plan.legs:
            by_match.setdefault(leg.match_no, []).append(leg)
        for match_no, legs in by_match.items():
            if len(legs) <= 1:
                continue
            violations.append(
                SameMatchPoolViolation(
                    plan_kind=plan.kind,
                    plan_name=plan.name,
                    match_no=match_no,
                    pools=tuple(leg.pool for leg in legs),
                    picks=tuple(leg.pick for leg in legs),
                    severity="blocking",
                )
            )
    return violations
