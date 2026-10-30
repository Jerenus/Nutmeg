"""待签收件箱（2026-10-30 产品形态 Task 10.3）：`nutmeg inbox propose|ask|answer|done|list|seed`。

账只追加（`<data_dir>/proposals.jsonl`），取值与折叠见 `nutmeg.decision.proposals`。会话起草提案用
`propose`；又在聊天里列了一遍用 `ask`；Jun 在聊天里答了，用 `answer` 把他的原话记进账（几条一起答
＝一批）；签了的执行完用 `done` 回挂结果。
"""
from __future__ import annotations

from pathlib import Path

import nutmeg.interfaces.cli as _cli

inbox_app = _cli.typer.Typer(help="待签收件箱：提案、问过几次、你的答复与原话、执行结果")
_cli.app.add_typer(inbox_app, name="inbox")
_DATA_DIR = _cli.typer.Option(Path(".nutmeg-data"), "--data-dir")
_IDS = _cli.typer.Argument(..., help="一个或几个 id（几个＝一批）")
_SEED = _cli.typer.Option(None, "--seed", help="默认 evidence/2026-10-30 种子")


def _fail(error: object) -> None:
    _cli.typer.echo(f"inbox error: {error}")
    raise _cli.typer.Exit(code=2)


@inbox_app.command("propose")
def inbox_propose(
    title: str = _cli.typer.Option(..., "--title"),
    body: str = _cli.typer.Option(..., "--body"),
    blocks: str = _cli.typer.Option("", "--blocks", help="拦住了什么"),
    deadline: str | None = _cli.typer.Option(None, "--deadline", help="ISO 时刻"),
    ref: str = _cli.typer.Option("", "--ref", help="会话 / 证据 / 记忆指针"),
    source: str = _cli.typer.Option("session", "--source"),
    data_dir: Path = _DATA_DIR,
) -> None:
    """起草一条待签提案，打印 id。"""
    from nutmeg.decision.proposals import propose

    try:
        pid = propose(data_dir, title=title, body=body, blocks=blocks, deadline=deadline,
                      ref=ref, source=source)
    except ValueError as error:
        _fail(error)
    _cli.typer.echo(pid)


@inbox_app.command("ask")
def inbox_ask(
    pid: str = _cli.typer.Argument(..., help="提案 id，如 P-1a2b3c4d / RSI-f94e4c"),
    where: str = _cli.typer.Option("", "--where", help="在哪又问了一次"),
    data_dir: Path = _DATA_DIR,
) -> None:
    """记一次「又被提起」（问过 +1）。"""
    from nutmeg.decision.proposals import ask

    try:
        ask(data_dir, pid, where=where)
    except KeyError:
        _fail(f"账上没有 {pid}")
    _cli.typer.echo(f"{pid} 问过 +1")


@inbox_app.command("answer")
def inbox_answer(
    pids: list[str] = _IDS,
    verdict: str = _cli.typer.Option(..., "--verdict", help="sign|modify|reject|stale"),
    words: str = _cli.typer.Option("", "--words", help="你的原话（modify 必填）"),
    by: str = _cli.typer.Option("jun", "--by"),
    data_dir: Path = _DATA_DIR,
) -> None:
    """记答复；几个 id 一起答写成同一批。"""
    from nutmeg.decision.proposals import VERDICTS, answer

    try:
        events = answer(data_dir, pids, verdict, words=words, by=by)
    except KeyError as error:
        _fail(f"账上没有 {error.args[0]}")
    except ValueError as error:
        _fail(error)
    batch = f" · 批 {events[0]['batch']}" if events[0]["batch"] else ""
    _cli.typer.echo(f"{' '.join(e['id'] for e in events)} → {VERDICTS[verdict]}{batch}")


@inbox_app.command("done")
def inbox_done(
    pid: str = _cli.typer.Argument(...),
    result: str = _cli.typer.Option(..., "--result", help="执行了什么：commit / 命令 / 文件"),
    data_dir: Path = _DATA_DIR,
) -> None:
    """签 / 改过的提案执行完，回挂结果。"""
    from nutmeg.decision.proposals import done

    try:
        done(data_dir, pid, result=result)
    except KeyError:
        _fail(f"账上没有 {pid}")
    except ValueError as error:
        _fail(error)
    _cli.typer.echo(f"{pid} → 已执行")


@inbox_app.command("list")
def inbox_list(
    pending: bool = _cli.typer.Option(False, "--pending", help="只列待签"),
    data_dir: Path = _DATA_DIR,
) -> None:
    """每条一行：id 日期 状态 问过/积压 标题（待签在前）；含闭环里开着的 RSI 项。"""
    from nutmeg.decision.proposals import STATUSES, inbox

    rows = inbox(data_dir)
    if pending:
        rows = [r for r in rows if r["status"] == "pending"]
    for r in rows:
        tail = f" · {r['words']}" if r.get("words") else ""
        flag = "!" if r.get("overdue") else " "
        _cli.typer.echo(f"{r['id']} {str(r['at'])[:10]} {STATUSES[r['status']]} {flag}"
                        f"问{r['asked_count']}/{r['age_days']}天 {r['title']}{tail}")
    if not rows:
        _cli.typer.echo("（无）")


@inbox_app.command("seed")
def inbox_seed(
    seed: Path | None = _SEED,
    data_dir: Path = _DATA_DIR,
) -> None:
    """一次性回填会话种子（可反复跑，不重写）。"""
    from nutmeg.decision.proposals import SEED
    from nutmeg.decision.proposals import seed as seed_rows

    out = seed_rows(data_dir, seed or SEED)
    _cli.typer.echo(f"added {out['added']} · skipped {out['skipped']}")
