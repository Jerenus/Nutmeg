from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from sqlalchemy import inspect, select, text

from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.operator.decision_actions import (
    NoTicketDecisionContext,
    OperatorDecisionActions,
    RecordNoTicketRequest,
)
from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository.migrations import MIGRATIONS, migration_status, run_migrations
from tests.ontology.operator.test_judgment_actions import (
    AT,
    WORK_ITEM_ID,
)
from tests.ontology.operator.test_judgment_actions import (
    _fixture as _judgment_fixture,
)

REVIEW_TABLES = {
    "operator_review_items",
    "operator_scoreboard_effect_disposition_revisions",
    "operator_scoreboard_review_observation_links",
    "operator_scoreboard_review_completion_requests",
    "operator_scoreboard_review_completion_receipts",
}


def _columns(engine, table_name: str) -> set[str]:
    return {str(column["name"]) for column in inspect(engine).get_columns(table_name)}


def _seed_immediate_fact_before_v25(tmp_path: Path):
    fixture = _judgment_fixture(tmp_path, migrations=MIGRATIONS[:24])

    def context_resolver(_uow, **scope) -> NoTicketDecisionContext:
        current = fixture.decision_actions.no_ticket_decision_context(
            task_family_id="jczq:2026-09-04",
            lane="jczq",
            business_key="2026-09-04",
            work_item_id=WORK_ITEM_ID,
            as_of=scope["as_of"],
        )
        return replace(
            current,
            phase="evidence",
            requirement_snapshot_hash="a" * 64,
            missing_requirement_ids=("E2",),
            stale_requirement_ids=(),
            conflicting_requirement_ids=(),
            market_prior_baseline_revision_id=None,
            baseline_envelope_revision_id=None,
            candidate_set_revision_id=None,
            comparison_candidate_revision_ids=(),
        )

    actions = OperatorDecisionActions(
        fixture.action_service,
        no_ticket_context_resolver=context_resolver,
    )
    context = context_resolver(None, as_of=AT + timedelta(minutes=1))
    outcome = actions.record_no_ticket(
        RecordNoTicketRequest(
            task_family_id="jczq:2026-09-04",
            lane="jczq",
            business_key="2026-09-04",
            work_item_id=WORK_ITEM_ID,
            expected_task_snapshot_hash=context.task_snapshot_hash,
            expected_scope_fingerprint=context.scope_fingerprint,
            reason_code="evidence_incomplete",
            reason_basis="rule_derived",
            reason_text="Required evidence was unavailable before the cutoff.",
            rule_ids=("EVIDENCE-GATE",),
            comparison_candidate_revision_id=None,
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="review-migration:no-ticket",
            requested_at=AT + timedelta(minutes=1),
        )
    )
    fact_id = next(
        ref.object_id
        for ref in outcome.result_refs
        if ref.object_type == "operator_review_eligibility_fact"
    )
    return fixture.engine, fact_id


def test_migration_25_adds_review_storage_fresh_and_from_v24(tmp_path: Path) -> None:
    assert len(MIGRATIONS) >= 25
    target_migrations = MIGRATIONS[:25]
    for label, initial in (("fresh", ()), ("upgrade", MIGRATIONS[:24])):
        engine = _judgment_fixture(
            tmp_path / label,
            migrations=initial or target_migrations,
        ).engine
        if initial:
            assert migration_status(engine).current_version == 24
            assert REVIEW_TABLES.isdisjoint(inspect(engine).get_table_names())
            run_migrations(engine, target_migrations)

        assert migration_status(engine).current_version == 25
        assert REVIEW_TABLES <= set(inspect(engine).get_table_names())


def test_review_storage_is_normalized_and_append_only(tmp_path: Path) -> None:
    engine = _judgment_fixture(tmp_path).engine

    assert {
        "review_id",
        "review_eligibility_fact_id",
        "task_family_id",
        "work_item_id",
        "task_snapshot_hash",
        "lane",
        "business_key",
        "review_kind",
        "market_prior_baseline_revision_id",
        "outcome_revision_ids_json",
        "materialized_by_action_id",
        "materialized_at",
    } == _columns(engine, "operator_review_items")
    assert {
        "disposition_revision_id",
        "family_id",
        "revision_no",
        "supersedes_revision_id",
        "review_id",
        "disposition",
        "reason",
        "pre_update_legacy_sha256",
        "required_metric_keys_json",
        "created_by_action_id",
        "created_at",
    } == _columns(engine, "operator_scoreboard_effect_disposition_revisions")
    assert {
        "completion_receipt_id",
        "review_id",
        "disposition_revision_id",
        "completion_request_id",
        "post_update_legacy_sha256",
        "observation_action_ids_json",
        "shadow_review_id",
        "shadow_source_high_watermark",
        "completed_by_action_id",
        "completed_at",
    } == _columns(engine, "operator_scoreboard_review_completion_receipts")

    with engine.connect() as connection:
        trigger_names = set(
            connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
            ).scalars()
        )
    for table_name in REVIEW_TABLES:
        assert f"{table_name}_no_update" in trigger_names
        assert f"{table_name}_no_delete" in trigger_names
    assert {
        "operator_scoreboard_disposition_single_root",
        "operator_scoreboard_disposition_linear_child",
        "operator_scoreboard_disposition_before_completion",
        "operator_review_eligibility_enqueue_materialization",
        "operator_scoreboard_completion_request_enqueue",
    } <= trigger_names


def test_migration_24_enqueues_and_v25_preserves_one_job_per_existing_fact(
    tmp_path: Path,
) -> None:
    engine, fact_id = _seed_immediate_fact_before_v25(tmp_path)
    with engine.connect() as connection:
        before_upgrade = connection.execute(
            text(
                "SELECT worker_job_id, source_object_type, source_object_id, state "
                "FROM operator_worker_jobs WHERE job_kind = 'review_materialization'"
            )
        ).one()
    assert before_upgrade == (
        f"review-materialization:{fact_id}",
        "operator_review_eligibility_fact",
        fact_id,
        "queued",
    )

    run_migrations(engine)
    run_migrations(engine)

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT worker_job_id, source_object_type, source_object_id, state "
                "FROM operator_worker_jobs WHERE job_kind = 'review_materialization'"
            )
        ).all()
    assert rows == [before_upgrade]


def test_review_action_permissions_keep_judgment_out_of_system_roles(tmp_path: Path) -> None:
    engine = _judgment_fixture(tmp_path).engine
    action_types = {
        "materialize_operator_review_item",
        "record_scoreboard_effect_disposition",
        "request_scoreboard_review_completion",
        "complete_scoreboard_review",
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
        ("materialize_operator_review_item", "deterministic_system"),
        ("record_scoreboard_effect_disposition", "judge_operator"),
        ("request_scoreboard_review_completion", "judge_operator"),
        ("complete_scoreboard_review", "deterministic_system"),
    }
