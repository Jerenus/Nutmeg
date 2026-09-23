"""Discovery Harness CLI: read-only projections plus explicit shadow-store Actions.

Only `register-baseline` and `shadow-run` write, and only to a store outside the
production data directory. Every other command opens stores read-only.
"""

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
from nutmeg.discovery.day_inputs import read_structural_input_from_day
from nutmeg.discovery.iteration_contract import load_iteration_contract
from nutmeg.discovery.online_recorder import record_shadow_world
from nutmeg.discovery.readiness import assess_readiness
from nutmeg.ontology.actions.discovery_policy_actions import RegisterPolicyRevisionRequest
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.discovery.models import DiscoveryStatus
from nutmeg.ontology.discovery.read_service import DiscoveryReadService
from nutmeg.ontology.paths import OntologyPaths
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.discovery import PolicyRevisionRow

discovery_app = typer.Typer(
    help="Discovery Harness governed state (read-only views; shadow-store Actions are explicit)"
)
_cli.app.add_typer(discovery_app, name="discovery")
DATA_DIR_OPTION = typer.Option(Path(".nutmeg-data"), "--data-dir")
SOURCE_DAY_OPTION = typer.Option(
    ..., "--source-day", help="business day YYYY-MM-DD under <jczq-dir>/daily/ to freeze"
)
JCZQ_DIR_OPTION = typer.Option(Path(".nutmeg-data/jczq"), "--jczq-dir")
SHADOW_DB_OPTION = typer.Option(..., "--shadow-db")
CUTOFF_OPTION = typer.Option(..., "--cutoff-at")
APPROVAL_FILE_OPTION = typer.Option(..., "--approval-file")
BY_OPTION = typer.Option(..., "--by", help="human operator identity recorded as created_by")
REPO_ROOT = Path(__file__).resolve().parents[3]
PILOT_PATH = REPO_ROOT / "experiments/discovery/structural-candidate-v1.contract.json"
BASELINE_PATH = REPO_ROOT / "experiments/discovery/structural-baseline-v1.policy.json"
ITERATION_PATH = REPO_ROOT / "experiments/discovery/structural-iteration-v1.contract.json"
PRODUCTION_DATA_DIR = REPO_ROOT / ".nutmeg-data"


def _database(data_dir: Path) -> Path:
    return OntologyPaths.from_data_dir(data_dir.resolve()).database


def reject_production_store(database: Path) -> None:
    """Shadow-namespace writes may never target the production data directory."""
    resolved = database.resolve()
    production = PRODUCTION_DATA_DIR.resolve()
    if resolved == production or production in resolved.parents:
        raise ValueError(
            "shadow store may not live inside the production data directory "
            f"{production}; pass a separate --data-dir/--shadow-db"
        )


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
    if promotion and version < 43:
        typer.echo("discovery error: promotion unavailable; migration 43 required", err=True)
        raise typer.Exit(code=1)
    engine = create_engine("sqlite+pysqlite://", creator=lambda: sqlite3.connect(uri, uri=True))
    return DiscoveryReadService(engine)


@discovery_app.command("readiness")
def readiness(data_dir: Path = DATA_DIR_OPTION) -> None:
    database = _database(data_dir)
    if database.is_file():
        report = _read_service(database).readiness()
    else:
        pilot = load_pilot_contract(PILOT_PATH)
        report = assess_readiness((), pilot.readiness)
    typer.echo(json.dumps(asdict(report), ensure_ascii=False, sort_keys=True))


@discovery_app.command("register-baseline")
def register_baseline(by: str = BY_OPTION, data_dir: Path = DATA_DIR_OPTION) -> None:
    """Register the frozen D0 incumbent artifact in a non-production shadow store (human Action)."""
    try:
        if not by.strip():
            raise ValueError("--by requires a human operator identity")
        database = _database(data_dir)
        reject_production_store(database)
        pilot = load_pilot_contract(PILOT_PATH)
        baseline = load_baseline_policy(BASELINE_PATH)
        if (
            baseline.constraints_version != pilot.pilot_id
            or set(baseline.compatible_world_families) != {pilot.task_family}
            or {step.action for step in baseline.steps} - {"continue_batch", "stop"}
        ):
            raise ValueError("baseline artifact does not bind the frozen pilot contract")
        artifact = baseline.model_dump(mode="json")
        artifact_hash = canonical_hash(baseline)
        now = datetime.now(UTC)
        policy = PolicyRevisionRow(
            policy_revision_id=baseline.policy_revision_id,
            family=baseline.family,
            source_artifact_hash=artifact_hash,
            interface_version=baseline.interface_version,
            constraints_version=baseline.constraints_version,
            generator_family=baseline.generator_family,
            generator_revision="operator-authored-d0",
            generation_trace_hash=None,
            generator_descriptors={"source": "operator_authored_d0_incumbent"},
            generation_input_manifest_hash=canonical_hash(pilot),
            generation_budget={},
            generation_cost={},
            generation_timeout_seconds=0,
            rationale=baseline.rationale,
            change_summary="D0 frozen incumbent: bounded exhaustive shard enumeration then stop",
            configuration={"steps": artifact["steps"]},
            random_seed_policy=artifact["random_seed_policy"],
            compatible_world_families=list(baseline.compatible_world_families),
            max_resource_permissions={
                "max_nodes": pilot.budgets.max_nodes,
                "max_rounds": pilot.budgets.max_rounds,
                "max_concurrency": pilot.budgets.max_concurrency,
                "max_wall_seconds": pilot.budgets.max_wall_seconds,
            },
            change_surfaces=list(baseline.change_surfaces),
            novelty_descriptors={},
            validation_result={
                "valid": True,
                "checks": ["strict_schema", "pilot_binding", "closed_selectors"],
                "pilot_contract_hash": canonical_hash(pilot),
            },
            created_by=by,
            created_at=now.isoformat(),
            action_id="pending",
        )
        from nutmeg.config.settings import AppSettings

        kernel = _cli.build_ontology_kernel(AppSettings(data_dir=data_dir.resolve()))
        kernel.initialize()
        try:
            existing = _read_service(database).policy_lineage(baseline.policy_revision_id)
        except KeyError:
            existing = None
        if existing is not None:
            raise ValueError(
                f"policy revision already registered by {existing['policy']['created_by']} "
                f"with artifact {existing['policy']['source_artifact_hash']}"
            )
        outcome = kernel.discovery_policy_actions.register_policy(
            RegisterPolicyRevisionRequest(
                policy=policy,
                artifact=artifact,
                parent_policy_revision_ids=(),
                actor_id=by,
                actor_role=ActorRole.JUDGE_OPERATOR,
                idempotency_key=f"discovery:register:{baseline.policy_revision_id}:{artifact_hash}",
                requested_at=now,
            )
        )
        if outcome.status is not ActionStatus.COMMITTED:
            raise ValueError(f"registration {outcome.status.value}: {outcome.error_detail}")
    except (OSError, TypeError, ValueError) as exc:
        typer.echo(f"discovery error: {exc}", err=True)
        raise typer.Exit(code=1) from None
    typer.echo(
        json.dumps(
            {
                "policy_revision_id": baseline.policy_revision_id,
                "source_artifact_hash": artifact_hash,
                "action_id": outcome.action_id,
                "database": str(database),
            },
            sort_keys=True,
        )
    )


