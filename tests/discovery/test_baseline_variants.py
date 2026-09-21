from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from nutmeg.discovery.baseline_variants import (
    DeterministicBaselineVariantArtifact,
    load_policy_artifact,
    variant_policy_revision_id,
)
from nutmeg.discovery.environment import ContinueBatch, Observation, Stop
from nutmeg.discovery.replay_runner import policy_decision, run_registered_replay
from nutmeg.ontology.actions.discovery_policy_actions import (
    DiscoveryPolicyActions,
    RegisterPolicyRevisionRequest,
)
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.discovery.models import canonical_hash
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from tests.discovery.test_online_adapter import _snapshot
from tests.discovery.test_online_recorder import _rig as _online_rig
from tests.ontology.test_discovery_policy_actions import T0, _registration, _rig


def _document() -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": "1",
        "family": "structural_candidate_exploration",
        "interface_version": "discovery-policy-v1",
        "constraints_version": "structural-candidate-v1",
        "generator_family": "baseline",
        "change_surfaces": ["exploration_policy"],
        "random_seed_policy": {"kind": "none", "deterministic": True},
        "compatible_world_families": ["structural_candidate_audit"],
        "template_order": ["2x1", "1x1"],
        "batch_limit": 1,
        "stop_selector": "best_audit_clean_node_per_band",
        "rationale": "Bounded deterministic ordering challenger.",
    }
    return {"policy_revision_id": variant_policy_revision_id(body), **body}


def test_variant_is_content_addressed_strict_and_deterministic():
    artifact = DeterministicBaselineVariantArtifact.model_validate(_document())
    assert artifact.policy_revision_id == variant_policy_revision_id(
        artifact.model_dump(mode="json", exclude={"policy_revision_id"})
    )
    assert load_policy_artifact(_document()) == artifact
    assert load_policy_artifact(dict(reversed(_document().items()))) == artifact

    with pytest.raises(ValidationError, match="model_weights"):
        DeterministicBaselineVariantArtifact.model_validate(
            {**_document(), "model_weights": {"hidden": True}}
        )


def test_variant_rejects_forged_id_duplicate_templates_and_executable_fields():
    with pytest.raises(ValueError, match="content-addressed"):
        DeterministicBaselineVariantArtifact.model_validate(
            {
                **_document(),
                "policy_revision_id": "structural-baseline-variant-000000000000000000000000",
            }
        )
    with pytest.raises(ValueError, match="template"):
        DeterministicBaselineVariantArtifact.model_validate(
            {**_document(), "template_order": ["1x1", "1x1"]}
        )
    with pytest.raises(ValidationError, match="executable"):
        DeterministicBaselineVariantArtifact.model_validate(
            {**_document(), "executable": "module:function"}
        )


def test_variant_registration_is_operator_only_and_preserves_closed_surfaces(tmp_path):
    actions, engine = _rig(tmp_path)
    artifact = _document()
    base = _registration()
    policy = replace(
        base.policy,
        policy_revision_id=artifact["policy_revision_id"],
        source_artifact_hash=canonical_hash(artifact),
        family="structural_candidate_exploration",
        interface_version="discovery-policy-v1",
        constraints_version="structural-candidate-v1",
    )
    request = RegisterPolicyRevisionRequest(
        policy=policy,
        artifact=artifact,
        parent_policy_revision_ids=(),
        actor_id="op:jun",
        actor_role=ActorRole.JUDGE_OPERATOR,
        idempotency_key="policy:variant",
        requested_at=T0,
    )

    denied = actions.register_policy(
        replace(
            request,
            actor_id="sys:generator",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key="policy:variant:denied",
        )
    )
    assert denied.status is ActionStatus.REJECTED
    assert actions.register_policy(request).status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        stored = uow.discovery.policy(artifact["policy_revision_id"])
    assert stored.change_surfaces == ["exploration_policy"]
    assert stored.generator_family == "baseline"


def test_variant_interpreter_uses_only_visible_templates_and_declared_batch_limit():
    artifact = DeterministicBaselineVariantArtifact.model_validate(_document())
    observation = Observation(
        world_id="world-1",
        visible_node_ids=("root",),
        frontier_node_ids=("root",),
        selectable_node_ids=(),
        legal_template_ids=("1x1", "2x1", "3x1"),
        remaining_rounds=2,
        remaining_nodes=3,
        max_concurrency=3,
    )

    first = policy_decision(artifact, 1, observation)
    assert isinstance(first, ContinueBatch)
    assert tuple(item.template_ids for item in first.items) == (("2x1",),)
    assert isinstance(policy_decision(artifact, 2, observation), Stop)


def test_registered_variant_replay_is_reproducible_on_sealed_fixture(tmp_path):
    from nutmeg.discovery.contracts import load_pilot_contract
    from nutmeg.discovery.online_recorder import record_shadow_world

    engine = _online_rig(tmp_path)
    artifact = DeterministicBaselineVariantArtifact.model_validate(_document())
    with OntologyUnitOfWork(engine) as uow:
        incumbent = uow.discovery.policy("structural-baseline-v1")
    policy = replace(
        incumbent,
        policy_revision_id=artifact.policy_revision_id,
        source_artifact_hash=canonical_hash(artifact.model_dump(mode="json")),
    )
    actions = DiscoveryPolicyActions(ActionService(lambda: OntologyUnitOfWork(engine)))
    actions.register_policy(
        RegisterPolicyRevisionRequest(
            policy=policy,
            artifact=artifact.model_dump(mode="json"),
            parent_policy_revision_ids=("structural-baseline-v1",),
            actor_id="op:jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="policy:variant:e2e",
            requested_at=T0,
        )
    )
    recorded = record_shadow_world(
        _snapshot(),
        engine=engine,
        shadow_database=tmp_path / "shadow.db",
        source_database=tmp_path / "business.db",
        policy_revision_id="structural-baseline-v1",
        requested_at=T0,
        fixture_only=True,
    )
    pilot = load_pilot_contract(
        Path(__file__).resolve().parents[2]
        / "experiments/discovery/structural-candidate-v1.contract.json"
    )
    first = run_registered_replay(
        engine, recorded.world_id, artifact, pilot, seed=11, requested_at=T0
    )
    second = run_registered_replay(
        engine, recorded.world_id, artifact, pilot, seed=11, requested_at=T0
    )
    assert first.trace_hash == second.trace_hash
