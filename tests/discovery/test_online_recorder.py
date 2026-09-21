from __future__ import annotations

import sqlite3
import threading
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from nutmeg.discovery.contracts import canonical_hash as contract_hash
from nutmeg.discovery.contracts import load_baseline_policy
from nutmeg.discovery.online_adapter import ShardExecution
from nutmeg.discovery.online_inputs import freeze_structural_input
from nutmeg.discovery.online_recorder import (
    _source_fingerprint,
    board_size_stratum,
    record_shadow_world,
    run_shard_isolated,
)
from nutmeg.ontology.actions.discovery_policy_actions import (
    DiscoveryPolicyActions,
    RegisterPolicyRevisionRequest,
)
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.discovery.models import canonical_hash
from nutmeg.ontology.discovery.read_service import DiscoveryReadService
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from tests.discovery.test_online_adapter import _snapshot
from tests.discovery.test_online_inputs import _freeze, _references
from tests.ontology.operator.test_candidate_actions import (
    _generate,
    _generation_request,
    _ready_fixture,
)
from tests.ontology.operator.test_judgment_actions import AT
from tests.ontology.test_discovery_repository import _policy

BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "experiments/discovery/structural-baseline-v1.policy.json"
)
T0 = datetime(2026, 9, 21, 7, 1, tzinfo=UTC)


def _rig(tmp_path):
    engine = build_ontology_engine(tmp_path / "shadow.db")
    run_migrations(engine)
    with sqlite3.connect(tmp_path / "business.db") as connection:
        connection.execute("CREATE TABLE protected (id INTEGER PRIMARY KEY)")
    baseline = load_baseline_policy(BASELINE_PATH)
    policy = replace(
        _policy(baseline.policy_revision_id),
        family=baseline.family,
        interface_version=baseline.interface_version,
        constraints_version=baseline.constraints_version,
        source_artifact_hash=contract_hash(baseline),
        compatible_world_families=list(baseline.compatible_world_families),
        change_surfaces=list(baseline.change_surfaces),
        validation_result={"valid": True},
        max_resource_permissions={},
        created_by="op:jun",
    )
    actions = DiscoveryPolicyActions(ActionService(lambda: OntologyUnitOfWork(engine)))
    outcome = actions.register_policy(
        RegisterPolicyRevisionRequest(
            policy=policy,
            artifact=baseline.model_dump(mode="json"),
            parent_policy_revision_ids=(),
            actor_id="op:jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="test:register:baseline",
            requested_at=T0,
        )
    )
    assert outcome.status is ActionStatus.COMMITTED
    return engine


def _artifact(payload):
    return {**payload, "content_hash": canonical_hash(payload)}


def test_board_size_strata_cover_small_medium_and_large():
    assert [board_size_stratum(count) for count in (4, 5, 9, 10)] == [
        "small", "medium", "medium", "large"
    ]


def _slow_shard(_snapshot, _template_id, _pilot):
    import time

    time.sleep(2)


def _fast_shard(_snapshot, template_id, _pilot):
    manifest = _artifact({"shard": template_id})
    return ShardExecution(
        template_ids=(template_id,), status="no_solution",
        artifact_manifest=manifest, artifact_hash=manifest["content_hash"],
        diagnostic_codes=("no_feasible_candidate",), resource_cost={"wall_ms": 1},
        evaluation={}, selectable=False,
    )


def test_isolated_shard_times_out_and_reclaims_process():
    from nutmeg.discovery.contracts import load_pilot_contract

    pilot = load_pilot_contract(
        Path(__file__).resolve().parents[2]
        / "experiments/discovery/structural-candidate-v1.contract.json"
    )
    result = run_shard_isolated(
        _snapshot(), "1x1", pilot, timeout_seconds=0.2, worker_fn=_slow_shard
    )
    assert result.status == "failed"
    assert result.diagnostic_codes == ("timeout",)
    assert result.resource_cost["wall_ms"] is not None


