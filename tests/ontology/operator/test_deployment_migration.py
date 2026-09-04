from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.operator.decision_actions import SelectTicketCandidateRequest
from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import MIGRATIONS, migration_status, run_migrations
from tests.ontology.operator.test_candidate_actions import (
    _generate,
    _generation_request,
    _ready_fixture,
)
from tests.ontology.operator.test_judgment_actions import AT, WORK_ITEM_ID

DEPLOYMENT_TABLES = {
    "operator_ticket_decision_lineage_revisions",
    "operator_ticket_decision_lineage_items",
    "operator_ticket_audit_override_receipts",
    "operator_candidate_generation_override_links",
    "operator_no_ticket_revisions",
    "operator_no_ticket_offer_scopes",
    "operator_no_ticket_artifact_scopes",
    "operator_no_ticket_command_receipts",
    "operator_artifact_work_item_links",
    "operator_protected_artifact_bindings",
    "operator_protected_artifact_offer_revision_links",
    "operator_confirmation_challenge_revisions",
    "operator_confirmation_challenge_heads",
    "operator_artifact_terminal_receipts",
    "operator_review_eligibility_facts",
}


def _columns(engine, table_name: str) -> dict[str, dict[str, object]]:
    return {
        str(column["name"]): column
        for column in inspect(engine).get_columns(table_name)
    }


def _foreign_keys(engine, table_name: str) -> set[tuple[tuple[str, ...], str]]:
    return {
        (
            tuple(str(name) for name in item["constrained_columns"]),
            str(item["referred_table"]),
        )
        for item in inspect(engine).get_foreign_keys(table_name)
    }


def _unique_column_sets(engine, table_name: str) -> set[tuple[str, ...]]:
    return {
        tuple(str(column) for column in constraint["column_names"])
        for constraint in inspect(engine).get_unique_constraints(table_name)
    }


def test_migration_22_adds_exact_deployment_tables_fresh_and_from_v21(
    tmp_path: Path,
) -> None:
    v21_engine = build_ontology_engine(tmp_path / "v21.db")
    run_migrations(v21_engine, MIGRATIONS[:21])
    v21_tables = set(inspect(v21_engine).get_table_names())

    for label, initial in (("fresh", ()), ("upgrade", MIGRATIONS[:21])):
        engine = build_ontology_engine(tmp_path / f"{label}.db")
        if initial:
            run_migrations(engine, initial)
        run_migrations(engine, MIGRATIONS[:22])

        assert migration_status(engine).current_version == 22
        assert set(inspect(engine).get_table_names()) - v21_tables == DEPLOYMENT_TABLES


def test_migration_22_declares_normalized_bindings_and_restricted_foreign_keys(
    tmp_path: Path,
) -> None:
    engine = build_ontology_engine(tmp_path / "shape.db")
    run_migrations(engine)

    assert {
        "lineage_revision_id",
        "lineage_family_id",
        "revision_no",
        "supersedes_revision_id",
        "ticket_batch_revision_id",
        "task_family_id",
        "work_item_id",
        "task_snapshot_hash",
        "slate_revision_id",
        "task_evidence_bundle_revision_id",
        "market_prior_baseline_revision_id",
        "baseline_envelope_revision_id",
        "judgment_prescription_revision_id",
        "candidate_set_revision_id",
        "candidate_selection_id",
        "candidate_revision_id",
        "audit_policy_version",
        "content_hash",
        "action_id",
        "created_at",
    } == set(_columns(engine, "operator_ticket_decision_lineage_revisions"))
    assert {
        "lineage_item_id",
        "lineage_revision_id",
        "item_index",
        "candidate_ticket_id",
        "ticket_index",
        "candidate_ticket_leg_id",
        "leg_index",
        "official_offer_revision_id",
        "match_id",
        "market_definition_id",
        "selection_code",
        "market_prior_baseline_probability_id",
        "operator_match_judgment_revision_id",
        "forecast_revision_id",
    } == set(_columns(engine, "operator_ticket_decision_lineage_items"))

    binding_columns = _columns(engine, "operator_protected_artifact_bindings")
    assert {
        "protected_artifact_binding_id",
        "ticket_artifact_id",
        "lineage_revision_id",
        "candidate_revision_id",
        "candidate_ticket_id",
        "ticket_index",
        "ticket_kind",
        "stake_minor",
        "currency",
        "composition_hash",
        "fixed_prize_policy_revision_id",
        "frozen_deadline_at",
        "action_id",
        "created_at",
    } == set(binding_columns)
    assert all(
        not binding_columns[name]["nullable"]
        for name in (
            "ticket_artifact_id",
            "lineage_revision_id",
            "candidate_revision_id",
            "candidate_ticket_id",
            "ticket_index",
            "ticket_kind",
            "stake_minor",
            "currency",
            "composition_hash",
            "frozen_deadline_at",
            "created_at",
        )
    )
    assert (
        ("candidate_ticket_id",),
        "operator_candidate_tickets",
    ) in _foreign_keys(engine, "operator_protected_artifact_bindings")
    assert {
        ("ticket_artifact_id",),
        ("candidate_revision_id", "ticket_index"),
    } <= _unique_column_sets(engine, "operator_protected_artifact_bindings")

    terminal_fks = _foreign_keys(engine, "operator_artifact_terminal_receipts")
    assert (
        ("challenge_revision_id",),
        "operator_confirmation_challenge_revisions",
    ) in terminal_fks
    assert (
        ("ticket_artifact_id",),
        "audited_ticket_artifacts",
    ) in terminal_fks
    assert {
        ("ticket_artifact_id",),
        ("challenge_revision_id",),
    } <= _unique_column_sets(engine, "operator_artifact_terminal_receipts")

    challenge_fks = _foreign_keys(engine, "operator_confirmation_challenge_revisions")
    assert {
        (("ticket_artifact_id",), "audited_ticket_artifacts"),
        (
            ("lineage_revision_id",),
            "operator_ticket_decision_lineage_revisions",
        ),
        (
            ("supersedes_revision_id",),
            "operator_confirmation_challenge_revisions",
        ),
    } <= challenge_fks


