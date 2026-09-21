from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from nutmeg.discovery.generator_evolution import generate_evolution
from nutmeg.ontology.actions.discovery_policy_actions import (
    DiscoveryPolicyActions,
    RecordPolicyGenerationRoundRequest,
)
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.discovery.models import canonical_hash
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.discovery import PolicyGenerationRoundRow
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from tests.discovery.test_generator_evolution import _context, _ready
from tests.ontology.test_discovery_policy_actions import _registration


def _round():
    manifest = {
        "development_worlds": [],
        "eligible_parent_ids": [],
        "generator_revision": "baseline-v1",
    }
    trace = {"attempts": [], "proposals": []}
    return PolicyGenerationRoundRow(
        generation_round_id="round-1",
        generator_family="baseline",
        generator_revision="baseline-v1",
        generator_artifact_hash=canonical_hash({"revision": "baseline-v1"}),
        input_manifest_hash=canonical_hash(manifest),
        input_manifest=manifest,
        eligible_parent_ids=[],
        seed=7,
        candidate_cap=2,
        compute_budget=2,
        timeout_seconds=10,
        generation_cost={"attempts": 0},
        status="blocked",
        candidate_hashes=[],
        trace=trace,
        trace_hash=canonical_hash(trace),
        blocking_metrics=["sealed_worlds"],
        created_at=datetime(2026, 9, 22, tzinfo=UTC).isoformat(),
        action_id="pending",
    )


