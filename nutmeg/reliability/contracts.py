"""Strict, deterministic contracts for release-governance evidence."""
from __future__ import annotations

import math
from dataclasses import dataclass

RELEASE_POLICY_VERSION = "release-v1"

FAULT_SCENARIOS = (
    "provider_timeout",
    "partial_provider_response",
    "invalid_provider_schema",
    "sqlite_lock",
    "process_interruption",
    "duplicate_action",
    "sse_disconnect",
    "projection_interruption",
)
FAULT_OUTCOMES = {"retryable", "degraded", "blocked"}

PERFORMANCE_BUDGETS_MS = {
    "board_query_ms": 500.0,
    "match_query_ms": 800.0,
    "action_ack_ms": 1000.0,
    "event_reconnect_ms": 2000.0,
}

EVIDENCE_KINDS = frozenset(
    {
        "scheduler_authority",
        "deterministic_suite",
        "migration_replay",
        "fault_matrix",
        "ai_safety",
        "browser_e2e",
        "performance",
        "backup_restore",
        "observability",
        "soak_run",
    }
)


@dataclass(frozen=True, slots=True)
class ValidationResult:
    passed: bool
    failures: tuple[str, ...] = ()


def validate_json_value(value: object, path: str = "report") -> None:
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must contain only finite JSON numbers")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            validate_json_value(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} JSON object keys must be strings")
            validate_json_value(item, f"{path}.{key}")
        return
    raise ValueError(f"{path} must contain only JSON values")


