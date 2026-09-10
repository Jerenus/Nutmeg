from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import (
    MIGRATIONS,
    migration_status,
    run_migrations,
)
from nutmeg.ontology.repository.operator_decision import OperatorDecisionRepository

AT = "2026-09-04T08:00:00+00:00"

REVISION_INSERT = text(
    "INSERT INTO operator_task_evidence_bundle_revisions "
    "(task_evidence_bundle_revision_id, task_family_id, lane, business_key, revision_no, "
    "evidence_freeze_request_id, link_action_id, slate_revision_id, task_snapshot_hash, "
    "requirement_revision_token, information_cutoff_at, policy_version, "
    "dependency_fingerprint, required_match_count, bundle_count, item_count, "
    "conflicts_cleared_count, content_hash, frozen_at, supersedes_revision_id) VALUES "
    "(:revision_id, 'zucai:26116', 'zucai', '26116', :revision_no, :request_id, "
    ":link_action_id, 'slate-1', :task_snapshot_hash, :requirement_revision_token, :at, "
    "'governance-v1', :dependency_fingerprint, :declared_count, :declared_count, "
    ":declared_count, 0, :content_hash, :at, :supersedes_revision_id)"
)

ITEM_INSERT = text(
    "INSERT INTO operator_task_evidence_bundle_items "
    "(task_evidence_bundle_item_id, task_evidence_bundle_revision_id, item_index, match_id, "
    "evidence_bundle_id, freeze_bundle_action_id, requirement_states_json, "
    "requirement_ref_tokens_json, market_prior_ref_tokens_json, "
    "conflicts_cleared_ref_tokens_json, content_hash) VALUES "
    "(:item_id, :revision_id, :item_index, :match_id, :evidence_bundle_id, :freeze_action_id, "
    "'{}', '[]', '[]', '[]', :content_hash)"
)

JOB_INSERT = text(
    "INSERT INTO operator_worker_jobs "
    "(worker_job_id, job_kind, source_object_type, source_object_id, state, lease_owner, "
    "lease_expires_at, attempt_count, available_at, last_error_code, result_action_id, "
    "result_object_type, result_object_id, created_at, updated_at) VALUES "
    "(:worker_job_id, :job_kind, :source_object_type, :source_object_id, :state, "
    ":lease_owner, :lease_expires_at, :attempt_count, :available_at, :last_error_code, "
    ":result_action_id, :result_object_type, :result_object_id, :created_at, :updated_at)"
)


def _initialize(path: Path, *, from_version: int | None = None):
    engine = build_ontology_engine(path)
    if from_version is not None:
        run_migrations(engine, MIGRATIONS[:from_version])
    run_migrations(engine, MIGRATIONS[:19])
    return engine


def _insert_action(
    connection,
    suffix: str,
    action_type: str,
    role: str,
    *,
    status: str = "committed",
    result_object_id: str | None = None,
) -> None:
    result_refs = (
        "[]"
        if result_object_id is None
        else (
            '[{"object_id":"'
            + result_object_id
            + '","object_type":"evidence_bundle"}]'
        )
    )
    connection.execute(
        text(
            "INSERT INTO actions "
            "(action_id, action_type, actor_id, actor_role, requested_at, idempotency_key, "
            "request_hash, expected_versions_json, payload_json, policy_version, status, "
            "result_refs_json, committed_at) VALUES "
            "(:action_id, :action_type, 'fixture', :role, :at, :key, :hash, '{}', '{}', "
            "'governance-v1', :status, :result_refs, :committed_at)"
        ),
        {
            "action_id": f"ACT-{suffix}",
            "action_type": action_type,
            "role": role,
            "status": status,
            "at": AT,
            "key": f"freeze-migration:{suffix}",
            "hash": (suffix * 64)[:64],
            "committed_at": AT if status == "committed" else None,
            "result_refs": result_refs,
        },
    )


