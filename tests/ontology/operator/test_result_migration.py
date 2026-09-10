from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import (
    MIGRATIONS,
    migration_status,
    run_migrations,
)

RESULT_TABLES = {
    "operator_result_set_families",
    "operator_result_set_revisions",
    "operator_result_match_revisions",
    "operator_result_source_receipts",
    "operator_outcome_revisions",
    "zucai_prize_table_revisions",
    "zucai_prize_table_tiers",
    "operator_settlement_requests",
    "operator_task_settlement_runs",
    "operator_task_settlement_skips",
    "operator_ticket_settlement_revisions",
    "operator_ticket_note_settlements",
    "operator_ticket_note_leg_settlements",
    "operator_settlement_cash_links",
}


def _columns(engine, table_name: str) -> set[str]:
    return {
        str(column["name"])
        for column in inspect(engine).get_columns(table_name)
    }


def _unique_column_sets(engine, table_name: str) -> set[tuple[str, ...]]:
    return {
        tuple(str(column) for column in constraint["column_names"])
        for constraint in inspect(engine).get_unique_constraints(table_name)
    }


_AT = "2026-09-05T08:00:00+00:00"


def _insert_action(
    connection,
    action_id: str,
    action_type: str,
    actor_role: str,
    *,
    status: str = "accepted",
    payload: dict[str, object] | None = None,
    result_ref: tuple[str, str] | None = None,
) -> None:
    result_refs = (
        []
        if result_ref is None
        else [{"object_type": result_ref[0], "object_id": result_ref[1]}]
    )
    connection.execute(
        text(
            "INSERT INTO actions "
            "(action_id, action_type, actor_id, actor_role, requested_at, "
            "idempotency_key, request_hash, expected_versions_json, payload_json, "
            "policy_version, status, result_refs_json, committed_at) VALUES "
            "(:action_id, :action_type, 'migration-fixture', :actor_role, :at, "
            ":key, :hash, '{}', :payload, 'governance-v1', :status, :refs, "
            ":committed_at)"
        ),
        {
            "action_id": action_id,
            "action_type": action_type,
            "actor_role": actor_role,
            "at": _AT,
            "key": f"result-migration:{action_id}",
            "hash": f"hash:{action_id}",
            "payload": json.dumps(payload or {}, separators=(",", ":")),
            "status": status,
            "refs": json.dumps(result_refs, separators=(",", ":")),
            "committed_at": _AT if status == "committed" else None,
        },
    )


def _insert_result_set(
    connection,
    *,
    action_id: str,
    result_set_id: str = "result-set-1",
    lane: str = "jczq",
    prize_table_id: str | None = None,
) -> None:
    connection.execute(
        text(
            "INSERT INTO operator_result_set_families "
            "(result_set_family_id, task_family_id, lane, business_key, created_at) "
            "VALUES (:family_id, 'task-1', :lane, :business_key, :at)"
        ),
        {
            "family_id": f"family:{result_set_id}",
            "lane": lane,
            "business_key": f"business:{result_set_id}",
            "at": _AT,
        },
    )
    connection.execute(
        text(
            "INSERT INTO operator_result_set_revisions "
            "(result_set_revision_id, result_set_family_id, revision_no, "
            "supersedes_revision_id, task_family_id, work_item_id, lane, business_key, "
            "task_snapshot_hash, slate_revision_id, result_cutoff_at, importer_version, "
            "zucai_prize_table_revision_id, match_count, source_receipt_count, "
            "outcome_count, content_hash, action_id, created_at) VALUES "
            "(:result_set_id, :family_id, 1, NULL, 'task-1', 'work-1', :lane, "
            ":business_key, 'snapshot-1', 'slate-1', :at, 'migration-test-v1', "
            ":prize_table_id, 1, 3, 1, :content_hash, :action_id, :at)"
        ),
        {
            "result_set_id": result_set_id,
            "family_id": f"family:{result_set_id}",
            "lane": lane,
            "business_key": f"business:{result_set_id}",
            "at": _AT,
            "prize_table_id": prize_table_id,
            "content_hash": f"hash:{result_set_id}",
            "action_id": action_id,
        },
    )


