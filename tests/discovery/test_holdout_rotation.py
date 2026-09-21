import pytest

from nutmeg.discovery.holdout_rotation import Exposure, RotationWorld, validate_rotation


def test_exposed_world_never_hidden_again():
    with pytest.raises(ValueError, match="exposed.*hidden"):
        validate_rotation(
            (Exposure("old", ("d", "s", "r"), "2026-09-01T00:00:00+00:00"),),
            (RotationWorld("old", ("d", "s", "r"), "2026-09-01T00:00:00+00:00", "holdout", True),),
        )


@pytest.mark.parametrize(
    "cutoff,sealed,cluster",
    [
        ("2026-09-01T00:00:00+00:00", True, ("new", "s", "r")),
        ("2026-09-02T00:00:00+00:00", False, ("new", "s", "r")),
        ("2026-09-02T00:00:00+00:00", True, ("d", "s", "r")),
    ],
)
def test_exposed_development_requires_strict_new_sealed_hidden_holdout(cutoff, sealed, cluster):
    with pytest.raises(ValueError, match="strictly newer|exposed world"):
        validate_rotation(
            (Exposure("old", ("d", "s", "r"), "2026-09-01T00:00:00+00:00"),),
            (
                RotationWorld(
                    "old", ("d", "s", "r"), "2026-09-01T00:00:00+00:00", "development", True
                ),
                RotationWorld("new", cluster, cutoff, "holdout", sealed),
            ),
        )


def test_strict_new_sealed_hidden_holdout_allows_development_reuse():
    validate_rotation(
        (Exposure("old", ("d", "s", "r"), "2026-09-01T00:00:00+00:00"),),
        (
            RotationWorld("old", ("d", "s", "r"), "2026-09-01T00:00:00+00:00", "development", True),
            RotationWorld("new", ("new", "s", "r"), "2026-09-02T00:00:00+00:00", "holdout", True),
        ),
    )


def test_hidden_holdout_cannot_be_generator_input():
    with pytest.raises(ValueError, match="generator input"):
        validate_rotation(
            (),
            (
                RotationWorld(
                    "new", ("new", "s", "r"), "2026-09-02T00:00:00+00:00", "holdout", True
                ),
            ),
            generator_world_ids=("new",),
        )
    with pytest.raises(ValueError, match="generator input"):
        validate_rotation(
            (),
            (
                RotationWorld(
                    "derivative", ("new", "s", "r"), "2026-09-02T00:00:00+00:00", "holdout", True
                ),
            ),
            generator_cluster_keys=(("new", "s", "r"),),
        )
