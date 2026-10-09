"""球队损耗台账 CLI（2026-10-09）。

设计稿：docs/superpowers/specs/2026-10-09-team-load-ledger-design.md。

只展示、只记账：台账不进 belief、不进票面；F16 前瞻实证之前不给任何权重。"""
from __future__ import annotations

from pathlib import Path

import typer

import nutmeg.interfaces.cli as _cli

_DATA_DIR = typer.Option(Path(".nutmeg-data"), "--data-dir")
load_app = typer.Typer(help="球队损耗台账（休息天数 / 14 天场数 / 下一场 / 长歇 + rubric 伤停）")
_cli.app.add_typer(load_app, name="load")


@load_app.command("ledger")
def ledger(
    day: str | None = typer.Option(None, "--day", help="竞彩当日板 + 当天截止的足彩期次"),
    issue: str | None = typer.Option(None, "--issue", help="只算这一期足彩"),
    write: bool = typer.Option(False, "--write", help="落盘（已开球的行保留原样）"),
    data_dir: Path = _DATA_DIR,
) -> None:
    """逐场列出两队损耗；不加 --write 只预览。"""
    from nutmeg.decision.team_load import (
        brief_cell,
        build_index,
        jczq_ledger_rows,
        now_bj,
        write_day_ledgers,
        write_zucai_ledger,
        zucai_ledger_rows,
    )
    from nutmeg.decision.zucai_identity import closing_issues

    if not day and not issue:
        raise typer.BadParameter("需要 --day 或 --issue")
    now = now_bj()
    index = build_index(data_dir)
    boards: list[tuple[str, dict]] = []
    if issue:
        boards.append((f"足彩 {issue}", zucai_ledger_rows(data_dir, issue, now=now, index=index)))
    else:
        boards.append((f"竞彩 {day}", jczq_ledger_rows(data_dir, day, now=now, index=index)))
        for closing, _doc in closing_issues(Path(data_dir) / "zucai", day):
            boards.append((f"足彩 {closing}",
                           zucai_ledger_rows(data_dir, closing, now=now, index=index)))
    for label, rows in boards:
        typer.echo(f"## {label}：{len(rows)} 场" + ("" if write else "（预览，不落盘）"))
        for k, row in sorted(rows.items(), key=lambda kv: (len(kv[0]), kv[0])):
            typer.echo(f"  {k:>6} {row['home']}-{row['away']}  {brief_cell(row)}")
    if write:
        if issue:
            path = write_zucai_ledger(data_dir, issue, now=now, index=index)
            typer.echo(f"→ {path}" if path else "（无期次文件，未写）")
        else:
            out = write_day_ledgers(data_dir, day, now=now, index=index)
            for path in [out["jczq"], *out["zucai"].values()]:
                if path:
                    typer.echo(f"→ {path}")
