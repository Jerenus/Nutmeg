from types import SimpleNamespace

from nutmeg.discovery.brake_monitor import brake_condition


def test_registered_hard_condition_trips_once():
    deployment = SimpleNamespace(brake_conditions={"conditions": ["permission_leak"]})
    assert brake_condition(
        deployment, {"permission_leak": "evidence-hash"}, already_braked=False
    ) == ("permission_leak", "evidence-hash")
    assert (
        brake_condition(deployment, {"permission_leak": "evidence-hash"}, already_braked=True)
        is None
    )


def test_unregistered_or_unverified_condition_never_selects_target():
    deployment = SimpleNamespace(brake_conditions={"conditions": ["permission_leak"]})
    assert (
        brake_condition(deployment, {"resource_overrun": "evidence-hash"}, already_braked=False)
        is None
    )
    assert brake_condition(deployment, {"permission_leak": ""}, already_braked=False) is None
