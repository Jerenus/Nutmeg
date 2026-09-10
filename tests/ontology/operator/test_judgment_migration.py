from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import MIGRATIONS, migration_status, run_migrations

AT = "2026-09-04T08:00:00+00:00"

PARENT_COLUMNS = {
    "operator_market_prior_baseline_revisions": {
        "market_prior_baseline_revision_id",
        "market_prior_baseline_family_id",
        "revision_no",
        "supersedes_revision_id",
        "task_family_id",
        "work_item_id",
        "task_snapshot_hash",
        "slate_revision_id",
        "task_evidence_bundle_revision_id",
        "information_cutoff_at",
        "policy_version",
        "arithmetic_version",
        "probability_precision",
        "comparison_only",
        "content_hash",
        "action_id",
        "created_at",
    },
    "operator_baseline_envelope_revisions": {
        "baseline_envelope_revision_id",
        "baseline_envelope_family_id",
        "revision_no",
        "supersedes_revision_id",
        "task_family_id",
        "work_item_id",
        "task_snapshot_hash",
        "slate_revision_id",
        "task_evidence_bundle_revision_id",
        "ticket_kind",
        "capital_cap_minor",
        "currency",
        "maximum_ticket_count",
        "maximum_exhaustive_candidate_count",
        "content_hash",
        "action_id",
        "created_at",
    },
    "operator_match_judgment_revisions": {
        "operator_match_judgment_revision_id",
        "operator_match_judgment_family_id",
        "revision_no",
        "supersedes_revision_id",
        "task_family_id",
        "work_item_id",
        "task_snapshot_hash",
        "slate_revision_id",
        "task_evidence_bundle_revision_id",
        "market_prior_baseline_revision_id",
        "match_id",
        "official_offer_revision_id",
        "market_definition_id",
        "forecast_revision_id",
        "falsifier",
        "rationale",
        "content_hash",
        "action_id",
        "created_at",
    },
    "operator_judgment_prescription_revisions": {
        "judgment_prescription_revision_id",
        "judgment_prescription_family_id",
        "revision_no",
        "supersedes_revision_id",
        "task_family_id",
        "work_item_id",
        "task_snapshot_hash",
        "slate_revision_id",
        "task_evidence_bundle_revision_id",
        "market_prior_baseline_revision_id",
        "baseline_envelope_revision_id",
        "required_match_count",
        "judgment_count",
        "content_hash",
        "action_id",
        "created_at",
    },
}

PARENT_FAMILY_COLUMNS = {
    "operator_market_prior_baseline_revisions": "market_prior_baseline_family_id",
    "operator_baseline_envelope_revisions": "baseline_envelope_family_id",
    "operator_match_judgment_revisions": "operator_match_judgment_family_id",
    "operator_judgment_prescription_revisions": "judgment_prescription_family_id",
}

CHILD_TABLES = {
    "operator_market_prior_baseline_probabilities",
    "operator_baseline_envelope_offer_constraints",
    "operator_baseline_envelope_face_bundles",
    "operator_baseline_envelope_bundle_faces",
    "operator_baseline_envelope_structure_templates",
    "operator_baseline_envelope_template_offers",
    "operator_match_judgment_probabilities",
    "operator_match_judgment_factor_adjustments",
    "operator_match_judgment_factor_offsets",
    "operator_match_judgment_factor_evidence_refs",
    "operator_match_judgment_face_bundles",
    "operator_match_judgment_bundle_faces",
    "operator_match_judgment_rule_refs",
    "operator_match_judgment_evidence_refs",
    "operator_judgment_prescription_items",
}

DECIMAL_COLUMNS = {
    "operator_market_prior_baseline_probabilities": {"probability_decimal"},
    "operator_match_judgment_probabilities": {
        "prior_probability_decimal",
        "belief_probability_decimal",
        "delta_probability_decimal",
    },
    "operator_match_judgment_factor_offsets": {"offset_probability_decimal"},
}

REVISION_CONTRACTS = {
    "market_prior_baseline": {
        "table": "operator_market_prior_baseline_revisions",
        "id_column": "market_prior_baseline_revision_id",
        "family_column": "market_prior_baseline_family_id",
        "action_type": "freeze_market_prior_baseline",
        "actor_role": "deterministic_system",
    },
    "baseline_envelope": {
        "table": "operator_baseline_envelope_revisions",
        "id_column": "baseline_envelope_revision_id",
        "family_column": "baseline_envelope_family_id",
        "action_type": "record_baseline_envelope",
        "actor_role": "judge_operator",
    },
    "match_judgment": {
        "table": "operator_match_judgment_revisions",
        "id_column": "operator_match_judgment_revision_id",
        "family_column": "operator_match_judgment_family_id",
        "action_type": "commit_operator_match_judgment",
        "actor_role": "judge_operator",
    },
    "judgment_prescription": {
        "table": "operator_judgment_prescription_revisions",
        "id_column": "judgment_prescription_revision_id",
        "family_column": "judgment_prescription_family_id",
        "action_type": "freeze_judgment_prescription",
        "actor_role": "judge_operator",
    },
}


