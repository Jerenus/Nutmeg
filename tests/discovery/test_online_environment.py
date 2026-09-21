from __future__ import annotations

from datetime import UTC, datetime

import pytest

from nutmeg.discovery.environment import Continue, ContinueBatch, Stop
from nutmeg.discovery.online_recorder import OnlineRecordingEnvironment
from nutmeg.ontology.discovery.models import canonical_hash
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from tests.discovery.test_online_adapter import _snapshot
from tests.discovery.test_online_recorder import _rig


def _online(tmp_path, *, fixture_only=True):
    return OnlineRecordingEnvironment(
        _snapshot(),
        engine=_rig(tmp_path),
        shadow_database=tmp_path / "shadow.db",
        source_database=tmp_path / "business.db",
        policy_revision_id="structural-baseline-v1",
        requested_at=datetime(2026, 9, 21, 7, 1, tzinfo=UTC),
        fixture_only=fixture_only,
    )


def test_online_environment_executes_only_after_visible_continuation(tmp_path):
    engine = _rig(tmp_path)
    snapshot = _snapshot()
    online = OnlineRecordingEnvironment(
        snapshot,
        engine=engine,
        shadow_database=tmp_path / "shadow.db",
        source_database=tmp_path / "business.db",
        policy_revision_id="structural-baseline-v1",
        requested_at=datetime(2026, 9, 21, 7, 1, tzinfo=UTC),
        fixture_only=True,
    )
    observation = online.reset()
    assert observation.visible_node_ids == (f"{observation.world_id}:root",)
    with OntologyUnitOfWork(engine) as uow:
        assert len(uow.discovery.nodes_for_world(observation.world_id)) == 1
    chosen = snapshot.template_ids[0]
    result = online.continue_batch(
        ContinueBatch((Continue(observation.visible_node_ids[0], (chosen,)),))
    )
    assert len(result.revealed_node_ids) == 1
    assert result.observation.visible_node_ids == (
        observation.visible_node_ids[0],
        *result.revealed_node_ids,
    )
    with OntologyUnitOfWork(engine) as uow:
        assert len(uow.discovery.nodes_for_world(observation.world_id)) == 2
        assert uow.discovery.world_state(observation.world_id) == "running"
    terminal = online.stop(Stop(()))
    assert terminal.reason == "policy_stop"
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.world_state(observation.world_id) == "sealed"


def test_online_environment_rejects_unattested_run_before_world_create(tmp_path):
    online = _online(tmp_path, fixture_only=False)
    with pytest.raises(ValueError, match="attested source"):
        online.reset()
    with OntologyUnitOfWork(online._engine) as uow:
        identity = canonical_hash([_snapshot().manifest_hash, "structural-baseline-v1"])
        world_id = f"discovery-world-{identity[:24]}"
        assert uow.discovery.world(world_id) is None


def test_authoritative_lineage_is_bound_into_new_world(tmp_path):
    from nutmeg.discovery.deployment_runtime import Controller

    engine = _rig(tmp_path)
    controller = Controller("structural-baseline-v1", "canary", True, "a" * 64, "dep-1")
    online = OnlineRecordingEnvironment(
        _snapshot(), engine=engine, shadow_database=tmp_path / "shadow.db",
        source_database=tmp_path / "business.db",
        policy_revision_id="structural-baseline-v1",
        requested_at=datetime(2026, 9, 21, 7, 1, tzinfo=UTC), fixture_only=True,
        controller=controller,
    )
    root = online.reset()
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.world(root.world_id).input_manifest["policy_lineage"] == {
            "policy_revision_id": "structural-baseline-v1",
            "scope_contract_hash": "a" * 64,
            "policy_deployment_id": "dep-1",
        }


def test_online_environment_rejects_multi_template_action_without_truncation(tmp_path):
    online = _online(tmp_path)
    root = online.reset().visible_node_ids[0]
    with pytest.raises(ValueError, match="single template"):
        online.continue_batch(ContinueBatch((Continue(root, (_snapshot().template_ids[0],) * 2),)))
    with OntologyUnitOfWork(online._engine) as uow:
        assert len(uow.discovery.nodes_for_world(online.observation().world_id)) == 1


