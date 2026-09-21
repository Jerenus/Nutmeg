from __future__ import annotations

import pytest

from nutmeg.ontology.discovery.models import (
    ArchiveDisposition,
    ChangeSurface,
    DeploymentDecision,
    WorldEventKind,
    canonical_hash,
    project_policy_lifecycle,
    project_world_state,
    validate_change_surfaces,
)


def test_canonical_hash_ignores_key_order_but_not_values():
    assert canonical_hash({"b": 2, "a": 1}) == canonical_hash({"a": 1, "b": 2})
    assert canonical_hash({"a": 1}) != canonical_hash({"a": 2})


def test_world_projection_is_append_only_and_terminal():
    assert project_world_state(()) == "missing"
    assert project_world_state((WorldEventKind.CREATED,)) == "created"
    assert project_world_state((WorldEventKind.CREATED, WorldEventKind.RUN_STARTED)) == "running"
    assert project_world_state((WorldEventKind.CREATED, WorldEventKind.SEALED)) == "sealed"
    with pytest.raises(ValueError, match="terminal"):
        project_world_state(
            (WorldEventKind.CREATED, WorldEventKind.SEALED, WorldEventKind.RUN_STARTED)
        )


def test_v1_rejects_frozen_change_surface():
    validate_change_surfaces((ChangeSurface.EXPLORATION_POLICY,))
    validate_change_surfaces((ChangeSurface.CLOSED_OPERATOR,))
    with pytest.raises(ValueError, match="frozen"):
        validate_change_surfaces((ChangeSurface.MODEL_OR_SYSTEM,))


def test_archive_is_not_deployment_and_lifecycle_is_conservative():
    assert ArchiveDisposition.STEPPING_STONE.value == "stepping_stone"
    assert project_policy_lifecycle(registered=True, winner=False, deployment=None) == "validated"
    assert project_policy_lifecycle(
        registered=True, winner=False, deployment=None,
        archive_disposition=ArchiveDisposition.STEPPING_STONE,
    ) == "stepping_stone"
    assert project_policy_lifecycle(
        registered=True, winner=True, deployment=DeploymentDecision.SHADOW,
    ) == "shadow"