def _insert_action(
    connection,
    action_id: str,
    *,
    action_type: str,
    actor_role: str,
    status: str = "accepted",
) -> None:
    connection.execute(
        text(
            "INSERT INTO actions "
            "(action_id, action_type, actor_id, actor_role, requested_at, idempotency_key, "
            "request_hash, expected_versions_json, payload_json, policy_version, status, "
            "result_refs_json, committed_at) VALUES "
            "(:action_id, :action_type, 'migration-fixture', :actor_role, :at, :key, :hash, "
            "'{}', '{}', 'governance-v1', :status, '[]', :committed_at)"
        ),
        {
            "action_id": action_id,
            "action_type": action_type,
            "actor_role": actor_role,
            "at": AT,
            "key": f"judgment-migration:{action_id}",
            "hash": f"hash:{action_id}",
            "status": status,
            "committed_at": AT if status == "committed" else None,
        },
    )


def _insert_revision(
    connection,
    kind: str,
    suffix: str,
    *,
    family_id: str | None = None,
    revision_no: int = 1,
    supersedes_revision_id: str | None = None,
    action_type: str | None = None,
    actor_role: str | None = None,
    action_status: str = "accepted",
) -> str:
    contract = REVISION_CONTRACTS[kind]
    revision_id = f"{kind}-{suffix}"
    action_id = f"ACT-{kind}-{suffix}"
    _insert_action(
        connection,
        action_id,
        action_type=action_type or contract["action_type"],
        actor_role=actor_role or contract["actor_role"],
        status=action_status,
    )
    common = {
        "revision_id": revision_id,
        "family_id": family_id or f"{kind}-family-{suffix}",
        "revision_no": revision_no,
        "supersedes_revision_id": supersedes_revision_id,
        "action_id": action_id,
        "content_hash": f"content:{kind}:{suffix}",
        "at": AT,
    }
    if kind == "market_prior_baseline":
        connection.execute(
            text(
                "INSERT INTO operator_market_prior_baseline_revisions "
                "(market_prior_baseline_revision_id, market_prior_baseline_family_id, "
                "revision_no, supersedes_revision_id, task_family_id, work_item_id, "
                "task_snapshot_hash, slate_revision_id, task_evidence_bundle_revision_id, "
                "information_cutoff_at, policy_version, arithmetic_version, "
                "probability_precision, comparison_only, content_hash, action_id, created_at) "
                "VALUES (:revision_id, :family_id, :revision_no, :supersedes_revision_id, "
                "'jczq:2026-09-04', 'jczq:2026-09-04:wave:current', :snapshot_hash, "
                "'slate-1', 'task-bundle-1', :at, 'governance-v1', 'decimal-v1', 12, 1, "
                ":content_hash, :action_id, :at)"
            ),
            {**common, "snapshot_hash": f"snapshot:{suffix}"},
        )
    elif kind == "baseline_envelope":
        connection.execute(
            text(
                "INSERT INTO operator_baseline_envelope_revisions "
                "(baseline_envelope_revision_id, baseline_envelope_family_id, revision_no, "
                "supersedes_revision_id, task_family_id, work_item_id, task_snapshot_hash, "
                "slate_revision_id, task_evidence_bundle_revision_id, ticket_kind, "
                "capital_cap_minor, currency, maximum_ticket_count, "
                "maximum_exhaustive_candidate_count, content_hash, action_id, created_at) "
                "VALUES (:revision_id, :family_id, :revision_no, :supersedes_revision_id, "
                "'jczq:2026-09-04', 'jczq:2026-09-04:wave:current', :snapshot_hash, "
                "'slate-1', 'task-bundle-1', 'jczq', 20000, 'CNY', 2, 100, :content_hash, "
                ":action_id, :at)"
            ),
            {**common, "snapshot_hash": f"snapshot:{suffix}"},
        )
    elif kind == "match_judgment":
        connection.execute(
            text(
                "INSERT INTO operator_match_judgment_revisions "
                "(operator_match_judgment_revision_id, operator_match_judgment_family_id, "
                "revision_no, supersedes_revision_id, task_family_id, work_item_id, "
                "task_snapshot_hash, slate_revision_id, task_evidence_bundle_revision_id, "
                "market_prior_baseline_revision_id, baseline_envelope_revision_id, match_id, "
                "official_offer_revision_id, market_definition_id, forecast_revision_id, "
                "falsifier, rationale, content_hash, action_id, created_at) VALUES "
                "(:revision_id, :family_id, :revision_no, :supersedes_revision_id, "
                "'jczq:2026-09-04', 'jczq:2026-09-04:wave:current', :snapshot_hash, "
                "'slate-1', 'task-bundle-1', 'market_prior_baseline-dependency', "
                "'baseline_envelope-dependency', 'match-1', 'offer-revision-1', 'md-had', "
                ":forecast_revision_id, 'fixture falsifier', 'fixture rationale', "
                ":content_hash, :action_id, :at)"
            ),
            {
                **common,
                "snapshot_hash": f"snapshot:{suffix}",
                "forecast_revision_id": f"forecast-{suffix}",
            },
        )
    else:
        connection.execute(
            text(
                "INSERT INTO operator_judgment_prescription_revisions "
                "(judgment_prescription_revision_id, judgment_prescription_family_id, "
                "revision_no, supersedes_revision_id, task_family_id, work_item_id, "
                "task_snapshot_hash, slate_revision_id, task_evidence_bundle_revision_id, "
                "market_prior_baseline_revision_id, baseline_envelope_revision_id, "
                "required_match_count, judgment_count, content_hash, action_id, created_at) "
                "VALUES (:revision_id, :family_id, :revision_no, :supersedes_revision_id, "
                "'jczq:2026-09-04', 'jczq:2026-09-04:wave:current', :snapshot_hash, "
                "'slate-1', 'task-bundle-1', 'market_prior_baseline-dependency', "
                "'baseline_envelope-dependency', 1, 1, :content_hash, :action_id, :at)"
            ),
            {**common, "snapshot_hash": f"snapshot:{suffix}"},
        )
    return revision_id


