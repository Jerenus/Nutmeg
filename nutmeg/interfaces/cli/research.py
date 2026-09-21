"""CLI for the JCZQ board research bridge."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import typer

import nutmeg.interfaces.cli as _cli
from nutmeg.decision.research_runner import _claude_cli as _claude
from nutmeg.decision.research_runner import _cli_fulfill as _fulfill

research_app = typer.Typer(help="竞彩全板深研桥（headless）")
_cli.app.add_typer(research_app, name="research")
_DAY = typer.Option(..., "--day")
_JCZQ_DIR = typer.Option(Path(".nutmeg-data/jczq"), "--jczq-dir")
_DATA_DIR = typer.Option(Path(".nutmeg-data"), "--data-dir")


def _board_matches(day: str, data_dir: Path) -> list[dict]:
    from nutmeg.config.settings import AppSettings
    from nutmeg.ontology import build_ontology_kernel
    from nutmeg.ontology.identity.models import EntityType
    from nutmeg.ontology.ingest.sporttery import parse_sporttery_markets
    from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
    from nutmeg.product.repository import ProductReadRepository

    data_dir = Path(data_dir).resolve()
    kernel = build_ontology_kernel(AppSettings(data_dir=data_dir))
    kernel.initialize()
    market_path = data_dir / "jczq" / "daily" / day / "sporttery_markets.json"
    market_doc = json.loads(market_path.read_text(encoding="utf-8"))
    code_by_match: dict[str, str] = {}
    with OntologyUnitOfWork(kernel.engine) as uow:
        for parsed in parse_sporttery_markets(market_doc, business_date=day):
            match_id = uow.identity.entity_by_external_id(
                EntityType.MATCH,
                provider=parsed.provider,
                external_id=parsed.external_id,
            )
            if match_id:
                code_by_match[match_id] = parsed.match_no

    start = datetime.fromisoformat(f"{day}T00:00:00+08:00").astimezone(UTC)
    rows = ProductReadRepository(kernel.engine, kernel.paths.analytics).board_matches(
        start.isoformat(),
        (start + timedelta(days=2)).isoformat(),
        as_of=datetime.now(UTC).isoformat(),
    )
    return [
        {**row, "board_code": code_by_match[row["match_id"]]}
        for row in rows
        if row["match_id"] in code_by_match
    ]


def _profile_lookup(jczq_dir: Path, day: str):
    from nutmeg.decision.entities import profiles_for_board
    from nutmeg.decision.store import DecisionStore

    board = json.loads(
        (Path(jczq_dir) / "daily" / day / "jczq-legs-base.json").read_text(
            encoding="utf-8"
        )
    )
    legs = list(board["legs"].values())
    teams = [team for leg in legs for team in (leg.get("home_team"), leg.get("away_team")) if team]
    profiles = profiles_for_board(
        DecisionStore(Path(jczq_dir) / "decision"),
        [str(leg.get("competition") or "") for leg in legs],
        teams,
    )
    notes_by_name = {
        item["board_name"]: "；".join(
            str(note.get("note") or "") for note in item.get("profile_notes") or []
        )
        for item in profiles["teams"]
    }
    by_match = {
        leg["match_id"]: {
            "home": notes_by_name.get(leg.get("home_team"), ""),
            "away": notes_by_name.get(leg.get("away_team"), ""),
        }
        for leg in legs
    }
    return lambda match_id: by_match.get(match_id, {})


@research_app.command("board")
def board(
    day: str = _DAY,
    jczq_dir: Path = _JCZQ_DIR,
    data_dir: Path = _DATA_DIR,
) -> None:
    from nutmeg.decision.jczq_board import build_board_legs

    doc = build_board_legs(day=day, matches=_board_matches(day, data_dir), jczq_dir=jczq_dir)
    typer.echo(f"{day} 板面 {len(doc['legs'])} 场 → jczq-legs-base.json（price_only）")


@research_app.command("run")
def run(
    day: str = _DAY,
    jczq_dir: Path = _JCZQ_DIR,
    data_dir: Path = _DATA_DIR,
    code: str | None = typer.Option(None, "--code"),
    budget: int | None = typer.Option(None, "--budget"),
    concurrency: int = typer.Option(2, "--concurrency", min=1),
) -> None:
    from nutmeg.decision.research_runner import RESEARCH_DAILY_BUDGET, run_day

    report = run_day(
        day=day,
        jczq_dir=jczq_dir,
        data_dir=data_dir,
        claude=_claude,
        fulfill=_fulfill,
        profile=_profile_lookup(jczq_dir, day),
        budget=budget if budget is not None else RESEARCH_DAILY_BUDGET,
        code=code,
        concurrency=concurrency,
    )
    for row in report["matches"]:
        suffix = f" {row['seconds']}s" if "seconds" in row else ""
        typer.echo(f"  {row['code']} {row['status']}{suffix}")
    typer.echo(
        f"used_attempts={report['used_attempts']} written={report['written']}"
    )


@research_app.command("intake")
def intake(
    day: str = _DAY,
    jczq_dir: Path = _JCZQ_DIR,
    write: bool = typer.Option(False, "--write"),
) -> None:
    from nutmeg.decision.jczq_reads import intake_board

    report = intake_board(day=day, jczq_dir=jczq_dir, write=write)
    suffix = "" if write else "（预演，未写）"
    typer.echo(f"入库 {len(report['ok'])} 场: {' '.join(report['ok'])}{suffix}")
    for code, messages in report["failed"].items():
        typer.echo(f"  ✗ {code}: {'; '.join(messages)}")


@_cli.app.command("jczq-build-reads")
def jczq_build_reads(
    day: str = _DAY,
    jczq_dir: Path = _JCZQ_DIR,
    made_at: str | None = typer.Option(None, "--made-at"),
) -> None:
    from nutmeg.decision.jczq_reads import build_jczq_reads

    reads = build_jczq_reads(
        day=day,
        jczq_dir=jczq_dir,
        made_at=made_at or datetime.now().astimezone().isoformat(timespec="seconds"),
    )
    typer.echo(
        f"{day} 草稿 Read {len(reads)} 条 → daily/{day}/reads.json"
        "（下一步 decision-read --reads-file）"
    )
