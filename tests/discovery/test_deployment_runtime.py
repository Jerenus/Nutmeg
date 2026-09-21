from types import SimpleNamespace

from nutmeg.discovery.deployment_runtime import controller_for


def _event(mode, **changes):
    values = dict(
        decision=mode,
        policy_revision_id="candidate",
        rollback_policy_revision_id="prior",
        effective_boundary="2026-09-25T00:00:00+00:00",
        scope={"pilot": "structural"},
        policy_deployment_id="d1",
        evidence_refs={},
    )
    return SimpleNamespace(**(values | changes))


def test_shadow_never_controls_business_workflow():
    controller = controller_for(_event("shadow"), None, boundary="2026-09-26T00:00:00+00:00")
    assert controller.authoritative is False
    assert controller.mode == "shadow"


def test_brake_restores_only_recorded_fallback():
    event = _event("canary")
    brake = SimpleNamespace(
        restored_policy_revision_id="prior", effective_boundary="2026-09-27T00:00:00+00:00"
    )
    controller = controller_for(event, brake, boundary="2026-09-27T00:00:00+00:00")
    assert controller.authoritative is False
    assert controller.policy_revision_id == "prior"
    assert controller.mode == "braked"


def test_control_without_reviewed_scope_is_never_authoritative():
    controller = controller_for(_event("deploy"), None, boundary="2026-09-26T00:00:00+00:00")
    assert controller.authoritative is False


def test_future_boundary_is_not_active():
    controller = controller_for(_event("canary"), None, boundary="2026-09-24T00:00:00+00:00")
    assert controller.authoritative is False


def test_reviewed_scope_caps_exposure_and_rejects_other_board():
    from nutmeg.ontology.discovery.models import canonical_hash
    from tests.discovery.test_pilot_scope import _contract

    contract = _contract()
    event = _event("canary", scope=contract["scope"],
                   effective_boundary=contract["effective_boundary"],
                   evidence_refs={"scope_contract": contract,
                                  "scope_contract_hash": canonical_hash(contract),
                                  "scope_approval_ref": contract["approval_ref"]})
    approved = dict(reviewed_hash=canonical_hash(contract),
                    approval_ref=contract["approval_ref"])
    assert not controller_for(event, None, boundary="2026-09-26T00:00:00+00:00",
                              board="board-1", exposure_used=1, **approved).authoritative
    from nutmeg.discovery.deployment_runtime import policy_lineage

    controller = controller_for(event, None, boundary="2026-09-26T00:00:00+00:00",
                                board="board-1", exposure_used=1, **approved)
    import pytest

    with pytest.raises(ValueError, match="inactive"):
        policy_lineage(controller)
    for board, used in (("board-2", 0), ("board-1", 2)):
        assert not controller_for(event, None, boundary="2026-09-26T00:00:00+00:00",
                                  board=board, exposure_used=used, **approved).authoritative
    assert not controller_for(event, None, boundary="2026-09-26T00:00:00+00:00",
                              board="board-1", exposure_used=0).authoritative
