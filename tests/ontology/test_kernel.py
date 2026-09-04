from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.repository.migrations import MIGRATIONS
from nutmeg.ontology.wiring import build_ontology_kernel


def test_status_does_not_create_an_uninitialized_database(tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    kernel = build_ontology_kernel(settings)
    status = kernel.status()
    assert status.initialized is False
    assert status.schema_version == 0
    assert not settings.ontology_db_path.exists()


def test_initialize_is_idempotent_and_status_is_healthy(tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    kernel = build_ontology_kernel(settings)
    first = kernel.initialize()
    second = kernel.initialize()
    status = kernel.status()
    assert first.applied_versions == tuple(migration.version for migration in MIGRATIONS)
    assert second.applied_versions == ()
    assert status.initialized is True
    assert status.schema_version == MIGRATIONS[-1].version
    assert status.pending_migrations == ()
    assert status.integrity_check == "ok"
    assert status.action_counts == {}
    assert status.artifact_count == 0
    assert status.retrieval_count == 0
    assert settings.ontology_artifact_dir.is_dir()


def test_kernel_wires_operator_decisions_into_protected_ticket_actions(
    tmp_path: Path,
) -> None:
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))

    assert kernel.protected_tickets._operator_decisions is kernel.decision_actions
