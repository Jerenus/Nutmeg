from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from nutmeg.ontology.repository import schema, schema_market
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import MIGRATIONS, migration_status, run_migrations
from tests.ontology.operator.test_judgment_actions import (
    _baseline_request,
    _fixture,
)

CANDIDATE_TABLES = {
    "operator_candidate_generation_requests",
    "operator_candidate_set_revisions",
    "operator_candidates",
    "operator_candidate_tickets",
    "operator_candidate_ticket_legs",
    "operator_candidate_metrics",
    "operator_candidate_audit_findings",
    "operator_candidate_selections",
    "zucai_fixed_prize_policy_revisions",
    "zucai_fixed_prize_policy_tiers",
}


def test_migration_21_applies_fresh_and_from_v20(tmp_path: Path) -> None:
    for label, initial in (("fresh", ()), ("upgrade", MIGRATIONS[:20])):
        engine = build_ontology_engine(tmp_path / f"{label}.db")
        if initial:
            run_migrations(engine, initial)
        run_migrations(engine, MIGRATIONS[:21])

        assert migration_status(engine).current_version == 21
        assert CANDIDATE_TABLES <= set(inspect(engine).get_table_names())


def test_migration_21_backfills_populated_append_only_v20_baseline(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path, migrations=MIGRATIONS[:20])
    fixture.decision_actions.freeze_market_prior_baseline(_baseline_request(fixture))

    raw = fixture.engine.raw_connection()
    try:
        raw.execute("PRAGMA foreign_keys = OFF")
        raw.executescript(
            """
            DROP TRIGGER operator_market_prior_baseline_probabilities_no_update;
            DROP TRIGGER operator_market_prior_baseline_probabilities_no_delete;
            DROP TRIGGER operator_market_prior_baseline_probabilities_no_late_insert;
            ALTER TABLE operator_market_prior_baseline_probabilities
              RENAME TO operator_market_prior_baseline_probabilities_current;
            CREATE TABLE operator_market_prior_baseline_probabilities (
              market_prior_baseline_probability_id TEXT PRIMARY KEY NOT NULL,
              market_prior_baseline_revision_id TEXT NOT NULL,
              item_index INTEGER NOT NULL,
              match_id TEXT NOT NULL,
              official_offer_revision_id TEXT NOT NULL,
              market_definition_id TEXT NOT NULL,
              face_code TEXT NOT NULL,
              probability_decimal TEXT NOT NULL,
              market_snapshot_id TEXT NOT NULL,
              quote_id TEXT NOT NULL,
              UNIQUE (market_prior_baseline_revision_id, item_index),
              UNIQUE (
                market_prior_baseline_revision_id,
                match_id,
                market_definition_id,
                face_code
              )
            );
            INSERT INTO operator_market_prior_baseline_probabilities
            SELECT
              market_prior_baseline_probability_id,
              market_prior_baseline_revision_id,
              item_index,
              match_id,
              official_offer_revision_id,
              market_definition_id,
              face_code,
              probability_decimal,
              market_snapshot_id,
              quote_id
            FROM operator_market_prior_baseline_probabilities_current;
            DROP TABLE operator_market_prior_baseline_probabilities_current;
            CREATE TRIGGER operator_market_prior_baseline_probabilities_no_update
            BEFORE UPDATE ON operator_market_prior_baseline_probabilities
            BEGIN
              SELECT RAISE(
                ABORT,
                'operator_market_prior_baseline_probabilities is append-only'
              );
            END;
            CREATE TRIGGER operator_market_prior_baseline_probabilities_no_delete
            BEFORE DELETE ON operator_market_prior_baseline_probabilities
            BEGIN
              SELECT RAISE(
                ABORT,
                'operator_market_prior_baseline_probabilities is append-only'
              );
            END;
            """
        )
        raw.commit()
    finally:
        raw.close()

    run_migrations(fixture.engine, MIGRATIONS[:21])

    assert migration_status(fixture.engine).current_version == 21
    with fixture.engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT booked_decimal_odds, quote_captured_at "
                "FROM operator_market_prior_baseline_probabilities"
            )
        ).all()
        trigger_names = set(
            connection.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger' "
                    "AND tbl_name = 'operator_market_prior_baseline_probabilities'"
                )
            ).scalars()
        )
    assert len(rows) == 3
    assert all(odds is not None and captured_at is not None for odds, captured_at in rows)
    assert "operator_market_prior_baseline_probabilities_no_update" in trigger_names