def _insert_decimal_child(
    connection,
    location: str,
    value: str,
    *,
    suffix: str = "decimal",
) -> None:
    if location == "market_prior":
        revision_id = _insert_revision(connection, "market_prior_baseline", suffix)
        connection.execute(
            text(
                "INSERT INTO operator_market_prior_baseline_probabilities "
                "(market_prior_baseline_probability_id, market_prior_baseline_revision_id, "
                "item_index, match_id, official_offer_revision_id, market_definition_id, "
                "face_code, probability_decimal, market_snapshot_id, quote_id, "
                "booked_decimal_odds, quote_captured_at) VALUES "
                "(:child_id, :revision_id, 0, 'match-1', 'offer-revision-1', 'md-had', "
                "'3', :value, 'snapshot-1', 'quote-1', '2.000000000000', :captured_at)"
            ),
            {
                "child_id": f"prior-probability-{suffix}",
                "revision_id": revision_id,
                "value": value,
                "captured_at": AT,
            },
        )
        return

    revision_id = _insert_revision(connection, "match_judgment", suffix)
    if location == "factor_offset":
        connection.execute(
            text(
                "INSERT INTO operator_match_judgment_factor_adjustments "
                "(operator_match_judgment_factor_adjustment_id, "
                "operator_match_judgment_revision_id, factor_index, factor_definition_id, "
                "scope_entity_id) VALUES "
                "(:adjustment_id, :revision_id, 0, 'factor-1', 'match-1')"
            ),
            {
                "adjustment_id": f"factor-adjustment-{suffix}",
                "revision_id": revision_id,
            },
        )
        connection.execute(
            text(
                "INSERT INTO operator_match_judgment_factor_offsets "
                "(operator_match_judgment_factor_offset_id, "
                "operator_match_judgment_factor_adjustment_id, face_index, face_code, "
                "offset_probability_decimal) VALUES "
                "(:offset_id, :adjustment_id, 0, '3', :value)"
            ),
            {
                "offset_id": f"factor-offset-{suffix}",
                "adjustment_id": f"factor-adjustment-{suffix}",
                "value": value,
            },
        )
        return

    values = {
        "prior": "0.400000000000",
        "belief": "0.350000000000",
        "delta": "-0.050000000000",
    }
    values[location] = value
    connection.execute(
        text(
            "INSERT INTO operator_match_judgment_probabilities "
            "(operator_match_judgment_probability_id, operator_match_judgment_revision_id, "
            "face_index, face_code, prior_probability_decimal, belief_probability_decimal, "
            "delta_probability_decimal) VALUES "
            "(:child_id, :revision_id, 0, '3', :prior, :belief, :delta)"
        ),
        {
            **values,
            "child_id": f"judgment-probability-{suffix}",
            "revision_id": revision_id,
        },
    )


