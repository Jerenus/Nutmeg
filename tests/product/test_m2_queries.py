import hashlib
from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from nutmeg.product.contracts import (
    AlertSummary,
    BoardResponse,
    MatchSummary,
    OperationsMetrics,
    OperationsResponse,
    ReadinessIssue,
    ReadinessLevel,
    ReadinessState,
)
from nutmeg.product.repository import ProductReadRepository

CLOCK = datetime(2026, 8, 24, 10, tzinfo=UTC)


@pytest.fixture
def m2_repository(m2_seeded_product) -> ProductReadRepository:
    return ProductReadRepository(m2_seeded_product.kernel.engine)


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


def test_repository_exposes_sources_identity_queue_and_failures(
    m2_repository: ProductReadRepository,
) -> None:
    sources = m2_repository.source_health(CLOCK.isoformat())
    identities = m2_repository.identity_queue(limit=500)
    failures = m2_repository.failed_actions(limit=20)

    assert {row["source_name"] for row in sources} == {"sporttery", "intl"}
    assert "team-duplicate" in {row["entity_id"] for row in identities}
    duplicate = m2_repository.identity_item("team", "team-duplicate")
    assert duplicate is not None
    assert duplicate["external_identifiers"] == ["api-football:duplicate-home-1"]
    assert duplicate["aliases"] == ["home fc duplicate"]
    assert failures[0]["status"] == "rejected"
    assert m2_repository.action_high_watermark() > 0
    assert m2_repository.pending_workflow_count(as_of=CLOCK.isoformat()) == 2
    assert m2_repository.flag_count_for_match(
        "match-1", as_of=CLOCK.isoformat()
    ) == 0


def test_repository_expands_source_and_evidence_lineage(
    m2_repository: ProductReadRepository,
) -> None:
    artifact_id = "sha256:" + hashlib.sha256(b"sporttery-fresh").hexdigest()
    retrieval_id = "RET-" + hashlib.sha256(
        b"fixture:artifact:sporttery"
    ).hexdigest()[:32]

    artifact_edges = m2_repository.lineage("source_artifact", artifact_id)
    retrieval_edges = m2_repository.lineage("artifact_retrieval", retrieval_id)
    snapshot_edges = m2_repository.lineage("market_snapshot", "snapshot-before")
    observation_edges = m2_repository.lineage("observation", "obs-before")
    claim_edges = m2_repository.lineage("claim", "claim-before")
    team_edges = m2_repository.lineage("team", "team-duplicate")

    assert artifact_edges is not None
    assert any(edge[0] == "artifact_has_retrieval" for edge in artifact_edges)
    assert retrieval_edges is not None
    assert (
        (
            "retrieval_of",
            "artifact_retrieval",
            retrieval_id,
            "source_artifact",
            artifact_id,
        )
        in retrieval_edges
    )
    assert snapshot_edges is not None
    assert any(edge[0] == "snapshot_for_match" for edge in snapshot_edges)
    assert observation_edges == [
        ("observation_for_match", "observation", "obs-before", "match", "match-1")
    ]
    assert claim_edges == [
        ("claim_for_match", "claim", "claim-before", "match", "match-1")
    ]
    assert team_edges is not None
    assert any(edge[0] == "team_has_external_id" for edge in team_edges)


def test_command_center_filters_without_hiding_unfiltered_counts(
    m2_product_services,
) -> None:
    result = m2_product_services.queries.command_center(
        date(2026, 8, 24),
        as_of=CLOCK,
        readiness=ReadinessLevel.READY,
        competition=None,
        query="Home",
    )
    empty = m2_product_services.queries.command_center(
        date(2026, 8, 24),
        as_of=CLOCK,
        readiness=ReadinessLevel.BLOCKED,
        competition=None,
        query="nothing",
    )

    assert [item.match_id for item in result.board.matches] == ["match-1"]
    assert empty.board.matches == []
    assert empty.readiness_counts["ready"] == 1
    assert "score" not in result.board.matches[0].model_dump()


def test_command_center_alert_match_links_url_encode_cutoff(
    m2_product_services,
) -> None:
    board = BoardResponse(
        date=date(2026, 8, 24),
        as_of=CLOCK,
        matches=[
            MatchSummary(
                match_id="match-1",
                home_team="Home FC",
                away_team="Away FC",
                readiness=ReadinessState(
                    level=ReadinessLevel.DEGRADED,
                    issues=[
                        ReadinessIssue(
                            code="source_stale",
                            message="source evidence is stale",
                            observed_at=CLOCK,
                        )
                    ],
                ),
            )
        ],
    )
    alerts = m2_product_services.queries._board_alerts(board, CLOCK)

    assert alerts[0].href == (
        "/matches/match-1?as_of=2026-08-24T10%3A00%3A00%2B00%3A00"
    )


def test_operations_turns_stale_source_and_failures_into_alerts(
    m2_product_services,
) -> None:
    result = m2_product_services.queries.operations(
        as_of=CLOCK,
        identity_limit=500,
    )
    limited = m2_product_services.queries.operations(as_of=CLOCK, identity_limit=1)

    assert {alert.code for alert in result.alerts} >= {
        "source_stale",
        "action_failed",
        "identity_unresolved",
    }
    assert result.metrics.ontology_integrity == "ok"
    assert result.metrics.action_high_watermark > 0
    assert result.metrics.unresolved_identity_count == len(result.identities)
    assert limited.metrics.unresolved_identity_count > len(limited.identities)
    assert result.sources[0].age_seconds is not None
