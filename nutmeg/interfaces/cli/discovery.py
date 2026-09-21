"""Read-only Discovery Harness status and durable object detail commands."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from urllib.parse import quote

import typer
from sqlalchemy import create_engine

import nutmeg.interfaces.cli as _cli
from nutmeg.ontology.discovery.models import DiscoveryStatus
from nutmeg.ontology.discovery.read_service import DiscoveryReadService
from nutmeg.ontology.paths import OntologyPaths

discovery_app = typer.Typer(help="Discovery Harness governed state (read-only)")
_cli.app.add_typer(discovery_app, name="discovery")
DATA_DIR_OPTION = typer.Option(Path(".nutmeg-data"), "--data-dir")


def _database(data_dir: Path) -> Path:
    return OntologyPaths.from_data_dir(data_dir.resolve()).database


def _read_service(database: Path) -> DiscoveryReadService:
    uri = f"file:{quote(str(database), safe='/')}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        try:
            version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        except sqlite3.OperationalError:
            version = None
    if version is None or version < 40:
        typer.echo(
            "discovery error: ontology schema 40 is required; run the approved migration", err=True
        )
        raise typer.Exit(code=1)
    engine = create_engine("sqlite+pysqlite://", creator=lambda: sqlite3.connect(uri, uri=True))
    return DiscoveryReadService(engine)


@discovery_app.command("status")
def status(
    policy_family: str = typer.Option("structural_candidate_exploration", "--family"),
    data_dir: Path = DATA_DIR_OPTION,
) -> None:
    database = _database(data_dir)
    state = (
        _read_service(database).status(policy_family)
        if database.is_file()
        else DiscoveryStatus(None, None, None, None, 0, 0, None)
    )
    typer.echo(f"incumbent: {state.incumbent_policy_revision_id or 'none'}")
    typer.echo(f"deployment: {state.active_deployment_state or 'none'}")
    typer.echo(f"latest tournament: {state.latest_tournament_id or 'none'}")
    typer.echo(f"latest world: {state.latest_world_id or 'none'}")
    typer.echo(f"sealed worlds: {state.sealed_world_count}")
    typer.echo(f"exposed holdouts: {state.exposed_holdout_count}")
    typer.echo(f"rollback: {state.rollback_policy_revision_id or 'none'}")


@discovery_app.command("show")
def show(
    kind: str = typer.Option(..., "--kind"),
    object_id: str = typer.Option(..., "--id"),
    data_dir: Path = DATA_DIR_OPTION,
) -> None:
    readers = {
        "world": "world_detail",
        "policy": "policy_lineage",
        "tournament": "tournament_detail",
    }
    if kind not in readers:
        typer.echo("discovery error: kind must be world, policy, or tournament", err=True)
        raise typer.Exit(code=1)
    database = _database(data_dir)
    if not database.is_file():
        typer.echo(f"discovery error: {kind} {object_id} not found", err=True)
        raise typer.Exit(code=1)
    service = _read_service(database)
    try:
        payload = getattr(service, readers[kind])(object_id)
    except KeyError:
        typer.echo(f"discovery error: {kind} {object_id} not found", err=True)
        raise typer.Exit(code=1) from None
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