def test_isolated_shard_returns_frozen_result_without_database_access():
    from nutmeg.discovery.contracts import load_pilot_contract

    pilot = load_pilot_contract(
        Path(__file__).resolve().parents[2]
        / "experiments/discovery/structural-candidate-v1.contract.json"
    )
    result = run_shard_isolated(
        _snapshot(), "1x1", pilot, timeout_seconds=5, worker_fn=_fast_shard
    )
    assert result.status == "no_solution"
    assert result.artifact_manifest["shard"] == "1x1"


def test_source_fingerprint_handles_quoted_table_names(tmp_path):
    database = tmp_path / "source.db"
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE "protected""table" (value TEXT)')
        connection.execute('INSERT INTO "protected""table" VALUES (\'initial\')')
    before = _source_fingerprint(database)
    with sqlite3.connect(database) as connection:
        connection.execute('UPDATE "protected""table" SET value = \'changed\'')
    assert _source_fingerprint(database) != before


def test_real_source_fixture_seals_shadow_without_business_mutation(tmp_path):
    business_dir = tmp_path / "business"
    business_dir.mkdir()
    fixture = _ready_fixture(business_dir)
    request = fixture.judgment.decision_actions.request_candidate_generation(
        _generation_request(fixture)
    )
    request_id = request.result_refs[0].object_id
    _generate(fixture, request_id=request_id)
    source_db = business_dir / "ontology.db"
    from nutmeg.discovery.online_inputs import read_structural_input_from_database

    snapshot = read_structural_input_from_database(
        source_db, request_id, cutoff_at=(AT + timedelta(seconds=10)).isoformat()
    )
    shadow_dir = tmp_path / "shadow"
    shadow_dir.mkdir()
    shadow_engine = _rig(shadow_dir)
    before = _source_fingerprint(source_db)
    result = record_shadow_world(
        snapshot, engine=shadow_engine, shadow_database=shadow_dir / "shadow.db",
        source_database=source_db, policy_revision_id="structural-baseline-v1",
        requested_at=AT + timedelta(seconds=11), fixture_only=True,
    )
    assert _source_fingerprint(source_db) == before
    with OntologyUnitOfWork(shadow_engine) as uow:
        assert uow.discovery.world_state(result.world_id) == "sealed"
        assert len(uow.discovery.nodes_for_world(result.world_id)) >= 3
        assert uow.discovery.world(result.world_id).provenance_mode == "historical_replay_source"


def test_shadow_world_seals_complete_ordered_lineage(tmp_path):
    engine = _rig(tmp_path)
    result = record_shadow_world(
        _snapshot(),
        engine=engine,
        shadow_database=tmp_path / "shadow.db",
        source_database=tmp_path / "business.db",
        policy_revision_id="structural-baseline-v1",
        requested_at=T0,
        fixture_only=True,
    )
    assert result.sealed_manifest_hash
    assert DiscoveryReadService(engine).readiness().metrics["sealed_worlds"].observed == 0
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.world_state(result.world_id) == "sealed"
        assert uow.discovery.world(result.world_id).provenance_mode == "historical_replay_source"
        nodes = uow.discovery.nodes_for_world(result.world_id)
        assert len(nodes) == 3
        assert [n.visibility_sequence for n in nodes] == [1, 2, 3]
        assert nodes[1].parent_node_id == nodes[0].node_id
        assert nodes[1].policy_decision["policy_revision_id"] == "structural-baseline-v1"
        assert uow.discovery.run(f"{result.world_id}:run").environment_mode == "shadow"
        assert nodes[1].artifact_manifest is not None
        assert uow.discovery.latest_node_evaluation(nodes[1].node_id) is not None
        assert nodes[-1].continuation_action["operator"] == "stop"
        assert nodes[-1].artifact_manifest["selected_node_ids"] == list(result.selected_node_ids)
        independent = canonical_hash({
            "world_id": result.world_id,
            "input_manifest_hash": uow.discovery.world(result.world_id).input_manifest_hash,
            "nodes": [
                {key: value for key, value in asdict(node).items() if key != "action_id"}
                for node in nodes
            ],
        })
        assert result.sealed_manifest_hash == independent


