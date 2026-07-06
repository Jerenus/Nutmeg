"""决策本体系统五动词 CLI(spec §3)。M0:sense 可 replay,余为骨架。

仿 cli/jczq.py 模式:@_cli.app.command 注册,由 cli/__init__ 底部 import 触发。
"""
from __future__ import annotations

from pathlib import Path

import nutmeg.interfaces.cli as _cli

# 含嵌套 Path() 构造的 Option 提到模块级单例(避 B008,仿 jczq.py 的
# JCZQ_OUTPUT_DIR_OPTION 惯例);行为与内联默认完全一致。
_OUTPUT_DIR_OPTION = _cli.typer.Option(Path(".nutmeg-data/jczq"), "--output-dir")
_READS_FILE_OPTION = _cli.typer.Option(..., "--reads-file", help="Read JSON 数组文件")


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
def decision_read(
    reads_file: Path = _READS_FILE_OPTION,
    output_dir: Path = _OUTPUT_DIR_OPTION,
) -> None:
    """决策本体 · 动词二:摄取 Claude 运行时产出的 Read(校验+落库)。"""
    from nutmeg.decision.verbs import run_read_ingest
    _cli.typer.echo(run_read_ingest(reads_file, output_dir))


@_cli.app.command("decision-capture-closing")
def decision_capture_closing(
    run_date: str = _cli.typer.Option(..., "--run-date"),
    output_dir: Path = _OUTPUT_DIR_OPTION,
    taken_at: str = _cli.typer.Option(..., "--taken-at"),
) -> None:
    """决策本体 · 收盘捕获:近开赛欧赔 → CLV 参照快照。"""
    from nutmeg.decision.verbs import run_capture_closing
    _cli.typer.echo(run_capture_closing(run_date, output_dir, taken_at))


@_cli.app.command("decision-express")
def decision_express() -> None:
    """决策本体 · 动词三:Reads → Ticket(M1 接入)。"""
    _cli.typer.echo("decision-express: M0 骨架 — 组合枚举/预算闸见 nutmeg.decision.express")


@_cli.app.command("decision-reconcile")
def decision_reconcile(
    run_date: str = _cli.typer.Option(..., "--run-date", help="YYYY-MM-DD"),
    output_dir: Path = _OUTPUT_DIR_OPTION,
    settled_at: str = _cli.typer.Option(..., "--settled-at", help="ISO 结算时刻"),
) -> None:
    """决策本体 · 动词四:赛果+收盘 → Settlement(Brier+CLV)落库。"""
    from nutmeg.decision.verbs import run_reconcile
    _cli.typer.echo(run_reconcile(run_date, output_dir, settled_at))


@_cli.app.command("decision-calibrate")
def decision_calibrate(
    output_dir: Path = _OUTPUT_DIR_OPTION,
    as_of: str = _cli.typer.Option(..., "--as-of", help="YYYY-MM-DD"),
) -> None:
    """决策本体 · 动词五:聚合 Settlement → FactorVerdict + 校准面板。"""
    from nutmeg.decision.verbs import run_calibrate_panel
    _cli.typer.echo(run_calibrate_panel(output_dir, as_of))
