"""Read-only Discovery Harness status and durable object detail commands."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import typer
from sqlalchemy import create_engine

import nutmeg.interfaces.cli as _cli
from nutmeg.discovery.contracts import (
    canonical_hash,
    load_baseline_policy,
    load_pilot_contract,
)
from nutmeg.discovery.online_inputs import read_structural_input_from_database
from nutmeg.discovery.online_recorder import record_shadow_world
from nutmeg.discovery.readiness import assess_readiness
from nutmeg.ontology.discovery.models import DiscoveryStatus
from nutmeg.ontology.discovery.read_service import DiscoveryReadService
from nutmeg.ontology.paths import OntologyPaths
from nutmeg.ontology.repository.connection import build_ontology_engine

discovery_app = typer.Typer(help="Discovery Harness governed state (read-only)")
_cli.app.add_typer(discovery_app, name="discovery")
DATA_DIR_OPTION = typer.Option(Path(".nutmeg-data"), "--data-dir")
SOURCE_DB_OPTION = typer.Option(..., "--source-db")
SHADOW_DB_OPTION = typer.Option(..., "--shadow-db")
GENERATION_REQUEST_OPTION = typer.Option(..., "--generation-request-id")
CUTOFF_OPTION = typer.Option(..., "--cutoff-at")
APPROVAL_FILE_OPTION = typer.Option(..., "--approval-file")


def _database(data_dir: Path) -> Path:
    return OntologyPaths.from_data_dir(data_dir.resolve()).database


def _read_service(
    database: Path, *, generation: bool = False, promotion: bool = False
) -> DiscoveryReadService:
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
    if generation and version < 41:
        typer.echo("discovery error: generation unavailable; migration 41 required", err=True)
        raise typer.Exit(code=1)
    if promotion and version < 42:
        typer.echo("discovery error: promotion unavailable; migration 42 required", err=True)
        raise typer.Exit(code=1)
    engine = create_engine("sqlite+pysqlite://", creator=lambda: sqlite3.connect(uri, uri=True))
    return DiscoveryReadService(engine)


@discovery_app.command("readiness")
def readiness(data_dir: Path = DATA_DIR_OPTION) -> None:
    database = _database(data_dir)
    if database.is_file():
        report = _read_service(database).readiness()
    else:
        pilot = load_pilot_contract(
            Path(__file__).resolve().parents[3]
            / "experiments/discovery/structural-candidate-v1.contract.json"
        )
        report = assess_readiness((), pilot.readiness)
    typer.echo(json.dumps(asdict(report), ensure_ascii=False, sort_keys=True))


@discovery_app.command("shadow-run")
def shadow_run(
    source_db: Path = SOURCE_DB_OPTION,
    shadow_db: Path = SHADOW_DB_OPTION,
    generation_request_id: str = GENERATION_REQUEST_OPTION,
    cutoff_at: str = CUTOFF_OPTION,
    approval_file: Path = APPROVAL_FILE_OPTION,
) -> None:
    """Record one separately approved, pre-registered baseline in a shadow store."""
    if not approval_file.is_file():
        typer.echo("discovery error: separate approval file is required", err=True)
        raise typer.Exit(code=1)
    try:
        approval = json.loads(approval_file.read_text(encoding="utf-8"))
        expected_scope = {
            "source_db": str(source_db.resolve()),
            "shadow_db": str(shadow_db.resolve()),
            "generation_request_id": generation_request_id,
            "cutoff_at": cutoff_at,
            "policy_revision_id": "structural-baseline-v1",
        }
        if (
            approval["scope"] != expected_scope
            or not approval["approval_id"]
            or not approval["approved_by"]
        ):
            raise ValueError("approval scope or identity mismatch")
        approved_at = datetime.fromisoformat(approval["approved_at"])
        cutoff = datetime.fromisoformat(cutoff_at)
        if (
            approved_at.tzinfo is None
            or cutoff.tzinfo is None
            or approved_at > cutoff
            or cutoff > datetime.now(UTC)
        ):
            raise ValueError("approval and cutoff must be prospective and timezone-aware")
        if datetime.now(UTC) - cutoff > timedelta(hours=24):
            raise ValueError("prospective cutoff expired; historical backfill is forbidden")
        if source_db.resolve() == shadow_db.resolve():
            raise ValueError("source and shadow stores must be distinct")
        if not source_db.is_file() or not shadow_db.is_file():
            raise ValueError("both pre-existing databases are required")
        service = _read_service(shadow_db)
        policy = service.policy_lineage("structural-baseline-v1")["policy"]
        baseline = load_baseline_policy(
            Path(__file__).resolve().parents[3]
            / "experiments/discovery/structural-baseline-v1.policy.json"
        )
        if (
            policy["source_artifact_hash"] != canonical_hash(baseline)
            or policy["created_by"] != approval["approved_by"]
            or not policy["validation_result"].get("valid")
        ):
            raise ValueError("approved baseline is not operator-registered")
        snapshot = read_structural_input_from_database(
            source_db, generation_request_id, cutoff_at=cutoff_at
        )
        engine = build_ontology_engine(shadow_db)
        try:
            result = record_shadow_world(
                snapshot,
                engine=engine,
                shadow_database=shadow_db,
                source_database=source_db,
                policy_revision_id="structural-baseline-v1",
                generation_request_id=generation_request_id,
                requested_at=datetime.now(UTC),
                approval=approval,
            )
        finally:
            engine.dispose()
    except (KeyError, OSError, TypeError, ValueError) as exc:
        typer.echo(f"discovery error: {exc}", err=True)
        raise typer.Exit(code=1) from None
    typer.echo(
        json.dumps(
            {
                "world_id": result.world_id,
                "sealed_manifest_hash": result.sealed_manifest_hash,
                "approval_id": approval["approval_id"],
            },
            sort_keys=True,
        )
    )


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


@discovery_app.command("promotion")
def promotion(
    policy_family: str = typer.Option("structural_candidate_exploration", "--family"),
    data_dir: Path = DATA_DIR_OPTION,
) -> None:
    database = _database(data_dir)
    state = (
        _read_service(database, promotion=True).promotion(policy_family)
        if database.is_file()
        else {
            "incumbent": None,
            "replay_winner": None,
            "shadow_windows": [],
            "deployment": None,
            "brake": None,
            "control_available": False,
        }
    )
    typer.echo(json.dumps(state, ensure_ascii=False, sort_keys=True))


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
        "generation": "generation_detail",
    }
    if kind not in readers:
        typer.echo(
            "discovery error: kind must be world, policy, tournament, or generation", err=True
        )
        raise typer.Exit(code=1)
    database = _database(data_dir)
    if not database.is_file():
        typer.echo(f"discovery error: {kind} {object_id} not found", err=True)
        raise typer.Exit(code=1)
    service = _read_service(database, generation=kind in {"generation", "policy"})
    try:
        payload = getattr(service, readers[kind])(object_id)
    except KeyError:
        typer.echo(f"discovery error: {kind} {object_id} not found", err=True)
        raise typer.Exit(code=1) from None
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
