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


def test_cap_ranking_and_baseline_deltas_are_stable() -> None:
    payload = _payload()
    payload["baseline_id"] = "A"
    payload["versions"] += [
        {"id": "B", "faces": {"1": "310", "2": "3"}},
        {"id": "C", "faces": {"1": "31", "2": "31"}},
        {"id": "D", "faces": {"1": "31", "2": "3"}},
    ]
    payload["budget_yuan"] = 8

    result = optimize(payload)

    assert result["ranking"] == ["C", "B", "A", "D"]
    assert result["best_within_cap_id"] == "C"
    c_version = next(item for item in result["versions"] if item["id"] == "C")
    assert c_version["within_cap"] is True
    assert c_version["delta_vs_baseline"] == pytest.approx(
        {
            "notes": 2,
            "cost_yuan": 4,
            "p_all_pp": 20,
            "expected_broken": -0.25,
        }
    )


def test_no_candidate_within_cap_is_reported_without_a_decision() -> None:
    payload = _payload()
    payload["budget_yuan"] = 1

    result = optimize(payload)

    assert result["ranking"] == []
    assert result["best_within_cap_id"] is None
    assert result["versions"][0]["within_cap"] is False


def test_group_union_probability_uses_inclusion_exclusion() -> None:
    payload = _payload()
    payload["versions"] = [
        {"id": "H", "faces": {"1": "3"}},
        {"id": "D", "faces": {"1": "1"}},
    ]
    payload["groups"] = [{"id": "pair", "version_ids": ["H", "D"]}]

    group = optimize(payload)["groups"][0]

    assert group["p_any_all"] == pytest.approx(0.8)
    assert group["common_dead_faces"] == [{"match_no": "1", "faces": "0"}]


def test_group_intersection_combines_constraints_on_different_legs() -> None:
    payload = _payload()
    payload["versions"] = [
        {"id": "M1", "faces": {"1": "3"}},
        {"id": "M2", "faces": {"2": "3"}},
    ]
    payload["groups"] = [{"id": "pair", "version_ids": ["M1", "M2"]}]

    group = optimize(payload)["groups"][0]

    assert group["p_any_all"] == pytest.approx(0.8)
    assert group["common_dead_faces"] == []


@pytest.mark.parametrize(
    "groups",
    [
        [{"id": "pair", "version_ids": ["A", "missing"]}],
        [{"id": "pair", "version_ids": ["A", "A"]}],
        [
            {"id": "pair", "version_ids": ["A"]},
            {"id": "pair", "version_ids": ["A"]},
        ],
    ],
)
def test_invalid_group_references_are_rejected(groups) -> None:
    payload = _payload()
    payload["groups"] = groups

    with pytest.raises(OptimizerInputError):
        optimize(payload)