def test_shadow_store_must_not_alias_business_source(tmp_path):
    engine = _rig(tmp_path)
    with pytest.raises(ValueError, match="distinct"):
        record_shadow_world(
            _snapshot(),
            engine=engine,
            shadow_database=tmp_path / "shadow.db",
            source_database=tmp_path / "shadow.db",
            policy_revision_id="structural-baseline-v1",
            requested_at=T0,
        )


def test_unattested_fixture_cannot_claim_prospective_world(tmp_path):
    engine = _rig(tmp_path)
    with pytest.raises(ValueError, match="attested"):
        record_shadow_world(
            _snapshot(),
            engine=engine,
            shadow_database=tmp_path / "shadow.db",
            source_database=tmp_path / "business.db",
            policy_revision_id="structural-baseline-v1",
            requested_at=T0,
        )


def test_attested_source_still_requires_explicit_approved_scope(tmp_path):
    engine = _rig(tmp_path)
    snapshot = _freeze(source_identity=str((tmp_path / "business.db").resolve()))
    with pytest.raises(ValueError, match="approval"):
        record_shadow_world(
            snapshot, engine=engine, shadow_database=tmp_path / "shadow.db",
            source_database=tmp_path / "business.db", policy_revision_id="structural-baseline-v1",
            generation_request_id="request-1", requested_at=T0,
        )


def _approval(source, shadow):
    return {
        "approval_id": "approved-shadow-1", "approved_by": "op:jun",
        "approved_at": "2026-09-21T06:59:00+00:00",
        "scope": {
            "source_db": str(source.resolve()), "shadow_db": str(shadow.resolve()),
            "generation_request_id": "request-1", "cutoff_at": "2026-09-21T07:00:00+00:00",
            "policy_revision_id": "structural-baseline-v1",
        },
    }


def test_approval_scope_must_match_exact_source_and_request(tmp_path):
    engine = _rig(tmp_path)
    source = tmp_path / "business.db"
    snapshot = _freeze(source_identity=str(source.resolve()))
    approval = _approval(source, tmp_path / "shadow.db")
    approval["scope"]["generation_request_id"] = "different"
    with pytest.raises(ValueError, match="approval scope"):
        record_shadow_world(
            snapshot, engine=engine, shadow_database=tmp_path / "shadow.db",
            source_database=source, policy_revision_id="structural-baseline-v1",
            generation_request_id="request-1", requested_at=T0, approval=approval,
        )


def test_backdated_request_cannot_make_historical_input_prospective(tmp_path):
    engine = _rig(tmp_path)
    source = tmp_path / "business.db"
    cutoff = "2026-09-04T07:00:00+00:00"
    references = tuple(
        {**reference, "captured_at": "2026-09-04T06:00:00+00:00"}
        for reference in _references()
    )
    snapshot = _freeze(
        references=references, cutoff_at=cutoff, source_identity=str(source.resolve())
    )
    approval = _approval(source, tmp_path / "shadow.db")
    approval["scope"]["cutoff_at"] = cutoff
    approval["approved_at"] = "2026-09-04T06:59:00+00:00"
    with pytest.raises(ValueError, match="expired"):
        record_shadow_world(
            snapshot, engine=engine, shadow_database=tmp_path / "shadow.db",
            source_database=source, policy_revision_id="structural-baseline-v1",
            generation_request_id="request-1", requested_at=datetime(2026, 9, 4, 7, 1, tzinfo=UTC),
            approval=approval,
        )


def test_forged_source_identity_cannot_claim_prospective_world(tmp_path):
    engine = _rig(tmp_path)
    forged = _freeze(source_identity=str((tmp_path / "business.db").resolve()))
    with pytest.raises(ValueError, match="source request"):
        record_shadow_world(
            forged, engine=engine, shadow_database=tmp_path / "shadow.db",
            source_database=tmp_path / "business.db", policy_revision_id="structural-baseline-v1",
            generation_request_id="request-1", requested_at=T0,
            approval=_approval(tmp_path / "business.db", tmp_path / "shadow.db"),
        )


