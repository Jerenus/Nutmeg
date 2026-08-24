from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from nutmeg.product.contracts import (
    AlertSummary,
    MatchSummary,
    OperationsMetrics,
    OperationsResponse,
    ReadinessLevel,
    ReadinessState,
)

CLOCK = datetime(2026, 8, 24, 10, tzinfo=UTC)


def test_m2_contracts_are_versioned_and_strict() -> None:
    response = OperationsResponse(
        as_of=CLOCK,
        sources=[],
        identities=[],
        recent_failures=[],
        alerts=[],
        metrics=OperationsMetrics(
            ontology_integrity="ok",
            ontology_schema_version=10,
            action_high_watermark=8,
            outbox_high_watermark=8,
            projection_run_count=1,
            unresolved_identity_count=0,
        ),
    )

    assert response.schema_version == "1"
    with pytest.raises(ValidationError):
        AlertSummary(
            alert_id="alert-1",
            severity="warn",
            code="source_stale",
            title="stale source",
            detail="age exceeds six hours",
            observed_at=CLOCK,
            invented=True,
        )


def test_match_summary_m2_fields_keep_conservative_defaults() -> None:
    summary = MatchSummary(
        match_id="match-1",
        home_team="Home FC",
        away_team="Away FC",
        readiness=ReadinessState(level=ReadinessLevel.DEGRADED),
    )

    assert summary.evidence_count == 0
    assert summary.workflow_state == "unread"
    assert summary.next_action == "inspect"
    assert summary.flag_count == 0
