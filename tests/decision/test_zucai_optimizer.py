import copy

import pytest

from nutmeg.decision.zucai_optimizer import OptimizerInputError, optimize


def _payload() -> dict:
    return {
        "issue": "X",
        "price_per_note": 2,
        "budget_yuan": 12,
        "fair": {
            "1": {"home": 0.5, "draw": 0.3, "away": 0.2},
            "2": {"home": 0.6, "draw": 0.25, "away": 0.15},
        },
        "versions": [{"id": "A", "faces": {"1": "31", "2": "3"}}],
    }


def test_single_version_arithmetic() -> None:
    result = optimize(_payload())

    version = result["versions"][0]
    assert version["notes"] == 2
    assert version["cost_yuan"] == 4
    assert version["p_all"] == pytest.approx(0.48)
    assert version["expected_broken"] == pytest.approx(0.6)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload["fair"]["1"].update(away=0.1),
        lambda payload: payload["versions"][0]["faces"].update({"1": "33"}),
        lambda payload: payload["versions"][0]["faces"].update({"1": "3x"}),
        lambda payload: payload["versions"][0]["faces"].update({"3": "3"}),
        lambda payload: payload["versions"].append({"id": "A", "faces": {"1": "3"}}),
    ],
)
def test_invalid_input_is_rejected(mutation) -> None:
    payload = copy.deepcopy(_payload())
    mutation(payload)

    with pytest.raises(OptimizerInputError):
        optimize(payload)
