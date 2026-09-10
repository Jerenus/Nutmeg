from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import OperationalError

from nutmeg.ontology.errors import MigrationDriftError
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import MIGRATIONS, migration_status, run_migrations

LEGACY_SCHEMA_19_CHECKSUM = (
    "0f9b22848b47a447e1a18edf03a5eed3a33af4d968c5031c5b7c443307cbe964"
)
CURRENT_SCHEMA_19_CHECKSUM = (
    "b77216c4f5f250bd5dd2b2e240c31bb0fb262a5664192f37d205604b57e37673"
)

V19_TABLES = (
    "operator_evidence_freeze_requests",
    "operator_task_evidence_bundle_revisions",
    "operator_task_evidence_bundle_items",
    "operator_worker_jobs",
)
LEGACY_V19_TRIGGERS = frozenset(
    {
        "operator_worker_job_immutable_source",
        "operator_worker_job_terminal_immutable",
        "task_evidence_bundle_linear_child",
        "task_evidence_bundle_root_revision_no",
        "task_evidence_bundle_single_root",
    }
)
MISSING_V19_TRIGGERS = frozenset(
    {
        "operator_evidence_freeze_request_action",
        "operator_evidence_freeze_request_no_delete",
        "operator_evidence_freeze_request_no_update",
        "operator_worker_job_evidence_freeze_result_insert",
        "operator_worker_job_evidence_freeze_result_update",
        "operator_worker_job_terminal_no_delete",
        "task_evidence_bundle_counts_match_items",
        "task_evidence_bundle_item_after_finalize",
        "task_evidence_bundle_item_freeze_action",
        "task_evidence_bundle_item_no_delete",
        "task_evidence_bundle_item_no_update",
        "task_evidence_bundle_revision_no_delete",
        "task_evidence_bundle_revision_no_update",
    }
)
LATER_WORKER_TRIGGERS = frozenset(
    {
        "operator_candidate_generation_job_source",
        "operator_review_worker_job_source",
        "operator_review_worker_result_insert",
        "operator_review_worker_result_update",
        "operator_scoreboard_completion_worker_job_source",
        "operator_worker_job_candidate_result_insert",
        "operator_worker_job_candidate_result_update",
        "operator_worker_job_market_baseline_result_insert",
        "operator_worker_job_market_baseline_result_update",
    }
)

CURRENT_RESULT_CHECK = (
    "CONSTRAINT ck_operator_worker_job_result_ref CHECK "
    "((state = 'completed' AND result_action_id IS NOT NULL "
    "AND result_object_type IS NOT NULL AND result_object_id IS NOT NULL) "
    "OR (state != 'completed' AND result_action_id IS NULL "
    "AND result_object_type IS NULL AND result_object_id IS NULL))"
)
LEGACY_RESULT_CHECK = (
    "CONSTRAINT ck_operator_worker_job_result_ref CHECK "
    "((result_object_type IS NULL) = (result_object_id IS NULL))"
)


def _table_sql(connection: Connection, table_name: str) -> str:
    return str(
        connection.execute(
            text(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'table' AND name = :table_name"
            ),
            {"table_name": table_name},
        ).scalar_one()
    )


def _trigger_sql(connection: Connection, trigger_name: str) -> str:
    value = connection.execute(
        text(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'trigger' AND name = :trigger_name"
        ),
        {"trigger_name": trigger_name},
    ).scalar_one()
    return " ".join(str(value).split())


def _replace_empty_table(
    connection: Connection,
    table_name: str,
    transform: Callable[[str], str],
) -> None:
    table_sql = _table_sql(connection, table_name)
    index_sql = tuple(
        str(value)
        for value in connection.execute(
            text(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'index' AND tbl_name = :table_name AND sql IS NOT NULL "
                "ORDER BY name"
            ),
            {"table_name": table_name},
        ).scalars()
    )
    trigger_sql = tuple(
        str(value)
        for value in connection.execute(
            text(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'trigger' AND tbl_name = :table_name "
                "ORDER BY name"
            ),
            {"table_name": table_name},
        ).scalars()
    )
    connection.exec_driver_sql(f"DROP TABLE {table_name}")
    connection.exec_driver_sql(transform(table_sql))
    for statement in (*index_sql, *trigger_sql):
        connection.exec_driver_sql(statement)


