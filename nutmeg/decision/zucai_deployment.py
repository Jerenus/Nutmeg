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
RENJIU_HISTORY_WINDOW_EFFECTIVE_ISSUE = 26113
"""当前官方任九历史锚窗口（2026-08-29 用户裁定，26113 ADJ-2）。

CLI 与 product 查询从 26113 起共用滚动 12 期官方中位；更早期次保留当时
显式登记的窗口，以便历史裁决可复现。"""

PASS_RATIO_MAX = 0.95
REDUCE_RATIO_MIN = 2.2
_TOLERANCE = 1e-12

STRONG_ANCHOR_P = 0.70
HOT_BOARD_ANCHORS = 5
"""热板阈值：板面上 fair≥70% 的强锚数 ≥5 时，中位奖金锚零描述力。

实证（scoreboard `deployment_gate_anchor_bias` / `prize_negative_correlation`）：
26120 六强锚 → 中位锚 ¥4,964 vs 实开 ¥145（高估 34 倍）；
26121 六强锚 → 中位锚 ¥2,857 vs 实开 ¥14（高估 204 倍）；
反向的 26113 冷板 → 中位锚 ¥3,113 vs 实开 ¥31,729（低估 10.2 倍）。
**中位数在两头都错**，因为奖金与当期难度强相关而中位数是全样本的。
强锚数是**赛前可观测**的难度代理，所以它能在赛前说出中位数说不出的话。

⚠️这仍然是**报告**：不排序、不阻断、不建议空仓（宪法第二序 + 部署门条）。"""


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
    strong_anchor_count: int | None = None

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
            "strong_anchor_count": self.strong_anchor_count,
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
    """Select maximum all-correct probability inside the cap and report economics."""
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
        or window_raw <= 0
        or (
            int(issue) >= RENJIU_HISTORY_WINDOW_EFFECTIVE_ISSUE
            and window_raw != RENJIU_HISTORY_WINDOW
        )
    ):
        raise ValueError(
            "history_window must be positive and must equal 12 from issue 26113"
        )
    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise ValueError("candidates must be a nonempty list")
    candidates = [_candidate(item) for item in raw_candidates]
    if len({item.candidate_id for item in candidates}) != len(candidates):
        raise ValueError("candidate ids must be unique")
    inside = [item for item in candidates if item.stake_yuan <= int(cap)]
    if not inside:
        raise ValueError("no candidate is inside period_cap_yuan")
    # Constitutional ordering: maximize P inside the external cap. Economic ratios below
    # remain report-only and never choose a smaller ticket or a no-ticket outcome.
    selected = min(
        inside,
        key=lambda item: (
            -item.hit_probability,
            item.stake_yuan,
            item.candidate_id,
        ),
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
        strong_anchor_count=_strong_anchor_count(payload),
    )


def _strong_anchor_count(payload: dict) -> int | None:
    """板面强锚数（fair≥70% 的场次）。显式给 `strong_anchor_count` 优先；
    否则从 `fair` 逐场推。两者都缺 → None（缺数据不猜，报告里显式写"未给"）。"""
    explicit = payload.get("strong_anchor_count")
    if isinstance(explicit, int) and not isinstance(explicit, bool) and explicit >= 0:
        return explicit
    fair = payload.get("fair")
    if not isinstance(fair, dict) or not fair:
        return None
    count = 0
    for row in fair.values():
        if isinstance(row, dict) and row:
            values = [v for v in row.values() if isinstance(v, (int, float))]
            if values and max(values) >= STRONG_ANCHOR_P:
                count += 1
    return count


def _board_regime_line(result: DeploymentGateResult) -> str:
    """强锚分档提示。中位锚在热板高估几十倍、在冷板低估十倍——分档把这件事写在赛前。"""
    n = result.strong_anchor_count
    if n is None:
        return ("板面难度: 未给 fair/strong_anchor_count，无法分档；"
                "中位锚只描述典型夜，不描述本期。")
    if n >= HOT_BOARD_ANCHORS:
        return (f"板面难度: **热板**（{n} 个 fair≥{STRONG_ANCHOR_P:.0%} 强锚 ≥"
                f"{HOT_BOARD_ANCHORS}）。26120/26121 同型实开 ¥145/¥14，"
                f"中位锚高估 34/204 倍——本期回本倍数请当作**下界**读，"
                f"帽内复式即使 9/9 也可能亏。")
    if n <= 2:
        return (f"板面难度: **冷板候选**（仅 {n} 个强锚）。26118 同型实开 ¥75,521"
                f"（中位 21 倍）——中位锚在这一档系统性低估。")
    return (f"板面难度: 中性（{n} 个强锚）。中位锚的描述力在此档最好，"
            f"但仍只描述典型夜。")


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
    lines.append(_board_regime_line(result))
    if result.state is DeploymentGateState.REVIEW:
        lines.append("观察: 历史中位倍数处于 review 区间；出票取舍由 Jun 裁决。")
    elif result.state is DeploymentGateState.REDUCE_OR_EMPTY:
        lines.append("观察: 历史中位倍数处于高压区间；减注或空仓仅由 Jun 裁决。")
    else:
        lines.append("报告通过；出票仍须用户确认与 ledger 入账。")
    return "\n".join(lines)
