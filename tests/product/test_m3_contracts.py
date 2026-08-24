from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from nutmeg.product.contracts import (
    AdjudicationSummary,
    AgentProposalSummary,
    ClaimSummary,
    CopilotDraft,
    CopilotRequest,
    EvidenceBundleSummary,
    EvidenceConflictSummary,
    EvidenceSpanSummary,
    EvidenceSummary,
    FlagInstanceSummary,
    MatchContextSummary,
    MatchDetail,
    MatchSummary,
    ObjectRefContract,
    ObservationSummary,
    PrecedentLinkSummary,
    PredictionSummary,
    ReadinessLevel,
    ReadinessState,
)

CUTOFF = datetime(2026, 8, 24, 10, tzinfo=UTC)


def _draft_payload() -> dict[str, object]:
    return {
        "summary": "Home structure is weaker.",
        "scenarios": [
            {
                "label": "lineup remains incomplete",
                "mechanism": "midfield protection remains weak",
                "probability": 0.6,
            }
        ],
        "proposed_belief": {"home": 0.45, "draw": 0.32, "away": 0.23},
        "factors": [],
        "falsifier": "confirmed lineup restores the missing player",
        "citations": [{"object_type": "claim", "object_id": "claim-a"}],
        "conflicts": ["availability"],
        "missing_evidence": ["official lineup"],
    }


def test_copilot_contracts_require_citations_and_forbid_authority_fields() -> None:
    draft = CopilotDraft(**_draft_payload())
    assert draft.citations == [
        ObjectRefContract(object_type="claim", object_id="claim-a")
    ]

    without_citations = _draft_payload()
    without_citations["citations"] = []
    with pytest.raises(ValidationError, match="too_short"):
        CopilotDraft(**without_citations)

    with_authority = _draft_payload()
    with_authority["action_type"] = "commit_forecast"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        CopilotDraft(**with_authority)


def test_copilot_request_is_versioned_and_carries_retry_identity() -> None:
    request = CopilotRequest(
        idempotency_key="copilot:match-1:one",
        prompt="Investigate the lineup conflict.",
        as_of=CUTOFF,
    )
    assert request.schema_version == "1"
    assert request.idempotency_key == "copilot:match-1:one"


def test_conflict_and_proposal_contracts_keep_machine_state_explicit() -> None:
    conflict = EvidenceConflictSummary(
        conflict_id="conflict-1",
        predicate="availability",
        claim_ids=["claim-a", "claim-b"],
        statuses=["verified", "verified"],
        blocking=True,
    )
    proposal = AgentProposalSummary(
        agent_proposal_id="proposal-1",
        subject_type="match",
        subject_id="match-1",
        proposal_type="forecast",
        status="pending",
        version=1,
        information_cutoff_at="2026-08-24T10:00:00+00:00",
        operator_prompt="Investigate the lineup conflict.",
        summary="The conflict must be adjudicated.",
        scenarios=[],
        proposed_belief=None,
        factors=[],
        falsifier=None,
        citations=[
            EvidenceSpanSummary(
                object_type="claim",
                object_id="claim-a",
                artifact_id="sha256:a",
                artifact_retrieval_id="ret-a",
                quote="Player is out",
                locator="p1",
            )
        ],
        citation_coverage=0.5,
        conflicts=["availability"],
        missing_evidence=["official lineup"],
        model_name="fixture-model",
        model_version="1",
        created_at="2026-08-24T10:01:00+00:00",
        resolved_at=None,
        resolved_by_action_id=None,
    )
    assert conflict.blocking is True
    assert proposal.citations[0].object_id == "claim-a"
    assert proposal.citation_coverage == 0.5