def _seed_revision_dependencies(connection) -> None:
    connection.execute(
        text(
            "INSERT INTO source_runs "
            "(source_run_id, source_name, source_type, started_at, finished_at, status) "
            "VALUES ('run-1', 'sporttery', 'official_sale_schedule', :at, :at, 'succeeded')"
        ),
        {"at": AT},
    )
    connection.execute(
        text(
            "INSERT INTO source_artifacts "
            "(artifact_id, first_recorded_at, content_type, storage_path, byte_size, "
            "content_hash) VALUES ('artifact-1', :at, 'application/json', "
            "'sha256/freeze-migration', 2, :hash)"
        ),
        {"at": AT, "hash": "f" * 64},
    )
    connection.execute(
        text(
            "INSERT INTO artifact_retrievals "
            "(artifact_retrieval_id, artifact_id, source_run_id, source_name, source_type, "
            "reported_content_type, retrieved_at, status) VALUES "
            "('retrieval-1', 'artifact-1', 'run-1', 'sporttery', "
            "'official_sale_schedule', 'application/json', :at, 'stored')"
        ),
        {"at": AT},
    )
    connection.execute(
        text(
            "INSERT INTO official_sale_slate_revisions "
            "(slate_revision_id, slate_family_id, lane, business_key, revision_no, "
            "source_artifact_retrieval_id, published_at, retrieved_at, valid_from, "
            "supersedes_slate_revision_id, content_hash) VALUES "
            "('slate-1', 'zucai:26116', 'zucai', '26116', 1, 'retrieval-1', :at, :at, "
            ":at, NULL, :hash)"
        ),
        {"at": AT, "hash": "e" * 64},
    )
    for index in (1, 2, 3):
        _insert_action(connection, f"request-{index}", "request_evidence_freeze", "judge_operator")
        _insert_action(
            connection,
            f"link-{index}",
            "link_operator_task_evidence_freeze",
            "deterministic_system",
        )
        _insert_action(
            connection,
            f"freeze-{index}",
            "freeze_evidence_bundle",
            "deterministic_system",
            result_object_id=f"bundle-{index}",
        )
        connection.execute(
            text(
                "INSERT INTO operator_evidence_freeze_requests "
                "(evidence_freeze_request_id, action_id, task_family_id, lane, business_key, "
                "slate_revision_id, task_snapshot_hash, requirement_revision_token, "
                "information_cutoff_at, policy_version, dependency_fingerprint, requested_at) "
                "VALUES (:request_id, :action_id, 'zucai:26116', 'zucai', '26116', "
                "'slate-1', :hash, :requirements, :at, 'governance-v1', :dependency, :at)"
            ),
            {
                "request_id": f"request-{index}",
                "action_id": f"ACT-request-{index}",
                "hash": str(index) * 64,
                "requirements": f"requirements-{index}",
                "dependency": chr(96 + index) * 64,
                "at": AT,
            },
        )
        connection.execute(
            text("INSERT INTO matches (match_id) VALUES (:match_id)"),
            {"match_id": f"match-{index}"},
        )
        connection.execute(
            text(
                "INSERT INTO evidence_bundles "
                "(evidence_bundle_id, match_id, frozen_at, information_cutoff_at, "
                "prior_distribution_json, source_coverage_json, freshness_json, content_hash) "
                "VALUES (:bundle_id, :match_id, :at, :at, '{}', '{}', '{}', :content_hash)"
            ),
            {
                "bundle_id": f"bundle-{index}",
                "match_id": f"match-{index}",
                "at": AT,
                "content_hash": str(index) * 64,
            },
        )


def _revision_values(
    index: int,
    *,
    revision_no: int,
    supersedes_revision_id: str | None,
    declared_count: int = 1,
    link_action_id: str | None = None,
    at: str = AT,
) -> dict[str, object]:
    return {
        "revision_id": f"task-bundle-{index}",
        "revision_no": revision_no,
        "request_id": f"request-{index}",
        "link_action_id": link_action_id or f"ACT-link-{index}",
        "task_snapshot_hash": str(index) * 64,
        "requirement_revision_token": f"requirements-{index}",
        "dependency_fingerprint": chr(96 + index) * 64,
        "declared_count": declared_count,
        "content_hash": chr(102 + index) * 64,
        "at": at,
        "supersedes_revision_id": supersedes_revision_id,
    }


def _item_values(
    index: int,
    *,
    revision_id: str | None = None,
    freeze_action_id: str | None = None,
    item_index: int = 0,
) -> dict[str, object]:
    return {
        "item_id": f"task-bundle-item-{index}",
        "revision_id": revision_id or f"task-bundle-{index}",
        "item_index": item_index,
        "match_id": f"match-{index}",
        "evidence_bundle_id": f"bundle-{index}",
        "freeze_action_id": freeze_action_id or f"ACT-freeze-{index}",
        "content_hash": chr(109 + index) * 64,
    }


