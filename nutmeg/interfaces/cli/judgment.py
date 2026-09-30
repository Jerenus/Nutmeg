"""判断唯一事实 P0（2026-10-01）：`nutmeg judgment project` 从内核投影一块板的 Read 并比对。"""
from __future__ import annotations

from pathlib import Path

import nutmeg.interfaces.cli as _cli

judgment_app = _cli.typer.Typer(help="判断唯一事实：内核 revision → Read 投影与比对")
_cli.app.add_typer(judgment_app, name="judgment")

_DAY = _cli.typer.Option(None, "--day", help="竞彩板面日 YYYY-MM-DD")
_ISSUE = _cli.typer.Option(None, "--issue", help="足彩期号 如 26135")
_DATA_DIR = _cli.typer.Option(Path(".nutmeg-data"), "--data-dir")
_WRITE = _cli.typer.Option(True, "--write/--no-write",
                           help="落 reads.projected.json 与 judgment-projection.json")


@judgment_app.command("project")
def judgment_project(
    day: str | None = _DAY,
    issue: str | None = _ISSUE,
    data_dir: Path = _DATA_DIR,
    write: bool = _WRITE,
) -> None:
    """从内核投影一块板的 Read（每序列最高 revision），与 reads.json 逐场比对。"""
    from nutmeg.decision.judgment_projection import run_projection

    try:
        out = run_projection(data_dir, day=day, issue=issue, write=write)
    except ValueError as exc:
        _cli.typer.echo(f"judgment error: {exc}")
        raise _cli.typer.Exit(code=2) from exc
    result = out["result"]
    _cli.typer.echo(f"{out['board_key']}：{out['line']}")
    for row in result["mismatch"]:
        _cli.typer.echo(f"   分歧 {row['code']}：内核 belief {row['kernel']['belief']}"
                        f" ／ 文件 belief {row['file']['belief']}")
    for row in result["same_judgment_new_version"]:
        _cli.typer.echo(f"   同判断新版本 {row['code']}：内核 {row['kernel']}"
                        f" ／ 文件 {row['file']}")
    if result["only_in_file"]:
        _cli.typer.echo(f"   仅文件（未交本体或已开球）：{len(result['only_in_file'])} 场")
    if result["only_in_kernel"]:
        _cli.typer.echo(f"   仅内核（文件已删或重建）：{len(result['only_in_kernel'])} 场")
    if out["report"]:
        _cli.typer.echo(f"→ {out['report']}")