def test_migration_22_permissions_are_judge_only_and_add_no_confirmation_authority(
    tmp_path: Path,
) -> None:
    engine = build_ontology_engine(tmp_path / "permissions.db")
    run_migrations(engine)
    action_types = {
        "record_ticket_audit_override",
        "record_no_ticket",
        "supersede_no_ticket",
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
        ("record_ticket_audit_override", "judge_operator"),
        ("record_no_ticket", "judge_operator"),
        ("supersede_no_ticket", "judge_operator"),
    }


@dataclass(frozen=True, slots=True)
class _DeploymentIds:
    engine: object
    task_family_id: str
    task_snapshot_hash: str
    slate_revision_id: str
    task_evidence_bundle_revision_id: str
    market_prior_baseline_revision_id: str
    market_prior_baseline_probability_id: str
    baseline_envelope_revision_id: str
    judgment_prescription_revision_id: str
    operator_match_judgment_revision_id: str
    forecast_revision_id: str
    candidate_set_revision_id: str
    candidate_selection_id: str
    candidate_revision_id: str
    candidate_ticket_id: str
    candidate_ticket_leg_id: str
    ticket_batch_revision_id: str
    ticket_artifact_id: str


def _insert_action(
    connection,
    action_id: str,
    action_type: str,
    *,
    actor_role: str = "judge_operator",
) -> None:
    connection.execute(
        text(
            "INSERT INTO actions "
            "(action_id, action_type, actor_id, actor_role, requested_at, "
            "idempotency_key, request_hash, expected_versions_json, payload_json, "
            "policy_version, status, result_refs_json, committed_at) VALUES "
            "(:action_id, :action_type, 'migration-fixture', :actor_role, :at, "
            ":key, :hash, '{}', '{}', 'governance-v1', 'accepted', '[]', NULL)"
        ),
        {
            "action_id": action_id,
            "action_type": action_type,
            "actor_role": actor_role,
            "at": AT.isoformat(),
            "key": f"deployment-migration:{action_id}",
            "hash": f"hash:{action_id}",
        },
    )


def _deployment_ids(tmp_path: Path) -> _DeploymentIds:
    fixture = _ready_fixture(tmp_path)
    request = fixture.judgment.decision_actions.request_candidate_generation(
        _generation_request(fixture)
    )
    _generate(fixture, request_id=request.result_refs[0].object_id)
    with fixture.judgment.engine.connect() as connection:
        candidate = connection.execute(
            text(
                "SELECT candidate_revision_id, candidate_set_revision_id "
                "FROM operator_candidates JOIN operator_candidate_set_revisions "
                "USING (candidate_set_revision_id) WHERE set_kind = 'judgment_bound'"
            )
        ).one()
    selected = fixture.judgment.decision_actions.select_ticket_candidate(
        SelectTicketCandidateRequest(
            candidate_set_revision_id=candidate.candidate_set_revision_id,
            candidate_revision_id=candidate.candidate_revision_id,
            reason="Jun selected this fixture candidate.",
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="deployment-migration:selection",
            requested_at=AT + timedelta(seconds=9),
            expected_current_revision_no=0,
        )
    )
    candidate_selection_id = selected.result_refs[0].object_id

    with fixture.judgment.engine.begin() as connection:
        context = connection.execute(
            text(
                "SELECT candidate_set.task_family_id, candidate_set.task_snapshot_hash, "
                "candidate_set.slate_revision_id, request.task_evidence_bundle_revision_id, "
                "candidate_set.market_prior_baseline_revision_id, "
                "candidate_set.baseline_envelope_revision_id, "
                "candidate_set.judgment_prescription_revision_id, "
                "ticket.candidate_ticket_id, leg.candidate_ticket_leg_id, "
                "judgment.operator_match_judgment_revision_id, judgment.forecast_revision_id, "
                "baseline.market_prior_baseline_probability_id "
                "FROM operator_candidate_set_revisions AS candidate_set "
                "JOIN operator_candidate_generation_requests AS request "
                "ON request.generation_request_id = candidate_set.generation_request_id "
                "JOIN operator_candidates AS candidate "
                "ON candidate.candidate_set_revision_id = candidate_set.candidate_set_revision_id "
                "JOIN operator_candidate_tickets AS ticket "
                "ON ticket.candidate_revision_id = candidate.candidate_revision_id "
                "JOIN operator_candidate_ticket_legs AS leg "
                "ON leg.candidate_ticket_id = ticket.candidate_ticket_id "
                "JOIN operator_judgment_prescription_items AS prescription_item "
                "ON prescription_item.judgment_prescription_revision_id = "
                "candidate_set.judgment_prescription_revision_id "
                "JOIN operator_match_judgment_revisions AS judgment "
                "ON judgment.operator_match_judgment_revision_id = "
                "prescription_item.operator_match_judgment_revision_id "
                "JOIN operator_market_prior_baseline_probabilities AS baseline "
                "ON baseline.market_prior_baseline_revision_id = "
                "candidate_set.market_prior_baseline_revision_id "
                "AND baseline.match_id = leg.match_id "
                "AND baseline.face_code = leg.selection_code "
                "WHERE candidate.candidate_revision_id = :candidate_revision_id"
            ),
            {"candidate_revision_id": candidate.candidate_revision_id},
        ).one()
        connection.execute(
            text(
                "INSERT INTO cash_accounts "
                "(account_id, channel_scope, currency, status) "
                "VALUES ('account-1', 'jczq', 'CNY', 'active')"
            )
        )
        _insert_action(connection, "action-batch-1", "create_ticket_batch")
        connection.execute(
            text(
                "INSERT INTO ticket_batch_revisions "
                "(ticket_batch_revision_id, ticket_batch_id, revision_no, "
                "supersedes_revision_id, run_date, channel, account_id, currency, "
                "deadline_at, input_legs_json, composition_json, audit_findings_json, "
                "state, content_hash, source_artifact_id, created_at, "
                "created_by_action_id) VALUES "
                "('batch-revision-1', 'batch-1', 1, NULL, '2026-09-04', 'jczq', "
                "'account-1', 'CNY', :deadline, '[]', '{}', '[]', 'draft', "
                ":content_hash, 'artifact-1', :at, 'action-batch-1')"
            ),
            {
                "deadline": (AT + timedelta(hours=4)).isoformat(),
                "content_hash": "d" * 64,
                "at": AT.isoformat(),
            },
        )
        _insert_action(connection, "action-approve-1", "approve_ticket_batch")
        connection.execute(
            text(
                "INSERT INTO audited_ticket_artifacts "
                "(ticket_artifact_id, ticket_batch_revision_id, ticket_index, "
                "ticket_hash, source_artifact_id, amount, currency, channel, "
                "deadline_at, payload_json, approved_at, approved_by_action_id) VALUES "
                "('ticket-artifact-1', 'batch-revision-1', 0, :ticket_hash, "
                "'artifact-1', 2.0, 'CNY', 'jczq', :deadline, '{}', :at, "
                "'action-approve-1')"
            ),
            {
                "ticket_hash": "e" * 64,
                "deadline": (AT + timedelta(hours=4)).isoformat(),
                "at": AT.isoformat(),
            },
        )

    return _DeploymentIds(
        engine=fixture.judgment.engine,
        task_family_id=context.task_family_id,
        task_snapshot_hash=context.task_snapshot_hash,
        slate_revision_id=context.slate_revision_id,
        task_evidence_bundle_revision_id=context.task_evidence_bundle_revision_id,
        market_prior_baseline_revision_id=context.market_prior_baseline_revision_id,
        market_prior_baseline_probability_id=context.market_prior_baseline_probability_id,
        baseline_envelope_revision_id=context.baseline_envelope_revision_id,
        judgment_prescription_revision_id=context.judgment_prescription_revision_id,
        operator_match_judgment_revision_id=context.operator_match_judgment_revision_id,
        forecast_revision_id=context.forecast_revision_id,
        candidate_set_revision_id=candidate.candidate_set_revision_id,
        candidate_selection_id=candidate_selection_id,
        candidate_revision_id=candidate.candidate_revision_id,
        candidate_ticket_id=context.candidate_ticket_id,
        candidate_ticket_leg_id=context.candidate_ticket_leg_id,
        ticket_batch_revision_id="batch-revision-1",
        ticket_artifact_id="ticket-artifact-1",
    )


