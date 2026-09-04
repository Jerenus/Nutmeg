from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from nutmeg.config.settings import AppSettings
from nutmeg.interfaces.cli import app
from nutmeg.interfaces.cli import ontology as ontology_cli
from nutmeg.ontology.actions.artifact_ingest import ArtifactIngestRequest
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import MIGRATIONS, run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel
from nutmeg.product.operator_runtime import OntologyWriterLease, OperatorRuntimeError


def _production_settings(tmp_path: Path) -> AppSettings:
    production = (tmp_path / ".nutmeg-data").resolve()
    return AppSettings(
        _env_file=None,
        data_dir=production,
        production_data_dir=production,
    )


def _seed_pending_production(settings: AppSettings) -> None:
    settings.ontology_dir.mkdir(parents=True, exist_ok=True)
    engine = build_ontology_engine(settings.ontology_db_path)
    run_migrations(engine, MIGRATIONS[:-1])
    engine.dispose()


def test_plain_init_refuses_pending_production_migration(
    monkeypatch, tmp_path: Path
) -> None:
    settings = _production_settings(tmp_path)
    _seed_pending_production(settings)
    monkeypatch.setattr(ontology_cli._cli, "get_settings", lambda: settings)

    result = CliRunner().invoke(app, ["ontology", "init"])

    assert result.exit_code != 0
    assert "production_migration_requires_guarded_init" in result.output


def test_plain_init_remains_legal_for_fresh_isolated_database(
    monkeypatch, tmp_path: Path
) -> None:
    production = (tmp_path / "production").resolve()
    settings = AppSettings(
        _env_file=None,
        data_dir=(tmp_path / "isolated").resolve(),
        production_data_dir=production,
    )
    monkeypatch.setattr(ontology_cli._cli, "get_settings", lambda: settings)

    result = CliRunner().invoke(app, ["ontology", "init"])

    assert result.exit_code == 0
    assert settings.ontology_db_path.exists()


def test_guarded_init_refuses_writer_contention_before_creating_backup(
    monkeypatch, tmp_path: Path
) -> None:
    settings = _production_settings(tmp_path)
    _seed_pending_production(settings)
    backup = (settings.data_dir / "archive" / "before-v16.db").resolve()
    monkeypatch.setattr(ontology_cli._cli, "get_settings", lambda: settings)
    writer = OntologyWriterLease.shared(settings.data_dir)
    writer.acquire()
    try:
        result = CliRunner().invoke(
            app,
            [
                "ontology",
                "guarded-init",
                "--data-dir",
                str(settings.data_dir),
                "--backup-file",
                str(backup),
            ],
        )
    finally:
        writer.release()

    assert result.exit_code != 0
    assert "ontology_maintenance_conflict" in result.output
    assert not backup.exists()


def test_kernel_action_uow_participates_in_shared_writer_lease(tmp_path: Path) -> None:
    settings = AppSettings(
        _env_file=None,
        data_dir=(tmp_path / "isolated").resolve(),
        production_data_dir=(tmp_path / "production").resolve(),
    )
    kernel = build_ontology_kernel(settings)
    kernel.initialize()
    maintenance = OntologyWriterLease.exclusive(settings.data_dir)
    maintenance.acquire()
    try:
        try:
            kernel.artifact_ingest.ingest(
                ArtifactIngestRequest(
                    content=b"guarded-writer",
                    content_type="application/json",
                    source_name="fixture",
                    source_type="test",
                    actor_id="source:fixture",
                    actor_role=ActorRole.CONNECTOR,
                    idempotency_key="guarded-writer:blocked",
                    retrieved_at=datetime(2026, 9, 4, tzinfo=UTC),
                )
            )
        except OperatorRuntimeError as error:
            assert error.code == "ontology_maintenance_conflict"
        else:
            raise AssertionError("typed Action bypassed the maintenance writer lease")
    finally:
        maintenance.release()


def test_direct_uow_for_a_wired_kernel_uses_the_registered_writer_lease(
    tmp_path: Path,
) -> None:
    settings = AppSettings(
        _env_file=None,
        data_dir=(tmp_path / "isolated").resolve(),
        production_data_dir=(tmp_path / "production").resolve(),
    )
    kernel = build_ontology_kernel(settings)
    kernel.initialize()

    with OntologyUnitOfWork(kernel.engine):
        contender = OntologyWriterLease.exclusive(settings.data_dir)
        try:
            contender.acquire()
        except OperatorRuntimeError as error:
            assert error.code == "ontology_maintenance_conflict"
        else:
            contender.release()
            raise AssertionError("direct UOW bypassed the registered writer lease")


def test_guarded_init_holds_one_exclusive_lease_across_every_stage(
    tmp_path: Path,
) -> None:
    settings = _production_settings(tmp_path)
    _seed_pending_production(settings)
    backup = (settings.data_dir / "archive" / "before-v16.db").resolve()
    observed: list[str] = []

    def probe(stage: str) -> None:
        observed.append(stage)
        contender = OntologyWriterLease.shared(settings.data_dir)
        try:
            contender.acquire()
        except OperatorRuntimeError as error:
            assert error.code == "ontology_maintenance_conflict"
        else:
            contender.release()
            raise AssertionError(f"writer entered during guarded stage {stage}")

    report = ontology_cli.guarded_initialize(
        settings=settings,
        data_dir=settings.data_dir,
        backup_file=backup,
        stage_hook=probe,
    )

    assert observed == [
        "source_audited",
        "backup_created",
        "backup_audited",
        "migration_applied",
        "source_verified",
    ]
    assert report["schema_version"] == MIGRATIONS[-1].version
    assert report["backup_file"] == str(backup)
    assert report["lease"] == {
        "data_dir": str(settings.data_dir),
        "mode": "exclusive",
        "path": str(settings.data_dir / "state/ontology-writer.lock"),
    }
    assert report["applied_versions"] == [MIGRATIONS[-1].version]
    assert report["source_before"] == report["backup"]
    assert report["source_before"]["schema_version"] == MIGRATIONS[-2].version
    assert report["source_after"]["schema_version"] == MIGRATIONS[-1].version
    assert report["source_after"]["action_high_water"] == report["action_high_water"]
    assert len(report["backup_sha256"]) == 64
    assert set(report["backup_sha256"]) <= set("0123456789abcdef")
    assert backup.exists()
    with sqlite3.connect(backup) as connection:
        version = connection.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]
    assert version == MIGRATIONS[-2].version


def test_guarded_init_rejects_unsafe_targets_before_opening_source(tmp_path: Path) -> None:
    settings = _production_settings(tmp_path)
    _seed_pending_production(settings)

    for data_dir, backup, expected in (
        (Path("relative"), settings.data_dir / "archive/a.db", "absolute"),
        (settings.data_dir, Path("relative.db"), "absolute"),
        (settings.data_dir, tmp_path / "outside.db", "archive"),
        (tmp_path / "other", settings.data_dir / "archive/a.db", "production"),
    ):
        try:
            ontology_cli.guarded_initialize(
                settings=settings,
                data_dir=data_dir,
                backup_file=backup,
            )
        except ValueError as error:
            assert expected in str(error)
        else:
            raise AssertionError(f"unsafe target was accepted: {data_dir}, {backup}")
