from pathlib import Path

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

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
    first = run_migrations(engine, migrations=MIGRATIONS[:2])
    second = run_migrations(engine, migrations=MIGRATIONS[:2])
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


def test_schema_35_adds_historical_replay_authority_and_action_pair_guard(
    tmp_path: Path,
) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)

    assert migration_status(engine).current_version == 40
    assert "historical_replay_runs" in inspect(engine).get_table_names()
    action_columns = {
        column["name"] for column in inspect(engine).get_columns("actions")
    }
    assert {"historical_replay", "replay_run_id"} <= action_columns

    base_values = {
        "action_id": "ACT-invalid-replay-pair",
        "action_type": "ingest_artifact",
        "actor_id": "source:test",
        "actor_role": "connector",
        "requested_at": "2026-09-20T00:00:00+00:00",
        "idempotency_key": "invalid-replay-pair",
        "request_hash": "0" * 64,
        "expected_versions_json": "{}",
        "payload_json": "{}",
        "policy_version": "governance-v1",
        "status": "accepted",
        "result_refs_json": "[]",
    }
    with pytest.raises(IntegrityError, match="historical replay provenance pair"):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO actions ("
                    "action_id, action_type, actor_id, actor_role, requested_at, "
                    "idempotency_key, request_hash, expected_versions_json, payload_json, "
                    "policy_version, status, result_refs_json, historical_replay, replay_run_id"
                    ") VALUES ("
                    ":action_id, :action_type, :actor_id, :actor_role, :requested_at, "
                    ":idempotency_key, :request_hash, :expected_versions_json, :payload_json, "
                    ":policy_version, :status, :result_refs_json, 1, NULL)"
                ),
                base_values,
            )
