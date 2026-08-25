import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.artifact_ingest import ArtifactIngestRequest
from nutmeg.ontology.actions.models import ActorRole, ObjectRef
from nutmeg.ontology.actions.reliability_actions import (
    RecordReliabilityEvidenceRequest,
)
from nutmeg.ontology.reliability.models import ReliabilityEvidenceRow
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel
from nutmeg.reliability.contracts import CHECK_REPORT_SPECS, FAULT_SCENARIOS, PERFORMANCE_BUDGETS_MS
from nutmeg.reliability.release import ReleaseEvaluator

NOW = datetime(2026, 8, 24, 12, tzinfo=UTC)
COMMIT = "abc123"
SYSTEM_KINDS = (
    "scheduler_authority",
    "deterministic_suite",
    "migration_replay",
    "fault_matrix",
    "ai_safety",
    "browser_e2e",
    "performance",
    "backup_restore",
    "observability",
)


def _kernel(tmp_path: Path):
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    return kernel


def _report(kind: str, *, candidate: str = COMMIT, passed: bool = True):
    if kind == "fault_matrix":
        rows = [
            {
                "scenario": scenario,
                "test_ref": f"tests/fault/test_{scenario}.py",
                "observed_result": "contained",
                "outcome": "retryable",
                "state_corruption": False,
            }
            for scenario in FAULT_SCENARIOS
        ]
        if not passed:
            rows[0]["state_corruption"] = True
        return {
            "schema_version": "fault-v1",
            "candidate_commit": candidate,
            "policy_version": "release-v1",
            "scenarios": rows,
        }
    if kind == "performance":
        metrics = {
            name: {"p95_ms": budget, "sample_count": 20}
            for name, budget in PERFORMANCE_BUDGETS_MS.items()
        }
        if not passed:
            metrics["board_query_ms"]["p95_ms"] = 501
        return {
            "schema_version": "performance-v1",
            "candidate_commit": candidate,
            "policy_version": "release-v1",
            "volume_multiplier": 10,
            "metrics": metrics,
        }
    schema_version, required_checks = CHECK_REPORT_SPECS[kind]
    return {
        "schema_version": schema_version,
        "candidate_commit": candidate,
        "policy_version": "release-v1",
        "checks": {name: passed for name in sorted(required_checks)},
    }


def _record_system(
    kernel,
    kind: str,
    *,
    candidate: str = COMMIT,
    passed: bool = True,
    observed_to: datetime = NOW,
    requested_at: datetime = NOW,
    suffix: str = "base",
):
    return kernel.reliability_actions.record_evidence(
        RecordReliabilityEvidenceRequest(
            evidence_kind=kind,
            workflow="system",
            business_date=None,
            observed_from=observed_to - timedelta(hours=1),
            observed_to=observed_to,
            status="passed" if passed else "failed",
            report=_report(kind, candidate=candidate, passed=passed),
            source_refs=[ObjectRef("test_run", f"{kind}-{suffix}")],
            actor_id="system:release-test",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key=f"m6:{kind}:{suffix}",
            requested_at=requested_at,
        )
    )


def _record_soak(
    kernel,
    workflow: str,
    day: datetime,
    *,
    suffix: str = "base",
    dispatch: bool = False,
    synthetic: bool = False,
    divergence: int = 0,
):
    passed = not dispatch and not synthetic and divergence == 0
    return kernel.reliability_actions.record_evidence(
        RecordReliabilityEvidenceRequest(
            evidence_kind="soak_run",
            workflow=workflow,
            business_date=day.date().isoformat(),
            observed_from=day,
            observed_to=day + timedelta(hours=1),
            status="passed" if passed else "failed",
            report={
                "schema_version": "soak-v1",
                "policy_version": "release-v1",
                "dispatch": dispatch,
                "synthetic": synthetic,
                "divergences": {
                    "identity": divergence,
                    "audit": 0,
                    "ledger": 0,
                },
            },
            source_refs=[
                ObjectRef("soak_run", f"{workflow}-{day.date().isoformat()}-{suffix}")
            ],
            actor_id="system:soak",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key=(
                f"m6:soak:{workflow}:{day.date().isoformat()}:{suffix}"
            ),
            requested_at=NOW,
        )
    )


