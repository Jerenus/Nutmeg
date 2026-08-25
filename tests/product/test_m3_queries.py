from datetime import timedelta

from nutmeg.product.contracts import ReadinessLevel

from .conftest import CLOCK


def test_investigation_assembles_context_evidence_and_workflow(
    m3_product_services,
) -> None:
    detail = m3_product_services.queries.match("match-1", as_of=CLOCK)

    assert detail.context is not None
    assert detail.context.match_revision_id == "mr-before"
    assert detail.context.home_team_id == "team-home"
    assert detail.context.away_team_id == "team-away"
    assert [item.market_snapshot_id for item in detail.market_timeline] == [
        "snapshot-early",
        "snapshot-before",
    ]
    assert detail.evidence.claims[0].spans
    assert detail.evidence.observations[0].source_retrieval_ids
    assert detail.evidence.conflicts[0].predicate == "availability_risk"
    assert detail.agent_proposals[0].model_name == "fixture-agent"
    assert detail.agent_proposals[0].citation_coverage == 1 / 3
    assert detail.evidence_bundles[0].content_hash == "fixture-bundle-hash"
    assert detail.flag_instances[0].flag_type == "anchor_shield_out"
    assert detail.predictions[0].prediction_id == "prediction-fixture"
    assert detail.precedent_links[0].precedent_link_id == "precedent-fixture"
    assert detail.adjudications[0].adjudication_id == "adjudication-fixture"


def test_provisional_disagreement_warns_without_blocking_forecast(
    m3_product_services,
) -> None:
    detail = m3_product_services.queries.match("match-1", as_of=CLOCK)
    conflict = detail.evidence.conflicts[0]

    assert conflict.blocking is False
    assert conflict.claim_ids == ["claim-before", "claim-conflict"]
    assert conflict.statuses == ["provisional", "provisional"]
    assert detail.match.readiness.level is ReadinessLevel.DEGRADED
    assert [issue.code for issue in detail.match.readiness.issues][-1] == (
        "source_conflict_provisional"
    )


def test_only_verified_value_disagreement_blocks_forecast(
    m3_product_services,
) -> None:
    detail = m3_product_services.queries.match(
        "match-1", as_of=CLOCK + timedelta(minutes=30)
    )
    conflict = detail.evidence.conflicts[0]

    assert conflict.blocking is True
    assert conflict.statuses == ["verified", "verified"]
    assert detail.match.readiness.level is ReadinessLevel.BLOCKED
    assert [issue.code for issue in detail.match.readiness.issues][-1] == (
        "source_conflict_unresolved"
    )


def test_conflict_identity_is_stable_for_equal_as_of_input(m3_product_services) -> None:
    first = m3_product_services.queries.match("match-1", as_of=CLOCK)
    second = m3_product_services.queries.match("match-1", as_of=CLOCK)

    assert first.evidence.conflicts[0].conflict_id.startswith("conflict-")
    assert first.evidence.conflicts == second.evidence.conflicts