def _insert_complete_revision(
    connection,
    index: int,
    *,
    revision_no: int,
    supersedes_revision_id: str | None,
    at: str = AT,
) -> None:
    connection.execute(ITEM_INSERT, _item_values(index))
    connection.execute(
        REVISION_INSERT,
        _revision_values(
            index,
            revision_no=revision_no,
            supersedes_revision_id=supersedes_revision_id,
            at=at,
        ),
    )


def test_current_task_bundle_respects_historical_as_of(tmp_path: Path) -> None:
    engine = _initialize(tmp_path / "ontology.db")
    later = "2026-09-04T09:00:00+00:00"
    with engine.begin() as connection:
        _seed_revision_dependencies(connection)
        _insert_complete_revision(
            connection,
            1,
            revision_no=1,
            supersedes_revision_id=None,
        )
        _insert_complete_revision(
            connection,
            2,
            revision_no=2,
            supersedes_revision_id="task-bundle-1",
            at=later,
        )

    with engine.connect() as connection:
        repository = OperatorDecisionRepository(connection)
        historical = repository.current_task_evidence_bundle_revision(
            "zucai:26116",
            as_of="2026-09-04T08:30:00+00:00",
        )
        current = repository.current_task_evidence_bundle_revision(
            "zucai:26116",
            as_of=later,
        )

    assert historical is not None
    assert historical.task_evidence_bundle_revision_id == "task-bundle-1"
    assert current is not None
    assert current.task_evidence_bundle_revision_id == "task-bundle-2"


def _job_values(
    worker_job_id: str,
    *,
    state: str = "queued",
    source_object_id: str = "request-1",
) -> dict[str, object]:
    completed = state == "completed"
    leased = state == "leased"
    return {
        "worker_job_id": worker_job_id,
        "job_kind": "evidence_freeze",
        "source_object_type": "operator_evidence_freeze_request",
        "source_object_id": source_object_id,
        "state": state,
        "lease_owner": "worker:test" if leased else None,
        "lease_expires_at": "2026-09-04T08:05:00+00:00" if leased else None,
        "attempt_count": 0,
        "available_at": AT,
        "last_error_code": "invariant_failure" if state == "failed" else None,
        "result_action_id": "ACT-link-1" if completed else None,
        "result_object_type": "task_evidence_bundle_revision" if completed else None,
        "result_object_id": "task-bundle-1" if completed else None,
        "created_at": AT,
        "updated_at": AT,
    }


def test_migration_19_applies_fresh_and_from_v18_with_closed_permissions(
    tmp_path: Path,
) -> None:
    expected_tables = {
        "operator_evidence_freeze_requests",
        "operator_task_evidence_bundle_revisions",
        "operator_task_evidence_bundle_items",
        "operator_worker_jobs",
    }
    expected_permissions = {
        ("request_evidence_freeze", "judge_operator"),
        ("freeze_evidence_bundle", "deterministic_system"),
        ("link_operator_task_evidence_freeze", "deterministic_system"),
    }

    for name, initial_version in (("fresh", None), ("upgrade", 18)):
        engine = _initialize(tmp_path / f"{name}.db", from_version=initial_version)

        assert migration_status(engine).current_version >= 19
        assert expected_tables <= set(inspect(engine).get_table_names())
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT action_type, actor_role FROM action_permissions "
                    "WHERE action_type IN "
                    "('request_evidence_freeze', 'freeze_evidence_bundle', "
                    "'link_operator_task_evidence_freeze')"
                )
            ).all()
        assert set(rows) == expected_permissions


def test_worker_jobs_enforce_closed_kind_state_and_unique_source(tmp_path: Path) -> None:
    engine = _initialize(tmp_path / "ontology.db")
    base = _job_values("job-1", source_object_id="job-1")

    with engine.begin() as connection:
        connection.execute(JOB_INSERT, base)

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO operator_worker_jobs "
                    "(worker_job_id, job_kind, source_object_type, source_object_id, state, "
                    "attempt_count, available_at, created_at, updated_at) "
                    "VALUES ('job-2', 'evidence_freeze', "
                    "'operator_evidence_freeze_request', 'job-1', 'queued', 0, :at, :at, :at)"
                ),
                {"at": AT},
            )

    for column, invalid in (("job_kind", "automatic_bet"), ("state", "running")):
        row = dict(base, worker_job_id=f"job-invalid-{column}", source_object_id=column)
        row[column] = invalid
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(JOB_INSERT, row)


