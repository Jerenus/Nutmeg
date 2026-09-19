"""把 RSI 义务接进现有链条的三根线。都是「加一行」，不改被接线方的语义。

失败不抛：备料链 / 观察仪 / 结算链的主任务不能因为登记失败而失败——但要打印，别静默。
"""
from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path

Invoker = Callable[[list[str]], tuple[int, str]]

# 结算后 grade/verdict 的「预期非零」：不是失败，是状态。
_NO_ADAPTER = "尚未接入"
_NOT_DUE = "未到期"


def _cli_invoke(argv: list[str]) -> tuple[int, str]:
    """进程内跑 `nutmeg <argv>`。任何失败（非零退出 / 异常）都只打印警告并返回 (非零, 输出)。"""
    try:
        from typer.testing import CliRunner

        from nutmeg.interfaces.cli import app

        result = CliRunner().invoke(app, argv)
    except Exception as exc:  # noqa: BLE001 —— 接线层是主任务的旁支，绝不向上抛
        print(f"⚠️rsi 接线未成功（不影响主任务）：{' '.join(argv)}\n{exc!r}"[-600:])
        return 1, repr(exc)
    output = result.output or ""
    if result.exit_code != 0:
        tail = output.strip()[-300:]
        if result.exception is not None and not tail:
            tail = repr(result.exception)
            output = output or tail
        print(f"⚠️rsi 接线未成功（不影响主任务）：{' '.join(argv)}\n{tail}")
    return result.exit_code, output


def after_prep(*, issue: str, day: str, data_dir: Path, invoke: Invoker = _cli_invoke) -> None:
    """备料链跑完：为当天排义务，并把待办（几点前跑哪条 instrument）打到终端。"""
    invoke(["rsi", "schedule", "--day", day, "--issue", issue, "--data-dir", str(data_dir)])
    invoke(["rsi", "due", "--day", day, "--data-dir", str(data_dir)])


def after_observation_artifact(*, exp: str, duty: str, issue: str, day: str, artifact: Path,
                               n_rows: int, data_dir: Path,
                               invoke: Invoker = _cli_invoke) -> None:
    """观察仪产物落盘后登记 fulfil（前瞻性由 CLI 按产物 mtime 与最早开球判定）。"""
    invoke(["rsi", "fulfill", "--exp", exp, "--duty", duty, "--day", day, "--issue", issue,
            "--artifact", str(artifact), "--n-rows", str(n_rows), "--data-dir", str(data_dir)])


def after_capital_plan(
    *,
    exp: str,
    issue: str,
    day: str,
    plan_id: str,
    data_dir: Path,
    captured_at: datetime | None = None,
    invoke: Invoker = _cli_invoke,
) -> None:
    """Register one F4 observation after a capital plan commits."""
    artifact = Path(data_dir) / "zucai" / f"{issue}-capital-plan.txt"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(plan_id + "\n", encoding="utf-8")
    if captured_at is not None:
        timestamp = captured_at.timestamp()
        os.utime(artifact, (timestamp, timestamp))
    invoke(
        [
            "rsi",
            "fulfill",
            "--exp",
            exp,
            "--duty",
            "capital-plan",
            "--day",
            day,
            "--issue",
            issue,
            "--artifact",
            str(artifact),
            "--n-rows",
            "1",
            "--data-dir",
            str(data_dir),
        ]
    )


def _active_experiments(data_dir: Path) -> list[str]:
    """从本体读 status ∈ {observing, graded} 的实验 id（结算后该结账的那些）。"""
    from datetime import UTC, datetime

    from nutmeg.config.settings import AppSettings
    from nutmeg.ontology import build_ontology_kernel
    from nutmeg.product.repository import ProductReadRepository

    kernel = build_ontology_kernel(AppSettings(data_dir=data_dir))
    kernel.initialize()
    rows = ProductReadRepository(kernel.engine).experiments(
        as_of=datetime.now(UTC).isoformat())
    return [r["exp_id"] for r in rows if r.get("status") in ("observing", "graded")]


def after_settle(*, day: str, data_dir: Path, invoke: Invoker = _cli_invoke,
                 experiments: Iterable[str] | None = None) -> dict[str, str]:
    """结算跑完（非 dry-run）：每条在观察中的实验 grade 一次；grade 成功再试 verdict。

    spec 2026-09-18 §8.1 第 3 项。返回 {exp_id: 状态}，状态 ∈
    verdict_recorded / not_due / skipped_no_adapter / grade_failed / verdict_failed / error。
    `尚未接入`（无结账适配器）与 `未到期` 都是预期结果，不是失败。永不向上抛。
    """
    report: dict[str, str] = {}
    try:
        exp_ids = list(experiments) if experiments is not None else _active_experiments(data_dir)
    except Exception as exc:  # noqa: BLE001 —— 读不到本体也不能拖垮结算
        print(f"⚠️rsi 结算接线未成功（不影响主任务）：读实验列表失败 {exc!r}"[-600:])
        return report
    for exp in exp_ids:
        try:
            rc, out = invoke(["rsi", "grade", "--exp", exp, "--mode", "prospective",
                              "--data-dir", str(data_dir)])
            if rc != 0:
                status = "skipped_no_adapter" if _NO_ADAPTER in out else "grade_failed"
            else:
                rc, out = invoke(["rsi", "verdict", "--exp", exp, "--data-dir", str(data_dir)])
                if rc == 0:
                    status = "verdict_recorded"
                elif _NOT_DUE in out:
                    status = "not_due"
                else:
                    status = "verdict_failed"
        except Exception as exc:  # noqa: BLE001 —— 接线层是主任务的旁支，绝不向上抛
            print(f"⚠️rsi 结算接线未成功（不影响主任务）：{exp} {exc!r}"[-600:])
            status = "error"
        report[exp] = status
        print(f"rsi 结账 {day} {exp} → {status}")
    return report