def _object(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _exact_keys(document: dict[str, object], expected: set[str], name: str) -> None:
    missing = expected - set(document)
    unknown = set(document) - expected
    if missing:
        raise ValueError(f"{name} missing fields: {', '.join(sorted(missing))}")
    if unknown:
        raise ValueError(f"{name} has unknown fields: {', '.join(sorted(unknown))}")


def _required_string(document: dict[str, object], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    return value


def _common_report(document: dict[str, object], schema_version: str) -> None:
    if document.get("schema_version") != schema_version:
        raise ValueError(f"schema_version must be {schema_version}")
    _required_string(document, "candidate_commit")
    if document.get("policy_version") != RELEASE_POLICY_VERSION:
        raise ValueError(f"policy_version must be {RELEASE_POLICY_VERSION}")


def validate_fault_matrix(report: dict[str, object]) -> ValidationResult:
    validate_json_value(report)
    _exact_keys(
        report,
        {"schema_version", "candidate_commit", "policy_version", "scenarios"},
        "fault report",
    )
    _common_report(report, "fault-v1")
    scenarios = report["scenarios"]
    if not isinstance(scenarios, list):
        raise ValueError("scenarios must be an array")
    seen: set[str] = set()
    failures: list[str] = []
    row_keys = {
        "scenario",
        "test_ref",
        "observed_result",
        "outcome",
        "state_corruption",
    }
    for raw in scenarios:
        row = _object(raw, "fault scenario")
        _exact_keys(row, row_keys, "fault scenario")
        scenario = _required_string(row, "scenario")
        if scenario not in FAULT_SCENARIOS:
            raise ValueError(f"unknown fault scenario {scenario}")
        if scenario in seen:
            raise ValueError(f"duplicate fault scenario {scenario}")
        seen.add(scenario)
        _required_string(row, "test_ref")
        _required_string(row, "observed_result")
        if row["outcome"] not in FAULT_OUTCOMES:
            raise ValueError(f"invalid fault outcome for {scenario}")
        if not isinstance(row["state_corruption"], bool):
            raise ValueError("state_corruption must be boolean")
        if row["state_corruption"]:
            failures.append(f"{scenario}:state_corruption")
    missing = set(FAULT_SCENARIOS) - seen
    if missing:
        raise ValueError(f"missing fault scenario: {', '.join(sorted(missing))}")
    return ValidationResult(not failures, tuple(failures))


def validate_performance_report(report: dict[str, object]) -> ValidationResult:
    validate_json_value(report)
    _exact_keys(
        report,
        {
            "schema_version",
            "candidate_commit",
            "policy_version",
            "volume_multiplier",
            "metrics",
        },
        "performance report",
    )
    _common_report(report, "performance-v1")
    multiplier = report["volume_multiplier"]
    if (
        isinstance(multiplier, bool)
        or not isinstance(multiplier, (int, float))
        or not math.isfinite(float(multiplier))
        or multiplier < 10
    ):
        raise ValueError("volume_multiplier must be finite and at least 10")
    metrics = _object(report["metrics"], "metrics")
    missing = set(PERFORMANCE_BUDGETS_MS) - set(metrics)
    unknown = set(metrics) - set(PERFORMANCE_BUDGETS_MS)
    if missing:
        raise ValueError(f"missing performance metric: {', '.join(sorted(missing))}")
    if unknown:
        raise ValueError(f"unknown performance metric: {', '.join(sorted(unknown))}")
    failures: list[str] = []
    for name, budget in PERFORMANCE_BUDGETS_MS.items():
        metric = _object(metrics[name], f"metric {name}")
        _exact_keys(metric, {"p95_ms", "sample_count"}, f"metric {name}")
        p95 = metric["p95_ms"]
        samples = metric["sample_count"]
        if (
            isinstance(p95, bool)
            or not isinstance(p95, (int, float))
            or not math.isfinite(float(p95))
            or p95 < 0
        ):
            raise ValueError(f"{name} p95_ms must be a finite non-negative number")
        if isinstance(samples, bool) or not isinstance(samples, int) or samples <= 0:
            raise ValueError(f"{name} sample_count must be a positive integer")
        if float(p95) > budget:
            failures.append(f"{name}:budget_exceeded")
    return ValidationResult(not failures, tuple(failures))


def validate_soak_report(report: dict[str, object]) -> ValidationResult:
    validate_json_value(report)
    _exact_keys(
        report,
        {"schema_version", "policy_version", "dispatch", "synthetic", "divergences"},
        "soak report",
    )
    if report["schema_version"] != "soak-v1":
        raise ValueError("schema_version must be soak-v1")
    if report["policy_version"] != RELEASE_POLICY_VERSION:
        raise ValueError(f"policy_version must be {RELEASE_POLICY_VERSION}")
    if not isinstance(report["dispatch"], bool):
        raise ValueError("dispatch must be boolean")
    if not isinstance(report["synthetic"], bool):
        raise ValueError("synthetic must be boolean")
    divergences = _object(report["divergences"], "divergences")
    _exact_keys(divergences, {"identity", "audit", "ledger"}, "divergences")
    failures: list[str] = []
    if report["dispatch"]:
        failures.append("dispatch_enabled")
    if report["synthetic"]:
        failures.append("synthetic_evidence")
    for name in ("identity", "audit", "ledger"):
        count = divergences[name]
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError(f"{name} divergence must be a non-negative integer")
        if count:
            failures.append(f"{name}_divergence")
    return ValidationResult(not failures, tuple(failures))


def validate_check_report(report: dict[str, object]) -> ValidationResult:
    validate_json_value(report)
    _required_string(report, "candidate_commit")
    if report.get("policy_version") != RELEASE_POLICY_VERSION:
        raise ValueError(f"policy_version must be {RELEASE_POLICY_VERSION}")
    checks = _object(report.get("checks"), "checks")
    if not checks:
        raise ValueError("checks must contain at least one boolean")
    if any(not isinstance(value, bool) for value in checks.values()):
        raise ValueError("checks must contain only boolean values")
    failures = tuple(sorted(name for name, passed in checks.items() if not passed))
    return ValidationResult(not failures, failures)


VALIDATORS = {
    "fault_matrix": validate_fault_matrix,
    "performance": validate_performance_report,
    "soak_run": validate_soak_report,
}


def validate_evidence_report(
    evidence_kind: str, report: dict[str, object]
) -> ValidationResult:
    validator = VALIDATORS.get(evidence_kind, validate_check_report)
    return validator(report)