@pytest.mark.parametrize("operation", ("UPDATE", "DELETE"))
def test_evidence_freeze_requests_are_append_only(
    tmp_path: Path,
    operation: str,
) -> None:
    engine = _initialize(tmp_path / "ontology.db")
    with engine.begin() as connection:
        _seed_revision_dependencies(connection)

    statement = (
        "UPDATE operator_evidence_freeze_requests SET task_snapshot_hash = :hash "
        "WHERE evidence_freeze_request_id = 'request-1'"
        if operation == "UPDATE"
        else "DELETE FROM operator_evidence_freeze_requests "
        "WHERE evidence_freeze_request_id = 'request-1'"
    )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(text(statement), {"hash": "z" * 64})


@pytest.mark.parametrize(
    ("action_type", "actor_role", "status"),
    (
        ("link_operator_task_evidence_freeze", "deterministic_system", "committed"),
        ("request_evidence_freeze", "deterministic_system", "committed"),
        ("request_evidence_freeze", "judge_operator", "rejected"),
    ),
)
def test_evidence_freeze_request_requires_exact_committed_judge_action(
    tmp_path: Path,
    action_type: str,
    actor_role: str,
    status: str,
) -> None:
    engine = _initialize(tmp_path / "ontology.db")
    with engine.begin() as connection:
        _seed_revision_dependencies(connection)
        _insert_action(
            connection,
            "request-invalid",
            action_type,
            actor_role,
            status=status,
        )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO operator_evidence_freeze_requests "
                    "(evidence_freeze_request_id, action_id, task_family_id, lane, "
                    "business_key, slate_revision_id, task_snapshot_hash, "
                    "requirement_revision_token, information_cutoff_at, policy_version, "
                    "dependency_fingerprint, requested_at) VALUES "
                    "('request-invalid', 'ACT-request-invalid', 'zucai:26116', 'zucai', "
                    "'26116', 'slate-1', :hash, 'requirements-invalid', :at, "
                    "'governance-v1', :dependency, :at)"
                ),
                {"hash": "9" * 64, "dependency": "z" * 64, "at": AT},
            )


@pytest.mark.parametrize(
    "missing_column",
    ("result_action_id", "result_object_type", "result_object_id"),
)
def test_completed_worker_job_requires_full_result_reference(
    tmp_path: Path,
    missing_column: str,
) -> None:
    engine = _initialize(tmp_path / "ontology.db")
    with engine.begin() as connection:
        _seed_revision_dependencies(connection)
        _insert_complete_revision(
            connection,
            1,
            revision_no=1,
            supersedes_revision_id=None,
        )
        connection.execute(JOB_INSERT, _job_values("job-complete", state="completed"))

    invalid = _job_values(f"job-missing-{missing_column}", state="completed")
    invalid[missing_column] = None
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(JOB_INSERT, invalid)


def test_failed_worker_job_rejects_result_references(tmp_path: Path) -> None:
    engine = _initialize(tmp_path / "ontology.db")
    with engine.begin() as connection:
        _insert_action(
            connection,
            "link-1",
            "link_operator_task_evidence_freeze",
            "deterministic_system",
        )
        connection.execute(JOB_INSERT, _job_values("job-failed", state="failed"))

    invalid = _job_values("job-failed-with-result", state="failed")
    invalid.update(
        result_action_id="ACT-link-1",
        result_object_type="task_evidence_bundle_revision",
        result_object_id="task-bundle-result",
    )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(JOB_INSERT, invalid)


@pytest.mark.parametrize(
    ("action_type", "actor_role"),
    (
        ("request_evidence_freeze", "deterministic_system"),
        ("link_operator_task_evidence_freeze", "judge_operator"),
    ),
)
def test_completed_evidence_freeze_job_requires_exact_result_action_authority(
    tmp_path: Path,
    action_type: str,
    actor_role: str,
) -> None:
    engine = _initialize(tmp_path / "ontology.db")
    with engine.begin() as connection:
        _seed_revision_dependencies(connection)
        _insert_action(connection, "job-result", action_type, actor_role, status="accepted")
        connection.execute(ITEM_INSERT, _item_values(1))
        connection.execute(
            REVISION_INSERT,
            _revision_values(
                1,
                revision_no=1,
                supersedes_revision_id=None,
                link_action_id="ACT-job-result",
            ),
        )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            invalid = _job_values("job-invalid-result", state="completed")
            invalid["result_action_id"] = "ACT-job-result"
            connection.execute(JOB_INSERT, invalid)


