"""把 RSI 义务接进现有链条的两根线。都是「加一行」，不改被接线方的语义。

失败不抛：备料链与观察仪的主任务不能因为登记失败而失败——但要打印，别静默。
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

Invoker = Callable[[list[str]], int]


def _cli_invoke(argv: list[str]) -> int:
    """进程内跑 `nutmeg <argv>`。任何失败（非零退出 / 异常）都只打印警告并返回非零。"""
    try:
        from typer.testing import CliRunner

        from nutmeg.interfaces.cli import app

        result = CliRunner().invoke(app, argv)
    except Exception as exc:  # noqa: BLE001 —— 接线层是主任务的旁支，绝不向上抛
        print(f"⚠️rsi 接线未成功（不影响主任务）：{' '.join(argv)}\n{exc!r}"[-600:])
        return 1
    if result.exit_code != 0:
        tail = (result.output or "").strip()[-300:]
        if result.exception is not None and not tail:
            tail = repr(result.exception)
        print(f"⚠️rsi 接线未成功（不影响主任务）：{' '.join(argv)}\n{tail}")
    return result.exit_code


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