def _insert_unsafe_policy_fixture_soak(
    kernel,
    workflow: str,
    day: datetime,
    *,
    suffix: str,
    dispatch: bool = False,
    synthetic: bool = False,
) -> None:
    action = kernel.artifact_ingest.ingest(
        ArtifactIngestRequest(
            content=f'{{"policy_fixture":"{suffix}"}}'.encode(),
            content_type="application/json",
            source_name="m6-policy-fixture",
            source_type="test-only",
            actor_id="source:m6-policy-test",
            actor_role=ActorRole.CONNECTOR,
            idempotency_key=f"m6:policy-fixture:{suffix}",
            retrieved_at=NOW,
        )
    )
    digest = hashlib.sha256(f"unsafe-policy-fixture:{suffix}".encode()).hexdigest()
    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.reliability.insert_evidence(
            ReliabilityEvidenceRow(
                reliability_evidence_id=f"rel-{digest[:32]}",
                evidence_kind="soak_run",
                workflow=workflow,
                business_date=day.date().isoformat(),
                observed_from=day.isoformat(),
                observed_to=(day + timedelta(hours=1)).isoformat(),
                status="failed",
                report={
                    "schema_version": "soak-v1",
                    "policy_version": "release-v1",
                    "dispatch": dispatch,
                    "synthetic": synthetic,
                    "divergences": {"identity": 0, "audit": 0, "ledger": 0},
                },
                source_refs=[
                    {"object_type": "test_fixture", "object_id": suffix}
                ],
                content_hash=digest,
                recorded_at=(NOW + timedelta(minutes=1)).isoformat(),
                action_id=action.action_id,
            )
        )


def _evaluate(kernel, *, evaluated_at: datetime = NOW):
    with OntologyUnitOfWork(kernel.engine) as uow:
        return ReleaseEvaluator(uow.reliability).evaluate(
            "v1.0.0", candidate_commit=COMMIT, evaluated_at=evaluated_at
        )


def _seed_system(kernel) -> None:
    for kind in SYSTEM_KINDS:
        observed = NOW - timedelta(minutes=30)
        _record_system(
            kernel,
            kind,
            observed_to=observed,
            requested_at=observed,
        )


def _seed_soak(kernel, days: int = 14) -> None:
    start = (NOW - timedelta(days=13)).replace(hour=0)
    for offset in range(days):
        day = start + timedelta(days=offset)
        for workflow in ("jczq", "zucai"):
            _record_soak(kernel, workflow, day)


def test_empty_ledger_blocks_six_gates_with_stable_snapshot(tmp_path: Path) -> None:
    kernel = _kernel(tmp_path)

    first = _evaluate(kernel)
    second = _evaluate(kernel)

    assert first.ready is False
    assert tuple(first.gates) == ("G1", "G2", "G3", "G4", "G5", "G6")
    assert {gate.code for gate in first.gates.values()} == {"missing_evidence"}
    assert first.evidence_snapshot_sha256 == second.evidence_snapshot_sha256
    assert first.approval_status == "none"


def test_each_gate_uses_current_candidate_and_non_future_evidence(
    tmp_path: Path,
) -> None:
    kernel = _kernel(tmp_path)
    _record_system(
        kernel,
        "scheduler_authority",
        candidate="old",
        suffix="old",
        requested_at=NOW - timedelta(minutes=4),
    )
    evaluation = _evaluate(kernel)
    assert evaluation.gates["G1"].code == "candidate_mismatch"

    _record_system(
        kernel,
        "scheduler_authority",
        passed=False,
        suffix="failed",
        requested_at=NOW - timedelta(minutes=3),
    )
    evaluation = _evaluate(kernel)
    assert evaluation.gates["G1"].code == "evidence_failed"

    _record_system(
        kernel,
        "scheduler_authority",
        observed_to=NOW + timedelta(hours=1),
        suffix="future",
        requested_at=NOW - timedelta(minutes=2),
    )
    evaluation = _evaluate(kernel)
    assert evaluation.gates["G1"].code == "future_evidence"

    _record_system(
        kernel,
        "scheduler_authority",
        suffix="current",
        requested_at=NOW - timedelta(minutes=1),
    )
    assert _evaluate(kernel).gates["G1"].passed is True


