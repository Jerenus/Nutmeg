from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import (
    MIGRATIONS,
    migration_status,
    run_migrations,
)


def test_jczq_board_research_state_schema_is_additive_and_append_only(tmp_path):
    engine = build_ontology_engine(tmp_path / "ontology.db")

    first = run_migrations(engine)
    second = run_migrations(engine)

    assert 32 in first.applied_versions
    assert second.applied_versions == ()
    assert migration_status(engine).current_version == 37
    assert "operator_jczq_board_research_states" in inspect(engine).get_table_names()
    with engine.begin() as connection:
        permission = connection.scalar(
            text(
                "SELECT COUNT(*) FROM action_permissions "
                "WHERE action_type = 'reconcile_jczq_board_research' "
                "AND actor_role = 'deterministic_system'"
            )
        )
    assert permission == 1


def test_jczq_board_research_state_rows_cannot_be_updated(tmp_path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO actions "
                "(action_id, action_type, actor_id, actor_role, requested_at, "
                "idempotency_key, request_hash, payload_json, expected_versions_json, "
                "policy_version, status, result_refs_json, committed_at, error_code, "
                "error_detail) VALUES "
                "('ACT-board', 'reconcile_jczq_board_research', 'system:test', "
                "'deterministic_system', '2026-09-19T08:00:00+00:00', 'board:test', "
                "'hash', '{}', '{}', 'governance-v1', 'committed', '[]', "
                "'2026-09-19T08:00:00+00:00', NULL, NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO operator_jczq_board_research_states VALUES "
                "('state-1', '2026-09-19', 'match-1', '001', 'price_only', "
                "NULL, NULL, NULL, '2026-09-19T18:00:00+00:00', 0, "
                "'ACT-board', '2026-09-19T08:00:00+00:00')"
            )
        )
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE operator_jczq_board_research_states "
                    "SET status = 'rejected' WHERE board_research_state_id = 'state-1'"
                )
            )
    except IntegrityError:
        pass
    else:
        raise AssertionError("board research state update should be blocked")


def test_v33_backfills_v32_board_states_as_revision_one(tmp_path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine, MIGRATIONS[:32])
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO actions "
                "(action_id, action_type, actor_id, actor_role, requested_at, "
                "idempotency_key, request_hash, payload_json, expected_versions_json, "
                "policy_version, status, result_refs_json, committed_at, error_code, "
                "error_detail) VALUES "
                "('ACT-board', 'reconcile_jczq_board_research', 'system:test', "
                "'deterministic_system', '2026-09-19T08:00:00+00:00', 'board:test', "
                "'hash', '{}', '{}', 'governance-v1', 'committed', '[]', "
                "'2026-09-19T08:00:00+00:00', NULL, NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO operator_jczq_board_research_states VALUES "
                "('state-1', '2026-09-19', 'match-1', '001', 'price_only', "
                "NULL, NULL, NULL, '2026-09-19T18:00:00+00:00', 0, "
                "'ACT-board', '2026-09-19T08:00:00+00:00')"
            )
        )

    run_migrations(engine, MIGRATIONS[:33])

    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT revision_no, supersedes_revision_id, status, match_id "
                "FROM operator_jczq_board_research_state_revisions"
            )
        ).one()
    assert row == (1, None, "price_only", "match-1")
