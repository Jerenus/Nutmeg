"""Deterministic Zucai deployment arithmetic; ticket decisions stay in the main loop."""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from enum import StrEnum

from nutmeg.decision.zucai_official import (
    RENJIU_RETURN_RATE,
    OfficialRenjiuHistory,
)

RENJIU_HISTORY_WINDOW = 12
"""官方任九历史锚的唯一窗口（2026-08-29 用户裁定，26113 ADJ-2）。

CLI 与 product 查询共用同一常量：奖金锚必须是滚动 12 期官方中位。
n=3 近期窗已废止——26112 用它锚 ¥414 而实开 ¥4,098（10 倍低估）。"""

PASS_RATIO_MAX = 0.95
REDUCE_RATIO_MIN = 2.2
_TOLERANCE = 1e-12


class DeploymentGateState(StrEnum):
    PASS = "pass"
    REVIEW = "review"
    REDUCE_OR_EMPTY = "reduce_or_empty"


@dataclass(frozen=True)
class DeploymentCandidate:
    candidate_id: str
    stake_yuan: int
    hit_probability: float


@dataclass(frozen=True)
class DeploymentGateResult:
    issue: str
    state: DeploymentGateState
    selected_id: str
    stake_yuan: int
    hit_probability: float
    period_cap_yuan: int
    capital_utilization: float
    break_even_bonus: float
    median_bonus: float
    median_sale_amount: float
    break_even_to_median: float
    equivalent_max_winning_stakes: int
    history_as_of_issue: str
    history_window: int
    history_issues: tuple[str, ...]
    excluded_over_cap: tuple[str, ...]

    @property
    def exit_code(self) -> int:
        return {
            DeploymentGateState.PASS: 0,
            DeploymentGateState.REVIEW: 2,
            DeploymentGateState.REDUCE_OR_EMPTY: 3,
        }[self.state]

    def to_dict(self) -> dict[str, object]:
        return {
            "issue": self.issue,
            "state": self.state.value,
            "exit_code": self.exit_code,
            "selected_id": self.selected_id,
            "stake_yuan": self.stake_yuan,
            "hit_probability": self.hit_probability,
            "period_cap_yuan": self.period_cap_yuan,
            "capital_utilization": self.capital_utilization,
            "break_even_bonus": self.break_even_bonus,
            "median_bonus": self.median_bonus,
            "median_sale_amount": self.median_sale_amount,
            "break_even_to_median": self.break_even_to_median,
            "equivalent_max_winning_stakes": self.equivalent_max_winning_stakes,
            "history_as_of_issue": self.history_as_of_issue,
            "history_window": self.history_window,
            "history_issues": list(self.history_issues),
            "excluded_over_cap": list(self.excluded_over_cap),
        }


def _positive_number(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field} must be a positive number")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{field} must be a positive number")
    return number


def _candidate(value: object) -> DeploymentCandidate:
    if not isinstance(value, dict):
        raise ValueError("candidates must contain objects")
    candidate_id = str(value.get("id", "")).strip()
    stake = _positive_number(value.get("stake_yuan"), field="stake_yuan")
    probability = _positive_number(
        value.get("hit_probability"), field="hit_probability"
    )
    if not candidate_id:
        raise ValueError("candidate id is required")
    if not stake.is_integer():
        raise ValueError("stake_yuan must be a whole yuan amount")
    if probability > 1:
        raise ValueError("hit_probability must be <= 1")
    return DeploymentCandidate(candidate_id, int(stake), probability)


def _cohort(
    history: list[OfficialRenjiuHistory], *, as_of_issue: str, window: int
) -> list[OfficialRenjiuHistory]:
    if not as_of_issue.isdigit():
        raise ValueError("history_as_of_issue must be numeric")
    eligible = []
    for row in history:
        if (
            not row.issue.isdigit()
            or row.stake_count <= 0
            or row.stake_amount <= 0
            or row.sale_amount <= 0
        ):
            raise ValueError("official history contains invalid facts")
        if not row.payout_consistent_with_return_rate():
            raise ValueError(f"official history return rate drifted for {row.issue}")
        if int(row.issue) < int(as_of_issue):
            eligible.append(row)
    eligible.sort(key=lambda row: int(row.issue), reverse=True)
    if len(eligible) < window:
        raise ValueError(
            f"history_window={window} requires {window} prior official rows, got {len(eligible)}"
        )
    return eligible[:window]


