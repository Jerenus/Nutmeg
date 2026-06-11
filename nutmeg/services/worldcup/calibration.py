"""每日校准闭环(spec §3.5)— 单日只入账不改模型,n≥15 且显著跑偏才渲染警示。

口径:模型 Brier vs 市场 Brier(市场缺失的场次不参与 Brier 对比,但参与 λ 残差)。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

MIN_N = 15
LAMBDA_RESIDUAL_LIMIT = 0.3
BRIER_GAP_LIMIT = 0.05


@dataclass(frozen=True, slots=True)
class CalibrationEntry:
    date: str
    match_id: str
    model_p: dict[str, float]
    market_p: dict[str, float] | None
    outcome: str                      # home / draw / away(90 分钟)
    brier_model: float
    brier_market: float | None
    lambda_pred_total: float
    goals_actual: int


def brier(probs: dict[str, float], outcome: str) -> float:
    return sum(
        (probs.get(o, 0.0) - (1.0 if o == outcome else 0.0)) ** 2
        for o in ("home", "draw", "away")
    )


def append_entries(path: Path, entries: list[CalibrationEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(asdict(e), ensure_ascii=False) + "\n")


def load_entries(path: Path) -> list[CalibrationEntry]:
    if not path.exists():
        return []
    return [
        CalibrationEntry(**json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def calibration_alert(entries: list[CalibrationEntry]) -> str | None:
    """n≥MIN_N 且(λ 残差均值越限 或 Brier 显著落后市场)→ 警示文案;否则 None。"""
    if len(entries) < MIN_N:
        return None
    resid = [e.goals_actual - e.lambda_pred_total for e in entries]
    mean_resid = sum(resid) / len(resid)
    paired = [e for e in entries if e.brier_market is not None]
    brier_gap = (
        (sum(e.brier_model for e in paired) - sum(e.brier_market for e in paired))
        / len(paired)
        if paired else 0.0
    )
    problems: list[str] = []
    if abs(mean_resid) > LAMBDA_RESIDUAL_LIMIT:
        problems.append(f"λ 残差均值 {mean_resid:+.2f}(限 ±{LAMBDA_RESIDUAL_LIMIT})")
    if brier_gap > BRIER_GAP_LIMIT:
        problems.append(f"模型 Brier 落后市场 {brier_gap:+.3f}(限 +{BRIER_GAP_LIMIT})")
    if not problems:
        return None
    return (
        "🟨 校准警示(n=" + str(len(entries)) + "):" + ";".join(problems)
        + " — 按 §30 纪律提示人工重定标,模型本日不自动改。"
    )