def _initialize(path: Path, *, from_version: int | None = None):
    engine = build_ontology_engine(path)
    if from_version is not None:
        run_migrations(engine, MIGRATIONS[:from_version])
    run_migrations(engine, MIGRATIONS[:20])
    return engine


def test_migration_20_applies_fresh_and_from_v19_with_closed_permissions(
    tmp_path: Path,
) -> None:
    expected_permissions = {
        ("freeze_market_prior_baseline", "deterministic_system"),
        ("record_baseline_envelope", "judge_operator"),
        ("commit_operator_match_judgment", "judge_operator"),
        ("freeze_judgment_prescription", "judge_operator"),
    }
    expected_tables = {*PARENT_COLUMNS, *CHILD_TABLES}

    for name, initial_version in (("fresh", None), ("upgrade", 19)):
        engine = _initialize(tmp_path / f"{name}.db", from_version=initial_version)

        assert migration_status(engine).current_version == 20
        assert expected_tables <= set(inspect(engine).get_table_names())
        with engine.connect() as connection:
            permissions = set(
                connection.execute(
                    text(
                        "SELECT action_type, actor_role FROM action_permissions "
                        "WHERE action_type IN "
                        "('freeze_market_prior_baseline', 'record_baseline_envelope', "
                        "'commit_operator_match_judgment', "
                        "'freeze_judgment_prescription')"
                    )
                ).all()
            )
        assert permissions == expected_permissions


def test_revision_parents_have_complete_lineage_and_normalized_children(
    tmp_path: Path,
) -> None:
    engine = _initialize(tmp_path / "ontology.db")
    inspector = inspect(engine)

    for table_name, expected_columns in PARENT_COLUMNS.items():
        actual = {column["name"] for column in inspector.get_columns(table_name)}
        assert expected_columns <= actual
        assert not any(name.endswith("_json") for name in actual)
        unique_sets = {
            tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints(table_name)
        }
        family_column = PARENT_FAMILY_COLUMNS[table_name]
        assert (family_column, "revision_no") in unique_sets

    for table_name in CHILD_TABLES:
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        assert not any(name.endswith("_json") for name in columns)
        assert inspector.get_foreign_keys(table_name)


def test_every_normalized_child_has_complete_append_only_triggers(tmp_path: Path) -> None:
    engine = _initialize(tmp_path / "ontology.db")
    expected = {
        f"{table_name}_{suffix}"
        for table_name in CHILD_TABLES
        for suffix in ("no_update", "no_delete", "no_late_insert")
    }
    with engine.connect() as connection:
        actual = set(
            connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
            ).scalars()
        )

    assert expected <= actual


def test_committed_revision_children_cannot_be_changed_or_extended(tmp_path: Path) -> None:
    engine = _initialize(tmp_path / "ontology.db")
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.exec_driver_sql("PRAGMA defer_foreign_keys=ON")
            revision_id = _insert_revision(
                connection,
                "market_prior_baseline",
                "immutable-child",
            )
            connection.execute(
                text(
                    "INSERT INTO operator_market_prior_baseline_probabilities "
                    "(market_prior_baseline_probability_id, "
                    "market_prior_baseline_revision_id, item_index, match_id, "
                    "official_offer_revision_id, market_definition_id, face_code, "
                    "probability_decimal, market_snapshot_id, quote_id, "
                    "booked_decimal_odds, quote_captured_at) VALUES "
                    "('immutable-probability', :revision_id, 0, 'match-1', "
                    "'offer-revision-1', 'md-had', '3', '0.400000000000', "
                    "'snapshot-1', 'quote-1', '2.000000000000', :captured_at)"
                ),
                {"revision_id": revision_id, "captured_at": AT},
            )
            connection.execute(
                text(
                    "UPDATE actions SET status = 'committed', committed_at = :at "
                    "WHERE action_id = 'ACT-market_prior_baseline-immutable-child'"
                ),
                {"at": AT},
            )

            for statement in (
                "UPDATE operator_market_prior_baseline_probabilities "
                "SET probability_decimal = '0.500000000000' "
                "WHERE market_prior_baseline_probability_id = 'immutable-probability'",
                "DELETE FROM operator_market_prior_baseline_probabilities "
                "WHERE market_prior_baseline_probability_id = 'immutable-probability'",
                "INSERT INTO operator_market_prior_baseline_probabilities "
                "(market_prior_baseline_probability_id, "
                "market_prior_baseline_revision_id, item_index, match_id, "
                "official_offer_revision_id, market_definition_id, face_code, "
                "probability_decimal, market_snapshot_id, quote_id, "
                "booked_decimal_odds, quote_captured_at) VALUES "
                "('late-probability', 'market_prior_baseline-immutable-child', 1, "
                "'match-1', 'offer-revision-1', 'md-had', '1', '0.300000000000', "
                "'snapshot-1', 'quote-1', '2.000000000000', "
                "'2026-09-04T08:00:00+00:00')",
            ):
                with pytest.raises(IntegrityError, match="append-only"):
                    connection.execute(text(statement))
        finally:
            transaction.rollback()


