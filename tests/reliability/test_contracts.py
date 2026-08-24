from copy import deepcopy

import pytest

from nutmeg.reliability.contracts import (
    FAULT_SCENARIOS,
    PERFORMANCE_BUDGETS_MS,
    validate_fault_matrix,
    validate_performance_report,
    validate_soak_report,
)


def _fault_report() -> dict[str, object]:
    return {
        "schema_version": "fault-v1",
        "candidate_commit": "abc123",
        "policy_version": "release-v1",
        "scenarios": [
            {
                "scenario": scenario,
                "test_ref": f"tests/fault/test_{scenario}.py",
                "observed_result": f"{scenario} contained without corruption",
                "outcome": "blocked" if scenario == "sqlite_lock" else "retryable",
                "state_corruption": False,
            }
            for scenario in FAULT_SCENARIOS
        ],
    }


def _performance_report() -> dict[str, object]:
    return {
        "schema_version": "performance-v1",
        "candidate_commit": "abc123",
        "policy_version": "release-v1",
        "volume_multiplier": 10,
        "metrics": {
            metric: {"p95_ms": budget, "sample_count": 20}
            for metric, budget in PERFORMANCE_BUDGETS_MS.items()
        },
    }


def test_fault_matrix_requires_exact_executable_scenarios() -> None:
    report = _fault_report()
    assert validate_fault_matrix(report).passed is True

    missing = deepcopy(report)
    missing["scenarios"].pop()  # type: ignore[union-attr]
    with pytest.raises(ValueError, match="missing fault scenario"):
        validate_fault_matrix(missing)

    duplicate = deepcopy(report)
    duplicate["scenarios"].append(deepcopy(duplicate["scenarios"][0]))  # type: ignore[union-attr,index]
    with pytest.raises(ValueError, match="duplicate fault scenario"):
        validate_fault_matrix(duplicate)

    unknown = deepcopy(report)
    unknown["scenarios"][0]["scenario"] = "unknown"  # type: ignore[index]
    with pytest.raises(ValueError, match="unknown fault scenario"):
        validate_fault_matrix(unknown)

    claimed = deepcopy(report)
    claimed["scenarios"][0]["test_ref"] = ""  # type: ignore[index]
    with pytest.raises(ValueError, match="test_ref"):
        validate_fault_matrix(claimed)


def test_fault_matrix_records_a_valid_failed_outcome() -> None:
    report = _fault_report()
    report["scenarios"][0]["state_corruption"] = True  # type: ignore[index]

    result = validate_fault_matrix(report)

    assert result.passed is False
    assert result.failures == ("provider_timeout:state_corruption",)


def test_performance_contract_has_fixed_budgets_and_finite_samples() -> None:
    report = _performance_report()
    assert validate_performance_report(report).passed is True

    too_small = deepcopy(report)
    too_small["volume_multiplier"] = 9
    with pytest.raises(ValueError, match="volume_multiplier"):
        validate_performance_report(too_small)

    missing = deepcopy(report)
    del missing["metrics"]["action_ack_ms"]  # type: ignore[index]
    with pytest.raises(ValueError, match="missing performance metric"):
        validate_performance_report(missing)

    non_finite = deepcopy(report)
    non_finite["metrics"]["board_query_ms"]["p95_ms"] = float("nan")  # type: ignore[index]
    with pytest.raises(ValueError, match="finite"):
        validate_performance_report(non_finite)

    over = deepcopy(report)
    over["metrics"]["match_query_ms"]["p95_ms"] = 801  # type: ignore[index]
    result = validate_performance_report(over)
    assert result.passed is False
    assert result.failures == ("match_query_ms:budget_exceeded",)


def test_soak_contract_forbids_dispatch_synthetic_and_divergence() -> None:
    report = {
        "schema_version": "soak-v1",
        "policy_version": "release-v1",
        "dispatch": False,
        "synthetic": False,
        "divergences": {"identity": 0, "audit": 0, "ledger": 0},
    }
    assert validate_soak_report(report).passed is True

    dispatched = {**report, "dispatch": True}
    assert validate_soak_report(dispatched).failures == ("dispatch_enabled",)

    synthetic = {**report, "synthetic": True}
    assert validate_soak_report(synthetic).failures == ("synthetic_evidence",)

    divergent = deepcopy(report)
    divergent["divergences"]["identity"] = 1  # type: ignore[index]
    assert validate_soak_report(divergent).failures == ("identity_divergence",)

    malformed = deepcopy(report)
    malformed["divergences"]["audit"] = -1  # type: ignore[index]
    with pytest.raises(ValueError, match="non-negative integer"):
        validate_soak_report(malformed)