def evaluate_deployment_gate(
    payload: dict, history: list[OfficialRenjiuHistory]
) -> DeploymentGateResult:
    """Select max-P structure inside the cap and evaluate official-median economics."""
    if not isinstance(payload, dict):
        raise ValueError("deployment gate input must be an object")
    issue = str(payload.get("issue", "")).strip()
    as_of_issue = str(payload.get("history_as_of_issue", "")).strip()
    if not issue or not issue.isdigit():
        raise ValueError("issue must be numeric")
    cap = _positive_number(payload.get("period_cap_yuan"), field="period_cap_yuan")
    if not cap.is_integer():
        raise ValueError("period_cap_yuan must be a whole yuan amount")
    window_raw = payload.get("history_window")
    if (
        isinstance(window_raw, bool)
        or not isinstance(window_raw, int)
        or window_raw != RENJIU_HISTORY_WINDOW
    ):
        raise ValueError(f"history_window must equal {RENJIU_HISTORY_WINDOW}")
    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise ValueError("candidates must be a nonempty list")
    candidates = [_candidate(item) for item in raw_candidates]
    if len({item.candidate_id for item in candidates}) != len(candidates):
        raise ValueError("candidate ids must be unique")
    inside = [item for item in candidates if item.stake_yuan <= int(cap)]
    if not inside:
        raise ValueError("no candidate is inside period_cap_yuan")
    selected = min(
        inside,
        key=lambda item: (-item.hit_probability, item.stake_yuan, item.candidate_id),
    )
    cohort = _cohort(history, as_of_issue=as_of_issue, window=window_raw)
    median_bonus = float(statistics.median(row.stake_amount for row in cohort))
    median_sale = float(statistics.median(row.sale_amount for row in cohort))
    break_even = selected.stake_yuan / selected.hit_probability
    ratio = break_even / median_bonus
    if ratio <= PASS_RATIO_MAX + _TOLERANCE:
        state = DeploymentGateState.PASS
    elif ratio >= REDUCE_RATIO_MIN - _TOLERANCE:
        state = DeploymentGateState.REDUCE_OR_EMPTY
    else:
        state = DeploymentGateState.REVIEW
    return DeploymentGateResult(
        issue=issue,
        state=state,
        selected_id=selected.candidate_id,
        stake_yuan=selected.stake_yuan,
        hit_probability=selected.hit_probability,
        period_cap_yuan=int(cap),
        capital_utilization=selected.stake_yuan / cap,
        break_even_bonus=break_even,
        median_bonus=median_bonus,
        median_sale_amount=median_sale,
        break_even_to_median=ratio,
        equivalent_max_winning_stakes=math.floor(
            median_sale * RENJIU_RETURN_RATE / break_even
        ),
        history_as_of_issue=as_of_issue,
        history_window=window_raw,
        history_issues=tuple(row.issue for row in cohort),
        excluded_over_cap=tuple(sorted(
            item.candidate_id for item in candidates if item.stake_yuan > cap
        )),
    )


def format_deployment_gate(result: DeploymentGateResult) -> str:
    lines = [
        f"== {result.issue} 足彩部署门 ==",
        f"帽内最优: {result.selected_id} ¥{result.stake_yuan:,} / "
        f"帽 ¥{result.period_cap_yuan:,} = {result.capital_utilization:.1%}; "
        f"P(全中)={result.hit_probability:.2%}",
        f"回本奖金: ¥{result.break_even_bonus:,.0f}; "
        f"官方历史中位: ¥{result.median_bonus:,.0f}; "
        f"倍数={result.break_even_to_median:.2f}x",
        f"64%返奖等价中奖注数上限: {result.equivalent_max_winning_stakes:,}",
        f"状态: {result.state.value} (exit {result.exit_code})",
    ]
    if result.state is DeploymentGateState.REVIEW:
        lines.append("建议: 先构造丢场式减注版并重跑；是否采用由主循环裁决。")
    elif result.state is DeploymentGateState.REDUCE_OR_EMPTY:
        lines.append("建议: 优先丢场式减注并重跑；无合格减注版时才空仓。")
    else:
        lines.append("报告通过；出票仍须用户确认与 ledger 入账。")
    return "\n".join(lines)
