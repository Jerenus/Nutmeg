import pytest

from nutmeg.discovery.pilot_scope import validate_control_scope


def _contract():
    return {
        "schema_version": "1", "pilot_id": "structural-candidate-v1",
        "family": "structural_candidate_exploration", "task_family": "structural_candidate_audit",
        "mode": "scoped_control", "scope": {"pilot": "structural", "board": "board-1"},
        "operators": ["enumerate_template_shard", "stop"],
        "effective_boundary": "2026-09-26T00:00:00+00:00", "exposure_cap": 2,
        "fallback_policy_revision_id": "prior", "no_ticket_fallback": True,
        "brake_codes": ["permission_leak", "protected_mutation"],
        "approval_ref": "review:external-1",
    }


def test_control_contract_requires_external_reviewed_hash_and_approval():
    from nutmeg.discovery.pilot_scope import PilotScopeContract
    from nutmeg.ontology.discovery.models import canonical_hash

    document = _contract()
    contract = PilotScopeContract.model_validate(document)
    with pytest.raises((TypeError, ValueError)):
        contract.scope["board"] = "other"
    digest = canonical_hash(contract.model_dump(mode="json"))
    assert validate_control_scope(document["scope"], document, reviewed_hash=digest,
                                  approval_ref="review:external-1") == contract
    for supplied in (None, "0" * 64):
        with pytest.raises(ValueError, match="reviewed prospective scope"):
            validate_control_scope(document["scope"], document, reviewed_hash=supplied,
                                   approval_ref="review:external-1")
    with pytest.raises(ValueError, match="reviewed prospective scope"):
        validate_control_scope(document["scope"], document, reviewed_hash=digest)


@pytest.mark.parametrize("change", [
    {"exposure_cap": 0}, {"operators": ["place_ticket"]},
    {"no_ticket_fallback": False}, {"mode": "shadow_only"},
    {"scope": {"pilot": "other"}}, {"brake_codes": []},
    {"protected_actions": ["place_ticket"]},
])
def test_control_contract_rejects_expanded_or_unsafe_surface(change):
    from nutmeg.discovery.pilot_scope import PilotScopeContract

    with pytest.raises(ValueError):
        PilotScopeContract.model_validate(_contract() | change)


def test_shadow_only_contract_never_grants_control():
    with pytest.raises(ValueError, match="reviewed prospective scope"):
        validate_control_scope({"pilot": "structural"}, {"mode": "shadow_only"})


def test_fixture_claim_of_approval_is_not_authority():
    with pytest.raises(ValueError, match="reviewed prospective scope"):
        validate_control_scope({"pilot": "structural", "approved": True}, {"mode": "shadow_only"})
