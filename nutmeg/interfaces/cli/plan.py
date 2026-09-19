"""Traditional Zucai structural planning commands."""
from __future__ import annotations

from pathlib import Path

import typer

import nutmeg.interfaces.cli as _cli

plan_app = typer.Typer(help="传统足彩专项：定级/风向 → 前沿 → 人挑 → 定案 → 对账")
_cli.app.add_typer(plan_app, name="plan")

_DATA_DIR = typer.Option(Path(".nutmeg-data"), "--data-dir")
_ISSUE = typer.Option(..., "--issue")
_CHANNEL = typer.Option(..., "--channel", help="renjiu | shengfucai")
_CAP = typer.Option(None, "--cap", help="Yuan cap; defaults to 400")
_POINT = typer.Option(..., "--point", help="frontier point k")
_EDIT = typer.Option(None, "--edit", help="edited {match_no: faces} JSON")


def _fail(message: str) -> None:
    typer.echo(f"plan error: {message}")
    raise typer.Exit(code=1)


@plan_app.command("tiers")
def tiers(issue: str = _ISSUE, data_dir: Path = _DATA_DIR) -> None:
    """Run the B5c matrix tiers and descriptive board wind."""
    from nutmeg.decision.plan_flow import run_tiers

    try:
        doc = run_tiers(issue=issue, data_dir=data_dir)
    except FileNotFoundError as exc:
        _fail(str(exc))
    wind = doc["wind"]
    typer.echo(
        f"{issue} 风向 {wind['regime']} · 各级 {wind['tiers']} · "
        f"可收窄面 {wind['narrowable_faces']} · 建议帽档 {wind['cap_band']}"
    )
    for match_no, tier in sorted(doc["tiers"].items(), key=lambda item: int(item[0])):
        typer.echo(f"  场{match_no:>2} {tier}")


@plan_app.command("frontier")
def frontier(
    issue: str = _ISSUE,
    channel: str = _CHANNEL,
    cap: int | None = _CAP,
    data_dir: Path = _DATA_DIR,
) -> None:
    """Enumerate the matrix frontier and strict-floor maximum probability."""
    from nutmeg.decision.plan_flow import run_frontier
    from nutmeg.decision.structure_space import NoFaceStatusError

    cap_yuan = cap or 400
    try:
        result = run_frontier(
            issue=issue, channel=channel, cap_yuan=cap_yuan, data_dir=data_dir
        )
    except (FileNotFoundError, NoFaceStatusError, ValueError) as exc:
        _fail(str(exc))
    max_probability = (
        "空前沿" if result["max_p"] is None else f"{result['max_p'] * 100:.2f}%"
    )
    strict_probability = (
        "空" if result["strict_max_p"] is None else f"{result['strict_max_p'] * 100:.2f}%"
    )
    typer.echo(
        f"{issue} {channel} ¥{cap_yuan}：前沿 {result['n_points']} 点 · "
        f"帽内 max P {max_probability} · strict 地板 {strict_probability}"
    )
    for point in result["points"][:12]:
        faces = " ".join(
            f"{match_no}:{face_string}"
            for match_no, face_string in sorted(
                point["faces"].items(), key=lambda item: int(item[0])
            )
        )
        typer.echo(
            f"  #{point['k']:<3} {point['notes']:>5}注 ¥{point['stake_yuan']:<5} "
            f"P {point['p_all'] * 100:6.2f}% {point['shape']['singles']}单"
            f"{point['shape']['doubles']}双{point['shape']['fulls']}包  {faces}"
        )


@plan_app.command("choose")
def choose(
    issue: str = _ISSUE,
    channel: str = _CHANNEL,
    point: int = _POINT,
    edit: Path | None = _EDIT,
    data_dir: Path = _DATA_DIR,
) -> None:
    """Choose a frontier point, optionally recording a human edit."""
    from nutmeg.decision.plan_flow import run_choose

    try:
        result = run_choose(
            issue=issue,
            channel=channel,
            point=point,
            data_dir=data_dir,
            edit_file=edit,
        )
    except (FileNotFoundError, StopIteration, KeyError) as exc:
        _fail(f"frontier point or file is missing: {exc}")
    typer.echo(
        f"{result['candidate_node']} ← {result['parent']} · {result['notes']} 注 "
        f"¥{result['stake_yuan']} · P {result['p_all'] * 100:.2f}%\n"
        f"  → {result['legs_file']}（下一步 B6：decision-audit-legs）"
    )