def test_migration_21_upgrades_a_historical_v20_selection_table_without_deployable(
    tmp_path: Path,
) -> None:
    engine = build_ontology_engine(tmp_path / "historical-v20.db")
    run_migrations(engine, MIGRATIONS[:20])
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE selection_definitions DROP COLUMN deployable"
        )

    assert "deployable" not in {
        column["name"] for column in inspect(engine).get_columns("selection_definitions")
    }

    run_migrations(engine)

    columns = {
        column["name"] for column in inspect(engine).get_columns("selection_definitions")
    }
    with engine.connect() as connection:
        generic = connection.execute(
            text(
                "SELECT deployable FROM selection_definitions "
                "WHERE selection_id = 'sel-crs-other'"
            )
        ).scalar_one()
    assert "deployable" in columns
    assert generic == 0


def test_candidate_storage_is_normalized_and_set_kind_is_closed(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "candidate.db")
    run_migrations(engine)
    inspector = inspect(engine)

    assert {
        "candidate_set_revision_id",
        "candidate_set_family_id",
        "revision_no",
        "supersedes_revision_id",
        "generation_request_id",
        "task_family_id",
        "work_item_id",
        "task_snapshot_hash",
        "slate_revision_id",
        "market_prior_baseline_revision_id",
        "baseline_envelope_revision_id",
        "judgment_prescription_revision_id",
        "set_kind",
        "generator_version",
        "audit_policy_version",
        "candidate_count",
        "content_hash",
        "action_id",
        "created_at",
    } <= {
        column["name"]
        for column in inspector.get_columns("operator_candidate_set_revisions")
    }
    set_columns = {
        column["name"]
        for column in inspector.get_columns("operator_candidate_set_revisions")
    }
    candidate_columns = {
        column["name"] for column in inspector.get_columns("operator_candidates")
    }
    assert "comparison_only" in set_columns
    assert "comparison_only_count" not in set_columns
    assert {
        "candidate_revision_id",
        "candidate_set_revision_id",
        "candidate_index",
        "partition",
        "rank",
        "deployable",
        "leg_audit_completed",
        "prescription_audit_completed",
        "budget_check_completed",
        "deployment_report_completed",
        "content_hash",
    } <= candidate_columns
    assert "comparison_only" not in candidate_columns
    assert {
        "candidate_ticket_id",
        "candidate_revision_id",
        "ticket_index",
        "ticket_kind",
        "structure_code",
        "group_code",
        "currency",
        "unit_stake_minor",
        "unit_count",
        "stake_minor",
        "composition_hash",
        "fixed_prize_policy_revision_id",
    } <= {
        column["name"]
        for column in inspector.get_columns("operator_candidate_tickets")
    }
    assert {
        "candidate_ticket_id",
        "leg_index",
        "official_offer_revision_id",
        "match_id",
        "market_definition_id",
        "selection_code",
        "quote_id",
        "booked_decimal_odds",
        "settlement_parameter_decimal",
    } <= {
        column["name"]
        for column in inspector.get_columns("operator_candidate_ticket_legs")
    }

    create_sql = next(
        row[0]
        for row in engine.connect().execute(
            text(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'table' AND name = 'operator_candidate_set_revisions'"
            )
        )
    )
    assert "judgment_bound" in create_sql
    assert "conditional_market_counterfactual" in create_sql
    candidate_sql = next(
        row[0]
        for row in engine.connect().execute(
            text(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'table' AND name = 'operator_candidates'"
            )
        )
    )
    assert "partition IN ('eligible', 'audit_blocked', 'over_cap')" in candidate_sql
    assert "'comparison_only'" not in candidate_sql


def test_candidate_selection_is_a_revisioned_append_only_typed_object(
    tmp_path: Path,
) -> None:
    engine = build_ontology_engine(tmp_path / "selection-revisions.db")
    run_migrations(engine)
    inspector = inspect(engine)

    assert {
        "candidate_selection_id",
        "candidate_selection_family_id",
        "revision_no",
        "supersedes_revision_id",
        "candidate_set_revision_id",
        "candidate_revision_id",
        "task_family_id",
        "work_item_id",
        "task_snapshot_hash",
        "slate_revision_id",
        "reason",
        "content_hash",
        "action_id",
        "selected_at",
    } <= {
        column["name"]
        for column in inspector.get_columns("operator_candidate_selections")
    }
    trigger_names = {
        row[0]
        for row in engine.connect().execute(
            text(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'trigger' AND tbl_name = 'operator_candidate_selections'"
            )
        )
    }
    assert {
        "candidate_selection_single_root",
        "candidate_selection_linear_revision",
        "candidate_selection_typed_action",
        "operator_candidate_selections_no_update",
        "operator_candidate_selections_no_delete",
    } <= trigger_names


