"""纠正账（2026-10-30 产品形态 Task 10.2）：`nutmeg correction add|list|status|backfill`。

账只追加（`<data_dir>/corrections.jsonl`），取值与折叠见 `nutmeg.decision.corrections`。
「已回写」「无处可写」只在这里标——页面只许「确认」与「不改·记一笔」，真回写之后再由会话标。
"""
from __future__ import annotations

from pathlib import Path

import nutmeg.interfaces.cli as _cli

correction_app = _cli.typer.Typer(help="纠正账：旧→新、类型、谁发现、证据、回写到哪、状态")
_cli.app.add_typer(correction_app, name="correction")
_DATA_DIR = _cli.typer.Option(Path(".nutmeg-data"), "--data-dir")
_SEED = _cli.typer.Option(None, "--seed", help="默认 evidence/2026-10-30 种子")


def _fail(error: object) -> None:
    _cli.typer.echo(f"correction error: {error}")
    raise _cli.typer.Exit(code=2)


@correction_app.command("add")
def correction_add(
    obj: str = _cli.typer.Option(..., "--obj", help="对象，如 issue:26151/m3、slip:26150-T2"),
    old: str = _cli.typer.Option(..., "--old"),
    new: str = _cli.typer.Option(..., "--new"),
    kind: str = _cli.typer.Option(..., "--kind", help="data|transcription|premise|self|overrule"),
    found_by: str = _cli.typer.Option(..., "--found-by", help="jun|machine|result|official"),
    evidence: str = _cli.typer.Option("", "--evidence", help="URL / 原句 / 官方"),
    dest: str = _cli.typer.Option("none", "--dest"),
    status: str = _cli.typer.Option("draft", "--status"),
    pile: str = _cli.typer.Option("", "--pile", help="复发堆名，如「截图抄录」"),
    note: str = _cli.typer.Option("", "--note"),
    data_dir: Path = _DATA_DIR,
) -> None:
    """记一条纠正，打印 id。"""
    from nutmeg.decision.corrections import record

    try:
        cid = record(data_dir, obj=obj, old=old, new=new, kind=kind, found_by=found_by,
                     evidence=evidence, dest=dest, status=status, pile=pile, note=note)
    except ValueError as error:
        _fail(error)
    _cli.typer.echo(cid)


@correction_app.command("list")
def correction_list(
    obj: str | None = _cli.typer.Option(None, "--obj", help="对象前缀（含下属）"),
    status: str | None = _cli.typer.Option(None, "--status"),
    data_dir: Path = _DATA_DIR,
) -> None:
    """每条一行：id 日期 类型 对象 旧→新 状态（新的在前）。"""
    from nutmeg.decision.corrections import KINDS, STATUSES, for_obj, load

    rows = load(data_dir)
    if obj:
        rows = for_obj(rows, obj)
    if status:
        rows = [r for r in rows if r.get("status") == status]
    for r in rows:
        _cli.typer.echo(f"{r['id']} {str(r.get('at') or '')[:10]} "
                        f"{KINDS.get(r.get('kind'), r.get('kind'))} {r.get('obj')} "
                        f"{r.get('old')}→{r.get('new')} "
                        f"{STATUSES.get(r.get('status'), r.get('status'))}")
    if not rows:
        _cli.typer.echo("（无）")


@correction_app.command("status")
def correction_status(
    cid: str = _cli.typer.Argument(..., help="纠正 id，如 C-1a2b3c4d"),
    status: str = _cli.typer.Argument(..., help="draft|confirmed|written|dismissed|nowhere"),
    note: str = _cli.typer.Option("", "--note"),
    data_dir: Path = _DATA_DIR,
) -> None:
    """改一条纠正的状态（追加事件）。"""
    from nutmeg.decision.corrections import set_status

    try:
        set_status(data_dir, cid, status, note=note)
    except KeyError:
        _fail(f"账上没有 {cid}")
    except ValueError as error:
        _fail(error)
    _cli.typer.echo(f"{cid} → {status}")


@correction_app.command("backfill")
def correction_backfill(
    seed: Path | None = _SEED,
    data_dir: Path = _DATA_DIR,
) -> None:
    """一次性回填：种子文件 + 主循环改判账 overrides.jsonl（可反复跑，不重写）。"""
    from nutmeg.decision.corrections import SEED, backfill

    out = backfill(data_dir, seed or SEED)
    _cli.typer.echo(f"added {out['added']} · skipped {out['skipped']}")