def test_source_change_during_verification_fails_before_world_create(tmp_path, monkeypatch):
    engine = _rig(tmp_path)
    source = tmp_path / "business.db"
    snapshot = _freeze(source_identity=str(source.resolve()))

    def change_source(*_args, **_kwargs):
        with sqlite3.connect(source) as connection:
            connection.execute("INSERT INTO protected (id) VALUES (1)")
        return snapshot

    monkeypatch.setattr(
        "nutmeg.discovery.online_recorder.read_structural_input_from_database",
        change_source,
    )
    with pytest.raises(ValueError, match="protected source changed"):
        record_shadow_world(
            snapshot, engine=engine, shadow_database=tmp_path / "shadow.db",
            source_database=source, policy_revision_id="structural-baseline-v1",
            generation_request_id="request-1", requested_at=T0,
            approval=_approval(source, tmp_path / "shadow.db"),
        )
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.counts()["discovery_world_count"] == 0


def test_failed_attempt_is_durable_and_no_solution_seals(tmp_path, monkeypatch):
    engine = _rig(tmp_path)
    result = ShardExecution(
        template_ids=("1x1",),
        status="failed",
        artifact_manifest=_artifact({"failure": "timeout"}),
        artifact_hash=canonical_hash({"failure": "timeout"}),
        diagnostic_codes=("timeout",),
        resource_cost={"wall_ms": 1200},
        evaluation=None,
        selectable=False,
    )
    monkeypatch.setattr(
        "nutmeg.discovery.online_recorder.execute_template_shard", lambda *_args, **_kwargs: result
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
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.world_state(recorded.world_id) == "sealed"
        assert uow.discovery.nodes_for_world(recorded.world_id)[1].diagnostic_codes == ["timeout"]
        assert recorded.selected_node_ids == ()


def test_adapter_crash_is_recorded_as_failed_attempt(tmp_path, monkeypatch):
    engine = _rig(tmp_path)

    def crash(*_args, **_kwargs):
        raise RuntimeError("adapter crashed before reporting cost")

    monkeypatch.setattr("nutmeg.discovery.online_recorder.execute_template_shard", crash)
    recorded = record_shadow_world(
        _snapshot(), engine=engine, shadow_database=tmp_path / "shadow.db",
        source_database=tmp_path / "business.db", policy_revision_id="structural-baseline-v1",
        requested_at=T0, fixture_only=True,
    )
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.world_state(recorded.world_id) == "sealed"
        failed = uow.discovery.nodes_for_world(recorded.world_id)[1]
        assert failed.execution_status == "failed"
        assert failed.resource_cost["wall_ms"] is None
        assert failed.diagnostic_codes == ["adapter_crash", "RuntimeError"]


def test_transient_failure_retry_is_a_new_linked_attempt(tmp_path, monkeypatch):
    engine = _rig(tmp_path)
    calls = []
    manifest = _artifact({"status": "recovered"})

    def flaky(_snapshot, template_ids, **_kwargs):
        calls.append(template_ids)
        if len(calls) == 1:
            return ShardExecution(
                template_ids=template_ids, status="failed",
                artifact_manifest=_artifact({"status": "crash"}),
                artifact_hash=canonical_hash({"status": "crash"}),
                diagnostic_codes=("adapter_crash",),
                resource_cost={"wall_ms": 1, "candidate_generation_count": 0},
                evaluation=None, selectable=False,
            )
        return ShardExecution(
            template_ids=template_ids, status="no_solution", artifact_manifest=manifest,
            artifact_hash=manifest["content_hash"],
            diagnostic_codes=("no_feasible_candidate",),
            resource_cost={"wall_ms": 1, "candidate_generation_count": 2},
            evaluation={}, selectable=False,
        )

    monkeypatch.setattr("nutmeg.discovery.online_recorder.execute_template_shard", flaky)
    recorded = record_shadow_world(
        _snapshot(), engine=engine, shadow_database=tmp_path / "shadow.db",
        source_database=tmp_path / "business.db", policy_revision_id="structural-baseline-v1",
        requested_at=T0, fixture_only=True,
    )
    assert len(calls) == 2
    with OntologyUnitOfWork(engine) as uow:
        nodes = uow.discovery.nodes_for_world(recorded.world_id)
        assert len(nodes) == 4
        assert nodes[2].retry_of_node_id == nodes[1].node_id
        assert nodes[1].execution_status == "failed"
        assert nodes[2].execution_status == "complete"


def test_lost_node_commit_response_retries_without_duplicate_execution(tmp_path, monkeypatch):
    from nutmeg.ontology.actions.discovery_world_actions import DiscoveryWorldActions

    engine = _rig(tmp_path)
    original = DiscoveryWorldActions.record_node
    calls = []

    def lost_response(self, request):
        calls.append(request.node.node_id)
        outcome = original(self, request)
        if len(calls) == 1:
            raise sqlite3.OperationalError("response lost after commit")
        return outcome

    monkeypatch.setattr(DiscoveryWorldActions, "record_node", lost_response)
    recorded = record_shadow_world(
        _snapshot(), engine=engine, shadow_database=tmp_path / "shadow.db",
        source_database=tmp_path / "business.db", policy_revision_id="structural-baseline-v1",
        requested_at=T0, fixture_only=True,
    )
    assert len([node_id for node_id in calls if node_id.endswith(":attempt:1")]) == 2
    with OntologyUnitOfWork(engine) as uow:
        assert len(uow.discovery.nodes_for_world(recorded.world_id)) == 3


def test_invalid_adapter_artifact_is_failed_not_selectable(tmp_path, monkeypatch):
    engine = _rig(tmp_path)
    tampered = ShardExecution(
        template_ids=("1x1",), status="complete",
        artifact_manifest={"content_hash": "different", "candidate_hashes": []},
        artifact_hash="expected", diagnostic_codes=(),
        resource_cost={"wall_ms": 1}, evaluation={"eligible_band_count": 1}, selectable=True,
    )
    monkeypatch.setattr(
        "nutmeg.discovery.online_recorder.execute_template_shard",
        lambda *_args, **_kwargs: tampered,
    )
    recorded = record_shadow_world(
        _snapshot(), engine=engine, shadow_database=tmp_path / "shadow.db",
        source_database=tmp_path / "business.db", policy_revision_id="structural-baseline-v1",
        requested_at=T0, fixture_only=True,
    )
    with OntologyUnitOfWork(engine) as uow:
        node = uow.discovery.nodes_for_world(recorded.world_id)[1]
        assert node.execution_status == "failed"
        assert node.diagnostic_codes == ["invalid_artifact"]
    assert recorded.selected_node_ids == ()


def test_exhausted_wall_budget_is_recorded_in_stop_reason(tmp_path, monkeypatch):
    engine = _rig(tmp_path)
    manifest = _artifact({"status": "no_solution"})
    slow = ShardExecution(
        template_ids=("1x1",), status="no_solution", artifact_manifest=manifest,
        artifact_hash=manifest["content_hash"],
        diagnostic_codes=("no_feasible_candidate",),
        resource_cost={"wall_ms": 120_001}, evaluation={}, selectable=False,
    )
    monkeypatch.setattr(
        "nutmeg.discovery.online_recorder.execute_template_shard",
        lambda *_args, **_kwargs: slow,
    )
    recorded = record_shadow_world(
        _snapshot(), engine=engine, shadow_database=tmp_path / "shadow.db",
        source_database=tmp_path / "business.db", policy_revision_id="structural-baseline-v1",
        requested_at=T0, fixture_only=True,
    )
    with OntologyUnitOfWork(engine) as uow:
        stop = uow.discovery.nodes_for_world(recorded.world_id)[-1]
        assert stop.artifact_manifest["reason"] == "wall_budget_exhausted"


def test_total_candidate_budget_exhaustion_preserves_unsealed_attempt(tmp_path, monkeypatch):
    engine = _rig(tmp_path)
    manifest = _artifact({"status": "over_budget"})
    expensive = ShardExecution(
        template_ids=("1x1",), status="no_solution", artifact_manifest=manifest,
        artifact_hash=manifest["content_hash"], diagnostic_codes=("no_feasible_candidate",),
        resource_cost={"wall_ms": 1, "candidate_generation_count": 50_001},
        evaluation={}, selectable=False,
    )
    monkeypatch.setattr(
        "nutmeg.discovery.online_recorder.execute_template_shard",
        lambda *_args, **_kwargs: expensive,
    )
    with pytest.raises(ValueError, match="candidate budget"):
        record_shadow_world(
            _snapshot(), engine=engine, shadow_database=tmp_path / "shadow.db",
            source_database=tmp_path / "business.db", policy_revision_id="structural-baseline-v1",
            requested_at=T0, fixture_only=True,
        )
    with OntologyUnitOfWork(engine) as uow:
        digest = canonical_hash([_snapshot().manifest_hash, "structural-baseline-v1"])
        world_id = f"discovery-world-{digest[:24]}"
        assert uow.discovery.world_state(world_id) == "running"
        assert len(uow.discovery.nodes_for_world(world_id)) == 2


def test_changed_source_preserves_unsealed_diagnostics(tmp_path, monkeypatch):
    engine = _rig(tmp_path)
    from nutmeg.discovery import online_recorder

    checks = iter(("before", "after"))
    monkeypatch.setattr(online_recorder, "_source_fingerprint", lambda _path: next(checks))
    with pytest.raises(ValueError, match="protected source changed"):
        record_shadow_world(
            _snapshot(),
            engine=engine,
            shadow_database=tmp_path / "shadow.db",
            source_database=tmp_path / "business.db",
            policy_revision_id="structural-baseline-v1",
            requested_at=T0,
            fixture_only=True,
        )
    with OntologyUnitOfWork(engine) as uow:
        digest = canonical_hash([_snapshot().manifest_hash, "structural-baseline-v1"])
        world_id = f"discovery-world-{digest[:24]}"
        assert uow.discovery.world_state(world_id) == "running"
        assert len(uow.discovery.nodes_for_world(world_id)) == 2


def test_same_frozen_execution_has_same_sealed_hash_across_shadow_stores(tmp_path, monkeypatch):
    fixed = ShardExecution(
        template_ids=("1x1",), status="no_solution",
        artifact_manifest=_artifact({"failure": "empty"}),
        artifact_hash=canonical_hash({"failure": "empty"}),
        diagnostic_codes=("no_feasible_candidate",),
        resource_cost={"wall_ms": 1}, evaluation={}, selectable=False,
    )
    monkeypatch.setattr(
        "nutmeg.discovery.online_recorder.execute_template_shard",
        lambda *_args, **_kwargs: fixed,
    )
    results = []
    for index in (1, 2):
        folder = tmp_path / str(index)
        folder.mkdir()
        engine = _rig(folder)
        results.append(record_shadow_world(
            _snapshot(), engine=engine, shadow_database=folder / "shadow.db",
            source_database=folder / "business.db", policy_revision_id="structural-baseline-v1",
            requested_at=T0, fixture_only=True,
        ).sealed_manifest_hash)
    assert results[0] == results[1]


def test_completion_order_does_not_change_visibility_order(tmp_path, monkeypatch):
    from nutmeg.product.operator_candidates import CandidateStructureTemplate

    base = _snapshot()
    second = CandidateStructureTemplate(
        kind="jczq_pass", structure_code="second", eligible_official_match_nos=("001",),
        required_offer_count=1, maximum_groups=1, pass_size=1,
    )
    snapshot = freeze_structural_input(
        candidate_input=replace(
            base.candidate_input, templates=(*base.candidate_input.templates, second)
        ),
        references=_references(), business_date=base.business_date,
        task_snapshot_hash=base.task_snapshot_hash, slate_revision_id=base.slate_revision_id,
        board_slate_revision_id=base.slate_revision_id, cutoff_at=base.cutoff_at,
        audit_policy_revision=base.audit_policy_revision, audit_offers=base.audit_offers,
    )
    completed = []
    both_started = threading.Event()
    first_wait_succeeded = []

    def execute(_snapshot, ids, **_kwargs):
        completed.append(ids[0])
        if ids[0] == "1x1":
            first_wait_succeeded.append(both_started.wait(timeout=0.5))
        else:
            both_started.set()
        return ShardExecution(
            template_ids=ids, status="no_solution",
            artifact_manifest=_artifact({"shard": ids[0]}),
            artifact_hash=canonical_hash({"shard": ids[0]}),
            diagnostic_codes=("no_feasible_candidate",),
            resource_cost={"wall_ms": 1}, evaluation={}, selectable=False,
        )

    monkeypatch.setattr("nutmeg.discovery.online_recorder.execute_template_shard", execute)
    engine = _rig(tmp_path)
    result = record_shadow_world(
        snapshot, engine=engine, shadow_database=tmp_path / "shadow.db",
        source_database=tmp_path / "business.db", policy_revision_id="structural-baseline-v1",
        requested_at=T0, fixture_only=True,
    )
    with OntologyUnitOfWork(engine) as uow:
        nodes = uow.discovery.nodes_for_world(result.world_id)
        assert [node.continuation_action["template_ids"] for node in nodes[1:-1]] == [
            ["1x1"], ["second"]
        ]
    assert set(completed) == {"1x1", "second"}
    assert first_wait_succeeded == [True]


def test_stop_selects_best_clean_node_for_each_band(tmp_path, monkeypatch):
    from nutmeg.product.operator_candidates import CandidateStructureTemplate

    base = _snapshot()
    second = CandidateStructureTemplate(
        kind="jczq_pass", structure_code="second", eligible_official_match_nos=("001",),
        required_offer_count=1, maximum_groups=1, pass_size=1,
    )
    snapshot = freeze_structural_input(
        candidate_input=replace(
            base.candidate_input, templates=(*base.candidate_input.templates, second)
        ),
        references=_references(), business_date=base.business_date,
        task_snapshot_hash=base.task_snapshot_hash, slate_revision_id=base.slate_revision_id,
        board_slate_revision_id=base.slate_revision_id, cutoff_at=base.cutoff_at,
        audit_policy_revision=base.audit_policy_revision, audit_offers=base.audit_offers,
    )

    def execute(_snapshot, ids, **_kwargs):
        probability = "0.500000000000" if ids[0] == "1x1" else "0.800000000000"
        manifest = _artifact({"shard": ids[0]})
        return ShardExecution(
            template_ids=ids, status="complete", artifact_manifest=manifest,
            artifact_hash=manifest["content_hash"], diagnostic_codes=(),
            resource_cost={"wall_ms": 1},
            evaluation={"best_objective_probability_by_band": {"10x": probability}},
            selectable=True,
        )

    monkeypatch.setattr("nutmeg.discovery.online_recorder.execute_template_shard", execute)
    engine = _rig(tmp_path)
    recorded = record_shadow_world(
        snapshot, engine=engine, shadow_database=tmp_path / "shadow.db",
        source_database=tmp_path / "business.db", policy_revision_id="structural-baseline-v1",
        requested_at=T0, fixture_only=True,
    )
    assert recorded.selected_node_ids == (f"{recorded.world_id}:attempt:2",)
    with OntologyUnitOfWork(engine) as uow:
        assert uow.discovery.nodes_for_world(recorded.world_id)[-1].artifact_manifest[
            "selected_node_ids"
        ] == list(recorded.selected_node_ids)
