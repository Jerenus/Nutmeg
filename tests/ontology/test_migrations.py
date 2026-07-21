from pathlib import Path

import pytest
from sqlalchemy import inspect, select

from nutmeg.ontology.errors import MigrationDriftError
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import (
    MIGRATIONS,
    Migration,
    migration_status,
    run_migrations,
)
from nutmeg.ontology.repository.schema import action_permissions, policy_versions


def test_migrations_apply_once_and_seed_governance_policy(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    first = run_migrations(engine)
    second = run_migrations(engine)
    assert first.applied_versions == (1, 2)
    assert second.applied_versions == ()
    assert migration_status(engine).current_version == 2
    assert {"actions", "policy_versions", "action_permissions", "source_runs",
            "source_artifacts", "artifact_retrievals"} <= set(
                inspect(engine).get_table_names()
            )
    with engine.connect() as connection:
        assert connection.execute(select(policy_versions.c.policy_version_id)).scalar_one() == (
            "governance-v1"
        )
        rows = connection.execute(select(action_permissions)).mappings().all()
        assert ("ingest_artifact", "connector") in {
            (row["action_type"], row["actor_role"]) for row in rows
        }


def test_changed_fingerprint_is_rejected_as_migration_drift(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    original = MIGRATIONS[0]
    changed = Migration(
        version=original.version,
        name=original.name,
        fingerprint="changed-after-apply",
        apply=original.apply,
    )
    with pytest.raises(MigrationDriftError, match="migration 1 checksum drift"):
        run_migrations(engine, migrations=(changed, *MIGRATIONS[1:]))