def _lineage_values(ids: _DeploymentIds, *, suffix: str, revision_no: int = 1):
    predecessor = None if revision_no == 1 else "lineage-revision-1"
    return {
        "revision_id": f"lineage-revision-{suffix}",
        "family_id": "lineage-family-1",
        "revision_no": revision_no,
        "predecessor": predecessor,
        "batch_revision_id": ids.ticket_batch_revision_id,
        "task_family_id": ids.task_family_id,
        "work_item_id": WORK_ITEM_ID,
        "task_snapshot_hash": ids.task_snapshot_hash,
        "slate_revision_id": ids.slate_revision_id,
        "bundle_revision_id": ids.task_evidence_bundle_revision_id,
        "baseline_revision_id": ids.market_prior_baseline_revision_id,
        "envelope_revision_id": ids.baseline_envelope_revision_id,
        "prescription_revision_id": ids.judgment_prescription_revision_id,
        "candidate_set_revision_id": ids.candidate_set_revision_id,
        "selection_id": ids.candidate_selection_id,
        "candidate_revision_id": ids.candidate_revision_id,
        "audit_policy_version": "operator-candidate-audit-v1",
        "content_hash": suffix * 64,
        "action_id": f"action-lineage-{suffix}",
        "created_at": AT.isoformat(),
    }


def _insert_lineage(connection, values: dict[str, object]) -> None:
    _insert_action(connection, str(values["action_id"]), "create_ticket_batch")
    connection.execute(
        text(
            "INSERT INTO operator_ticket_decision_lineage_revisions "
            "(lineage_revision_id, lineage_family_id, "
            "revision_no, supersedes_revision_id, ticket_batch_revision_id, "
            "task_family_id, work_item_id, task_snapshot_hash, slate_revision_id, "
            "task_evidence_bundle_revision_id, market_prior_baseline_revision_id, "
            "baseline_envelope_revision_id, judgment_prescription_revision_id, "
            "candidate_set_revision_id, candidate_selection_id, candidate_revision_id, "
            "audit_policy_version, content_hash, action_id, created_at) VALUES "
            "(:revision_id, :family_id, :revision_no, :predecessor, :batch_revision_id, "
            ":task_family_id, :work_item_id, :task_snapshot_hash, :slate_revision_id, "
            ":bundle_revision_id, :baseline_revision_id, :envelope_revision_id, "
            ":prescription_revision_id, :candidate_set_revision_id, :selection_id, "
            ":candidate_revision_id, :audit_policy_version, :content_hash, :action_id, "
            ":created_at)"
        ),
        values,
    )


