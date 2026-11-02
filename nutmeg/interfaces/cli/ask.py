"""行内追问（2026-11-02 产品形态 Task 10.4）：`nutmeg ask post|list|work`。

问答记在当天 `daily/<日>/discussion.jsonl`（见 `nutmeg.decision.asks`）。页面上的「问」由网页进程里
的后台线程作答；这里的 `work` 用于网页没在跑、或想在终端里补答最近两天的待答问。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import nutmeg.interfaces.cli as _cli

ask_app = _cli.typer.Typer(help="行内追问：一行上的问答线程、应答员补答")
_cli.app.add_typer(ask_app, name="ask")
_DATA_DIR = _cli.typer.Option(Path(".nutmeg-data"), "--data-dir")


def _fail(error: object) -> None:
    _cli.typer.echo(f"ask error: {error}")
    raise _cli.typer.Exit(code=2)


def _today() -> str:
    from nutmeg.decision.bj_time import BJ

    return datetime.now(BJ).date().isoformat()


@ask_app.command("post")
def ask_post(
    obj: str = _cli.typer.Option(
        ..., "--obj", help="issue:26153/m7 · jczq:2026-11-01/周日003 · ledger:2026-10"),
    text: str = _cli.typer.Option(..., "--text"),
    data_dir: Path = _DATA_DIR,
) -> None:
    """记一个问（不作答；作答用 `work` 或网页）。"""
    from nutmeg.decision.asks import ask

    try:
        got = ask(data_dir, obj=obj, text=text)
    except ValueError as error:
        _fail(error)
    _cli.typer.echo(f"{got['date']}#{got['seq']}")


@ask_app.command("list")
def ask_list(
    obj: str = _cli.typer.Option(..., "--obj", help="对象前缀，含下属对象"),
    days: int = _cli.typer.Option(30, "--days"),
    data_dir: Path = _DATA_DIR,
) -> None:
    """一个对象近 N 天的问答。"""
    from nutmeg.decision.asks import check_obj, thread

    try:
        rows = thread(data_dir, check_obj(obj), today=_today(), days=days)
    except ValueError as error:
        _fail(error)
    for q in rows:
        a = q["answer"]
        _cli.typer.echo(f"{q['date']}#{q['seq']} {q['at'][11:16]} {q['obj']}  问：{q['text']}")
        _cli.typer.echo(f"    答（{a.get('status')}）：{a['text']}" if a else "    （待答）")


@ask_app.command("work")
def ask_work(
    data_dir: Path = _DATA_DIR,
    push: bool = _cli.typer.Option(True, "--push/--no-push", help="答完推 Telegram"),
) -> None:
    """答掉最近两天的待答问（每个问一次 `claude -p`）。"""
    from nutmeg.decision.asks import telegram_push, work
    from nutmeg.decision.bj_time import BJ
    from nutmeg.interfaces.decision_web_asks import excerpt_for

    done = work(data_dir, today=_today(),
                excerpt_for=lambda obj: excerpt_for(data_dir, obj, now=datetime.now(BJ)),
                push=telegram_push if push else None)
    for row in done:
        _cli.typer.echo(f"{row['obj']} · {row['status']} · {row['text'][:80]}")
    _cli.typer.echo(f"答了 {len(done)} 个")
