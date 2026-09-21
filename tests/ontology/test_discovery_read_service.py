from __future__ import annotations

import pytest

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.discovery.read_service import DiscoveryReadService
from nutmeg.ontology.repository.discovery import PolicyParentLinkRow
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel
from tests.ontology.test_discovery_governance_actions import (
    _deployment_request,
    _finished,
    _rig,
)
from tests.ontology.test_discovery_repository import _policy, _record


def test_kernel_exposes_three_discovery_action_facades_and_counts(tmp_path):
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    for name in (
        "discovery_world_actions",
        "discovery_policy_actions",
        "discovery_governance_actions",
        "discovery_read",
    ):
        assert getattr(kernel, name) is not None
    assert kernel.status().discovery_world_count == 0
    kernel.initialize()
    assert kernel.status().policy_tournament_count == 0
    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.discovery.insert_policy(_policy("policy-1"))
    state = kernel.status()
    assert state.exploration_policy_revision_count == 1
    assert state.discovery_world_count == 0
    assert state.to_dict()["exploration_policy_revision_count"] == 1


def test_status_projection_returns_incumbent_tournament_world_and_rollback(tmp_path):
    actions, engine = _rig(tmp_path)
    _finished(actions, engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.discovery.insert_deployment(_deployment_request("shadow").deployment)
    service = DiscoveryReadService(engine)
    state = service.status("family-1")
    assert state.incumbent_policy_revision_id == "policy-1"
    assert state.active_deployment_state == "shadow"
    assert state.latest_tournament_id == "t-1"
    assert state.latest_world_id == "world-extra-28"
    assert state.sealed_world_count == 30
    assert state.exposed_holdout_count == 1
    assert state.rollback_policy_revision_id == "policy-2"


def test_world_detail_orders_nodes_by_visibility_and_never_exposes_hidden_children(tmp_path):
    actions, engine = _rig(tmp_path)
    _finished(actions, engine)
    detail = DiscoveryReadService(engine).world_detail("world-1")
    assert [node["node_id"] for node in detail["nodes"]] == [
        "world-1:root",
        "world-1:child",
        "world-1:second",
    ]
    assert "unrecorded" not in str(detail)
    with pytest.raises(KeyError):
        DiscoveryReadService(engine).world_detail("missing")


def test_policy_lineage_reports_generator_parents_archive_and_deployment_separately(tmp_path):
    actions, engine = _rig(tmp_path)
    _finished(actions, engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.discovery.insert_policy_parent_link(
            _record(
                PolicyParentLinkRow,
                policy_revision_id="policy-2",
                parent_index=0,
                parent_policy_revision_id="policy-1",
            )
        )
        uow.discovery.insert_deployment(_deployment_request("shadow").deployment)
    service = DiscoveryReadService(engine)
    winning = service.policy_lineage("policy-1")
    stepping = service.policy_lineage("policy-2")
    assert stepping["parents"] == ["policy-1"]
    assert stepping["archive_disposition"] == "stepping_stone"
    assert stepping["tournament_winner"] is False
    assert stepping["deployment_state"] is None
    assert winning["tournament_winner"] is True
    assert winning["deployment_state"] == "shadow"


def test_tournament_detail_decodes_archive_evidence(tmp_path):
    actions, engine = _rig(tmp_path)
    _finished(actions, engine)
    detail = DiscoveryReadService(engine).tournament_detail("t-1")
    assert detail["completion"]["winner_policy_revision_id"] == "policy-1"
    assert detail["archive_decisions"][0]["evidence"] == {"valid": True}


def test_tournament_detail_exposes_frozen_contract_hash_and_exposure_slice(tmp_path):
    actions, engine = _rig(tmp_path)
    _finished(actions, engine)
    detail = DiscoveryReadService(engine).tournament_detail("t-1")

    assert len(detail["results"]) == 60
    assert (
        detail["selection_contract_hash"]
        == detail["tournament"]["decision_contract"]["selection_contract_hash"]
    )
    assert detail["exposed_holdout_world_ids"] == ["world-2"]