def _insert_lineage_item(connection, ids: _DeploymentIds) -> None:
    connection.execute(
        text(
            "INSERT INTO operator_ticket_decision_lineage_items "
            "(lineage_item_id, lineage_revision_id, "
            "item_index, candidate_ticket_id, ticket_index, candidate_ticket_leg_id, "
            "leg_index, official_offer_revision_id, match_id, market_definition_id, "
            "selection_code, market_prior_baseline_probability_id, "
            "operator_match_judgment_revision_id, forecast_revision_id) VALUES "
            "('lineage-item-1', 'lineage-revision-1', 0, :candidate_ticket_id, 0, "
            ":candidate_ticket_leg_id, 0, 'offer-revision-1', 'match-1', 'md-had', "
            "'3', :baseline_probability_id, :judgment_revision_id, :forecast_revision_id)"
        ),
        {
            "candidate_ticket_id": ids.candidate_ticket_id,
            "candidate_ticket_leg_id": ids.candidate_ticket_leg_id,
            "baseline_probability_id": ids.market_prior_baseline_probability_id,
            "judgment_revision_id": ids.operator_match_judgment_revision_id,
            "forecast_revision_id": ids.forecast_revision_id,
        },
    )


def test_lineage_and_no_ticket_are_append_only_linear_revision_families(
    tmp_path: Path,
) -> None:
    ids = _deployment_ids(tmp_path)
    with ids.engine.begin() as connection:
        root = _lineage_values(ids, suffix="1")
        _insert_lineage(connection, root)
        _insert_lineage_item(connection, ids)
        with pytest.raises(IntegrityError, match="root revision"):
            _insert_lineage(connection, _lineage_values(ids, suffix="root"))
        child = _lineage_values(ids, suffix="2", revision_no=2)
        child["batch_revision_id"] = ids.ticket_batch_revision_id
        _insert_lineage(connection, child)
        with pytest.raises(IntegrityError, match="directly follow"):
            invalid = _lineage_values(ids, suffix="3", revision_no=4)
            invalid["predecessor"] = "lineage-revision-2"
            _insert_lineage(connection, invalid)
        with pytest.raises(IntegrityError, match="append-only"):
            connection.execute(
                text(
                    "UPDATE operator_ticket_decision_lineage_revisions "
                    "SET content_hash = 'changed' WHERE "
                    "lineage_revision_id = 'lineage-revision-1'"
                )
            )
        with pytest.raises(IntegrityError, match="append-only"):
            connection.execute(
                text(
                    "DELETE FROM operator_ticket_decision_lineage_items "
                    "WHERE lineage_item_id = 'lineage-item-1'"
                )
            )

        for suffix, revision_no, predecessor, action_type in (
            ("1", 1, None, "record_no_ticket"),
            ("2", 2, "no-ticket-revision-1", "supersede_no_ticket"),
        ):
            action_id = f"action-no-ticket-{suffix}"
            _insert_action(connection, action_id, action_type)
            connection.execute(
                text(
                    "INSERT INTO operator_no_ticket_revisions "
                    "(no_ticket_revision_id, no_ticket_family_id, revision_no, "
                    "supersedes_revision_id, action_id, task_family_id, work_item_id, "
                    "task_snapshot_hash, slate_revision_id, reason_code, reason_basis, "
                    "reason_text, rule_ids_json, phase, requirement_snapshot_hash, "
                    "missing_requirement_ids_json, stale_requirement_ids_json, "
                    "conflicting_requirement_ids_json, market_prior_baseline_revision_id, "
                    "baseline_envelope_revision_id, candidate_set_revision_id, "
                    "comparison_candidate_revision_id, deployment_outcome, content_hash, "
                    "recorded_at) VALUES "
                    "(:revision_id, 'no-ticket-family-1', :revision_no, :predecessor, "
                    ":action_id, :task_family_id, :work_item_id, :snapshot_hash, "
                    ":slate_revision_id, 'operator_discretion', 'operator_judgment', "
                    "'Jun closed or reopened the remaining scope.', '[]', 'candidate', "
                    "NULL, '[]', '[]', '[]', :baseline_revision_id, "
                    ":envelope_revision_id, :candidate_set_revision_id, "
                    ":candidate_revision_id, :outcome, :content_hash, :recorded_at)"
                ),
                {
                    "revision_id": f"no-ticket-revision-{suffix}",
                    "revision_no": revision_no,
                    "predecessor": predecessor,
                    "action_id": action_id,
                    "task_family_id": ids.task_family_id,
                    "work_item_id": WORK_ITEM_ID,
                    "snapshot_hash": ids.task_snapshot_hash,
                    "slate_revision_id": ids.slate_revision_id,
                    "baseline_revision_id": ids.market_prior_baseline_revision_id,
                    "envelope_revision_id": ids.baseline_envelope_revision_id,
                    "candidate_set_revision_id": ids.candidate_set_revision_id,
                    "candidate_revision_id": ids.candidate_revision_id,
                    "outcome": "no_ticket" if revision_no == 1 else "reopened",
                    "content_hash": suffix * 64,
                    "recorded_at": AT.isoformat(),
                },
            )
        with pytest.raises(IntegrityError, match="append-only"):
            connection.execute(
                text(
                    "UPDATE operator_no_ticket_revisions SET reason_text = 'rewritten' "
                    "WHERE no_ticket_revision_id = 'no-ticket-revision-1'"
                )
            )

    with ids.engine.connect() as connection:
        lineage_leaf = connection.execute(
            text(
                "SELECT lineage_revision_id FROM "
                "operator_ticket_decision_lineage_revisions AS revision WHERE NOT EXISTS "
                "(SELECT 1 FROM operator_ticket_decision_lineage_revisions AS child "
                "WHERE child.supersedes_revision_id = "
                "revision.lineage_revision_id)"
            )
        ).scalar_one()
        no_ticket_leaf = connection.execute(
            text(
                "SELECT no_ticket_revision_id FROM operator_no_ticket_revisions AS revision "
                "WHERE NOT EXISTS (SELECT 1 FROM operator_no_ticket_revisions AS child "
                "WHERE child.supersedes_revision_id = revision.no_ticket_revision_id)"
            )
        ).scalar_one()
    assert lineage_leaf == "lineage-revision-2"
    assert no_ticket_leaf == "no-ticket-revision-2"