def test_release_selects_latest_evidence_within_the_requested_candidate(
    tmp_path: Path,
) -> None:
    kernel = _kernel(tmp_path)
    current = _record_system(
        kernel,
        "scheduler_authority",
        suffix="requested-candidate",
        requested_at=NOW - timedelta(minutes=2),
    )
    _record_system(
        kernel,
        "scheduler_authority",
        candidate="next-candidate",
        suffix="newer-other-candidate",
        requested_at=NOW - timedelta(minutes=1),
    )

    evaluation = _evaluate(kernel)

    assert evaluation.gates["G1"].passed is True
    assert evaluation.gates["G1"].evidence_ids == (
        current.result_refs[0].object_id,
    )


def test_release_needs_14_dates_and_inclusive_span_for_both_workflows(
    tmp_path: Path,
) -> None:
    kernel = _kernel(tmp_path)
    _seed_system(kernel)
    _seed_soak(kernel, days=13)

    thirteen = _evaluate(kernel)
    assert all(thirteen.gates[gate].passed for gate in ("G1", "G2", "G3", "G4", "G5"))
    assert thirteen.gates["G6"].code == "soak_days_insufficient"
    assert thirteen.soak_coverage["jczq"].distinct_days == 13
    assert thirteen.soak_coverage["zucai"].distinct_days == 13

    final_day = NOW.replace(hour=0)
    _record_soak(kernel, "jczq", final_day, suffix="day-14")
    one_missing = _evaluate(kernel)
    assert one_missing.gates["G6"].code == "soak_days_insufficient"
    assert one_missing.soak_coverage["jczq"].distinct_days == 14
    assert one_missing.soak_coverage["zucai"].distinct_days == 13

    _record_soak(kernel, "zucai", final_day, suffix="day-14")
    green = _evaluate(kernel)
    assert green.ready is True
    assert green.gates["G6"].passed is True
    assert all(item.inclusive_span_days == 14 for item in green.soak_coverage.values())


def test_future_or_non_real_soak_blocks_operations_gate(tmp_path: Path) -> None:
    cases = (
        ("future", {"suffix": "future"}, NOW, "soak_future_date"),
        (
            "synthetic",
            {"suffix": "synthetic", "synthetic": True},
            NOW + timedelta(days=1, hours=2),
            "soak_synthetic",
        ),
        (
            "dispatch",
            {"suffix": "dispatch", "dispatch": True},
            NOW + timedelta(days=1, hours=2),
            "soak_dispatch",
        ),
        (
            "divergence",
            {"suffix": "divergence", "divergence": 1},
            NOW + timedelta(days=1, hours=2),
            "soak_divergence",
        ),
    )
    for name, options, evaluated_at, expected in cases:
        kernel = _kernel(tmp_path / name)
        _record_system(kernel, "backup_restore")
        _record_system(kernel, "observability")
        _seed_soak(kernel)
        assert _evaluate(kernel).gates["G6"].passed is True
        extra_day = (NOW + timedelta(days=1)).replace(hour=0)
        if options.get("synthetic") or options.get("dispatch"):
            _insert_unsafe_policy_fixture_soak(
                kernel,
                "jczq",
                extra_day,
                **options,
            )
        else:
            _record_soak(kernel, "jczq", extra_day, **options)
        assert _evaluate(kernel, evaluated_at=evaluated_at).gates["G6"].code == expected
