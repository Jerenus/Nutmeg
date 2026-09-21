from __future__ import annotations

import pytest
from pydantic import ValidationError

from nutmeg.discovery.generation_contracts import PolicyProgramArtifact, program_policy_revision_id


def _document():
    body = {
        "schema_version": "1",
        "family": "structural_candidate_exploration",
        "interface_version": "discovery-policy-v1",
        "constraints_version": "structural-candidate-v1",
        "generator_family": "bounded_evolution",
        "generator_revision": "bounded-evolution-v1",
        "parent_policy_revision_ids": ["a", "b"],
        "seed": 7,
        "change_surfaces": ["exploration_policy"],
        "descriptor_set": ["batch", "priority"],
        "program": {
            "template_order": ["1x1", "2x1"],
            "batch_limit": 2,
            "budget_allocation": "frontier_first",
            "stop_quality_threshold": "0",
        },
    }
    return {"policy_revision_id": program_policy_revision_id(body), **body}


def test_program_is_strict_content_addressed_and_stable():
    doc = _document()
    first = PolicyProgramArtifact.model_validate(doc)
    assert first == PolicyProgramArtifact.model_validate(dict(reversed(doc.items())))
    assert first.policy_revision_id == program_policy_revision_id(
        first.model_dump(mode="json", exclude={"policy_revision_id"})
    )
    for field, value in (
        ("model_weights", {"x": 1}),
        ("python_code", "import os"),
        ("evaluator", "changed"),
        ("permissions", ["deploy"]),
        ("business_rules", {}),
        ("resources", ["network"]),
        ("prompt", "unregistered"),
    ):
        with pytest.raises(ValidationError, match="forbidden|extra"):
            PolicyProgramArtifact.model_validate({**doc, field: value})


def test_program_rejects_parent_disorder_and_unbounded_state():
    doc = _document()
    for parents in (["b", "a"], ["a", "a"]):
        with pytest.raises(ValueError, match="parent"):
            PolicyProgramArtifact.model_validate({**doc, "parent_policy_revision_ids": parents})
    with pytest.raises(ValueError, match="state|size"):
        PolicyProgramArtifact.model_validate(
            {**doc, "program": {**doc["program"], "template_order": ["x" * 17000]}}
        )
    with pytest.raises(ValidationError):
        PolicyProgramArtifact.model_validate(
            {**doc, "program": {**doc["program"], "prompt_slot": "anything"}}
        )