def test_completed_evidence_freeze_job_binds_action_to_exact_revision(tmp_path: Path) -> None:
    engine = _initialize(tmp_path / "ontology.db")
    with engine.begin() as connection:
        _seed_revision_dependencies(connection)
        _insert_complete_revision(connection, 1, revision_no=1, supersedes_revision_id=None)
        _insert_complete_revision(
            connection,
            2,
            revision_no=2,
            supersedes_revision_id="task-bundle-1",
        )

    invalid = _job_values("job-crossed-result", state="completed")
    invalid["result_object_id"] = "task-bundle-2"
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(JOB_INSERT, invalid)


def test_completed_evidence_job_binds_result_to_its_own_source_request(
    tmp_path: Path,
) -> None:
    engine = _initialize(tmp_path / "ontology.db")
    with engine.begin() as connection:
        _seed_revision_dependencies(connection)
        _insert_complete_revision(connection, 1, revision_no=1, supersedes_revision_id=None)

    crossed = _job_values("job-crossed-source", state="completed")
    crossed.update(
        source_object_id="request-2",
        result_action_id="ACT-link-1",
        result_object_id="task-bundle-1",
    )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(JOB_INSERT, crossed)


def test_completed_evidence_freeze_job_allows_current_accepted_action(tmp_path: Path) -> None:
    engine = _initialize(tmp_path / "ontology.db")
    with engine.begin() as connection:
        _seed_revision_dependencies(connection)
        connection.execute(
            text(
                "UPDATE actions SET status = 'accepted', committed_at = NULL "
                "WHERE action_id = 'ACT-link-1'"
            )
        )
        _insert_complete_revision(connection, 1, revision_no=1, supersedes_revision_id=None)
        connection.execute(JOB_INSERT, _job_values("job-current-action", state="leased"))
        connection.execute(
            text(
                "UPDATE operator_worker_jobs SET state = 'completed', lease_owner = NULL, "
                "lease_expires_at = NULL, result_action_id = 'ACT-link-1', "
                "result_object_type = 'task_evidence_bundle_revision', "
                "result_object_id = 'task-bundle-1', updated_at = :at "
                "WHERE worker_job_id = 'job-current-action'"
            ),
            {"at": AT},
        )


def test_evidence_freeze_completion_update_rejects_wrong_result_action(tmp_path: Path) -> None:
    engine = _initialize(tmp_path / "ontology.db")
    with engine.begin() as connection:
        _seed_revision_dependencies(connection)
        _insert_complete_revision(connection, 1, revision_no=1, supersedes_revision_id=None)
        connection.execute(JOB_INSERT, _job_values("job-wrong-action", state="leased"))

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE operator_worker_jobs SET state = 'completed', lease_owner = NULL, "
                    "lease_expires_at = NULL, result_action_id = 'ACT-request-1', "
                    "result_object_type = 'task_evidence_bundle_revision', "
                    "result_object_id = 'task-bundle-1', updated_at = :at "
                    "WHERE worker_job_id = 'job-wrong-action'"
                ),
                {"at": AT},
            )


@pytest.mark.parametrize("state", ("completed", "failed"))
def test_terminal_worker_jobs_reject_update_and_delete(tmp_path: Path, state: str) -> None:
    engine = _initialize(tmp_path / "ontology.db")
    job_id = f"job-{state}"
    with engine.begin() as connection:
        _seed_revision_dependencies(connection)
        if state == "completed":
            _insert_complete_revision(connection, 1, revision_no=1, supersedes_revision_id=None)
        connection.execute(JOB_INSERT, _job_values(job_id, state=state))

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE operator_worker_jobs SET updated_at = :updated_at "
                    "WHERE worker_job_id = :worker_job_id"
                ),
                {"updated_at": "2026-09-04T08:01:00+00:00", "worker_job_id": job_id},
            )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM operator_worker_jobs WHERE worker_job_id = :worker_job_id"),
                {"worker_job_id": job_id},
            )