def test_prescription_revisions_may_reuse_unchanged_current_judgment(
    tmp_path: Path,
) -> None:
    engine = _initialize(tmp_path / "ontology.db")
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.exec_driver_sql("PRAGMA defer_foreign_keys=ON")
            judgment_id = _insert_revision(connection, "match_judgment", "shared")
            root_id = _insert_revision(
                connection,
                "judgment_prescription",
                "root",
                family_id="prescription-family",
            )
            child_id = _insert_revision(
                connection,
                "judgment_prescription",
                "child",
                family_id="prescription-family",
                revision_no=2,
                supersedes_revision_id=root_id,
            )

            for item_id, prescription_id in (
                ("prescription-item-root", root_id),
                ("prescription-item-child", child_id),
            ):
                connection.execute(
                    text(
                        "INSERT INTO operator_judgment_prescription_items "
                        "(operator_judgment_prescription_item_id, "
                        "judgment_prescription_revision_id, item_index, match_id, "
                        "operator_match_judgment_revision_id) VALUES "
                        "(:item_id, :prescription_id, 0, 'match-1', :judgment_id)"
                    ),
                    {
                        "item_id": item_id,
                        "prescription_id": prescription_id,
                        "judgment_id": judgment_id,
                    },
                )

            assert connection.scalar(
                text("SELECT COUNT(*) FROM operator_judgment_prescription_items")
            ) == 2
        finally:
            transaction.rollback()


def test_probability_and_offset_storage_uses_canonical_decimal_text(
    tmp_path: Path,
) -> None:
    engine = _initialize(tmp_path / "ontology.db")
    inspector = inspect(engine)

    with engine.connect() as connection:
        for table_name, decimal_columns in DECIMAL_COLUMNS.items():
            columns = {
                column["name"]: column for column in inspector.get_columns(table_name)
            }
            for column_name in decimal_columns:
                assert str(columns[column_name]["type"]).upper() == "TEXT"
                assert columns[column_name]["nullable"] is False
            table_sql = connection.execute(
                text(
                    "SELECT sql FROM sqlite_master "
                    "WHERE type = 'table' AND name = :table_name"
                ),
                {"table_name": table_name},
            ).scalar_one()
            for column_name in decimal_columns:
                assert f"typeof({column_name}) = 'text'" in table_sql.lower()


@pytest.mark.parametrize("kind", REVISION_CONTRACTS)
def test_revision_family_has_only_one_root(tmp_path: Path, kind: str) -> None:
    engine = _initialize(tmp_path / "ontology.db")
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.exec_driver_sql("PRAGMA defer_foreign_keys=ON")
            _insert_revision(connection, kind, "root", family_id="family-under-test")

            with pytest.raises(IntegrityError, match="root"):
                _insert_revision(
                    connection,
                    kind,
                    "second-root",
                    family_id="family-under-test",
                    revision_no=2,
                )
        finally:
            transaction.rollback()


@pytest.mark.parametrize("kind", REVISION_CONTRACTS)
@pytest.mark.parametrize("invalid_lineage", ("different_family", "skipped_revision"))
def test_revision_child_must_be_next_revision_in_same_family(
    tmp_path: Path,
    kind: str,
    invalid_lineage: str,
) -> None:
    engine = _initialize(tmp_path / "ontology.db")
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.exec_driver_sql("PRAGMA defer_foreign_keys=ON")
            root_id = _insert_revision(
                connection,
                kind,
                "root",
                family_id="family-under-test",
            )
            family_id = (
                "different-family"
                if invalid_lineage == "different_family"
                else "family-under-test"
            )
            revision_no = 2 if invalid_lineage == "different_family" else 3

            with pytest.raises(IntegrityError, match="family|revision_no"):
                _insert_revision(
                    connection,
                    kind,
                    invalid_lineage,
                    family_id=family_id,
                    revision_no=revision_no,
                    supersedes_revision_id=root_id,
                )
        finally:
            transaction.rollback()