def _insert_artifact_binding(connection, ids: _DeploymentIds) -> None:
    connection.execute(
        text(
            "INSERT INTO operator_artifact_work_item_links "
            "(artifact_work_item_link_id, ticket_artifact_id, task_family_id, "
            "work_item_id, task_snapshot_hash, slate_revision_id, action_id, linked_at) "
            "VALUES ('artifact-work-link-1', :artifact_id, :task_family_id, :work_item_id, "
            ":snapshot_hash, :slate_revision_id, 'action-approve-1', :at)"
        ),
        {
            "artifact_id": ids.ticket_artifact_id,
            "task_family_id": ids.task_family_id,
            "work_item_id": WORK_ITEM_ID,
            "snapshot_hash": ids.task_snapshot_hash,
            "slate_revision_id": ids.slate_revision_id,
            "at": AT.isoformat(),
        },
    )
    connection.execute(
        text(
            "INSERT INTO operator_protected_artifact_bindings "
            "(protected_artifact_binding_id, ticket_artifact_id, "
            "lineage_revision_id, candidate_revision_id, "
            "candidate_ticket_id, ticket_index, ticket_kind, stake_minor, currency, "
            "composition_hash, fixed_prize_policy_revision_id, frozen_deadline_at, "
            "action_id, created_at) VALUES "
            "('binding-1', :artifact_id, 'lineage-revision-1', :candidate_revision_id, "
            ":candidate_ticket_id, 0, 'jczq_pass', 200, 'CNY', :composition_hash, NULL, "
            ":deadline, 'action-approve-1', :at)"
        ),
        {
            "artifact_id": ids.ticket_artifact_id,
            "candidate_revision_id": ids.candidate_revision_id,
            "candidate_ticket_id": ids.candidate_ticket_id,
            "composition_hash": "ticket-" + "a" * 64,
            "deadline": (AT + timedelta(hours=4)).isoformat(),
            "at": AT.isoformat(),
        },
    )
    connection.execute(
        text(
            "INSERT INTO operator_protected_artifact_offer_revision_links "
            "(protected_artifact_offer_revision_link_id, ticket_artifact_id, "
            "offer_index, official_offer_revision_id) VALUES "
            "('artifact-offer-link-1', :artifact_id, 0, 'offer-revision-1')"
        ),
        {"artifact_id": ids.ticket_artifact_id},
    )


def _insert_terminal_receipt(
    connection,
    *,
    receipt_id: str,
    action_id: str,
    terminal_kind: str,
    terminal_reason: str,
) -> None:
    connection.execute(
        text(
            "INSERT INTO operator_artifact_terminal_receipts "
            "(artifact_terminal_receipt_id, ticket_artifact_id, "
            "challenge_revision_id, terminal_kind, terminal_reason, "
            "effective_cutoff_at, terminal_at, action_id) VALUES "
            "(:receipt_id, 'ticket-artifact-1', NULL, :terminal_kind, "
            ":terminal_reason, :deadline, :at, :action_id)"
        ),
        {
            "receipt_id": receipt_id,
            "terminal_kind": terminal_kind,
            "terminal_reason": terminal_reason,
            "deadline": (AT + timedelta(hours=4)).isoformat(),
            "at": AT.isoformat(),
            "action_id": action_id,
        },
    )


def _insert_review_eligibility_fact(
    connection,
    ids: _DeploymentIds,
    *,
    fact_id: str,
    action_id: str,
    fact_index: int,
    terminal_trigger: str,
    no_ticket_revision_id: str | None,
    artifact_terminal_receipt_id: str | None,
) -> None:
    connection.execute(
        text(
            "INSERT INTO operator_review_eligibility_facts "
            "(review_eligibility_fact_id, action_id, fact_index, terminal_trigger, "
            "task_family_id, work_item_id, task_snapshot_hash, no_ticket_revision_id, "
            "artifact_terminal_receipt_id, market_prior_baseline_revision_id, "
            "review_kind, readiness_condition, content_hash, created_at) VALUES "
            "(:fact_id, :action_id, :fact_index, :terminal_trigger, :task_family_id, "
            ":work_item_id, :snapshot_hash, :no_ticket_revision_id, "
            ":artifact_terminal_receipt_id, :baseline_revision_id, 'forecast_truth', "
            "'outcomes_required', :content_hash, :created_at)"
        ),
        {
            "fact_id": fact_id,
            "action_id": action_id,
            "fact_index": fact_index,
            "terminal_trigger": terminal_trigger,
            "task_family_id": ids.task_family_id,
            "work_item_id": WORK_ITEM_ID,
            "snapshot_hash": ids.task_snapshot_hash,
            "no_ticket_revision_id": no_ticket_revision_id,
            "artifact_terminal_receipt_id": artifact_terminal_receipt_id,
            "baseline_revision_id": ids.market_prior_baseline_revision_id,
            "content_hash": f"review-{fact_id}",
            "created_at": AT.isoformat(),
        },
    )