def _insert_settlement_request(
    connection,
    *,
    request_id: str,
    action_id: str,
) -> None:
    connection.execute(
        text(
            "INSERT INTO operator_settlement_requests "
            "(settlement_request_id, action_id, task_family_id, work_item_id, "
            "task_snapshot_hash, slate_revision_id, result_set_revision_id, "
            "prize_table_revision_id, requested_at) VALUES "
            "(:request_id, :action_id, 'task-1', 'work-1', 'snapshot-1', "
            "'slate-1', 'result-set-1', NULL, :at)"
        ),
        {"request_id": request_id, "action_id": action_id, "at": _AT},
    )


def _insert_settlement_run(
    connection,
    *,
    run_id: str,
    request_id: str,
    request_action_id: str,
    settle_action_id: str,
    ticket_count: int = 0,
) -> None:
    state = "settled" if ticket_count else "not_applicable"
    connection.execute(
        text(
            "INSERT INTO operator_task_settlement_runs "
            "(settlement_run_id, settlement_request_id, request_action_id, "
            "settle_action_id, task_family_id, work_item_id, work_item_snapshot_hash, "
            "result_set_revision_id, prize_table_revision_id, settlement_method_version, "
            "rounding_policy_version, fixed_prize_policy_revision_ids_json, "
            "settlement_state, requested_ticket_count, eligible_ticket_count, "
            "settled_ticket_count, skipped_ticket_count, persisted_settlement_count, "
            "persisted_note_grade_count, persisted_leg_grade_count, persisted_cash_count, "
            "ticket_settlement_revision_ids_json, completed_at) VALUES "
            "(:run_id, :request_id, :request_action_id, :settle_action_id, 'task-1', "
            "'work-1', 'snapshot-1', 'result-set-1', NULL, 'settlement-v1', "
            "'cn_sporttery_jczq_v1', '[]', :state, :ticket_count, :ticket_count, "
            ":ticket_count, 0, :ticket_count, 0, 0, 0, :settlement_ids, :at)"
        ),
        {
            "run_id": run_id,
            "request_id": request_id,
            "request_action_id": request_action_id,
            "settle_action_id": settle_action_id,
            "state": state,
            "ticket_count": ticket_count,
            "settlement_ids": (
                '["settlement-1"]' if ticket_count else "[]"
            ),
            "at": _AT,
        },
    )


def test_migration_24_adds_result_and_settlement_storage_fresh_and_from_v23(
    tmp_path: Path,
) -> None:
    assert len(MIGRATIONS) >= 24
    for label, initial in (("fresh", ()), ("upgrade", MIGRATIONS[:23])):
        engine = build_ontology_engine(tmp_path / f"{label}.db")
        if initial:
            run_migrations(engine, initial)
            assert migration_status(engine).current_version == 23
            assert RESULT_TABLES.isdisjoint(inspect(engine).get_table_names())

        run_migrations(engine, MIGRATIONS[:24])

        assert migration_status(engine).current_version == 24
        assert RESULT_TABLES <= set(inspect(engine).get_table_names())