def test_online_environment_continues_visible_child_at_next_depth(tmp_path):
    online = _online(tmp_path)
    root = online.reset().visible_node_ids[0]
    template = _snapshot().template_ids[0]
    first = online.continue_batch(ContinueBatch((Continue(root, (template,)),)))
    child_id = first.revealed_node_ids[0]
    second = online.continue_batch(ContinueBatch((Continue(child_id, (template,)),)))
    with OntologyUnitOfWork(online._engine) as uow:
        child = uow.discovery.node(second.revealed_node_ids[0])
    assert child.parent_node_id == child_id
    assert child.depth == 2


def test_online_environment_records_transient_retry_as_linked_attempt(tmp_path, monkeypatch):
    from nutmeg.discovery.online_adapter import ShardExecution

    online = _online(tmp_path)
    root = online.reset().visible_node_ids[0]
    template = _snapshot().template_ids[0]
    calls = []

    def flaky(_snapshot_arg, _template, _pilot):
        calls.append(_template)
        failed = len(calls) == 1
        manifest = {"retry": len(calls)}
        digest = canonical_hash(manifest)
        return ShardExecution(
            template_ids=(_template,), status="failed" if failed else "no_solution",
            artifact_manifest={**manifest, "content_hash": digest}, artifact_hash=digest,
            diagnostic_codes=("adapter_crash",) if failed else ("no_feasible_candidate",),
            resource_cost={"wall_ms": 1, "candidate_generation_count": 0},
            evaluation=None if failed else {}, selectable=False,
        )

    monkeypatch.setattr("nutmeg.discovery.online_recorder._run_shard", flaky)
    observed = []
    monkeypatch.setattr("nutmeg.discovery.brake_monitor.monitor_committed_fact",
                        lambda _engine, action_id: observed.append(action_id))
    result = online.continue_batch(ContinueBatch((Continue(root, (template,)),)))
    assert len(observed) == 1
    assert len(calls) == 2
    assert len(result.revealed_node_ids) == 2
    assert result.charged_cost["attempts"] == 2
    with OntologyUnitOfWork(online._engine) as uow:
        nodes = uow.discovery.nodes_for_world(result.observation.world_id)
    assert nodes[2].retry_of_node_id == nodes[1].node_id


def test_online_retry_reserves_node_budget_for_remaining_batch_items(tmp_path, monkeypatch):
    from dataclasses import replace

    from nutmeg.discovery.online_adapter import ShardExecution
    from nutmeg.discovery.online_inputs import freeze_structural_input
    from nutmeg.product.operator_candidates import CandidateStructureTemplate
    from tests.discovery.test_online_inputs import _references

    base = _snapshot()
    other = CandidateStructureTemplate(
        kind="jczq_pass", structure_code="other", eligible_official_match_nos=("001",),
        required_offer_count=1, maximum_groups=1, pass_size=1,
    )
    snapshot = freeze_structural_input(
        candidate_input=replace(
            base.candidate_input, templates=(*base.candidate_input.templates, other)
        ),
        references=_references(),
        business_date=base.business_date,
        task_snapshot_hash=base.task_snapshot_hash,
        slate_revision_id=base.slate_revision_id,
        board_slate_revision_id=base.slate_revision_id,
        cutoff_at=base.cutoff_at,
        audit_policy_revision=base.audit_policy_revision,
        audit_offers=base.audit_offers,
    )
    online = OnlineRecordingEnvironment(
        snapshot, engine=_rig(tmp_path), shadow_database=tmp_path / "shadow.db",
        source_database=tmp_path / "business.db", policy_revision_id="structural-baseline-v1",
        requested_at=datetime(2026, 9, 21, 7, 1, tzinfo=UTC), fixture_only=True,
    )
    root = online.reset().visible_node_ids[0]
    online._pilot = online._pilot.model_copy(
        update={"budgets": online._pilot.budgets.model_copy(update={"max_nodes": 4})}
    )
    calls = []

    def failed(_snapshot_arg, template, _pilot):
        calls.append(template)
        manifest = {"template": template}
        digest = canonical_hash(manifest)
        return ShardExecution(
            template_ids=(template,), status="failed",
            artifact_manifest={**manifest, "content_hash": digest}, artifact_hash=digest,
            diagnostic_codes=("adapter_crash",),
            resource_cost={"wall_ms": 1, "candidate_generation_count": 0},
            evaluation=None, selectable=False,
        )

    monkeypatch.setattr("nutmeg.discovery.online_recorder._run_shard", failed)
    templates = snapshot.template_ids
    result = online.continue_batch(
        ContinueBatch(tuple(Continue(root, (template,)) for template in templates))
    )
    assert calls == list(templates)
    assert result.charged_cost["attempts"] == 2
    assert result.observation.remaining_nodes == 0
