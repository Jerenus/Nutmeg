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


_BRIEF_WRITE = _cli.typer.Option(False, "--write", help="同时写 judgment-brief.md 到板面目录")


@judgment_app.command("brief")
def judgment_brief(
    day: str | None = _DAY,
    issue: str | None = _ISSUE,
    data_dir: Path = _DATA_DIR,
    write: bool = _BRIEF_WRITE,
    cap: int = _cli.typer.Option(800, "--cap", help="足彩初稿注金帽（元）"),
) -> None:
    """初判与解读（2026-10-01 定位）：每场一行，市场/判断/表态/种类/大热/旗。竞彩不出票；
    足彩附机器初稿（Jun：传统足彩的初稿不能省略），`--write` 同时落 draft 文件。"""
    from nutmeg.decision.judgment_brief import jczq_brief, render_jczq, render_zucai, zucai_brief

    if bool(day) == bool(issue):
        _cli.typer.echo("judgment error: --day 与 --issue 二选一")
        raise _cli.typer.Exit(code=2)
    if day:
        text = render_jczq(jczq_brief(data_dir, day))
        target = Path(data_dir) / "jczq" / "daily" / day / "judgment-brief.md"
    else:
        text = render_zucai(zucai_brief(data_dir, str(issue))) + "\n" + _draft_text(
            data_dir, str(issue), cap, write)
        target = Path(data_dir) / "zucai" / f"{issue}-judgment-brief.md"
    _cli.typer.echo(text)
    if write:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        _cli.typer.echo(f"→ {target}")


_CAP = _cli.typer.Option(800, "--cap", help="初稿注金帽（元）；刹车档自动取一半")


def _draft_text(data_dir: Path, issue: str, cap: int, write: bool) -> str:
    from nutmeg.decision.zucai_draft import build_draft, render_draft

    try:
        text = render_draft(build_draft(data_dir, issue, cap_yuan=cap, write=write))
    except FileNotFoundError as exc:
        return f"# 足彩初稿 · {issue}：未出——{exc}\n"
    section = _crowd_section(data_dir, issue)
    if write:
        md = Path(data_dir) / "zucai" / f"{issue}-draft.md"
        if md.exists():
            md.write_text(md.read_text("utf-8").rstrip("\n") + "\n\n" + section, encoding="utf-8")
    return text.rstrip("\n") + "\n\n" + section


def _crowd_section(data_dir: Path, issue: str) -> str:
    """人群地图（2026-10-07）；人群层是初稿的旁支，出错只写一行不挡初稿。"""
    try:
        from nutmeg.interfaces.cli.crowd import crowd_map_text

        return crowd_map_text(data_dir, issue, Path("experiments/registry"))
    except Exception as exc:  # noqa: BLE001
        return f"## 人群地图\n\n（未出：{exc!r}）\n"


@judgment_app.command("draft")
def judgment_draft(
    issue: str = _cli.typer.Option(..., "--issue", help="足彩期号 如 26135"),
    cap: int = _CAP,
    data_dir: Path = _DATA_DIR,
    write: bool = _WRITE,
) -> None:
    """足彩初稿（处方忠实：只丢场不降档；附刹车档与帽内 max-P 对照；初稿自己过审票）。

    落 `<期>-draft.json/.md` 与 `<期>-legs-draft-<channel>.json`，候选进工作台时间线。
    """
    _cli.typer.echo(_draft_text(data_dir, issue, cap, write))