def test_task_evidence_bundle_revision_requires_one_linear_leaf(tmp_path: Path) -> None:
    engine = _initialize(tmp_path / "ontology.db")
    with engine.begin() as connection:
        _seed_revision_dependencies(connection)
        _insert_complete_revision(
            connection,
            1,
            revision_no=1,
            supersedes_revision_id=None,
        )
        _insert_complete_revision(
            connection,
            2,
            revision_no=2,
            supersedes_revision_id="task-bundle-1",
        )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            _insert_complete_revision(
                connection,
                3,
                revision_no=2,
                supersedes_revision_id="task-bundle-1",
            )


def test_task_bundle_item_requires_exact_freeze_action_type(tmp_path: Path) -> None:
    engine = _initialize(tmp_path / "ontology.db")
    with engine.connect() as connection:
        transaction = connection.begin()
        _seed_revision_dependencies(connection)
        connection.exec_driver_sql("PRAGMA defer_foreign_keys=ON")
        with pytest.raises(IntegrityError):
            connection.execute(
                ITEM_INSERT,
                _item_values(1, freeze_action_id="ACT-link-1"),
            )
        transaction.rollback()


@pytest.mark.parametrize(
    ("role", "status", "result_object_id"),
    (
        ("judge_operator", "committed", "bundle-1"),
        ("deterministic_system", "accepted", "bundle-1"),
        ("deterministic_system", "committed", "bundle-2"),
    ),
)
def test_task_bundle_item_requires_exact_committed_bundle_action_result(
    tmp_path: Path,
    role: str,
    status: str,
    result_object_id: str,
) -> None:
    engine = _initialize(tmp_path / "ontology.db")
    with engine.connect() as connection:
        transaction = connection.begin()
        _seed_revision_dependencies(connection)
        _insert_action(
            connection,
            "freeze-invalid",
            "freeze_evidence_bundle",
            role,
            status=status,
            result_object_id=result_object_id,
        )
        connection.exec_driver_sql("PRAGMA defer_foreign_keys=ON")
        with pytest.raises(IntegrityError):
            connection.execute(
                ITEM_INSERT,
                _item_values(1, freeze_action_id="ACT-freeze-invalid"),
            )
        transaction.rollback()


def test_task_bundle_parent_rejects_declared_count_without_items(tmp_path: Path) -> None:
    engine = _initialize(tmp_path / "ontology.db")
    with engine.begin() as connection:
        _seed_revision_dependencies(connection)

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                REVISION_INSERT,
                _revision_values(1, revision_no=1, supersedes_revision_id=None),
            )


def test_task_bundle_items_and_declared_counts_commit_atomically(tmp_path: Path) -> None:
    engine = _initialize(tmp_path / "ontology.db")
    with engine.begin() as connection:
        _seed_revision_dependencies(connection)
        _insert_complete_revision(
            connection,
            1,
            revision_no=1,
            supersedes_revision_id=None,
        )

    with engine.connect() as connection:
        revision_count = connection.execute(
            text("SELECT COUNT(*) FROM operator_task_evidence_bundle_revisions")
        ).scalar_one()
        item_count = connection.execute(
            text("SELECT COUNT(*) FROM operator_task_evidence_bundle_items")
        ).scalar_one()
    assert (revision_count, item_count) == (1, 1)


def test_completed_task_bundle_rejects_item_mutation(tmp_path: Path) -> None:
    engine = _initialize(tmp_path / "ontology.db")
    with engine.begin() as connection:
        _seed_revision_dependencies(connection)
        _insert_complete_revision(
            connection,
            1,
            revision_no=1,
            supersedes_revision_id=None,
        )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                ITEM_INSERT,
                _item_values(2, revision_id="task-bundle-1", item_index=1),
            )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE operator_task_evidence_bundle_items SET content_hash = :hash "
                    "WHERE task_evidence_bundle_item_id = 'task-bundle-item-1'"
                ),
                {"hash": "z" * 64},
            )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM operator_task_evidence_bundle_items "
                    "WHERE task_evidence_bundle_item_id = 'task-bundle-item-1'"
                )
            )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE operator_task_evidence_bundle_revisions "
                    "SET required_match_count = 2, bundle_count = 2, item_count = 2 "
                    "WHERE task_evidence_bundle_revision_id = 'task-bundle-1'"
                )
            )
