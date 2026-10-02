"""账房（2026-10-01 定位）：`nutmeg account month [--month YYYY-MM] [--write]`。"""
from __future__ import annotations

from pathlib import Path

import nutmeg.interfaces.cli as _cli

account_app = _cli.typer.Typer(help="账房：月净值 vs 空仓、探索预算、判断力指标、实验判决")
_cli.app.add_typer(account_app, name="account")
_MONTH = _cli.typer.Option(None, "--month", help="YYYY-MM，默认本月")
_DATA_DIR = _cli.typer.Option(Path(".nutmeg-data"), "--data-dir")
_WRITE = _cli.typer.Option(False, "--write", help="写 analytics/account/<月>.md")
_PREVIOUS = _cli.typer.Option(False, "--previous",
                              help="上个月（月初定时器用：1 日 16:10 结完上月最后一批后出账）")


@account_app.command("month")
def account_month(month: str | None = _MONTH, data_dir: Path = _DATA_DIR,
                  write: bool = _WRITE, previous: bool = _PREVIOUS) -> None:
    """本月账：净值 vs 空仓（分渠道）、止损余量、探索预算、F14/G1/F15/F10/F9 最新结账、判决计数。"""
    from nutmeg.decision.account import current_month, month_report, previous_month, render_month

    if month and previous:
        _cli.typer.echo("account error: --month 与 --previous 二选一")
        raise _cli.typer.Exit(code=2)
    report = month_report(data_dir, previous_month() if previous else (month or current_month()))
    text = render_month(report)
    _cli.typer.echo(text)
    if write:
        target = Path(data_dir) / "analytics" / "account" / f"{report['month']}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        _cli.typer.echo(f"→ {target}")
