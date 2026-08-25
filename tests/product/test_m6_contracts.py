from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from nutmeg.product.contracts import (
    ReleaseApprovalSummary,
    ReleaseBackupRestoreSummary,
    ReleaseGateSummary,
    ReleasePerformanceSummary,
    ReleaseResponse,
    ReleaseSchedulerSummary,
    ReliabilityEvidenceSummary,
    ReliabilityMetricsResponse,
    RouteMetricSummary,
    SoakCoverageSummary,
)

NOW = datetime(2026, 8, 24, 12, tzinfo=UTC)


def _release() -> ReleaseResponse:
    return ReleaseResponse(
        release_version="v1.0.0",
        candidate_commit="abc123",
        policy_version="release-v1",
        evaluated_at=NOW,
        ready=False,
        gates=[
            ReleaseGateSummary(
                gate_id="G1",
                name="single-track authority",
                passed=False,
                code="missing_evidence",
                detail="missing evidence: scheduler_authority",
                evidence_ids=[],
            )
        ],
        evidence=[
            ReliabilityEvidenceSummary(
                reliability_evidence_id="rel-one",
                evidence_kind="scheduler_authority",
                workflow="system",
                business_date=None,
                observed_from=NOW,
                observed_to=NOW,
                status="failed",
                content_hash="a" * 64,
                recorded_at=NOW,
            )
        ],
        soak_coverage=[
            SoakCoverageSummary(
                workflow="jczq",
                dates=[],
                distinct_days=0,
                first_date=None,
                last_date=None,
                inclusive_span_days=0,
            )
        ],
        evidence_snapshot_sha256="b" * 64,
        approval_status="none",
        approval=None,
        scheduler_authority=ReleaseSchedulerSummary(
            reliability_evidence_id="rel-one",
            status="failed",
            observed_to=NOW,
            ontology_v2=False,
            scoreboard_authority="legacy",
            sop_ready=False,
            configured_stages=2,
            loaded_stages=1,
        ),
        backup_restore=ReleaseBackupRestoreSummary(
            reliability_evidence_id="rel-backup",
            status="passed",
            observed_to=NOW,
            sqlite_integrity="ok",
            schema_version=14,
            action_high_watermark=12,
            outbox_cursor=12,
            projection_high_watermark=12,
            source_manifest_sha256="c" * 64,
        ),
        performance=[
            ReleasePerformanceSummary(
                metric="board_query_ms",
                p95_ms=8.5,
                budget_ms=500,
                sample_count=20,
                passed=True,
            )
        ],
    )


def test_m6_release_contracts_are_strict_and_hide_report_payloads() -> None:
    release = _release()
    payload = release.model_dump(mode="json")

    assert payload["schema_version"] == "1"
    assert "report" not in payload["evidence"][0]
    assert "source_refs" not in payload["evidence"][0]
    assert payload["scheduler_authority"]["scoreboard_authority"] == "legacy"
    assert payload["backup_restore"]["sqlite_integrity"] == "ok"
    assert payload["performance"][0]["p95_ms"] == 8.5
    with pytest.raises(ValidationError, match="extra"):
        ReliabilityEvidenceSummary(
            **release.evidence[0].model_dump(),
            report={"secret": "must not escape"},
        )
    with pytest.raises(ValidationError, match="timezone"):
        ReleaseResponse(
            **{
                **release.model_dump(),
                "evaluated_at": datetime(2026, 8, 24, 12),
            }
        )
    with pytest.raises(ValidationError, match="extra"):
        ReleaseSchedulerSummary(
            **release.scheduler_authority.model_dump(),
            secret="must not escape",
        )


def test_m6_metrics_contract_is_bounded_and_versioned() -> None:
    response = ReliabilityMetricsResponse(
        as_of=NOW,
        routes=[
            RouteMetricSummary(
                route_template="/api/v1/release",
                method="GET",
                request_count=4,
                error_count=1,
                p95_ms=12.5,
            )
        ],
        action_status_counts={"committed": 3},
        action_high_watermark=3,
        outbox_high_watermark=3,
        outbox_lag=0,
        projection_state="unavailable",
        authority_state="legacy",
        evidence_freshness={},
        last_restore_drill=None,
    )

    assert response.routes[0].request_count == 4
    assert response.schema_version == "1"
    with pytest.raises(ValidationError):
        RouteMetricSummary(
            route_template="/api/v1/release?id=secret",
            method="GET",
            request_count=-1,
            error_count=0,
            p95_ms=1,
        )


def test_release_approval_summary_has_explicit_current_state() -> None:
    summary = ReleaseApprovalSummary(
        release_approval_id="rap-one",
        release_version="v1.0.0",
        evidence_snapshot_sha256="c" * 64,
        policy_version="release-v1",
        reason="reviewed",
        approved_at=NOW,
        status="current",
    )
    assert summary.status == "current"
