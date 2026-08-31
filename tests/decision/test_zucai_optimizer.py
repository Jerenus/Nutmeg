import copy
import json
from pathlib import Path

import pytest

from nutmeg.decision.zucai_optimizer import OptimizerInputError, format_report, optimize


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


def test_full_cover_is_certain_despite_rounded_fair_sum() -> None:
    payload = _payload()
    payload["fair"]["1"] = {"home": 0.5, "draw": 0.3, "away": 0.199}
    payload["versions"] = [{"id": "full", "faces": {"1": "310"}}]

    version = optimize(payload)["versions"][0]

    assert version["p_all"] == 1
    assert version["expected_broken"] == 0


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


def test_26111_u864_series_matches_recorded_probabilities() -> None:
    payload = {
        "issue": "26111",
        "price_per_note": 2,
        "budget_yuan": 864,
        "fair": {
            "1": {"home": 0.631, "draw": 0.193, "away": 0.176},
            "3": {"home": 0.622, "draw": 0.234, "away": 0.144},
            "5": {"home": 0.390, "draw": 0.295, "away": 0.315},
            "7": {"home": 0.753, "draw": 0.154, "away": 0.092},
            "9": {"home": 0.169, "draw": 0.200, "away": 0.631},
            "10": {"home": 0.636, "draw": 0.212, "away": 0.152},
            "11": {"home": 0.342, "draw": 0.290, "away": 0.367},
            "12": {"home": 0.702, "draw": 0.176, "away": 0.122},
            "14": {"home": 0.701, "draw": 0.177, "away": 0.122},
        },
        "versions": [
            {
                "id": "U864用户版",
                "faces": {
                    "1": "310",
                    "3": "3",
                    "5": "310",
                    "7": "31",
                    "9": "01",
                    "10": "31",
                    "11": "310",
                    "12": "31",
                    "14": "3",
                },
            },
            {
                "id": "U864优化版",
                "faces": {
                    "1": "310",
                    "3": "31",
                    "5": "310",
                    "7": "3",
                    "9": "01",
                    "10": "31",
                    "11": "310",
                    "12": "31",
                    "14": "3",
                },
            },
            {
                "id": "U1296",
                "faces": {
                    "1": "310",
                    "3": "31",
                    "5": "310",
                    "7": "3",
                    "9": "310",
                    "10": "31",
                    "11": "310",
                    "12": "31",
                    "14": "3",
                },
            },
        ],
    }

    result = optimize(payload)

    versions = {version["id"]: version for version in result["versions"]}
    assert [(versions[name]["notes"], versions[name]["cost_yuan"]) for name in versions] == [
        (432, 864),
        (432, 864),
        (648, 1296),
    ]
    # Persisted legs fair is rounded to 3 dp; rx kept 2 dp percentages from the
    # higher-precision working values. Half of the fair quantum is the replay tolerance.
    assert versions["U864用户版"]["p_all"] * 100 == pytest.approx(24.49, abs=0.05)
    assert versions["U864优化版"]["p_all"] * 100 == pytest.approx(27.96, abs=0.05)
    assert versions["U1296"]["p_all"] * 100 == pytest.approx(33.65, abs=0.05)
    assert result["ranking"] == ["U864优化版", "U864用户版"]
    assert result["best_within_cap_id"] == "U864优化版"


def _econ_payload(**changes):
    payload = {
        "issue": "26114",
        "price_per_note": 2,
        "median_bonus_yuan": 3113,
        "fair": {
            "1": {"home": 0.50, "draw": 0.30, "away": 0.20},
            "2": {"home": 0.60, "draw": 0.25, "away": 0.15},
        },
        "versions": [
            {"id": "small", "faces": {"1": "3", "2": "3"}},        # 1注, P=0.30
            {"id": "wide", "faces": {"1": "31", "2": "31"}},       # 4注, P=0.68
        ],
    }
    payload.update(changes)
    return payload


def test_break_even_line_computed_and_ranked_ascending():
    """s条修订(2026-08-31):给了 median_bonus_yuan 就按回本线升序,不按 P 降序。

    任九类固定奖金玩法中奖只拿 1 注奖金,加注必然抬高回本线 —— 26114 实证。
    """
    result = optimize(_econ_payload())
    by_id = {v["id"]: v for v in result["versions"]}
    # small: 2/0.30 ≈ 6.67 ; wide: 8/0.68 ≈ 11.76
    assert by_id["small"]["break_even_bonus_yuan"] < by_id["wide"]["break_even_bonus_yuan"]
    assert by_id["small"]["break_even_to_median"] == pytest.approx(
        by_id["small"]["break_even_bonus_yuan"] / 3113)
    # 排名按回本线升序 → small 在前，尽管 wide 的 P 更高
    assert result["ranking"][0] == "small"
    assert by_id["wide"]["p_all"] > by_id["small"]["p_all"]


def test_without_median_ranking_falls_back_to_probability():
    """未提供奖金锚时维持旧行为（P 降序），避免影响竞彩类玩法。"""
    payload = _econ_payload()
    del payload["median_bonus_yuan"]
    result = optimize(payload)
    assert result["ranking"][0] == "wide"          # P 最高者在前
    assert result["median_bonus_yuan"] is None
    assert "break_even_to_median" not in result["versions"][0]


def test_median_bonus_must_be_positive():
    with pytest.raises(OptimizerInputError):
        optimize(_econ_payload(median_bonus_yuan=0))


def test_fixed_bonus_ranking_keeps_decimal_precision():
    payload = {
        "issue": "26114",
        "median_bonus_yuan": 100,
        "fair": {
            "1": {
                "home": "0.333333333333333333",
                "draw": "0.333333333333333334",
                "away": "0.333333333333333333",
            }
        },
        "versions": [
            {"id": "single", "faces": {"1": "3"}},
            {"id": "double", "faces": {"1": "31"}},
        ],
    }

    result = optimize(payload)

    assert result["ranking"] == ["double", "single"]


def test_26114_fixed_bonus_fixture_replays_report_and_ranking():
    fixture = Path(__file__).parents[1] / "fixtures/zucai/26114-optimizer-break-even.json"
    result = optimize(json.loads(fixture.read_text("utf-8")))
    report = format_report(result)

    assert result["best_within_cap_id"] == "R256"
    assert "回本线" in report
    assert "官方中位奖金锚: ¥3,113" in report
    assert "排序按回本线升序" in report