def test_rich_investigation_contracts_preserve_ontology_fields() -> None:
    context = MatchContextSummary(
        match_revision_id="mr-1",
        competition_id="competition-1",
        competition_edition_id="edition-1",
        competition="League",
        round_label="Round 1",
        venue_id="venue-1",
        scheduled_at="2026-08-24T12:00:00+00:00",
        schedule_status="confirmed",
        status="scheduled",
        home_team_id="team-home",
        home_team="Home FC",
        away_team_id="team-away",
        away_team="Away FC",
    )
    bundle = EvidenceBundleSummary(
        evidence_bundle_id="bundle-1",
        frozen_at="2026-08-24T10:02:00+00:00",
        information_cutoff_at="2026-08-24T10:00:00+00:00",
        market_snapshot_id="snapshot-1",
        prior_distribution={"home": 0.5, "draw": 0.3, "away": 0.2},
        identity_resolution_version="identity-1",
        source_coverage={"sources": 3},
        freshness={"max_age_seconds": 300},
        content_hash="bundle-hash",
        item_refs=[ObjectRefContract(object_type="claim", object_id="claim-a")],
    )
    flag = FlagInstanceSummary(
        flag_instance_id="flag-1",
        flag_type="anchor_shield_out",
        match_id="match-1",
        direction="draw",
        strength=0.8,
        evidence_refs=[ObjectRefContract(object_type="claim", object_id="claim-a")],
        predicted_face="draw",
        status="active",
        created_at="2026-08-24T09:40:00+00:00",
    )
    prediction = PredictionSummary(
        prediction_id="prediction-1",
        match_id="match-1",
        claim="Home protection remains weak",
        falsifier="Starting midfielder returns",
        status="pending",
        outcome=None,
        registered_at="2026-08-24T09:41:00+00:00",
        settled_at=None,
    )
    precedent = PrecedentLinkSummary(
        precedent_link_id="precedent-1",
        subject_type="match",
        subject_id="match-1",
        precedent_match_id="match-old",
        scope="same_structure",
        evidence_refs=[ObjectRefContract(object_type="claim", object_id="claim-a")],
        created_at="2026-08-24T09:42:00+00:00",
    )
    adjudication = AdjudicationSummary(
        adjudication_id="adjudication-1",
        subject_type="claim",
        subject_id="claim-a",
        decision="reject",
        actor_id="operator:owner",
        reason="Official lineup supersedes the report",
        evidence_rejected=[
            ObjectRefContract(object_type="claim", object_id="claim-a")
        ],
        alternative={"status": "available"},
        created_at="2026-08-24T10:03:00+00:00",
        supersedes_adjudication_id=None,
    )

    assert context.home_team_id == "team-home"
    assert bundle.item_refs[0].object_type == "claim"
    assert flag.strength == 0.8
    assert prediction.outcome is None
    assert precedent.precedent_match_id == "match-old"
    assert adjudication.evidence_rejected[0].object_id == "claim-a"


def test_m3_extensions_keep_m1_m2_contracts_backward_compatible() -> None:
    claim = ClaimSummary(
        claim_id="claim-a",
        subject_type="match",
        subject_id="match-1",
        predicate="availability",
        value={"status": "out"},
        status="provisional",
        created_at="2026-08-24T09:00:00+00:00",
    )
    observation = ObservationSummary(
        observation_id="observation-a",
        observation_type="availability",
        subject_type="match",
        subject_id="match-1",
        value={"status": "out"},
        observed_at="2026-08-24T09:00:00+00:00",
        recorded_at="2026-08-24T09:01:00+00:00",
        verification_method="official",
    )
    detail = MatchDetail(
        match=MatchSummary(
            match_id="match-1",
            home_team="Home FC",
            away_team="Away FC",
            readiness=ReadinessState(level=ReadinessLevel.READY),
        ),
        evidence=EvidenceSummary(claims=[claim], observations=[observation]),
        as_of=CUTOFF,
    )

    assert claim.spans == []
    assert observation.source_retrieval_ids == []
    assert detail.evidence.conflicts == []
    assert detail.context is None
    assert detail.market_timeline == []
    assert detail.evidence_bundles == []
    assert detail.agent_proposals == []
