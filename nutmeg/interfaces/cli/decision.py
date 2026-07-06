"""决策本体系统五动词 CLI(spec §3)。M0:sense 可 replay,余为骨架。

仿 cli/jczq.py 模式:@_cli.app.command 注册,由 cli/__init__ 底部 import 触发。
"""
from __future__ import annotations

from pathlib import Path

import nutmeg.interfaces.cli as _cli

# 含嵌套 Path() 构造的 Option 提到模块级单例(避 B008,仿 jczq.py 的
# JCZQ_OUTPUT_DIR_OPTION 惯例);行为与内联默认完全一致。
_OUTPUT_DIR_OPTION = _cli.typer.Option(Path(".nutmeg-data/jczq"), "--output-dir")


@_cli.app.command("decision-sense")
def decision_sense(
    run_date: str = _cli.typer.Option(..., "--run-date", help="YYYY-MM-DD"),
    output_dir: Path = _OUTPUT_DIR_OPTION,
    taken_at: str = _cli.typer.Option(..., "--taken-at", help="ISO 时刻"),
) -> None:
    """决策本体 · 动词一:盘口快照 → Match+Snapshot 入库(replay)。"""
    from nutmeg.decision.verbs import run_sense
    _cli.typer.echo(run_sense(run_date, output_dir, taken_at))


@_cli.app.command("decision-read")
def decision_read() -> None:
    """决策本体 · 动词二:产 Read(Claude 运行时推理,M1 接入)。"""
    _cli.typer.echo("decision-read: M0 骨架 — Read 由 Claude 运行时产出并经 read_validate 校验")


@_cli.app.command("decision-express")
def decision_express() -> None:
    """决策本体 · 动词三:Reads → Ticket(M1 接入)。"""
    _cli.typer.echo("decision-express: M0 骨架 — 组合枚举/预算闸见 nutmeg.decision.express")


@_cli.app.command("decision-reconcile")
def decision_reconcile() -> None:
    """决策本体 · 动词四:赛果+收盘 → Settlement(M1 接入)。"""
    _cli.typer.echo("decision-reconcile: M0 骨架 — settle_read/settle_ticket_leg 见 reconcile")


@_cli.app.command("decision-calibrate")
def decision_calibrate() -> None:
    """决策本体 · 动词五:聚合 → FactorVerdict(M1 接入)。"""
    _cli.typer.echo("decision-calibrate: M0 骨架 — factor_verdict/enforce_active_cap 见 calibrate")