@pytest.mark.parametrize("kind", REVISION_CONTRACTS)
def test_revision_accepts_linear_child_in_same_family(tmp_path: Path, kind: str) -> None:
    engine = _initialize(tmp_path / "ontology.db")
    contract = REVISION_CONTRACTS[kind]
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.exec_driver_sql("PRAGMA defer_foreign_keys=ON")
            root_id = _insert_revision(
                connection,
                kind,
                "root",
                family_id="family-under-test",
            )
            _insert_revision(
                connection,
                kind,
                "child",
                family_id="family-under-test",
                revision_no=2,
                supersedes_revision_id=root_id,
            )

            assert connection.scalar(
                text(f"SELECT COUNT(*) FROM {contract['table']}")
            ) == 2
        finally:
            transaction.rollback()


@pytest.mark.parametrize("kind", REVISION_CONTRACTS)
@pytest.mark.parametrize("operation", ("UPDATE", "DELETE"))
def test_revision_rows_are_append_only(
    tmp_path: Path,
    kind: str,
    operation: str,
) -> None:
    engine = _initialize(tmp_path / "ontology.db")
    contract = REVISION_CONTRACTS[kind]
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.exec_driver_sql("PRAGMA defer_foreign_keys=ON")
            revision_id = _insert_revision(connection, kind, "immutable")
            statement = (
                f"UPDATE {contract['table']} SET content_hash = 'mutated' "
                f"WHERE {contract['id_column']} = :revision_id"
                if operation == "UPDATE"
                else (
                    f"DELETE FROM {contract['table']} "
                    f"WHERE {contract['id_column']} = :revision_id"
                )
            )

            with pytest.raises(IntegrityError, match="append-only"):
                connection.execute(text(statement), {"revision_id": revision_id})
        finally:
            transaction.rollback()


@pytest.mark.parametrize("kind", REVISION_CONTRACTS)
@pytest.mark.parametrize("invalid_provenance", ("action_type", "actor_role", "status"))
def test_revision_requires_exact_typed_action_provenance(
    tmp_path: Path,
    kind: str,
    invalid_provenance: str,
) -> None:
    engine = _initialize(tmp_path / "ontology.db")
    contract = REVISION_CONTRACTS[kind]
    overrides = {
        "action_type": {"action_type": "unrelated_action"},
        "actor_role": {
            "actor_role": (
                "judge_operator"
                if contract["actor_role"] == "deterministic_system"
                else "deterministic_system"
            )
        },
        "status": {"action_status": "rejected"},
    }
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.exec_driver_sql("PRAGMA defer_foreign_keys=ON")
            with pytest.raises(IntegrityError, match="Action"):
                _insert_revision(
                    connection,
                    kind,
                    f"invalid-{invalid_provenance}",
                    **overrides[invalid_provenance],
                )
        finally:
            transaction.rollback()


@pytest.mark.parametrize(
    ("job_overrides", "result_overrides"),
    (
        ({}, {"result_action_id": "ACT-wrong-result"}),
        ({}, {"result_object_type": "task_evidence_bundle_revision"}),
        ({}, {"result_object_id": "market_prior_baseline-other"}),
        ({"source_object_type": "operator_evidence_freeze_request"}, {}),
        ({"source_object_id": "task-bundle-other"}, {}),
    ),
)
def test_completed_market_baseline_job_requires_exact_typed_result(
    tmp_path: Path,
    job_overrides: dict[str, str],
    result_overrides: dict[str, str],
) -> None:
    engine = _initialize(tmp_path / "ontology.db")
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.exec_driver_sql("PRAGMA defer_foreign_keys=ON")
            revision_id = _insert_revision(connection, "market_prior_baseline", "worker")
            _insert_action(
                connection,
                "ACT-wrong-result",
                action_type="record_baseline_envelope",
                actor_role="judge_operator",
            )
            job = {
                "job_id": "market-baseline-job",
                "job_kind": "market_baseline",
                "source_object_type": "task_evidence_bundle_revision",
                "source_object_id": "task-bundle-1",
                "at": AT,
            }
            job.update(job_overrides)
            connection.execute(
                text(
                    "INSERT INTO operator_worker_jobs "
                    "(worker_job_id, job_kind, source_object_type, source_object_id, state, "
                    "lease_owner, lease_expires_at, attempt_count, available_at, created_at, "
                    "updated_at) VALUES (:job_id, :job_kind, :source_object_type, "
                    ":source_object_id, 'leased', 'worker:test', :at, 1, :at, :at, :at)"
                ),
                job,
            )
            result = {
                "result_action_id": "ACT-market_prior_baseline-worker",
                "result_object_type": "market_prior_baseline_revision",
                "result_object_id": revision_id,
                "job_id": job["job_id"],
                "at": AT,
            }
            result.update(result_overrides)

            with pytest.raises(IntegrityError, match="market baseline"):
                connection.execute(
                    text(
                        "UPDATE operator_worker_jobs SET state = 'completed', "
                        "lease_owner = NULL, lease_expires_at = NULL, "
                        "result_action_id = :result_action_id, "
                        "result_object_type = :result_object_type, "
                        "result_object_id = :result_object_id, updated_at = :at "
                        "WHERE worker_job_id = :job_id"
                    ),
                    result,
                )
        finally:
            transaction.rollback()