def test_artifact_bindings_challenges_and_terminal_receipts_enforce_identity(
    tmp_path: Path,
) -> None:
    ids = _deployment_ids(tmp_path)
    with ids.engine.begin() as connection:
        _insert_lineage(connection, _lineage_values(ids, suffix="1"))
        _insert_lineage_item(connection, ids)
        _insert_artifact_binding(connection, ids)
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO operator_protected_artifact_bindings "
                    "(protected_artifact_binding_id, ticket_artifact_id, "
                    "lineage_revision_id, candidate_revision_id, "
                    "candidate_ticket_id, ticket_index, ticket_kind, stake_minor, currency, "
                    "composition_hash, fixed_prize_policy_revision_id, frozen_deadline_at, "
                    "action_id, created_at) VALUES "
                    "('binding-invalid', 'ticket-artifact-1', 'lineage-revision-1', "
                    ":candidate_revision_id, 'missing-ticket', 0, 'jczq_pass', 200, 'CNY', "
                    ":hash, NULL, :deadline, 'action-approve-1', :at)"
                ),
                {
                    "candidate_revision_id": ids.candidate_revision_id,
                    "hash": "0" * 64,
                    "deadline": (AT + timedelta(hours=4)).isoformat(),
                    "at": AT.isoformat(),
                },
            )
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "UPDATE operator_protected_artifact_bindings SET stake_minor = 400 "
                    "WHERE protected_artifact_binding_id = 'binding-1'"
                )
            )

        _insert_action(connection, "action-challenge-1", "issue_ticket_confirmation")
        connection.execute(
            text(
                "INSERT INTO operator_confirmation_challenge_revisions "
                "(challenge_revision_id, challenge_family_id, legacy_confirmation_id, "
                "revision_no, supersedes_revision_id, ticket_artifact_id, "
                "artifact_composition_hash, lineage_revision_id, "
                "nonce_hash, issued_at, effective_cutoff_at, action_id) VALUES "
                "('challenge-1', 'challenge-family-1', NULL, 1, NULL, "
                "'ticket-artifact-1', :hash, 'lineage-revision-1', :nonce, :at, "
                ":deadline, 'action-challenge-1')"
            ),
            {
                "hash": "ticket-" + "a" * 64,
                "nonce": "1" * 64,
                "at": AT.isoformat(),
                "deadline": (AT + timedelta(hours=4)).isoformat(),
            },
        )
        connection.execute(
            text(
                "INSERT INTO operator_confirmation_challenge_heads "
                "(ticket_artifact_id, challenge_revision_id, challenge_family_id, "
                "revision_no, updated_at) VALUES "
                "('ticket-artifact-1', 'challenge-1', 'challenge-family-1', 1, :at)"
            ),
            {"at": AT.isoformat()},
        )
        _insert_action(connection, "action-terminal-1", "record_no_ticket")
        connection.execute(
            text(
                "INSERT INTO operator_artifact_terminal_receipts "
                "(artifact_terminal_receipt_id, ticket_artifact_id, "
                "challenge_revision_id, terminal_kind, terminal_reason, "
                "effective_cutoff_at, terminal_at, action_id) VALUES "
                "('terminal-1', 'ticket-artifact-1', 'challenge-1', 'shadow', "
                "'human_no_ticket', :deadline, :at, 'action-terminal-1')"
            ),
            {
                "deadline": (AT + timedelta(hours=4)).isoformat(),
                "at": AT.isoformat(),
            },
        )
        for terminal_kind, terminal_reason in (
            ("placed", "human_no_ticket"),
            ("shadow", "actual_placement_confirmed"),
        ):
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        "INSERT INTO operator_artifact_terminal_receipts "
                        "(artifact_terminal_receipt_id, ticket_artifact_id, "
                        "challenge_revision_id, terminal_kind, terminal_reason, "
                        "effective_cutoff_at, terminal_at, action_id) VALUES "
                        "(:receipt_id, 'ticket-artifact-1', NULL, :kind, :reason, "
                        ":deadline, :at, 'action-terminal-1')"
                    ),
                    {
                        "receipt_id": f"terminal-{terminal_kind}-{terminal_reason}",
                        "kind": terminal_kind,
                        "reason": terminal_reason,
                        "deadline": (AT + timedelta(hours=4)).isoformat(),
                        "at": AT.isoformat(),
                    },
                )
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO operator_artifact_terminal_receipts "
                    "(artifact_terminal_receipt_id, ticket_artifact_id, "
                    "challenge_revision_id, terminal_kind, terminal_reason, "
                    "effective_cutoff_at, terminal_at, action_id) VALUES "
                    "('terminal-missing-challenge', 'ticket-artifact-1', "
                    "'challenge-missing', 'shadow', 'human_no_ticket', :deadline, :at, "
                    "'action-terminal-1')"
                ),
                {
                    "deadline": (AT + timedelta(hours=4)).isoformat(),
                    "at": AT.isoformat(),
                },
            )


def test_terminal_receipt_reason_requires_its_exact_creating_action(
    tmp_path: Path,
) -> None:
    ids = _deployment_ids(tmp_path)
    with ids.engine.begin() as connection:
        _insert_lineage(connection, _lineage_values(ids, suffix="1"))
        _insert_lineage_item(connection, ids)
        _insert_artifact_binding(connection, ids)

        invalid_provenance = (
            (
                "confirm_ticket_placement",
                "judge_operator",
                "shadow",
                "human_no_ticket",
            ),
            (
                "record_no_ticket",
                "judge_operator",
                "placed",
                "actual_placement_confirmed",
            ),
            (
                "mark_ticket_shadow",
                "deterministic_system",
                "shadow",
                "official_offer_cancelled",
            ),
            (
                "import_official_sale_slate",
                "deterministic_system",
                "shadow",
                "deadline_unconfirmed",
            ),
        )
        for index, (action_type, actor_role, terminal_kind, terminal_reason) in enumerate(
            invalid_provenance
        ):
            action_id = f"action-invalid-terminal-{index}"
            _insert_action(
                connection,
                action_id,
                action_type,
                actor_role=actor_role,
            )
            with pytest.raises(IntegrityError, match="exact typed Action"):
                _insert_terminal_receipt(
                    connection,
                    receipt_id=f"terminal-invalid-{index}",
                    action_id=action_id,
                    terminal_kind=terminal_kind,
                    terminal_reason=terminal_reason,
                )

        _insert_action(connection, "action-terminal-valid", "record_no_ticket")
        _insert_terminal_receipt(
            connection,
            receipt_id="terminal-valid",
            action_id="action-terminal-valid",
            terminal_kind="shadow",
            terminal_reason="human_no_ticket",
        )


