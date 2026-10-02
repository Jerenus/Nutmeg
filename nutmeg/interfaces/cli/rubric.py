"""判断 rubric r1（2026-10-02）：系统一读者两读 + 报表。"""
from __future__ import annotations

from pathlib import Path

import nutmeg.interfaces.cli as _cli

rubric_app = _cli.typer.Typer(help="判断 rubric：读者 B 两读（kappa）、历史重打分、报表")
_cli.app.add_typer(rubric_app, name="rubric")

_DAY = _cli.typer.Option(None, "--day", help="竞彩板面日 YYYY-MM-DD")
_ISSUE = _cli.typer.Option(None, "--issue", help="足彩期号 如 26135")
_DATA_DIR = _cli.typer.Option(Path(".nutmeg-data"), "--data-dir")
_LIMIT = _cli.typer.Option(None, "--limit", help="最多读几份（历史重打分分批用）")
_FREE = _cli.typer.Option(False, "--free", help="再跑一次不看问题表的整体概率（防游戏对照）")
_FORCE = _cli.typer.Option(False, "--force", help="已有侧车也重跑")


@rubric_app.command("read")
def rubric_read(
    day: str | None = _DAY,
    issue: str | None = _ISSUE,
    data_dir: Path = _DATA_DIR,
    limit: int | None = _LIMIT,
    free: bool = _FREE,
    force: bool = _FORCE,
) -> None:
    """让读者 B（haiku）读当天/当期每份研究的证据层，逐项作答并与分析员算 kappa，写侧车。"""
    from nutmeg.decision.rubric_reader import read_many, research_files

    if bool(day) == bool(issue):
        _cli.typer.echo("rubric error: --day 与 --issue 二选一")
        raise _cli.typer.Exit(code=2)
    paths = research_files(data_dir, day=day, issue=issue)
    out = read_many(paths, free=free, force=force, limit=limit)
    _cli.typer.echo(f"rubric read {day or issue}：读 {len(out['done'])} · 跳过 {len(out['skipped'])}"
                    f" · 失败 {len(out['failed'])}（共 {len(paths)} 份研究）")
    for row in out["failed"]:
        _cli.typer.echo(f"   ✗ {row['path']}: {row['error']}")
    if out["failed"] and not out["done"]:
        raise _cli.typer.Exit(code=1)


@rubric_app.command("report")
def rubric_report(
    day: str | None = _DAY,
    issue: str | None = _ISSUE,
    data_dir: Path = _DATA_DIR,
) -> None:
    """侧车汇总：逐场 κ、逐项一致率、B free vs B 表 → analytics/rubric/<key>.json|md。"""
    from nutmeg.decision.rubric_reader import render_report, report

    if bool(day) == bool(issue):
        _cli.typer.echo("rubric error: --day 与 --issue 二选一")
        raise _cli.typer.Exit(code=2)
    out = report(data_dir, day=day, issue=issue)
    _cli.typer.echo(render_report(out))
    _cli.typer.echo(f"→ {out['path']}")
