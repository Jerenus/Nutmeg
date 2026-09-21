from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from nutmeg.ontology.actions.discovery_policy_actions import (
    DiscoveryPolicyActions,
    FinishPolicyReplayRequest,
    RegisterPolicyRevisionRequest,
    StartPolicyReplayRequest,
)
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService, ReplayActionContext
from nutmeg.ontology.discovery.models import canonical_hash
from nutmeg.ontology.errors import PermissionDeniedError
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.discovery import (
    DiscoveryRunRow,
    PolicyReplayCompletionRow,
    PolicyReplayRoundRow,
    PolicyReplayRunRow,
)
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from tests.ontology.test_discovery_repository import _event, _node, _policy, _record, _world

T0 = datetime(2026, 9, 21, 8, tzinfo=UTC)
ARTIFACT = {"schema_version": "1", "steps": [{"action": "stop"}]}


def _rig(tmp_path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    return DiscoveryPolicyActions(ActionService(lambda: OntologyUnitOfWork(engine))), engine


def _registration(**changes):
    policy = replace(
        _policy("policy-1"),
        source_artifact_hash=canonical_hash(ARTIFACT),
        compatible_world_families=["structural_candidate_audit"],
        validation_result={"valid": True},
        change_surfaces=["exploration_policy"],
        max_resource_permissions={},
    )
    return RegisterPolicyRevisionRequest(
        policy=changes.pop("policy", policy),
        artifact=changes.pop("artifact", ARTIFACT),
        parent_policy_revision_ids=changes.pop("parent_policy_revision_ids", ()),
        actor_id=changes.pop("actor_id", "op:jun"),
        actor_role=changes.pop("actor_role", ActorRole.JUDGE_OPERATOR),
        idempotency_key=changes.pop("idempotency_key", "policy:register"),
        requested_at=changes.pop("requested_at", T0),
        **changes,
    )


def test_register_policy_requires_operator_and_artifact_hash_match(tmp_path):
    actions, engine = _rig(tmp_path)
    denied = actions.register_policy(
        replace(
            _registration(),
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key="policy:system",
        )
    )
    assert denied.status is ActionStatus.REJECTED
    with pytest.raises(ValueError, match="hash mismatch"):
        actions.register_policy(
            replace(_registration(), artifact={"steps": []}, idempotency_key="policy:tampered")
        )
    outcome = actions.register_policy(_registration())
    assert outcome.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.policy("policy-1").source_artifact_hash == canonical_hash(ARTIFACT)
        assert [event.action_id for event in uow.outbox.after(0, limit=10)].count(
            outcome.action_id
        ) == 1


def test_register_policy_rejects_model_system_change_surface(tmp_path):
    actions, engine = _rig(tmp_path)
    request = _registration()
    with pytest.raises(ValueError, match="frozen"):
        actions.register_policy(
            replace(
                request,
                policy=replace(
                    request.policy, change_surfaces=["model_weights_or_executable_system"]
                ),
            )
        )
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.policy("policy-1") is None


def test_register_policy_rejects_frozen_fields_hidden_in_artifact(tmp_path):
    actions, engine = _rig(tmp_path)
    artifact = {**ARTIFACT, "model_weights": {"new": 1}}
    request = _registration(
        artifact=artifact,
        policy=replace(_registration().policy, source_artifact_hash=canonical_hash(artifact)),
    )
    with pytest.raises(ValueError, match="frozen|unsupported"):
        actions.register_policy(request)
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.policy("policy-1") is None


def test_register_policy_preserves_all_ordered_parents(tmp_path):
    actions, engine = _rig(tmp_path)
    for policy_id in ("policy-1", "policy-2"):
        base = _registration(
            policy=replace(_registration().policy, policy_revision_id=policy_id),
            idempotency_key=f"policy:{policy_id}",
        )
        assert actions.register_policy(base).status is ActionStatus.COMMITTED
    child = _registration(
        policy=replace(_registration().policy, policy_revision_id="policy-3"),
        parent_policy_revision_ids=("policy-2", "policy-1"),
        idempotency_key="policy:child",
    )
    assert actions.register_policy(child).status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.policy_parents("policy-3") == ("policy-2", "policy-1")


def _world_with_tree(engine, *, sealed=True):
    with OntologyUnitOfWork(engine) as uow:
        uow.discovery.insert_world(_world())
        uow.discovery.insert_world_event(_event(1, "created"))
        uow.discovery.insert_run(_record(DiscoveryRunRow, discovery_run_id="run-1"))
        uow.discovery.insert_world_event(_event(2, "run_started"))
        for node_id, sequence, parent in (
            ("node-root", 1, None),
            ("a", 2, "node-root"),
            ("a1", 3, "a"),
            ("b", 4, "node-root"),
        ):
            uow.discovery.insert_node(
                _node(
                    node_id,
                    sequence,
                    parent_node_id=parent,
                    discovery_run_id=None if parent is None else "run-1",
                )
            )
        if sealed:
            uow.discovery.insert_world_event(_event(3, "sealed"))


def _replay_request():
    return StartPolicyReplayRequest(
        replay=_record(
            PolicyReplayRunRow,
            policy_replay_run_id="replay-1",
            evaluator_revision="structural-candidate-evaluator-v1",
            initial_observation_hash=canonical_hash({"visible_node_ids": ["node-root"]}),
        ),
        initial_observation={"visible_node_ids": ["node-root"]},
        actor_id="sys:replay",
        actor_role=ActorRole.DETERMINISTIC_SYSTEM,
        idempotency_key="replay:start",
        requested_at=T0,
    )


def test_start_replay_requires_sealed_world_and_valid_policy(tmp_path):
    actions, engine = _rig(tmp_path)
    actions.register_policy(_registration())
    _world_with_tree(engine, sealed=False)
    with pytest.raises(ValueError, match="sealed"):
        actions.start_replay(_replay_request())
    with OntologyUnitOfWork(engine) as uow:
        uow.discovery.insert_world_event(_event(3, "sealed"))
    assert actions.start_replay(_replay_request()).status is ActionStatus.COMMITTED


def test_start_replay_rejects_unfrozen_extra_visibility_metadata(tmp_path):
    actions, engine = _rig(tmp_path)
    actions.register_policy(_registration())
    _world_with_tree(engine)
    request = _replay_request()
    observation = {"visible_node_ids": ["node-root"], "unrevealed_trace": ["a1"]}
    with pytest.raises(ValueError, match="initial observation"):
        actions.start_replay(
            replace(
                request,
                initial_observation=observation,
                replay=replace(
                    request.replay, initial_observation_hash=canonical_hash(observation)
                ),
            )
        )
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.policy_replay("replay-1") is None


def _finish_request(rounds, *, selected=("a",), trace_hash=None):
    trace = {
        "policy_revision_id": "policy-1",
        "world_id": "world-1",
        "rounds": [
            {field: getattr(row, field) for field in row.__dataclass_fields__} for row in rounds
        ],
        "stop_reason": "policy_stop",
        "selected_node_ids": list(selected),
    }
    return FinishPolicyReplayRequest(
        replay_run_id="replay-1",
        rounds=rounds,
        completion=_record(
            PolicyReplayCompletionRow,
            policy_replay_run_id="replay-1",
            stop_reason="policy_stop",
            selected_node_ids=list(selected),
            trace_hash=trace_hash or canonical_hash(trace),
        ),
        actor_id="sys:replay",
        actor_role=ActorRole.DETERMINISTIC_SYSTEM,
        idempotency_key="replay:finish",
        requested_at=T0,
    )


def _round(number, revealed):
    return _record(
        PolicyReplayRoundRow,
        policy_replay_run_id="replay-1",
        round_no=number,
        revealed_node_ids=list(revealed),
        requested_actions=[],
        accepted_actions=[],
        rejected_actions=[],
    )


def test_finish_replay_rejects_hidden_or_non_child_reveal(tmp_path):
    actions, engine = _rig(tmp_path)
    actions.register_policy(_registration())
    _world_with_tree(engine)
    actions.start_replay(_replay_request())
    with pytest.raises(ValueError, match="unrevealed parent"):
        actions.finish_replay(_finish_request((_round(1, ("a1",)),)))
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.policy_replay_rounds("replay-1") == ()
        assert uow.discovery.policy_replay_completion("replay-1") is None


def test_finish_replay_persists_ordered_prefix_trace_and_hash(tmp_path):
    actions, engine = _rig(tmp_path)
    actions.register_policy(_registration())
    _world_with_tree(engine)
    actions.start_replay(_replay_request())
    rounds = (_round(1, ("a", "b")), _round(2, ("a1",)))
    finish = _finish_request(rounds, selected=("a1",))
    assert actions.finish_replay(finish).status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.policy_replay_rounds("replay-1") == rounds
        assert (
            uow.discovery.policy_replay_completion("replay-1").trace_hash
            == finish.completion.trace_hash
        )
        assert len(uow.discovery.nodes_for_world("world-1")) == 4
        assert uow.discovery.world_state("world-1") == "sealed"


def test_replay_completion_is_single_assignment(tmp_path):
    actions, engine = _rig(tmp_path)
    actions.register_policy(_registration())
    _world_with_tree(engine)
    actions.start_replay(_replay_request())
    finish = _finish_request((_round(1, ("a",)),))
    actions.finish_replay(finish)
    with pytest.raises(ValueError, match="already completed"):
        actions.finish_replay(replace(finish, idempotency_key="replay:finish:again"))
    with OntologyUnitOfWork(engine) as uow:
        assert (
            uow.discovery.policy_replay_completion("replay-1").trace_hash
            == finish.completion.trace_hash
        )


def test_replay_cannot_mutate_source_world_or_call_protected_action(tmp_path):
    actions, engine = _rig(tmp_path)
    actions.register_policy(_registration())
    _world_with_tree(engine)
    actions.start_replay(_replay_request())
    with OntologyUnitOfWork(engine) as uow:
        before = (uow.discovery.world("world-1"), uow.discovery.nodes_for_world("world-1"))
    replay_bound = ActionService(
        lambda: OntologyUnitOfWork(engine),
        replay_context=ReplayActionContext(
            replay_run_id="missing", business_date="2026-09-21", isolated_database_identity="test"
        ),
    )
    from nutmeg.ontology.actions.models import ActionCommand

    protected = ActionCommand.create(
        action_type="approve_policy_deployment",
        actor_id="op:jun",
        actor_role=ActorRole.JUDGE_OPERATOR,
        idempotency_key="protected:replay",
        payload={},
        requested_at=T0,
    )
    with pytest.raises(PermissionDeniedError, match="protected action"):
        replay_bound.execute(protected, lambda _uow, _cmd: ())
    with OntologyUnitOfWork(engine) as uow:
        assert (uow.discovery.world("world-1"), uow.discovery.nodes_for_world("world-1")) == before
