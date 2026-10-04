"""日循环编排的结果类型与按步执行器（decision-am / decision-settle 共用）。

单步失败只记账、不断整日循环（cron 健壮性：best-effort，可见降级）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class DecisionStepResult:
    label: str
    status: str
    message: str
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "status": self.status,
            "message": self.message,
            "details": self.details,
        }


@dataclass(slots=True, frozen=True)
class DecisionWorkflowResult:
    name: str
    run_date: str
    steps: tuple[DecisionStepResult, ...]
    description: str | None = None

    @property
    def succeeded(self) -> bool:
        return all(step.status != "failed" for step in self.steps)

    @property
    def status(self) -> str:
        return "succeeded" if self.succeeded else "failed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "run_date": self.run_date,
            "status": self.status,
            "description": self.description,
            "steps": [step.to_dict() for step in self.steps],
        }

    def __str__(self) -> str:
        header = f"{self.name} {self.run_date}"
        if self.description:
            header += f" · {self.description}"
        return "\n".join([header, *(step.message for step in self.steps)])

    def __contains__(self, value: str) -> bool:
        return value in str(self)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compose(name: str, run_date: str, description: str, steps: list) -> DecisionWorkflowResult:
    """按序跑各步；步骤返回带 ``succeeded``/``to_dict`` 的结果对象时按它记成败。"""
    results: list[DecisionStepResult] = []
    for label, fn in steps:
        try:
            value = fn()
            if hasattr(value, "succeeded") and hasattr(value, "to_dict"):
                results.append(DecisionStepResult(
                    label=label,
                    status="succeeded" if value.succeeded else "failed",
                    message=str(value),
                    details=value.to_dict(),
                ))
            else:
                results.append(
                    DecisionStepResult(label=label, status="succeeded", message=str(value))
                )
        except Exception as exc:  # noqa: BLE001 — 单步失败不该拖垮整条日循环
            logger.warning("%s %s · %s 失败", name, run_date, label, exc_info=True)
            results.append(DecisionStepResult(
                label=label, status="failed", message=f"{label}: 失败 — {exc}",
            ))
    return DecisionWorkflowResult(name, run_date, tuple(results), description)