@discovery_app.command("shadow-run")
def shadow_run(
    source_day: str = SOURCE_DAY_OPTION,
    jczq_dir: Path = JCZQ_DIR_OPTION,
    shadow_db: Path = SHADOW_DB_OPTION,
    cutoff_at: str = CUTOFF_OPTION,
    approval_file: Path = APPROVAL_FILE_OPTION,
) -> None:
    """Record one separately approved, pre-registered baseline in a shadow store.

    The frozen input comes from the day source only: `--source-day` (the day's
    decision-lane files under `<jczq-dir>/daily/<day>/`).
    """
    if not approval_file.is_file():
        typer.echo("discovery error: separate approval file is required", err=True)
        raise typer.Exit(code=1)
    try:
        source: Path = jczq_dir / "daily" / source_day
        generation_request_id = f"day:{source_day}"
        approval = json.loads(approval_file.read_text(encoding="utf-8"))
        expected_scope = {
            "source_db": str(source.resolve()),
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
        if source.resolve() == shadow_db.resolve():
            raise ValueError("source and shadow stores must be distinct")
        reject_production_store(shadow_db)
        if not source.is_dir() or not shadow_db.is_file():
            raise ValueError("a pre-existing day directory and shadow database are required")
        service = _read_service(shadow_db)
        policy = service.policy_lineage("structural-baseline-v1")["policy"]
        baseline = load_baseline_policy(BASELINE_PATH)
        if (
            policy["source_artifact_hash"] != canonical_hash(baseline)
            or policy["created_by"] != approval["approved_by"]
            or not policy["validation_result"].get("valid")
        ):
            raise ValueError("approved baseline is not operator-registered")
        snapshot = read_structural_input_from_day(jczq_dir, source_day, cutoff_at=cutoff_at)
        engine = build_ontology_engine(shadow_db)
        try:
            result = record_shadow_world(
                snapshot,
                engine=engine,
                shadow_database=shadow_db,
                source_database=source,
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
            "latest_tournament_id": None,
            "latest_tournament_proof_hash": None,
            "shadow_windows": [],
            "scoped_deployments": [],
            "shadow_window_end": None,
            "shadow_effective_world_count": 0,
            "scope_hash": None,
            "scope_approval_ref": None,
            "effective_boundary": None,
            "rollback_target": None,
            "brake_conditions": None,
            "pending_shadow": False,
            "deployment": None,
            "brake": None,
            "control_available": False,
        }
    )
    typer.echo(json.dumps(state, ensure_ascii=False, sort_keys=True))


@discovery_app.command("iteration")
def iteration(
    policy_family: str = typer.Option("structural_candidate_exploration", "--family"),
    data_dir: Path = DATA_DIR_OPTION,
) -> None:
    """Show the proposed recursive-operation timeline without authorizing a cycle."""
    database = _database(data_dir)
    if database.is_file():
        state = _read_service(database, generation=True).iteration(policy_family)
    else:
        contract = load_iteration_contract(ITERATION_PATH, load_pilot_contract(PILOT_PATH))
        state = {
            "contract_status": contract.approval_status,
            "approval_ref": contract.approval_ref,
            "runtime_authority": False,
            "incumbent": None,
            "latest_tournament_id": None,
            "tournaments": [],
            "data_mode": "record_only",
            "raw_new_worlds": 0,
            "effective_new_clusters": 0,
            "excluded_duplicates": [],
            "trigger_blocks": ["no_store"]
            + (["contract_unapproved"] if contract.approval_status != "approved" else []),
            "exposed_holdout_ids": [],
            "protected_holdout_ids": [],
            "policy_lineage": {},
            "archive": {"active_ids": [], "capacity": 12},
            "drift": "unavailable",
            "pending_human_approval": contract.approval_status != "approved",
        }
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
