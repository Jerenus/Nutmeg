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
_WORKERS = _cli.typer.Option(4, "--workers", help="并发读者数（每份一个 claude -p）")
_PENDING = _cli.typer.Option(False, "--pending",
                             help="只读还没开球、还没有侧车的研究（竞彩昨天到明天 + 足彩近三期）")


@rubric_app.command("read")
def rubric_read(
    day: str | None = _DAY,
    issue: str | None = _ISSUE,
    data_dir: Path = _DATA_DIR,
    limit: int | None = _LIMIT,
    free: bool = _FREE,
    force: bool = _FORCE,
    workers: int = _WORKERS,
    pending: bool = _PENDING,
) -> None:
    """让读者 B（haiku）读当天/当期每份研究的证据层，逐项作答并与分析员算 kappa，写侧车。"""
    from nutmeg.decision.rubric_reader import pending_research, read_many, research_files

    if (bool(day) + bool(issue) + pending) != 1:
        _cli.typer.echo("rubric error: --day / --issue / --pending 三选一")
        raise _cli.typer.Exit(code=2)
    paths = (pending_research(data_dir) if pending
             else research_files(data_dir, day=day, issue=issue))
    out = read_many(paths, free=free, force=force, limit=limit, workers=workers)
    _cli.typer.echo(f"rubric read {day or issue or '开球前待读'}：读 {len(out['done'])} · "
                    f"跳过 {len(out['skipped'])} · 失败 {len(out['failed'])}"
                    f"（共 {len(paths)} 份研究）")
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


_VERSION = _cli.typer.Option(None, "--version", help="看某个版本的问题表（默认当前）")


@rubric_app.command("items")
def rubric_items(version: str = _VERSION) -> None:
    """打印问题表（治理：增删项走证据文档 → changelog → 升版本；评分器按版本过滤）。"""
    from nutmeg.decision.rubric_items import RUBRIC_CHANGELOG, RUBRIC_VERSION, items_markdown

    v = version or RUBRIC_VERSION
    _cli.typer.echo(f"# 判断 rubric {v}（当前 {RUBRIC_VERSION}）")
    _cli.typer.echo(items_markdown(v))
    _cli.typer.echo("")
    for entry in RUBRIC_CHANGELOG:
        _cli.typer.echo(f"- {entry['version']} {entry['date']}：{entry['change']}"
                        f"（{entry['evidence']}）")