def test_empty_round_is_atomic_and_append_only(tmp_path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    actions = DiscoveryPolicyActions(ActionService(lambda: OntologyUnitOfWork(engine)))
    request = RecordPolicyGenerationRoundRequest(
        _round(),
        "sys:generator",
        ActorRole.DETERMINISTIC_SYSTEM,
        "round-1",
        datetime(2026, 9, 22, tzinfo=UTC),
    )
    denied = actions.record_generation_round(
        replace(request, actor_role=ActorRole.AI_ANALYST, idempotency_key="denied")
    )
    assert denied.status is ActionStatus.REJECTED
    assert actions.record_generation_round(request).status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.generation_round("round-1").candidate_hashes == []
        assert [event.action_id for event in uow.outbox.after(0, limit=10)].count(
            uow.discovery.generation_round("round-1").action_id
        ) == 1
    for statement in (
        "UPDATE policy_generation_rounds SET status='ready' WHERE generation_round_id='round-1'",
        "DELETE FROM policy_generation_rounds WHERE generation_round_id='round-1'",
    ):
        with pytest.raises(IntegrityError, match="append-only"):
            with engine.begin() as connection:
                connection.exec_driver_sql(statement)


def test_round_rejects_unfrozen_world_and_trace_tampering(tmp_path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    actions = DiscoveryPolicyActions(ActionService(lambda: OntologyUnitOfWork(engine)))
    request = RecordPolicyGenerationRoundRequest(
        _round(),
        "sys:generator",
        ActorRole.DETERMINISTIC_SYSTEM,
        "round-1",
        datetime(2026, 9, 22, tzinfo=UTC),
    )
    for row, message in (
        (replace(request.round, trace_hash="a" * 64), "trace hash"),
        (replace(request.round, generation_cost={"attempts": 1}), "cost"),
        (
            replace(
                request.round,
                input_manifest={
                    **request.round.input_manifest,
                    "development_worlds": [{"world_id": "missing", "seal_hash": "a" * 64}],
                },
                input_manifest_hash=canonical_hash(
                    {
                        **request.round.input_manifest,
                        "development_worlds": [{"world_id": "missing", "seal_hash": "a" * 64}],
                    }
                ),
            ),
            "sealed development",
        ),
    ):
        with pytest.raises(ValueError, match=message):
            actions.record_generation_round(replace(request, round=row, idempotency_key=message))


def test_round_refuses_nonexistent_parent_and_holdout_world(tmp_path):
    from tests.ontology.test_discovery_repository import _event, _world

    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    actions = DiscoveryPolicyActions(ActionService(lambda: OntologyUnitOfWork(engine)))
    request = RecordPolicyGenerationRoundRequest(
        _round(),
        "sys:generator",
        ActorRole.DETERMINISTIC_SYSTEM,
        "round-1",
        datetime(2026, 9, 22, tzinfo=UTC),
    )
    parent_manifest = {**request.round.input_manifest, "eligible_parent_ids": ["missing"]}
    with pytest.raises(ValueError, match="parent"):
        actions.record_generation_round(
            replace(
                request,
                round=replace(
                    request.round,
                    eligible_parent_ids=["missing"],
                    input_manifest=parent_manifest,
                    input_manifest_hash=canonical_hash(parent_manifest),
                ),
            )
        )
    with OntologyUnitOfWork(engine) as uow:
        uow.discovery.insert_world(_world())
        uow.discovery.insert_world_event(_event(1, "created"))
        uow.discovery.insert_world_event(_event(2, "run_started"))
        uow.discovery.insert_world_event(_event(3, "sealed"))
    holdout_manifest = {
        **request.round.input_manifest,
        "development_cutoff": "2026-09-20T00:00:00+00:00",
        "development_worlds": [{"world_id": "world-1", "seal_hash": "a" * 64}],
    }
    with pytest.raises(ValueError, match="cutoff"):
        actions.record_generation_round(
            replace(
                request,
                round=replace(
                    request.round,
                    input_manifest=holdout_manifest,
                    input_manifest_hash=canonical_hash(holdout_manifest),
                ),
                idempotency_key="holdout",
            )
        )
    invalid_seal = {**holdout_manifest, "development_cutoff": "2026-09-22T00:00:00+00:00"}
    with pytest.raises(ValueError, match="seal|manifest"):
        actions.record_generation_round(
            replace(
                request,
                round=replace(
                    request.round,
                    input_manifest=invalid_seal,
                    input_manifest_hash=canonical_hash(invalid_seal),
                ),
                idempotency_key="invalid-seal",
            )
        )


def test_generated_policy_requires_exact_round_and_operator_admission(tmp_path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    actions = DiscoveryPolicyActions(ActionService(lambda: OntologyUnitOfWork(engine)))
    base = _registration(
        policy=replace(_registration().policy, family="structural_candidate_exploration")
    )
    assert actions.register_policy(base).status is ActionStatus.COMMITTED
    parent_id = base.policy.policy_revision_id
    from nutmeg.discovery.generation_contracts import EligibleParent

    context = _context().model_copy(
        update={
            "eligible_parents": (
                EligibleParent(
                    policy_revision_id=parent_id,
                    disposition="incumbent",
                    lineage_root=parent_id,
                    template_order=("1x1", "2x1"),
                    batch_limit=1,
                ),
            )
        }
    )
    proposal = generate_evolution(context, _ready()).proposals[0]
    artifact = proposal.model_dump(mode="json")
    manifest = {
        "development_worlds": [],
        "eligible_parent_ids": [parent_id],
        "generator_revision": "bounded-evolution-v1",
    }
    trace = {
        "attempts": [{"policy_revision_id": proposal.policy_revision_id, "status": "proposed"}],
        "proposals": [artifact],
    }
    round_row = replace(
        _round(),
        generator_family="bounded_evolution",
        generator_revision="bounded-evolution-v1",
        generator_artifact_hash=canonical_hash({"revision": "bounded-evolution-v1"}),
        input_manifest=manifest,
        input_manifest_hash=canonical_hash(manifest),
        eligible_parent_ids=[parent_id],
        status="complete",
        candidate_hashes=[canonical_hash(artifact)],
        trace=trace,
        trace_hash=canonical_hash(trace),
        generation_cost={"attempts": 1},
    )
    assert (
        actions.record_generation_round(
            RecordPolicyGenerationRoundRequest(
                round_row,
                "sys:generator",
                ActorRole.DETERMINISTIC_SYSTEM,
                "round-1",
                datetime(2026, 9, 22, tzinfo=UTC),
            )
        ).status
        is ActionStatus.COMMITTED
    )
    policy = replace(
        base.policy,
        policy_revision_id=proposal.policy_revision_id,
        source_artifact_hash=canonical_hash(artifact),
        generator_family="bounded_evolution",
        generator_revision="bounded-evolution-v1",
        generation_input_manifest_hash=round_row.input_manifest_hash,
        generation_trace_hash=round_row.trace_hash,
        generator_descriptors={"generation_round_id": "round-1"},
        generation_cost=round_row.generation_cost,
    )
    request = replace(
        base,
        policy=policy,
        artifact=artifact,
        parent_policy_revision_ids=(parent_id,),
        idempotency_key="admit",
    )
    for changed in (
        replace(
            request,
            policy=replace(policy, generation_trace_hash="bad"),
            idempotency_key="bad-trace",
        ),
        replace(request, parent_policy_revision_ids=(), idempotency_key="bad-parents"),
        replace(
            request,
            artifact={**artifact, "model_weights": {"x": 1}},
            policy=replace(
                policy, source_artifact_hash=canonical_hash({**artifact, "model_weights": {"x": 1}})
            ),
            idempotency_key="frozen",
        ),
    ):
        with pytest.raises(ValueError):
            actions.register_policy(changed)
    assert actions.register_policy(request).status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.policy_parents(proposal.policy_revision_id) == (parent_id,)
        assert (
            uow.discovery.policy(proposal.policy_revision_id).generation_trace_hash
            == round_row.trace_hash
        )


def test_baseline_proposal_uses_frozen_round_parent_at_operator_admission(tmp_path):
    from nutmeg.discovery.generator_baseline import generate_baselines

    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    actions = DiscoveryPolicyActions(ActionService(lambda: OntologyUnitOfWork(engine)))
    base = _registration(
        policy=replace(_registration().policy, family="structural_candidate_exploration")
    )
    assert actions.register_policy(base).status is ActionStatus.COMMITTED
    artifact = (
        generate_baselines(("1x1", "2x1"), seed=7, candidate_cap=1, attempt_budget=2)
        .proposals[0]
        .model_dump(mode="json")
    )
    manifest = {
        "development_worlds": [],
        "eligible_parent_ids": ["policy-1"],
        "generator_revision": "baseline-v1",
    }
    trace = {
        "attempts": [{"policy_revision_id": artifact["policy_revision_id"], "status": "proposed"}],
        "proposals": [artifact],
    }
    row = replace(
        _round(),
        generator_revision="baseline-v1",
        generator_artifact_hash=canonical_hash({"revision": "baseline-v1"}),
        input_manifest=manifest,
        input_manifest_hash=canonical_hash(manifest),
        eligible_parent_ids=["policy-1"],
        candidate_hashes=[canonical_hash(artifact)],
        trace=trace,
        trace_hash=canonical_hash(trace),
        generation_cost={"attempts": 1},
        status="truncated",
    )
    assert (
        actions.record_generation_round(
            RecordPolicyGenerationRoundRequest(
                row,
                "sys:generator",
                ActorRole.DETERMINISTIC_SYSTEM,
                "baseline:round",
                datetime(2026, 9, 22, tzinfo=UTC),
            )
        ).status
        is ActionStatus.COMMITTED
    )
    policy = replace(
        base.policy,
        policy_revision_id=artifact["policy_revision_id"],
        source_artifact_hash=canonical_hash(artifact),
        generator_revision="baseline-v1",
        generator_descriptors={"generation_round_id": "round-1"},
        generation_input_manifest_hash=row.input_manifest_hash,
        generation_trace_hash=row.trace_hash,
        generation_cost=row.generation_cost,
        family=artifact["family"],
        interface_version=artifact["interface_version"],
        constraints_version=artifact["constraints_version"],
    )
    assert (
        actions.register_policy(
            replace(
                base,
                policy=policy,
                artifact=artifact,
                parent_policy_revision_ids=("policy-1",),
                idempotency_key="baseline:admit",
            )
        ).status
        is ActionStatus.COMMITTED
    )
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.policy_parents(policy.policy_revision_id) == ("policy-1",)
