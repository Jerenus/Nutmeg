from nutmeg.discovery.drift_monitor import DriftSample, assess_drift


def sample(name, quality=1.0, nodes=10, code=None, stratum="small"):
    return DriftSample(name, stratum, quality, nodes, 2, 1.0, 1.0, 2, code)


def test_unknown_and_insufficient_samples_do_not_optimistically_pass():
    assert assess_drift((), (sample("n"),)).state == "unavailable"
    assert assess_drift((sample("o"),), (sample("n"),)).state == "insufficient_sample"


def test_branch_growth_without_frozen_quality_gain_holds():
    old = tuple(sample(f"o{i}") for i in range(3))
    new = tuple(sample(f"n{i}", nodes=15) for i in range(3))
    report = assess_drift(old, new)
    assert report.state == "hold_for_review"
    assert report.brake_code is None
    assert report.winner_id is None


def test_material_gain_in_other_frozen_quality_field_prevents_false_hold():
    from dataclasses import replace

    old = tuple(replace(sample(f"o{i}"), quality_vector=(1.0, 0.5, 2.0)) for i in range(3))
    new = tuple(
        replace(sample(f"n{i}", nodes=15), quality_vector=(1.0, 0.6, 2.0)) for i in range(3)
    )
    assert assess_drift(old, new).state == "observed"


def test_only_registered_hard_invariant_can_signal_brake():
    old = tuple(sample(f"o{i}") for i in range(3))
    soft = tuple(sample(f"n{i}", code="unregistered") for i in range(3))
    hard = tuple(sample(f"n{i}", code="protected_source_mutation") for i in range(3))
    assert assess_drift(old, soft).brake_code is None
    assert assess_drift(old, hard).brake_code is None
    assert (
        assess_drift(
            old, hard, registered_hard_invariants=("protected_source_mutation",)
        ).brake_code
        == "protected_source_mutation"
    )
