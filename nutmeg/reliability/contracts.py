"""Strict, deterministic contracts for release-governance evidence."""
from __future__ import annotations

import math
from dataclasses import dataclass

from nutmeg.ontology.actions.models import canonical_json

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


# Every generic check-report kind names its schema version and the checks that
# must actually have been run. A single self-declared boolean cannot turn a
# release gate green (independent-critique I-2).
CHECK_REPORT_SPECS: dict[str, tuple[str, frozenset[str]]] = {
    "scheduler_authority": (
        "scheduler-v1",
        frozenset(
            {
                "am_configured",
                "am_loaded",
                "close_configured",
                "close_loaded",
                "settle_configured",
                "settle_loaded",
                "ontology_v2",
                "scoreboard_authority",
                "sop_authority",
            }
        ),
    ),
    "deterministic_suite": (
        "deterministic_suite-v1",
        frozenset({"pytest_full", "ruff", "compileall"}),
    ),
    "migration_replay": (
        "migration_replay-v1",
        frozenset({"migration_applied", "integrity_ok", "reconcile_zero_mismatch"}),
    ),
    "ai_safety": (
        "ai_safety-v1",
        frozenset({"citation_gate", "role_denial", "prompt_injection_fixtures"}),
    ),
    "browser_e2e": (
        "browser_e2e-v1",
        frozenset({"desktop_lifecycle", "mobile_lifecycle", "console_clean"}),
    ),
    "backup_restore": (
        "backup_restore-v1",
        frozenset({"backup_created", "restore_verified", "projection_rebuilt"}),
    ),
    "observability": (
        "observability-v1",
        frozenset({"health_endpoint", "route_metrics", "outbox_lag_visible"}),
    ),
}

REPORT_MAX_CANONICAL_BYTES = 262_144


def validate_check_report(
    evidence_kind: str, report: dict[str, object]
) -> ValidationResult:
    validate_json_value(report)
    spec = CHECK_REPORT_SPECS.get(evidence_kind)
    if spec is None:
        raise ValueError(f"unknown check-report kind {evidence_kind!r}")
    schema_version, required_checks = spec
    required_keys = {"schema_version", "candidate_commit", "policy_version", "checks"}
    _exact_keys(
        {key: value for key, value in report.items() if key != "summary"},
        required_keys,
        f"{evidence_kind} report",
    )
    if report.get("schema_version") != schema_version:
        raise ValueError(f"schema_version must be {schema_version}")
    _required_string(report, "candidate_commit")
    if report.get("policy_version") != RELEASE_POLICY_VERSION:
        raise ValueError(f"policy_version must be {RELEASE_POLICY_VERSION}")
    checks = _object(report.get("checks"), "checks")
    if any(not isinstance(value, bool) for value in checks.values()):
        raise ValueError("checks must contain only boolean values")
    missing_checks = required_checks - set(checks)
    if missing_checks:
        raise ValueError(
            f"checks missing required entries: {', '.join(sorted(missing_checks))}"
        )
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
    validate_json_value(report)
    canonical_size = len(canonical_json(report).encode("utf-8"))
    if canonical_size > REPORT_MAX_CANONICAL_BYTES:
        raise ValueError(
            f"report exceeds the canonical size limit "
            f"({canonical_size} > {REPORT_MAX_CANONICAL_BYTES} bytes)"
        )
    validator = VALIDATORS.get(evidence_kind)
    if validator is not None:
        return validator(report)
    return validate_check_report(evidence_kind, report)
