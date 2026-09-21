import pytest

from nutmeg.discovery.pilot_scope import validate_control_scope


def test_shadow_only_contract_never_grants_control():
    with pytest.raises(ValueError, match="reviewed prospective scope"):
        validate_control_scope({"pilot": "structural"}, {"mode": "shadow_only"})


def test_fixture_claim_of_approval_is_not_authority():
    with pytest.raises(ValueError, match="reviewed prospective scope"):
        validate_control_scope({"pilot": "structural", "approved": True}, {"mode": "shadow_only"})