@pytest.mark.parametrize("action_type", ("record_no_ticket", "supersede_no_ticket"))
@pytest.mark.parametrize(
    "terminal_reason",
    ("confirmation_not_requested", "deadline_unconfirmed"),
)
def test_cutoff_first_no_ticket_actions_may_record_deadline_terminal_receipts(
    tmp_path: Path,
    action_type: str,
    terminal_reason: str,
) -> None:
    ids = _deployment_ids(tmp_path)
    with ids.engine.begin() as connection:
        _insert_lineage(connection, _lineage_values(ids, suffix="1"))
        _insert_lineage_item(connection, ids)
        _insert_artifact_binding(connection, ids)
        action_id = f"action-cutoff-{action_type}"
        _insert_action(connection, action_id, action_type)
        _insert_terminal_receipt(
            connection,
            receipt_id=f"terminal-cutoff-{action_type}-{terminal_reason}",
            action_id=action_id,
            terminal_kind="shadow",
            terminal_reason=terminal_reason,
        )


def test_already_current_command_receipt_requires_existing_no_ticket_revision(
    tmp_path: Path,
) -> None:
    ids = _deployment_ids(tmp_path)
    with ids.engine.begin() as connection:
        _insert_action(connection, "action-already-current", "record_no_ticket")
        with pytest.raises(
            IntegrityError,
            match="ck_operator_no_ticket_command_revision_result",
        ):
            connection.execute(
                text(
                    "INSERT INTO operator_no_ticket_command_receipts "
                    "(no_ticket_command_receipt_id, action_id, command_kind, "
                    "no_ticket_revision_id, task_family_id, work_item_id, "
                    "submitted_task_snapshot_hash, resolved_task_snapshot_hash, "
                    "result, received_at) VALUES "
                    "('receipt-already-current', 'action-already-current', "
                    "'record_no_ticket', NULL, :task_family_id, :work_item_id, "
                    ":snapshot_hash, :snapshot_hash, 'already_current', :received_at)"
                ),
                {
                    "task_family_id": ids.task_family_id,
                    "work_item_id": WORK_ITEM_ID,
                    "snapshot_hash": ids.task_snapshot_hash,
                    "received_at": AT.isoformat(),
                },
            )


def test_review_eligibility_source_is_xor_and_reconciles_creating_action(
    tmp_path: Path,
) -> None:
    ids = _deployment_ids(tmp_path)
    with ids.engine.begin() as connection:
        _insert_lineage(connection, _lineage_values(ids, suffix="1"))
        _insert_lineage_item(connection, ids)
        _insert_artifact_binding(connection, ids)
        _insert_action(connection, "action-no-ticket-review", "record_no_ticket")
        connection.execute(
            text(
                "INSERT INTO operator_no_ticket_revisions "
                "(no_ticket_revision_id, no_ticket_family_id, revision_no, "
                "supersedes_revision_id, action_id, task_family_id, work_item_id, "
                "task_snapshot_hash, slate_revision_id, reason_code, reason_basis, "
                "reason_text, rule_ids_json, phase, requirement_snapshot_hash, "
                "missing_requirement_ids_json, stale_requirement_ids_json, "
                "conflicting_requirement_ids_json, market_prior_baseline_revision_id, "
                "baseline_envelope_revision_id, candidate_set_revision_id, "
                "comparison_candidate_revision_id, deployment_outcome, content_hash, "
                "recorded_at) VALUES "
                "('no-ticket-review', 'no-ticket-review-family', 1, NULL, "
                "'action-no-ticket-review', :task_family_id, :work_item_id, "
                ":snapshot_hash, :slate_revision_id, 'operator_discretion', "
                "'operator_judgment', 'Jun closed the remaining scope.', '[]', "
                "'candidate', NULL, '[]', '[]', '[]', :baseline_revision_id, "
                ":envelope_revision_id, :candidate_set_revision_id, "
                ":candidate_revision_id, 'no_ticket', :content_hash, :recorded_at)"
            ),
            {
                "task_family_id": ids.task_family_id,
                "work_item_id": WORK_ITEM_ID,
                "snapshot_hash": ids.task_snapshot_hash,
                "slate_revision_id": ids.slate_revision_id,
                "baseline_revision_id": ids.market_prior_baseline_revision_id,
                "envelope_revision_id": ids.baseline_envelope_revision_id,
                "candidate_set_revision_id": ids.candidate_set_revision_id,
                "candidate_revision_id": ids.candidate_revision_id,
                "content_hash": "n" * 64,
                "recorded_at": AT.isoformat(),
            },
        )
        _insert_terminal_receipt(
            connection,
            receipt_id="terminal-review",
            action_id="action-no-ticket-review",
            terminal_kind="shadow",
            terminal_reason="human_no_ticket",
        )

        _insert_review_eligibility_fact(
            connection,
            ids,
            fact_id="review-valid-no-ticket",
            action_id="action-no-ticket-review",
            fact_index=0,
            terminal_trigger="no_ticket",
            no_ticket_revision_id="no-ticket-review",
            artifact_terminal_receipt_id=None,
        )
        invalid_sources = (
            ("review-no-source", "no_ticket", None, None),
            (
                "review-two-sources",
                "no_ticket",
                "no-ticket-review",
                "terminal-review",
            ),
            (
                "review-wrong-trigger",
                "artifact_terminal",
                "no-ticket-review",
                None,
            ),
        )
        for fact_index, (
            fact_id,
            terminal_trigger,
            no_ticket_revision_id,
            artifact_terminal_receipt_id,
        ) in enumerate(invalid_sources, start=1):
            with pytest.raises(IntegrityError):
                _insert_review_eligibility_fact(
                    connection,
                    ids,
                    fact_id=fact_id,
                    action_id="action-no-ticket-review",
                    fact_index=fact_index,
                    terminal_trigger=terminal_trigger,
                    no_ticket_revision_id=no_ticket_revision_id,
                    artifact_terminal_receipt_id=artifact_terminal_receipt_id,
                )

        _insert_action(connection, "action-review-unrelated", "record_no_ticket")
        with pytest.raises(IntegrityError, match="creating Action"):
            _insert_review_eligibility_fact(
                connection,
                ids,
                fact_id="review-wrong-action",
                action_id="action-review-unrelated",
                fact_index=0,
                terminal_trigger="no_ticket",
                no_ticket_revision_id="no-ticket-review",
                artifact_terminal_receipt_id=None,
            )