def test_completed_market_baseline_job_accepts_current_action_result(tmp_path: Path) -> None:
    engine = _initialize(tmp_path / "ontology.db")
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.exec_driver_sql("PRAGMA defer_foreign_keys=ON")
            revision_id = _insert_revision(connection, "market_prior_baseline", "worker")
            connection.execute(
                text(
                    "INSERT INTO operator_worker_jobs "
                    "(worker_job_id, job_kind, source_object_type, source_object_id, state, "
                    "lease_owner, lease_expires_at, attempt_count, available_at, created_at, "
                    "updated_at) VALUES ('market-baseline-job', 'market_baseline', "
                    "'task_evidence_bundle_revision', 'task-bundle-1', 'leased', "
                    "'worker:test', :at, 1, :at, :at, :at)"
                ),
                {"at": AT},
            )
            connection.execute(
                text(
                    "UPDATE operator_worker_jobs SET state = 'completed', lease_owner = NULL, "
                    "lease_expires_at = NULL, "
                    "result_action_id = 'ACT-market_prior_baseline-worker', "
                    "result_object_type = 'market_prior_baseline_revision', "
                    "result_object_id = :revision_id, updated_at = :at "
                    "WHERE worker_job_id = 'market-baseline-job'"
                ),
                {"revision_id": revision_id, "at": AT},
            )

            assert connection.scalar(
                text(
                    "SELECT COUNT(*) FROM operator_worker_jobs "
                    "WHERE worker_job_id = 'market-baseline-job' AND state = 'completed'"
                )
            ) == 1
        finally:
            transaction.rollback()


@pytest.mark.parametrize(
    "location",
    ("market_prior", "prior", "belief", "delta", "factor_offset"),
)
@pytest.mark.parametrize(
    "invalid_decimal",
    (
        "0.5",
        "+0.500000000000",
        "0.50000000000x",
        "0.5000000000000",
    ),
)
def test_decimal_storage_rejects_noncanonical_text(
    tmp_path: Path,
    location: str,
    invalid_decimal: str,
) -> None:
    engine = _initialize(tmp_path / "ontology.db")
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.exec_driver_sql("PRAGMA defer_foreign_keys=ON")
            with pytest.raises(IntegrityError):
                _insert_decimal_child(connection, location, invalid_decimal)
        finally:
            transaction.rollback()


def test_decimal_storage_accepts_canonical_signed_and_unsigned_text(tmp_path: Path) -> None:
    engine = _initialize(tmp_path / "ontology.db")
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.exec_driver_sql("PRAGMA defer_foreign_keys=ON")
            _insert_decimal_child(
                connection,
                "market_prior",
                "0.400000000000",
                suffix="valid-prior",
            )
            _insert_decimal_child(
                connection,
                "delta",
                "-0.050000000000",
                suffix="valid-delta",
            )
            _insert_decimal_child(
                connection,
                "factor_offset",
                "-0.050000000000",
                suffix="valid-offset",
            )

            assert connection.scalar(
                text(
                    "SELECT probability_decimal FROM "
                    "operator_market_prior_baseline_probabilities"
                )
            ) == "0.400000000000"
            assert connection.scalar(
                text(
                    "SELECT delta_probability_decimal FROM "
                    "operator_match_judgment_probabilities"
                )
            ) == "-0.050000000000"
            assert connection.scalar(
                text(
                    "SELECT offset_probability_decimal FROM "
                    "operator_match_judgment_factor_offsets"
                )
            ) == "-0.050000000000"
        finally:
            transaction.rollback()


