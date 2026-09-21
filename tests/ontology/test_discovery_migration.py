from __future__ import annotations

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import migration_status, run_migrations

EXPECTED_TABLES = {
    "protected_shadow_receipts",
    "policy_scope_reviews",
    "discovery_worlds",
    "discovery_world_events",
    "discovery_runs",
    "discovery_nodes",
    "discovery_node_evaluations",
    "exploration_policy_revisions",
    "exploration_policy_parent_links",
    "policy_replay_runs",
    "policy_replay_rounds",
    "policy_replay_completions",
    "policy_tournaments",
    "policy_tournament_candidates",
    "policy_tournament_worlds",
    "policy_tournament_results",
    "policy_tournament_completions",
    "policy_archive_decisions",
    "policy_holdout_exposures",
    "policy_deployments",
    "policy_brake_events",
}


def test_migration_40_creates_discovery_tables_and_permissions(tmp_path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    assert migration_status(engine).current_version == 44
    assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        rows = connection.exec_driver_sql(
            "SELECT action_type, actor_role FROM action_permissions "
            "WHERE action_type LIKE '%discovery%' OR action_type LIKE 'register_policy%' "
            "OR action_type LIKE '%policy_replay' OR action_type LIKE '%policy_tournament' "
            "OR action_type LIKE '%policy_deployment' OR action_type='trip_policy_brake'"
        ).all()
    assert ("approve_policy_deployment", "judge_operator") in rows
    assert ("approve_policy_deployment", "deterministic_system") not in rows
    assert ("trip_policy_brake", "deterministic_system") in rows


def test_generation_round_migration_is_append_only_and_role_separated(tmp_path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    assert "policy_generation_rounds" in inspect(engine).get_table_names()
    with engine.connect() as connection:
        roles = (
            connection.exec_driver_sql(
                "SELECT actor_role FROM action_permissions "
                "WHERE action_type='record_policy_generation_round'"
            )
            .scalars()
            .all()
        )
    assert roles == ["deterministic_system"]


def test_promotion_window_migration_is_append_only_and_human_only(tmp_path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    assert "policy_shadow_windows" in inspect(engine).get_table_names()
    with engine.connect() as connection:
        roles = (
            connection.exec_driver_sql(
                "SELECT actor_role FROM action_permissions "
                "WHERE action_type='preregister_policy_shadow_window'"
            )
            .scalars()
            .all()
        )
    assert roles == ["judge_operator"]


def test_discovery_base_rows_are_append_only(tmp_path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO exploration_policy_revisions "
            "(policy_revision_id,family,source_artifact_hash,interface_version,"
            "constraints_version,generator_family,generator_revision,generation_trace_hash,"
            "generator_descriptors_json,generation_input_manifest_hash,"
            "generation_budget_json,generation_cost_json,generation_timeout_seconds,"
            "rationale,change_summary,configuration_json,random_seed_policy_json,"
            "compatible_world_families_json,max_resource_permissions_json,"
            "change_surfaces_json,novelty_descriptors_json,validation_result_json,"
            "created_by,created_at,action_id) VALUES "
            "('p1','f','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',"
            "'v1','c1','baseline','g1',NULL,'{}',"
            "'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',"
            "'{}','{}',1,'r','s','{}','{}','[]','{}','[]','{}','{}',"
            "'op','2026-09-21T00:00:00+00:00','a1')"
        )
    with pytest.raises(IntegrityError, match="append-only"):
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "UPDATE exploration_policy_revisions SET rationale='changed' "
                "WHERE policy_revision_id='p1'"
            )