def _legacy_item_sql(current: str) -> str:
    marker = " ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED"
    assert current.count(marker) == 1
    return current.replace(marker, " ON DELETE RESTRICT")


def _legacy_worker_sql(current: str) -> str:
    assert current.count(CURRENT_RESULT_CHECK) == 1
    return current.replace(CURRENT_RESULT_CHECK, LEGACY_RESULT_CHECK)


def _v19_trigger_names(connection: Connection) -> frozenset[str]:
    rows = connection.execute(
        text(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'trigger' AND tbl_name IN "
            "('operator_evidence_freeze_requests', "
            "'operator_task_evidence_bundle_revisions', "
            "'operator_task_evidence_bundle_items', 'operator_worker_jobs')"
        )
    ).scalars()
    return frozenset(str(row) for row in rows)


def _legacy_v19_engine(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine, MIGRATIONS[:19])
    with engine.begin() as connection:
        for trigger_name in sorted(MISSING_V19_TRIGGERS):
            connection.exec_driver_sql(f"DROP TRIGGER {trigger_name}")
        _replace_empty_table(
            connection,
            "operator_task_evidence_bundle_items",
            _legacy_item_sql,
        )
        _replace_empty_table(
            connection,
            "operator_worker_jobs",
            _legacy_worker_sql,
        )
        connection.execute(
            text(
                "UPDATE schema_migrations SET checksum = :checksum "
                "WHERE version = 19"
            ),
            {"checksum": LEGACY_SCHEMA_19_CHECKSUM},
        )
        assert _v19_trigger_names(connection) == LEGACY_V19_TRIGGERS
    return engine


def test_exact_legacy_schema_19_upgrades_atomically_through_repair_migration(
    tmp_path: Path,
) -> None:
    engine = _legacy_v19_engine(tmp_path)
    canonical_engine = build_ontology_engine(tmp_path / "canonical.db")
    run_migrations(canonical_engine, MIGRATIONS[:19])

    report = run_migrations(engine, MIGRATIONS)

    assert MIGRATIONS[18].checksum == CURRENT_SCHEMA_19_CHECKSUM
    head_version = MIGRATIONS[-1].version
    assert report.applied_versions == tuple(range(20, head_version + 1))
    assert migration_status(engine).current_version == head_version
    with engine.connect() as connection:
        checksum = connection.execute(
            text("SELECT checksum FROM schema_migrations WHERE version = 19")
        ).scalar_one()
        assert checksum == CURRENT_SCHEMA_19_CHECKSUM
        trigger_names = _v19_trigger_names(connection)
        assert trigger_names >= LEGACY_V19_TRIGGERS | MISSING_V19_TRIGGERS
        assert trigger_names >= LATER_WORKER_TRIGGERS
        assert "DEFERRABLE INITIALLY DEFERRED" in _table_sql(
            connection,
            "operator_task_evidence_bundle_items",
        )
        worker_sql = _table_sql(connection, "operator_worker_jobs")
        assert CURRENT_RESULT_CHECK in worker_sql
        assert LEGACY_RESULT_CHECK not in worker_sql
        assert connection.execute(
            text(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type = 'table' AND name GLOB '_legacy_v19*'"
            )
        ).scalar_one() == 0
        with canonical_engine.connect() as canonical:
            for trigger_name in MISSING_V19_TRIGGERS:
                assert _trigger_sql(connection, trigger_name) == _trigger_sql(
                    canonical,
                    trigger_name,
                )

    assert run_migrations(engine, MIGRATIONS).applied_versions == ()


def test_legacy_schema_19_checksum_near_miss_is_rejected(tmp_path: Path) -> None:
    engine = _legacy_v19_engine(tmp_path)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE schema_migrations SET checksum = :checksum WHERE version = 19"),
            {"checksum": f"{LEGACY_SCHEMA_19_CHECKSUM[:-1]}0"},
        )

    with pytest.raises(MigrationDriftError, match="migration 19 checksum drift"):
        run_migrations(engine, MIGRATIONS)

    assert migration_status(engine).current_version == 19


