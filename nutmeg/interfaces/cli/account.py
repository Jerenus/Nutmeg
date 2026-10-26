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


_FROM = _cli.typer.Option("26136", "--from", help="起始期号（选择账自 26136 起攒）")
_TO = _cli.typer.Option(None, "--to", help="截止期号，默认到最新")


@account_app.command("choices")
def account_choices(start: str = _FROM, end: str | None = _TO,
                    data_dir: Path = _DATA_DIR) -> None:
    """选择账：每期同钱三列 Jun 实票 / 机器默认 / 退役形（丢光 C 档），攒 20 期再读。"""
    from nutmeg.decision.choice_ledger import build_choices, render_choices

    _cli.typer.echo(render_choices(build_choices(data_dir, start=start, end=end)))