def test_protected_artifact_offer_links_require_exact_order_and_complete_coverage(
    tmp_path: Path,
) -> None:
    ids = _deployment_ids(tmp_path)
    with ids.engine.begin() as connection:
        _insert_lineage(connection, _lineage_values(ids, suffix="1"))
        _insert_lineage_item(connection, ids)
        connection.execute(
            text(
                "INSERT INTO operator_artifact_work_item_links "
                "(artifact_work_item_link_id, ticket_artifact_id, task_family_id, "
                "work_item_id, task_snapshot_hash, slate_revision_id, action_id, "
                "linked_at) VALUES ('artifact-work-link-1', :artifact_id, "
                ":task_family_id, :work_item_id, :snapshot_hash, :slate_revision_id, "
                "'action-approve-1', :at)"
            ),
            {
                "artifact_id": ids.ticket_artifact_id,
                "task_family_id": ids.task_family_id,
                "work_item_id": WORK_ITEM_ID,
                "snapshot_hash": ids.task_snapshot_hash,
                "slate_revision_id": ids.slate_revision_id,
                "at": AT.isoformat(),
            },
        )
        connection.execute(
            text(
                "INSERT INTO operator_protected_artifact_bindings "
                "(protected_artifact_binding_id, ticket_artifact_id, "
                "lineage_revision_id, candidate_revision_id, candidate_ticket_id, "
                "ticket_index, ticket_kind, stake_minor, currency, composition_hash, "
                "fixed_prize_policy_revision_id, frozen_deadline_at, action_id, "
                "created_at) VALUES ('binding-1', :artifact_id, 'lineage-revision-1', "
                ":candidate_revision_id, :candidate_ticket_id, 0, 'jczq_pass', 200, "
                "'CNY', :composition_hash, NULL, :deadline, 'action-approve-1', :at)"
            ),
            {
                "artifact_id": ids.ticket_artifact_id,
                "candidate_revision_id": ids.candidate_revision_id,
                "candidate_ticket_id": ids.candidate_ticket_id,
                "composition_hash": "ticket-" + "a" * 64,
                "deadline": (AT + timedelta(hours=4)).isoformat(),
                "at": AT.isoformat(),
            },
        )

        with pytest.raises(IntegrityError, match="ordered candidate offer"):
            connection.execute(
                text(
                    "INSERT INTO operator_protected_artifact_offer_revision_links "
                    "(protected_artifact_offer_revision_link_id, ticket_artifact_id, "
                    "offer_index, official_offer_revision_id) VALUES "
                    "('artifact-offer-wrong-order', :artifact_id, 1, "
                    "'offer-revision-1')"
                ),
                {"artifact_id": ids.ticket_artifact_id},
            )

        with pytest.raises(IntegrityError, match="complete ordered offer coverage"):
            connection.execute(
                text(
                    "UPDATE actions SET status = 'committed', committed_at = :at "
                    "WHERE action_id = 'action-approve-1'"
                ),
                {"at": AT.isoformat()},
            )

        connection.execute(
            text(
                "INSERT INTO operator_protected_artifact_offer_revision_links "
                "(protected_artifact_offer_revision_link_id, ticket_artifact_id, "
                "offer_index, official_offer_revision_id) VALUES "
                "('artifact-offer-link-1', :artifact_id, 0, 'offer-revision-1')"
            ),
            {"artifact_id": ids.ticket_artifact_id},
        )
        connection.execute(
            text(
                "UPDATE actions SET status = 'committed', committed_at = :at "
                "WHERE action_id = 'action-approve-1'"
            ),
            {"at": AT.isoformat()},
        )


def test_override_review_and_no_ticket_storage_have_closed_checks_and_server_times(
    tmp_path: Path,
) -> None:
    engine = build_ontology_engine(tmp_path / "closed-checks.db")
    run_migrations(engine)

    for table_name, timestamp_column in (
        ("operator_ticket_audit_override_receipts", "recorded_at"),
        ("operator_no_ticket_revisions", "recorded_at"),
        ("operator_no_ticket_command_receipts", "received_at"),
        ("operator_artifact_terminal_receipts", "terminal_at"),
        ("operator_review_eligibility_facts", "created_at"),
    ):
        assert not _columns(engine, table_name)[timestamp_column]["nullable"]

    no_ticket_sql = engine.connect().execute(
        text(
            "SELECT sql FROM sqlite_master WHERE type = 'table' "
            "AND name = 'operator_no_ticket_revisions'"
        )
    ).scalar_one()
    assert all(
        value in no_ticket_sql
        for value in (
            "human_all_dice",
            "evidence_incomplete",
            "no_compliant_structure_within_cap",
            "discipline_brake",
            "operator_discretion",
            "rule_derived",
            "operator_judgment",
        )
    )
    review_sql = engine.connect().execute(
        text(
            "SELECT sql FROM sqlite_master WHERE type = 'table' "
            "AND name = 'operator_review_eligibility_facts'"
        )
    ).scalar_one()
    assert all(
        value in review_sql
        for value in (
            "operational_data_availability",
            "forecast_truth",
            "immediate",
            "outcomes_required",
        )
    )
