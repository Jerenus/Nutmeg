"""Traditional Zucai structural planning commands."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import typer

import nutmeg.interfaces.cli as _cli
from nutmeg.config.settings import AppSettings
from nutmeg.ontology import build_ontology_kernel
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

plan_app = typer.Typer(help="传统足彩专项：定级/风向 → 前沿 → 人挑 → 定案 → 对账")
_cli.app.add_typer(plan_app, name="plan")

_DATA_DIR = typer.Option(Path(".nutmeg-data"), "--data-dir")
_ISSUE = typer.Option(..., "--issue")
_CHANNEL = typer.Option(..., "--channel", help="renjiu | shengfucai")
_CAP = typer.Option(None, "--cap", help="Yuan cap; defaults to 400")
_POINT = typer.Option(..., "--point", help="frontier point k")
_EDIT = typer.Option(None, "--edit", help="edited {match_no: faces} JSON")
_CAP_SOURCE = typer.Option("baseline", "--cap-source", help="baseline | override | brake")
_ADJUDICATION = typer.Option(None, "--adjudication", help="required for override")


def _fail(message: str) -> None:
    typer.echo(f"plan error: {message}")
    raise typer.Exit(code=1)


def _kernel(data_dir: Path):
    kernel = build_ontology_kernel(
        AppSettings(data_dir=Path(data_dir).expanduser().resolve())
    )
    kernel.initialize()
    return kernel


def _jczq_used_today(data_dir: Path, day: str) -> int:
    path = Path(data_dir) / "betslips.jsonl"
    if not path.exists():
        return 0
    used = 0
    for line in path.read_text("utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        placed_at = str(row.get("placed_at") or "")
        if row.get("channel") == "jczq" and (not placed_at or placed_at[:10] == day):
            used += int(row.get("stake_yuan") or 0)
    return used


def _registered_slips(data_dir: Path, issue: str) -> dict[str, dict]:
    path = Path(data_dir) / "betslips.jsonl"
    if not path.exists():
        return {}
    slips = {}
    for line in path.read_text("utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if str(row.get("issue") or "") == issue or str(row.get("slip_id", "")).startswith(
            issue
        ):
            slips[row["slip_id"]] = row
    return slips


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


@plan_app.command("commit")
def commit(
    issue: str = _ISSUE,
    cap_source: str = _CAP_SOURCE,
    adjudication: str | None = _ADJUDICATION,
    data_dir: Path = _DATA_DIR,
) -> None:
    """Commit the B9 capital plan through its governed Action."""
    from nutmeg.decision.plan_flow import _day_of
    from nutmeg.ontology.actions.capital_actions import CommitCapitalPlanRequest

    zucai_dir = Path(data_dir) / "zucai"
    day = _day_of(issue, data_dir)
    frontiers = {}
    chosen = []
    caps = {"renjiu": 0, "shengfucai": 0, "total": 0}
    digit_face = {"3": "home", "1": "draw", "0": "away"}
    for channel in ("renjiu", "shengfucai"):
        frontier_path = zucai_dir / f"{issue}-frontier-{channel}.json"
        legs_path = zucai_dir / f"{issue}-legs-{channel}.json"
        if not (frontier_path.exists() and legs_path.exists()):
            continue
        frontier_doc = json.loads(frontier_path.read_text("utf-8"))
        frontiers[channel] = frontier_doc
        legs_raw = legs_path.read_bytes()
        legs = json.loads(legs_raw)["legs"]
        notes = 1
        for leg in legs.values():
            notes *= len(leg["faces"])
        probability = 1.0
        for leg in legs.values():
            probability *= sum(
                float(leg["fair"][digit_face[digit]]) for digit in leg["faces"]
            )
        chosen.append(
            {
                "channel": channel,
                "candidate_node": f"chosen@{channel}",
                "legs_file_hash": hashlib.sha256(legs_raw).hexdigest(),
                "notes": notes,
                "stake_yuan": notes * 2,
                "p_all": probability,
                "slip_id": None,
            }
        )
        caps[channel] = int(frontier_doc["cap_yuan"])
    if not chosen:
        _fail("没有已 choose 的票面（先 plan frontier → plan choose）")
    caps["total"] = caps["renjiu"] + caps["shengfucai"]
    used = _jczq_used_today(data_dir, day)
    matrix_probabilities = [
        frontier["max_p"]
        for frontier in frontiers.values()
        if frontier["max_p"] is not None
    ]
    strict_probabilities = [
        frontier["strict_max_p"]
        for frontier in frontiers.values()
        if frontier.get("strict_max_p") is not None
    ]
    kernel = _kernel(data_dir)
    now = datetime.now().astimezone()
    try:
        outcome = kernel.capital_actions.commit_capital_plan(
            CommitCapitalPlanRequest(
                issue=issue,
                day=day,
                cap_source=cap_source,
                adjudication_ref=adjudication,
                caps=caps,
                jczq_used_today=used,
                frontier_refs={
                    channel: frontier["frontier_hash"]
                    for channel, frontier in frontiers.items()
                },
                max_p_matrix=max(matrix_probabilities) if matrix_probabilities else None,
                max_p_strict=max(strict_probabilities) if strict_probabilities else None,
                chosen_p=max(item["p_all"] for item in chosen),
                chosen=chosen,
                verdict_refs=[],
                supersedes=None,
                actor_id="operator:plan",
                actor_role=ActorRole.JUDGE_OPERATOR,
                idempotency_key=f"zcp:{issue}:{now.isoformat(timespec='microseconds')}",
                requested_at=now,
            )
        )
    except ValueError as exc:
        _fail(str(exc))
    if outcome.status is ActionStatus.REJECTED:
        _fail(f"权限拒绝：{outcome.error_detail}")
    with OntologyUnitOfWork(kernel.engine) as uow:
        plan = uow.capital.latest_plan(issue)
    gate_cost = "None" if plan.gate_cost_pp is None else f"{plan.gate_cost_pp:+.2f}pp"
    typer.echo(
        f"{issue} 定案 {plan.plan_id} · {cap_source} · 足彩帽 ¥{caps['total']}"
        f"（竞彩已登记 ¥{used}） · max P 矩阵/strict/所选 = "
        f"{plan.max_p_matrix}/{plan.max_p_strict}/{plan.chosen_p} · gate_cost {gate_cost}"
    )


@plan_app.command("status")
def status(issue: str = _ISSUE, data_dir: Path = _DATA_DIR) -> None:
    """Reconcile the capital plan with registered slips."""
    kernel = _kernel(data_dir)
    with OntologyUnitOfWork(kernel.engine) as uow:
        plan = uow.capital.latest_plan(issue)
    if plan is None:
        _fail(f"{issue} 没有资金方案")
    slips = _registered_slips(data_dir, issue)
    typer.echo(
        f"{issue} {plan.plan_id} · {plan.cap_source} · 帽 {plan.caps} · "
        f"gate_cost {plan.gate_cost_pp}"
    )
    for chosen in plan.chosen:
        matches = [
            slip for slip in slips.values() if slip.get("channel") == chosen["channel"]
        ]
        if not matches:
            typer.echo(
                f"  {chosen['channel']} {chosen['notes']}注 ¥{chosen['stake_yuan']}  "
                "未入账（没入账=没打）"
            )
            continue
        slip = matches[0]
        suffix = "" if slip.get("scheme_no") else " · 方案号待补"
        typer.echo(
            f"  {chosen['channel']} {chosen['notes']}注 ¥{chosen['stake_yuan']}  "
            f"✓ {slip['slip_id']}{suffix}"
        )
