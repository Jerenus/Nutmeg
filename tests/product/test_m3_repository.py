from nutmeg.product.repository import ProductReadRepository


def test_claim_status_and_sources_are_replayed_at_cutoff(m3_seeded_product) -> None:
    repository = ProductReadRepository(m3_seeded_product.kernel.engine)

    claims = repository.claims_for_match(
        "match-1", "2026-08-24T10:00:00+00:00"
    )
    by_id = {item["claim_id"]: item for item in claims}
    assert by_id["claim-before"]["status"] == "provisional"
    assert by_id["claim-conflict"]["status"] == "provisional"
    assert by_id["claim-before"]["spans"][0] == {
        "object_type": "claim",
        "object_id": "claim-before",
        "artifact_id": by_id["claim-before"]["spans"][0]["artifact_id"],
        "artifact_retrieval_id": by_id["claim-before"]["spans"][0][
            "artifact_retrieval_id"
        ],
        "quote": "home player unavailable",
        "locator": "line:1",
    }

    observations = repository.observations_for_match(
        "match-1", "2026-08-24T10:00:00+00:00"
    )
    assert observations[0]["source_retrieval_ids"] == [
        by_id["claim-before"]["spans"][0]["artifact_retrieval_id"]
    ]


def test_future_projection_status_does_not_leak_into_historical_claims(
    m3_seeded_product,
) -> None:
    repository = ProductReadRepository(m3_seeded_product.kernel.engine)

    at_cutoff = repository.claims_for_match(
        "match-1", "2026-08-24T10:00:00+00:00"
    )
    after_adjudication = repository.claims_for_match(
        "match-1", "2026-08-24T10:30:00+00:00"
    )

    assert {item["status"] for item in at_cutoff} == {"provisional"}
    assert {item["status"] for item in after_adjudication} == {"verified"}


def test_market_timeline_and_bundles_obey_cutoff(m3_seeded_product) -> None:
    repository = ProductReadRepository(m3_seeded_product.kernel.engine)

    timeline = repository.market_timeline(
        "match-1", "md-had", "2026-08-24T10:00:00+00:00"
    )
    bundles = repository.evidence_bundles_for_match(
        "match-1", "2026-08-24T10:00:00+00:00"
    )

    assert [item["market_snapshot_id"] for item in timeline] == [
        "snapshot-early",
        "snapshot-before",
    ]
    assert bundles[0]["content_hash"] == "fixture-bundle-hash"
    assert bundles[0]["item_refs"] == [
        {"object_type": "claim", "object_id": "claim-before"},
        {"object_type": "observation", "object_id": "obs-before"},
    ]


def test_rich_workflow_reads_are_temporal_and_decoded(m3_seeded_product) -> None:
    repository = ProductReadRepository(m3_seeded_product.kernel.engine)
    cutoff = "2026-08-24T10:00:00+00:00"

    proposals = repository.agent_proposals_for_match("match-1", cutoff)
    flags = repository.flag_instances_for_match("match-1", cutoff)
    predictions = repository.predictions_for_match("match-1", cutoff)
    precedents = repository.precedents_for_match("match-1", cutoff)
    adjudications = repository.adjudications_for_match("match-1", cutoff)

    assert len(proposals) == 2
    assert [item["created_at"] for item in proposals] == sorted(
        item["created_at"] for item in proposals
    )
    assert proposals[0]["payload"] == {"note": "check lineup"}
    assert repository.agent_proposal(proposals[0]["agent_proposal_id"]) == proposals[0]
    assert flags[0]["evidence_refs"][0]["object_id"] == "claim-before"
    assert predictions[0]["falsifier"] == "starting midfielder returns"
    assert precedents[0]["scope"] == "same_structure"
    assert adjudications[0]["evidence_rejected"][0]["object_id"] == "claim-conflict"

    before_workflow = "2026-08-24T09:39:00+00:00"
    assert repository.agent_proposals_for_match("match-1", before_workflow) == []
    assert repository.flag_instances_for_match("match-1", before_workflow) == []
    assert repository.predictions_for_match("match-1", before_workflow) == []
    assert repository.precedents_for_match("match-1", before_workflow) == []
    assert repository.adjudications_for_match("match-1", before_workflow) == []
