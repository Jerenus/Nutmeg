"""`nutmeg retro encode`：复盘编码器——事实进记分牌，判断留给人（Jun 2026-09-30）。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import typer

import nutmeg.interfaces.cli as _cli

retro_app = typer.Typer(help="复盘编码：把实票结果与判断记分写进 scoreboard.json（只写事实）")
_cli.app.add_typer(retro_app, name="retro")
_DATE = typer.Option(None, "--date", help="竞彩板面日 YYYY-MM-DD")
_ISSUE = typer.Option(None, "--issue", help="足彩期号（需 official-results.json 已有开奖串）")
_PRIZE = typer.Option(None, "--prize-per-note", help="足彩官方单注奖金；缺则派奖留空")
_DATA_DIR = typer.Option(Path(".nutmeg-data"), "--data-dir")


@retro_app.command("encode")
def encode(
    date: str | None = _DATE,
    issue: str | None = _ISSUE,
    prize_per_note: float | None = _PRIZE,
    data_dir: Path = _DATA_DIR,
) -> None:
    from nutmeg.decision.retro_encoder import encode_jczq_day, encode_zucai_issue

    if not date and not issue:
        typer.echo("retro error: 给 --date 或 --issue", err=True)
        raise typer.Exit(code=1)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    out = {}
    if date:
        out["jczq"] = (encode_jczq_day(data_dir, date, now=now)
                       or {"date": date, "status": "no_results"})
    if issue:
        out["zucai"] = (encode_zucai_issue(data_dir, issue, prize_per_note=prize_per_note, now=now)
                        or {"issue": issue, "status": "no_official_draw"})
    typer.echo(json.dumps(out, ensure_ascii=False))