@pytest.mark.parametrize("near_miss", ("missing_present", "extra_missing"))
def test_legacy_schema_19_trigger_shape_near_miss_is_rejected(
    tmp_path: Path,
    near_miss: str,
) -> None:
    engine = _legacy_v19_engine(tmp_path)
    with engine.begin() as connection:
        if near_miss == "missing_present":
            connection.exec_driver_sql("DROP TRIGGER task_evidence_bundle_single_root")
        else:
            connection.exec_driver_sql(
                "CREATE TRIGGER operator_evidence_freeze_request_action "
                "BEFORE INSERT ON operator_evidence_freeze_requests BEGIN SELECT 1; END"
            )

    with pytest.raises(MigrationDriftError, match="migration 19 checksum drift"):
        run_migrations(engine, MIGRATIONS)

    assert migration_status(engine).current_version == 19


def test_legacy_schema_19_table_shape_near_miss_is_rejected(tmp_path: Path) -> None:
    engine = _legacy_v19_engine(tmp_path)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE operator_evidence_freeze_requests ADD COLUMN unexpected TEXT"
        )

    with pytest.raises(MigrationDriftError, match="migration 19 checksum drift"):
        run_migrations(engine, MIGRATIONS)

    assert migration_status(engine).current_version == 19


def test_legacy_schema_19_extra_policy_permission_is_rejected(tmp_path: Path) -> None:
    engine = _legacy_v19_engine(tmp_path)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO policy_versions "
                "(policy_version_id, policy_kind, version, payload_json, status, "
                "effective_at, created_at) VALUES "
                "('legacy-extra', 'legacy-extra', 1, '{}', 'active', "
                "'2026-09-05T00:00:00+00:00', '2026-09-05T00:00:00+00:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO action_permissions "
                "(policy_version_id, action_type, actor_role) VALUES "
                "('legacy-extra', 'request_evidence_freeze', 'judge_operator')"
            )
        )

    with pytest.raises(MigrationDriftError, match="migration 19 checksum drift"):
        run_migrations(engine, MIGRATIONS)

    assert migration_status(engine).current_version == 19


def test_nonempty_legacy_schema_19_is_rejected(tmp_path: Path) -> None:
    engine = _legacy_v19_engine(tmp_path)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO operator_worker_jobs "
                "(worker_job_id, job_kind, source_object_type, source_object_id, state, "
                "attempt_count, available_at, created_at, updated_at) VALUES "
                "('legacy-job', 'evidence_freeze', 'legacy', 'legacy', 'queued', 0, "
                "'2026-09-05T00:00:00+00:00', '2026-09-05T00:00:00+00:00', "
                "'2026-09-05T00:00:00+00:00')"
            )
        )

    with pytest.raises(MigrationDriftError, match="migration 19 checksum drift"):
        run_migrations(engine, MIGRATIONS)

    assert migration_status(engine).current_version == 19


def test_legacy_schema_19_normalization_rolls_back_if_later_migration_fails(
    tmp_path: Path,
) -> None:
    engine = _legacy_v19_engine(tmp_path)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE operator_market_prior_baseline_revisions (collision TEXT)"
        )

    with pytest.raises(OperationalError, match="already exists"):
        run_migrations(engine, MIGRATIONS)

    with engine.connect() as connection:
        checksum = connection.execute(
            text("SELECT checksum FROM schema_migrations WHERE version = 19")
        ).scalar_one()
        assert checksum == LEGACY_SCHEMA_19_CHECKSUM
        assert connection.execute(
            text(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type = 'table' AND name GLOB '_legacy_v19*'"
            )
        ).scalar_one() == 0
    assert migration_status(engine).current_version == 19


def test_repair_migration_is_idempotent_on_current_schema(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine, MIGRATIONS)
    migration_26 = MIGRATIONS[25]
    assert migration_26.version == 26
    with engine.begin() as connection:
        before = {
            table_name: _table_sql(connection, table_name) for table_name in V19_TABLES
        }
        migration_26.apply(connection)
        migration_26.apply(connection)
        after = {
            table_name: _table_sql(connection, table_name) for table_name in V19_TABLES
        }
    assert after == before
