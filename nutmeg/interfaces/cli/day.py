"""`nutmeg day`：每日对象 daily/<日>/ —— 先跑完、再对话。

设计：docs/superpowers/specs/2026-09-22-daily-operator-surface-design.md
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import typer

import nutmeg.interfaces.cli as _cli

day_app = typer.Typer(
    help="每日对象 daily/<日>：settle / brief / session / results / broadcast 作业、状态、讨论"
)
_cli.app.add_typer(day_app, name="day")

_DATE = typer.Option(None, "--date", help="业务日 YYYY-MM-DD，默认今天")
_DATA_DIR = typer.Option(Path(".nutmeg-data"), "--data-dir")
_JOB = typer.Option(..., "--job", help="settle | brief | session | results | broadcast | dream")
_FORCE = typer.Option(False, "--force", help="settle 已有 retro.md 也重跑")
_DRY = typer.Option(False, "--dry-run", help="只打印子进程命令，不执行、不写时间线")
_NOW = typer.Option(None, "--now", help="测试用 ISO 时刻（覆盖当前时间）")
_WITH_LOGIC = typer.Option(False, "--with-logic", help="逻辑层：每场一次无联网 claude -p")
_OUT = typer.Option(Path("site"), "--out", help="静态站输出目录（gitignored）")


def _now() -> datetime:
    return datetime.now().astimezone()


def _ctx(date: str | None, data_dir: Path, now: str | None = None):
    from nutmeg.decision.day_runner import DayContext, default_runner

    now_fn = (lambda: datetime.fromisoformat(now)) if now else _now
    return DayContext(
        root=Path(__file__).resolve().parents[3],
        data_dir=Path(data_dir).expanduser().resolve(),
        date=date or now_fn().date().isoformat(),
        runner=default_runner,
        now=now_fn,
    )


@day_app.command("run")
def run(job: str = _JOB, date: str | None = _DATE, data_dir: Path = _DATA_DIR,
        force: bool = _FORCE, dry_run: bool = _DRY, now: str | None = _NOW,
        with_logic: bool = _WITH_LOGIC) -> None:
    """跑一个作业并把结果追加到 daily/<日>/timeline.json。"""

    from nutmeg.decision.day_runner import JOBS, planned_commands, run_job

    if job not in JOBS:
        typer.echo(f"day error: 未知作业 {job!r}；可用：{', '.join(JOBS)}")
        raise typer.Exit(code=1)
    ctx = _ctx(date, data_dir, now)
    if dry_run:
        if job == "broadcast":
            from nutmeg.decision.day_broadcast import due_broadcasts, read_sent, render_broadcast
            from nutmeg.decision.day_decisions import broadcast_decisions

            decisions = broadcast_decisions(ctx.data_dir, ctx.date, now=ctx.now())
            sent = read_sent(ctx.data_dir, ctx.date)
            for b in due_broadcasts(decisions, now=ctx.now(), sent=sent):
                typer.echo(render_broadcast(b) + "\n---")
            return
        planned = planned_commands(ctx, job)
        for cmd in planned:
            typer.echo("    " + " ".join(cmd))
        if not planned and job != "settle":
            typer.echo(f"    [{job}] 纯 Python 作业，不起子进程")
        return
    record = run_job(ctx, job, force=force, with_logic=with_logic)
    typer.echo(f"day {ctx.date} {job}: {record.summary} (exit={record.exit})")
    for row in record.commands:
        typer.echo(f"    [{row['exit']}] {row['cmd'][:80]} · {row['tail'][:120]}")
    if record.exit != 0:
        raise typer.Exit(code=1)


@day_app.command("status")
def status(date: str | None = _DATE, data_dir: Path = _DATA_DIR) -> None:
    """打印当日时间线（每行带时间证据）。"""
    from nutmeg.decision.day_timeline import read_timeline

    ctx = _ctx(date, data_dir)
    rows = read_timeline(ctx.data_dir, ctx.date)
    if not rows:
        typer.echo(f"{ctx.date}: 尚无作业记录（{ctx.out_dir}）")
        return
    for r in rows:
        typer.echo(f"{r['finished_at']}  {r['job']:8} exit={r['exit']}  {r['summary'][:100]}")


@day_app.command("note")
def note(text: str = typer.Option(..., "--text"), obj: str = typer.Option("", "--obj"),
         who: str = typer.Option("jun", "--who"), date: str | None = _DATE,
         data_dir: Path = _DATA_DIR) -> None:
    """把一句讨论追加进 daily/<日>/discussion.jsonl（页面同步显示）。"""
    from nutmeg.decision.day_session import append_discussion

    ctx = _ctx(date, data_dir)
    path = append_discussion(ctx.data_dir, ctx.date, who=who, text=text, obj=obj,
                             at=_now().isoformat(timespec="seconds"))
    typer.echo(f"记入 {path}")


@day_app.command("publish")
def publish(date: str | None = _DATE, data_dir: Path = _DATA_DIR, out: Path = _OUT) -> None:
    """对外只读导出：site/<日>/index.html + index/method/record。含禁用文本即失败。"""
    from nutmeg.decision.day_publish import PublishError, publish_day

    ctx = _ctx(date, data_dir)
    try:
        report = publish_day(data_dir=ctx.data_dir, root=ctx.root, date=ctx.date, out_dir=Path(out))
    except PublishError as exc:
        typer.echo(f"day error: {exc}")
        raise typer.Exit(code=1) from exc
    typer.echo(f"published {report['date']} pages={report['pages']} "
              f"matches={report['matches']} → {out}")