def test_migration_registers_closed_candidate_permissions_and_crs_aggregates(
    tmp_path: Path,
) -> None:
    engine = build_ontology_engine(tmp_path / "permissions.db")
    run_migrations(engine)

    with engine.connect() as connection:
        permissions = set(
            connection.execute(
                select(
                    schema.action_permissions.c.action_type,
                    schema.action_permissions.c.actor_role,
                ).where(
                    schema.action_permissions.c.action_type.in_(
                        {
                            "register_zucai_fixed_prize_policy",
                            "request_candidate_generation",
                            "generate_ticket_candidate_set",
                            "select_ticket_candidate",
                        }
                    )
                )
            )
        )
        crs = {
            row.outcome_key: (row.selection_id, row.deployable)
            for row in connection.execute(
                select(
                    schema_market.selection_definitions.c.selection_id,
                    schema_market.selection_definitions.c.outcome_key,
                    schema_market.selection_definitions.c.deployable,
                ).where(
                    schema_market.selection_definitions.c.market_definition_id == "md-crs"
                )
            )
        }

    assert permissions == {
        ("register_zucai_fixed_prize_policy", "deterministic_system"),
        ("request_candidate_generation", "judge_operator"),
        ("request_candidate_generation", "replay_adjudicator"),
        ("generate_ticket_candidate_set", "deterministic_system"),
        ("generate_ticket_candidate_set", "replay_adjudicator"),
        ("select_ticket_candidate", "judge_operator"),
    }
    assert crs["win_other"] == ("sel-crs-win-other", 1)
    assert crs["draw_other"] == ("sel-crs-draw-other", 1)
    assert crs["loss_other"] == ("sel-crs-loss-other", 1)
    assert crs["other"] == ("sel-crs-other", 0)


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
            "(action_id, action_type, actor_id, actor_role, requested_at, "
            "idempotency_key, request_hash, expected_versions_json, payload_json, "
            "policy_version, status, result_refs_json, committed_at) VALUES "
            "(:action_id, :action_type, 'migration-fixture', :actor_role, :at, "
            ":key, :hash, '{}', '{}', 'governance-v1', :status, '[]', :committed_at)"
        ),
        {
            "action_id": action_id,
            "action_type": action_type,
            "actor_role": actor_role,
            "at": "2026-09-04T08:00:00+00:00",
            "key": f"candidate-migration:{action_id}",
            "hash": f"hash:{action_id}",
            "status": status,
            "committed_at": (
                "2026-09-04T08:00:00+00:00" if status == "committed" else None
            ),
        },
    )


def _copy_generation_request(
    connection,
    *,
    source_request_id: str,
    generation_request_id: str,
    action_id: str,
) -> None:
    source = connection.execute(
        text(
            "SELECT * FROM operator_candidate_generation_requests "
            "WHERE generation_request_id = :request_id"
        ),
        {"request_id": source_request_id},
    ).mappings().one()
    values = dict(source)
    values.update(
        generation_request_id=generation_request_id,
        action_id=action_id,
        content_hash=f"hash:{generation_request_id}",
    )
    columns = tuple(values)
    connection.execute(
        text(
            "INSERT INTO operator_candidate_generation_requests ("
            + ", ".join(columns)
            + ") VALUES ("
            + ", ".join(f":{column}" for column in columns)
            + ")"
        ),
        values,
    )