def test_migration_24_rebuilds_the_actual_v23_review_eligibility_shape(
    tmp_path: Path,
) -> None:
    engine = build_ontology_engine(tmp_path / "actual-v23-shape.db")
    run_migrations(engine, MIGRATIONS[:23])

    with engine.begin() as connection:
        for trigger_name in (
            "operator_review_eligibility_exact_source",
            "operator_review_eligibility_facts_no_update",
            "operator_review_eligibility_facts_no_delete",
        ):
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {trigger_name}")
        for index_row in connection.exec_driver_sql(
            "PRAGMA index_list(operator_review_eligibility_facts)"
        ).fetchall():
            index_name = str(index_row[1])
            if not index_name.startswith("sqlite_autoindex_"):
                quoted_name = connection.dialect.identifier_preparer.quote(index_name)
                connection.exec_driver_sql(f"DROP INDEX {quoted_name}")
        connection.exec_driver_sql(
            "ALTER TABLE operator_review_eligibility_facts "
            "RENAME TO operator_review_eligibility_facts_v24_shape"
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE operator_review_eligibility_facts (
              review_eligibility_fact_id TEXT PRIMARY KEY NOT NULL,
              action_id TEXT NOT NULL REFERENCES actions(action_id) ON DELETE RESTRICT,
              fact_index INTEGER NOT NULL,
              terminal_trigger TEXT NOT NULL,
              task_family_id TEXT NOT NULL,
              work_item_id TEXT NOT NULL,
              task_snapshot_hash TEXT NOT NULL,
              no_ticket_revision_id TEXT REFERENCES
                operator_no_ticket_revisions(no_ticket_revision_id) ON DELETE RESTRICT,
              artifact_terminal_receipt_id TEXT REFERENCES
                operator_artifact_terminal_receipts(artifact_terminal_receipt_id)
                ON DELETE RESTRICT,
              market_prior_baseline_revision_id TEXT REFERENCES
                operator_market_prior_baseline_revisions(
                  market_prior_baseline_revision_id
                ) ON DELETE RESTRICT,
              review_kind TEXT NOT NULL,
              readiness_condition TEXT NOT NULL,
              content_hash TEXT NOT NULL,
              created_at TEXT NOT NULL,
              CONSTRAINT ck_operator_review_eligibility_fact_index
                CHECK (fact_index >= 0),
              CONSTRAINT ck_operator_review_eligibility_terminal_trigger
                CHECK (terminal_trigger IN (
                  'no_ticket', 'artifact_terminal', 'official_cancellation'
                )),
              CONSTRAINT ck_operator_review_eligibility_source CHECK (
                (terminal_trigger = 'no_ticket'
                 AND no_ticket_revision_id IS NOT NULL
                 AND artifact_terminal_receipt_id IS NULL)
                OR
                (terminal_trigger IN ('artifact_terminal', 'official_cancellation')
                 AND no_ticket_revision_id IS NULL
                 AND artifact_terminal_receipt_id IS NOT NULL)
              ),
              CONSTRAINT ck_operator_review_eligibility_review_kind CHECK (
                review_kind IN ('operational_data_availability', 'forecast_truth')
              ),
              CONSTRAINT ck_operator_review_eligibility_readiness CHECK (
                readiness_condition IN ('immediate', 'outcomes_required')
              ),
              CONSTRAINT ck_operator_review_eligibility_kind_readiness CHECK (
                (review_kind = 'operational_data_availability'
                 AND readiness_condition = 'immediate'
                 AND market_prior_baseline_revision_id IS NULL)
                OR
                (review_kind = 'forecast_truth'
                 AND readiness_condition = 'outcomes_required'
                 AND market_prior_baseline_revision_id IS NOT NULL)
              ),
              CONSTRAINT uq_operator_review_eligibility_action_index
                UNIQUE (action_id, fact_index)
            )
            """
        )
        connection.exec_driver_sql(
            "DROP TABLE operator_review_eligibility_facts_v24_shape"
        )

    assert "settlement_run_id" not in _columns(
        engine,
        "operator_review_eligibility_facts",
    )
    run_migrations(engine, MIGRATIONS[:24])

    assert migration_status(engine).current_version == 24
    assert "settlement_run_id" in _columns(
        engine,
        "operator_review_eligibility_facts",
    )
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA integrity_check").scalar_one() == "ok"


def test_result_storage_has_revision_lineage_and_exact_money_fields(
    tmp_path: Path,
) -> None:
    engine = build_ontology_engine(tmp_path / "shape.db")
    run_migrations(engine)

    assert {
        "result_set_revision_id",
        "result_set_family_id",
        "revision_no",
        "supersedes_revision_id",
        "lane",
        "business_key",
        "task_snapshot_hash",
        "slate_revision_id",
        "result_cutoff_at",
        "importer_version",
        "content_hash",
        "action_id",
        "created_at",
    } <= _columns(engine, "operator_result_set_revisions")
    assert {
        "match_result_revision_id",
        "result_set_revision_id",
        "official_offer_revision_id",
        "match_id",
        "normalized_disposition",
        "normalized_home_90",
        "normalized_away_90",
        "agreement_state",
    } <= _columns(engine, "operator_result_match_revisions")
    assert {
        "result_source_receipt_id",
        "match_result_revision_id",
        "source_kind",
        "source_artifact_retrieval_id",
        "captured_at",
        "source_disposition",
        "home_90",
        "away_90",
        "receipt_state",
        "invalid_code",
    } <= _columns(engine, "operator_result_source_receipts")
    assert {
        "outcome_revision_id",
        "outcome_family_id",
        "revision_no",
        "supersedes_revision_id",
        "match_id",
        "match_result_revision_id",
        "result_set_revision_id",
        "result_disposition",
        "home_90",
        "away_90",
        "source_artifact_retrieval_ids_json",
        "recorded_at",
        "action_id",
    } <= _columns(engine, "operator_outcome_revisions")
    assert {
        "settlement_revision_id",
        "settlement_family_id",
        "revision_no",
        "supersedes_revision_id",
        "settlement_run_id",
        "ticket_id",
        "result_set_revision_id",
        "settlement_state",
        "currency",
        "paid_note_unit_count",
        "winning_note_unit_count",
        "void_note_unit_count",
        "gross_payout_minor",
        "action_id",
    } <= _columns(engine, "operator_ticket_settlement_revisions")
    assert {
        "settlement_cash_link_id",
        "settlement_revision_id",
        "transaction_id",
        "transaction_kind",
        "reverses_transaction_id",
        "amount_minor",
        "currency",
    } <= _columns(engine, "operator_settlement_cash_links")
    assert "settlement_run_id" in _columns(
        engine,
        "operator_review_eligibility_facts",
    )

    assert ("supersedes_revision_id",) in _unique_column_sets(
        engine,
        "operator_result_set_revisions",
    )
    assert ("supersedes_revision_id",) in _unique_column_sets(
        engine,
        "operator_outcome_revisions",
    )
    assert ("supersedes_revision_id",) in _unique_column_sets(
        engine,
        "operator_ticket_settlement_revisions",
    )
    assert ("reverses_transaction_id",) in _unique_column_sets(
        engine,
        "operator_settlement_cash_links",
    )


def test_result_and_settlement_business_rows_are_append_only(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "append-only.db")
    run_migrations(engine)

    with engine.connect() as connection:
        trigger_names = set(
            connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
            ).scalars()
        )

    for table_name in RESULT_TABLES:
        assert f"{table_name}_no_update" in trigger_names
        assert f"{table_name}_no_delete" in trigger_names


def test_result_revision_tables_enforce_linear_direct_predecessors(
    tmp_path: Path,
) -> None:
    engine = build_ontology_engine(tmp_path / "lineage.db")
    run_migrations(engine)

    with engine.connect() as connection:
        trigger_names = set(
            connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
            ).scalars()
        )

    for prefix in (
        "operator_result_set",
        "operator_outcome",
        "zucai_prize_table",
        "operator_ticket_settlement",
    ):
        assert {
            f"{prefix}_single_root",
            f"{prefix}_root_revision_no",
            f"{prefix}_linear_child",
        } <= trigger_names


def test_result_permissions_separate_import_request_and_execution(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "permissions.db")
    run_migrations(engine)
    action_types = {
        "import_result_evidence_set",
        "request_settlement",
        "settle_task",
    }

    with engine.connect() as connection:
        permissions = set(
            connection.execute(
                select(
                    schema.action_permissions.c.action_type,
                    schema.action_permissions.c.actor_role,
                ).where(schema.action_permissions.c.action_type.in_(action_types))
            )
        )

    assert permissions == {
        ("import_result_evidence_set", "deterministic_system"),
        ("request_settlement", "judge_operator"),
        ("settle_task", "deterministic_system"),
    }


def test_outcome_requires_the_same_import_action_as_its_result_set(
    tmp_path: Path,
) -> None:
    engine = build_ontology_engine(tmp_path / "outcome-action-binding.db")
    run_migrations(engine, MIGRATIONS[:24])

    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        _insert_action(
            connection,
            "import-result-set",
            "import_result_evidence_set",
            "deterministic_system",
        )
        _insert_action(
            connection,
            "import-unrelated",
            "import_result_evidence_set",
            "deterministic_system",
        )
        _insert_result_set(connection, action_id="import-result-set")
        connection.execute(
            text(
                "INSERT INTO operator_result_match_revisions "
                "(match_result_revision_id, result_set_revision_id, match_index, "
                "official_match_no, official_offer_revision_id, match_id, "
                "normalized_disposition, normalized_home_90, normalized_away_90, "
                "agreement_state) VALUES ('match-result-1', 'result-set-1', 0, "
                "'001', 'offer-1', 'match-1', 'played_90', 2, 1, 'agreed')"
            )
        )

        with pytest.raises(IntegrityError, match="same import Action"):
            connection.execute(
                text(
                    "INSERT INTO operator_outcome_revisions "
                    "(outcome_revision_id, outcome_family_id, revision_no, "
                    "supersedes_revision_id, outcome_index, match_id, "
                    "match_result_revision_id, result_set_revision_id, "
                    "result_disposition, home_90, away_90, "
                    "source_artifact_retrieval_ids_json, recorded_at, action_id) VALUES "
                    "('outcome-1', 'outcome-family-1', 1, NULL, 0, 'match-1', "
                    "'match-result-1', 'result-set-1', 'played_90', 2, 1, '[]', :at, "
                    "'import-unrelated')"
                ),
                {"at": _AT},
            )


def test_result_set_requires_prize_table_from_the_same_import_action(
    tmp_path: Path,
) -> None:
    engine = build_ontology_engine(tmp_path / "prize-action-binding.db")
    run_migrations(engine, MIGRATIONS[:24])

    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        _insert_action(
            connection,
            "import-result-set",
            "import_result_evidence_set",
            "deterministic_system",
        )
        _insert_action(
            connection,
            "import-prize-unrelated",
            "import_result_evidence_set",
            "deterministic_system",
        )
        connection.execute(
            text(
                "INSERT INTO zucai_prize_table_revisions "
                "(prize_table_revision_id, prize_table_family_id, revision_no, "
                "supersedes_revision_id, issue, currency, published_at, "
                "source_artifact_retrieval_id, tier_count, content_hash, action_id, "
                "created_at) VALUES ('prize-table-1', 'prize-family-1', 1, NULL, "
                "'26120', 'CNY', :at, 'retrieval-1', 3, 'prize-hash', "
                "'import-prize-unrelated', :at)"
            ),
            {"at": _AT},
        )

        with pytest.raises(IntegrityError, match="same import Action"):
            _insert_result_set(
                connection,
                action_id="import-result-set",
                lane="zucai",
                prize_table_id="prize-table-1",
            )


def test_settlement_run_rejects_another_type_correct_request_action(
    tmp_path: Path,
) -> None:
    engine = build_ontology_engine(tmp_path / "run-request-action-binding.db")
    run_migrations(engine, MIGRATIONS[:24])

    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        _insert_action(
            connection,
            "request-bound",
            "request_settlement",
            "judge_operator",
            status="committed",
            result_ref=("operator_settlement_request", "request-bound"),
        )
        _insert_action(
            connection,
            "request-unrelated-action",
            "request_settlement",
            "judge_operator",
            status="committed",
            result_ref=("operator_settlement_request", "request-unrelated"),
        )
        _insert_action(
            connection,
            "settle-action",
            "settle_task",
            "deterministic_system",
            payload={"settlement_request_id": "request-bound"},
        )
        _insert_settlement_request(
            connection,
            request_id="request-bound",
            action_id="request-bound",
        )

        with pytest.raises(IntegrityError, match="exact settlement request"):
            _insert_settlement_run(
                connection,
                run_id="run-1",
                request_id="request-bound",
                request_action_id="request-unrelated-action",
                settle_action_id="settle-action",
            )


def test_request_action_requires_the_exact_settlement_request_result_ref(
    tmp_path: Path,
) -> None:
    engine = build_ontology_engine(tmp_path / "request-result-ref-binding.db")
    run_migrations(engine, MIGRATIONS[:24])

    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        _insert_action(
            connection,
            "request-bound",
            "request_settlement",
            "judge_operator",
            payload={
                "result_set_revision_id": "result-set-1",
                "expected_task_snapshot_hash": "snapshot-1",
            },
        )
        _insert_settlement_request(
            connection,
            request_id="request-bound",
            action_id="request-bound",
        )

        with pytest.raises(IntegrityError, match="exact settlement request"):
            connection.execute(
                text(
                    "UPDATE actions SET status = 'committed', committed_at = :at, "
                    "result_refs_json = :refs WHERE action_id = 'request-bound'"
                ),
                {
                    "at": _AT,
                    "refs": json.dumps(
                        [
                            {
                                "object_type": "operator_settlement_request",
                                "object_id": "request-unrelated",
                            }
                        ],
                        separators=(",", ":"),
                    ),
                },
            )


def test_settlement_run_requires_its_request_actions_exact_result_ref(
    tmp_path: Path,
) -> None:
    engine = build_ontology_engine(tmp_path / "run-request-ref-binding.db")
    run_migrations(engine, MIGRATIONS[:24])

    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        _insert_action(
            connection,
            "request-bound",
            "request_settlement",
            "judge_operator",
            status="committed",
            result_ref=("operator_settlement_request", "request-unrelated"),
        )
        _insert_action(
            connection,
            "settle-action",
            "settle_task",
            "deterministic_system",
            payload={"settlement_request_id": "request-bound"},
        )
        _insert_settlement_request(
            connection,
            request_id="request-bound",
            action_id="request-bound",
        )

        with pytest.raises(IntegrityError, match="exact settlement request"):
            _insert_settlement_run(
                connection,
                run_id="run-1",
                request_id="request-bound",
                request_action_id="request-bound",
                settle_action_id="settle-action",
            )


def test_ticket_settlement_rejects_another_type_correct_settle_action(
    tmp_path: Path,
) -> None:
    engine = build_ontology_engine(tmp_path / "ticket-run-action-binding.db")
    run_migrations(engine, MIGRATIONS[:24])

    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        _insert_action(
            connection,
            "request-bound",
            "request_settlement",
            "judge_operator",
            status="committed",
            result_ref=("operator_settlement_request", "request-bound"),
        )
        _insert_action(
            connection,
            "settle-bound",
            "settle_task",
            "deterministic_system",
            payload={"settlement_request_id": "request-bound"},
        )
        _insert_action(
            connection,
            "settle-unrelated",
            "settle_task",
            "deterministic_system",
            payload={"settlement_request_id": "request-bound"},
        )
        _insert_settlement_request(
            connection,
            request_id="request-bound",
            action_id="request-bound",
        )
        _insert_settlement_run(
            connection,
            run_id="run-1",
            request_id="request-bound",
            request_action_id="request-bound",
            settle_action_id="settle-bound",
            ticket_count=1,
        )

        with pytest.raises(IntegrityError, match="exact settlement run"):
            connection.execute(
                text(
                    "INSERT INTO operator_ticket_settlement_revisions "
                    "(settlement_revision_id, settlement_family_id, revision_no, "
                    "supersedes_revision_id, settlement_index, settlement_run_id, "
                    "ticket_id, result_set_revision_id, prize_table_revision_id, "
                    "fixed_prize_policy_revision_id, method_version, "
                    "rounding_policy_version, settlement_state, currency, stake_minor, "
                    "distinct_note_count, paid_note_unit_count, winning_note_unit_count, "
                    "void_note_unit_count, gross_payout_minor, action_id, created_at) "
                    "VALUES ('settlement-1', 'settlement-family-1', 1, NULL, 0, "
                    "'run-1', 'ticket-1', 'result-set-1', NULL, NULL, "
                    "'settlement-v1', 'cn_sporttery_jczq_v1', 'settled', 'CNY', "
                    "200, 1, 1, 0, 0, 0, 'settle-unrelated', :at)"
                ),
                {"at": _AT},
            )


def test_settle_action_requires_the_exact_run_result_ref(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "settle-result-ref-binding.db")
    run_migrations(engine, MIGRATIONS[:24])

    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        _insert_action(
            connection,
            "request-bound",
            "request_settlement",
            "judge_operator",
            status="committed",
            result_ref=("operator_settlement_request", "request-bound"),
        )
        _insert_action(
            connection,
            "settle-bound",
            "settle_task",
            "deterministic_system",
            payload={"settlement_request_id": "request-bound"},
        )
        _insert_settlement_request(
            connection,
            request_id="request-bound",
            action_id="request-bound",
        )
        _insert_settlement_run(
            connection,
            run_id="run-1",
            request_id="request-bound",
            request_action_id="request-bound",
            settle_action_id="settle-bound",
        )

        with pytest.raises(IntegrityError, match="exact settlement run"):
            connection.execute(
                text(
                    "UPDATE actions SET status = 'committed', committed_at = :at, "
                    "result_refs_json = :refs WHERE action_id = 'settle-bound'"
                ),
                {
                    "at": _AT,
                    "refs": json.dumps(
                        [
                            {
                                "object_type": "operator_task_settlement_run",
                                "object_id": "run-unrelated",
                            }
                        ],
                        separators=(",", ":"),
                    ),
                },
            )