STRUCTURE_FACT_TABLES = {
    "operator_match_judgment_anchor_facts",
    "operator_match_judgment_face_precedents",
}


def test_migration_28_adds_the_leg_audit_structure_facts(tmp_path: Path) -> None:
    for name, initial_version in (("fresh", None), ("upgrade", 27)):
        engine = build_ontology_engine(tmp_path / f"structure-{name}.db")
        if initial_version is not None:
            run_migrations(engine, MIGRATIONS[:initial_version])
        run_migrations(engine, MIGRATIONS)

        inspector = inspect(engine)
        assert STRUCTURE_FACT_TABLES <= set(inspector.get_table_names())
        assert {
            column["name"]
            for column in inspector.get_columns("operator_match_judgment_anchor_facts")
        } == {
            "operator_match_judgment_anchor_fact_id",
            "operator_match_judgment_revision_id",
            "anchor_integrity",
        }
        assert {
            column["name"]
            for column in inspector.get_columns(
                "operator_match_judgment_face_precedents"
            )
        } == {
            "operator_match_judgment_face_precedent_id",
            "operator_match_judgment_revision_id",
            "precedent_index",
            "face_code",
            "precedent_ref",
            "status",
        }
        for table_name in STRUCTURE_FACT_TABLES:
            assert inspector.get_foreign_keys(table_name)
        with engine.connect() as connection:
            triggers = set(
                connection.execute(
                    text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
                ).scalars()
            )
        assert {
            f"{table_name}_{suffix}"
            for table_name in STRUCTURE_FACT_TABLES
            for suffix in ("no_update", "no_delete", "no_late_insert")
        } <= triggers


def _structure_fact_rows(revision_id: str) -> dict[str, dict[str, object]]:
    return {
        "operator_match_judgment_anchor_facts": {
            "operator_match_judgment_anchor_fact_id": "anchor-fact-1",
            "operator_match_judgment_revision_id": revision_id,
            "anchor_integrity": "pass",
        },
        "operator_match_judgment_face_precedents": {
            "operator_match_judgment_face_precedent_id": "face-precedent-1",
            "operator_match_judgment_revision_id": revision_id,
            "precedent_index": 0,
            "face_code": "1",
            "precedent_ref": "2026-05-12 same venue 1:0",
            "status": "dead",
        },
    }


@pytest.mark.parametrize(
    ("table_name", "column", "value"),
    [
        ("operator_match_judgment_anchor_facts", "anchor_integrity", "solid"),
        ("operator_match_judgment_face_precedents", "status", "maybe"),
        ("operator_match_judgment_face_precedents", "face_code", "9"),
    ],
)
def test_structure_facts_reject_values_outside_their_closed_vocabulary(
    tmp_path: Path,
    table_name: str,
    column: str,
    value: str,
) -> None:
    engine = build_ontology_engine(tmp_path / f"closed-{column}-{value}.db")
    run_migrations(engine, MIGRATIONS)

    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.exec_driver_sql("PRAGMA defer_foreign_keys=ON")
            revision_id = _insert_revision(connection, "match_judgment", "closed-vocab")
            row = _structure_fact_rows(revision_id)[table_name]
            row[column] = value
            columns = ", ".join(row)
            binds = ", ".join(f":{name}" for name in row)

            with pytest.raises(IntegrityError):
                connection.execute(
                    text(f"INSERT INTO {table_name} ({columns}) VALUES ({binds})"),
                    row,
                )
        finally:
            transaction.rollback()


def test_one_judgment_revision_carries_at_most_one_anchor_fact(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "anchor-unique.db")
    run_migrations(engine, MIGRATIONS)

    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.exec_driver_sql("PRAGMA defer_foreign_keys=ON")
            revision_id = _insert_revision(connection, "match_judgment", "anchor-unique")
            row = _structure_fact_rows(revision_id)[
                "operator_match_judgment_anchor_facts"
            ]
            columns = ", ".join(row)
            binds = ", ".join(f":{name}" for name in row)
            statement = text(
                "INSERT INTO operator_match_judgment_anchor_facts "
                f"({columns}) VALUES ({binds})"
            )
            connection.execute(statement, row)

            with pytest.raises(IntegrityError):
                connection.execute(
                    statement,
                    {**row, "operator_match_judgment_anchor_fact_id": "anchor-fact-2"},
                )
        finally:
            transaction.rollback()