def test_override_action_may_own_candidate_regeneration_but_other_authority_cannot(
    tmp_path: Path,
) -> None:
    from tests.ontology.operator.test_candidate_actions import (
        _generation_request,
        _ready_fixture,
    )

    fixture = _ready_fixture(tmp_path)
    original = fixture.judgment.decision_actions.request_candidate_generation(
        _generation_request(fixture)
    )
    source_request_id = original.result_refs[0].object_id

    with fixture.judgment.engine.begin() as connection:
        _insert_action(
            connection,
            "ACT-override-generation",
            action_type="record_ticket_audit_override",
            actor_role="judge_operator",
        )
        _copy_generation_request(
            connection,
            source_request_id=source_request_id,
            generation_request_id="generation-from-override",
            action_id="ACT-override-generation",
        )
        connection.execute(
            text(
                "INSERT INTO operator_worker_jobs "
                "(worker_job_id, job_kind, source_object_type, source_object_id, state, "
                "lease_owner, lease_expires_at, attempt_count, available_at, "
                "last_error_code, result_action_id, result_object_type, result_object_id, "
                "created_at, updated_at) VALUES "
                "('JOB-override-generation', 'candidate_generation', "
                "'operator_candidate_generation_request', 'generation-from-override', "
                "'queued', NULL, NULL, 0, :at, NULL, NULL, NULL, NULL, :at, :at)"
            ),
            {"at": "2026-09-04T08:00:00+00:00"},
        )

    for index, (action_type, actor_role) in enumerate(
        (
            ("record_ticket_audit_override", "ai_analyst"),
            ("record_no_ticket", "judge_operator"),
        )
    ):
        with pytest.raises(IntegrityError, match="requires its typed Action"):
            with fixture.judgment.engine.begin() as connection:
                action_id = f"ACT-invalid-generation-{index}"
                _insert_action(
                    connection,
                    action_id,
                    action_type=action_type,
                    actor_role=actor_role,
                )
                _copy_generation_request(
                    connection,
                    source_request_id=source_request_id,
                    generation_request_id=f"generation-invalid-{index}",
                    action_id=action_id,
                )


def test_fixed_prize_policy_requires_typed_action_and_freezes_children_after_commit(
    tmp_path: Path,
) -> None:
    engine = build_ontology_engine(tmp_path / "fixed-policy.db")
    run_migrations(engine)

    with engine.begin() as connection:
        _insert_action(
            connection,
            "ACT-wrong-policy",
            action_type="register_zucai_fixed_prize_policy",
            actor_role="judge_operator",
        )
        with pytest.raises(IntegrityError, match="requires its typed Action"):
            connection.execute(
                text(
                    "INSERT INTO zucai_fixed_prize_policy_revisions "
                    "(fixed_prize_policy_revision_id, fixed_prize_policy_family_id, "
                    "revision_no, supersedes_revision_id, policy_version, ticket_kind, "
                    "currency, standard_unit_stake_minor, official_void_rule, effective_at, "
                    "content_hash, action_id, created_at) VALUES "
                    "('policy-wrong', 'policy-family', 1, NULL, 'zucai-fixed-prize-v1', "
                    "'sfc', 'CNY', 200, 'all_faces_match', :at, 'hash-wrong', "
                    "'ACT-wrong-policy', :at)"
                ),
                {"at": "2026-09-04T08:00:00+00:00"},
            )

    with engine.begin() as connection:
        _insert_action(
            connection,
            "ACT-policy",
            action_type="register_zucai_fixed_prize_policy",
            actor_role="deterministic_system",
        )
        connection.execute(
            text(
                "INSERT INTO zucai_fixed_prize_policy_revisions "
                "(fixed_prize_policy_revision_id, fixed_prize_policy_family_id, "
                "revision_no, supersedes_revision_id, policy_version, ticket_kind, "
                "currency, standard_unit_stake_minor, official_void_rule, effective_at, "
                "content_hash, action_id, created_at) VALUES "
                "('policy-1', 'policy-family', 1, NULL, 'zucai-fixed-prize-v1', "
                "'sfc', 'CNY', 200, 'all_faces_match', :at, 'hash-1', 'ACT-policy', :at)"
            ),
            {"at": "2026-09-04T08:00:00+00:00"},
        )
        connection.execute(
            text(
                "INSERT INTO zucai_fixed_prize_policy_tiers "
                "(fixed_prize_policy_tier_id, fixed_prize_policy_revision_id, tier_index, "
                "tier_code, required_correct_count) VALUES "
                "('tier-1', 'policy-1', 0, 'sfc_first', 14)"
            )
        )
        connection.execute(
            text("UPDATE actions SET status = 'committed' WHERE action_id = 'ACT-policy'")
        )
        with pytest.raises(IntegrityError, match="append-only after commit"):
            connection.execute(
                text(
                    "INSERT INTO zucai_fixed_prize_policy_tiers "
                    "(fixed_prize_policy_tier_id, fixed_prize_policy_revision_id, "
                    "tier_index, tier_code, required_correct_count) VALUES "
                    "('tier-late', 'policy-1', 1, 'sfc_second', 13)"
                )
            )
        with pytest.raises(IntegrityError, match="append-only"):
            connection.execute(
                text(
                    "UPDATE zucai_fixed_prize_policy_revisions SET currency = 'USD' "
                    "WHERE fixed_prize_policy_revision_id = 'policy-1'"
                )
            )
