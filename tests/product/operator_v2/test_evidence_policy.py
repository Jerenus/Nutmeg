from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from nutmeg.product.operator_evidence import (
    ClaimEvidence,
    EvidenceClaimKind,
    EvidenceCoverage,
    EvidenceObservationKind,
    EvidenceState,
    IdentityEvidence,
    MarketEvidence,
    MatchEvidenceSnapshot,
    ObservationEvidence,
    OfficialOfferEvidence,
    OperatorEvidenceService,
    TaskEvidenceSnapshot,
    evaluate_match_requirements,
    evaluate_requirement,
    evaluate_task_evidence,
)

CUTOFF = datetime(2026, 9, 4, 10, tzinfo=UTC)


def _complete_match(
    match_id: str = "match-1",
    *,
    required_for_evidence: bool = True,
) -> MatchEvidenceSnapshot:
    home = f"{match_id}:home"
    away = f"{match_id}:away"
    return MatchEvidenceSnapshot(
        match_id=match_id,
        official_match_no="1",
        required_for_evidence=required_for_evidence,
        identity=IdentityEvidence(
            match_revision_ref_token=f"match-revision:{match_id}",
            match_revision_current=True,
            team_ids=(home, away),
            team_resolution_states=("resolved", "resolved"),
            unresolved_alias_ref_tokens=(),
            ambiguous_alias_ref_tokens=(),
            merged_away_ref_tokens=(),
        ),
        offer=OfficialOfferEvidence(
            ref_token=f"official-offer:{match_id}",
            current=True,
            source_official=True,
            valid_from=CUTOFF - timedelta(days=1),
            valid_to=CUTOFF + timedelta(hours=1),
            competition_revision_id="competition-edition-1",
            official_match_no="1",
            kickoff_at=CUTOFF + timedelta(hours=2),
            sale_deadline_at=CUTOFF + timedelta(hours=1),
            market_definition_ids=("md-had",),
        ),
        required_market_definition_ids=("md-had",),
        markets=(
            MarketEvidence(
                ref_token=f"snapshot:{match_id}:official",
                market_definition_id="md-had",
                source_kind="sporttery_official",
                observed_at=CUTOFF - timedelta(hours=1),
                resolved_identity=True,
            ),
            MarketEvidence(
                ref_token=f"snapshot:{match_id}:international",
                market_definition_id="md-had",
                source_kind="international_market",
                observed_at=CUTOFF - timedelta(hours=1),
                resolved_identity=True,
            ),
        ),
        observations=tuple(
            fact
            for team_id in (home, away)
            for fact in (
                ObservationEvidence(
                    ref_token=f"observation:{team_id}:availability-clear",
                    kind=EvidenceObservationKind.AVAILABILITY_CLEAR,
                    team_id=team_id,
                    observed_at=CUTOFF - timedelta(hours=1),
                    valid_from=CUTOFF - timedelta(hours=2),
                    valid_to=CUTOFF + timedelta(hours=1),
                    verification_method="official",
                    source_kinds=("credible_media", "club_official"),
                    authoritative_sample_ref_tokens=(),
                    value_fingerprint="no_known_absence",
                ),
                ObservationEvidence(
                    ref_token=f"observation:{team_id}:recent-form",
                    kind=EvidenceObservationKind.RECENT_FORM,
                    team_id=team_id,
                    observed_at=CUTOFF - timedelta(hours=2),
                    valid_from=CUTOFF - timedelta(days=3),
                    valid_to=None,
                    verification_method="deterministic",
                    source_kinds=("authoritative_results",),
                    authoritative_sample_ref_tokens=("result-1", "result-2"),
                    value_fingerprint="1-1-0:3-1",
                ),
                ObservationEvidence(
                    ref_token=f"observation:{team_id}:structure",
                    kind=EvidenceObservationKind.STRUCTURAL_CONTEXT,
                    team_id=team_id,
                    observed_at=CUTOFF - timedelta(hours=2),
                    valid_from=CUTOFF - timedelta(days=1),
                    valid_to=CUTOFF + timedelta(hours=1),
                    verification_method="official",
                    source_kinds=("club_official",),
                    authoritative_sample_ref_tokens=(),
                    value_fingerprint="material_squad_change:absent",
                ),
            )
        ),
        claims=(),
        coverage_ref_tokens=("coverage:E5:home",),
    )


@pytest.mark.parametrize(
    ("observed_at", "expected"),
    [
        (CUTOFF - timedelta(hours=6), EvidenceState.COMPLETE),
        (CUTOFF - timedelta(hours=6, microseconds=1), EvidenceState.STALE),
    ],
)
def test_market_freshness_boundary(observed_at, expected) -> None:
    snapshot = _complete_match()
    markets = tuple(
        replace(fact, observed_at=observed_at)
        if fact.source_kind == "sporttery_official"
        else fact
        for fact in snapshot.markets
    )

    status = evaluate_requirement("E3", replace(snapshot, markets=markets), cutoff=CUTOFF)

    assert status.state is expected


@pytest.mark.parametrize(
    ("requirement_id", "kind", "hours"),
    [
        ("E5", EvidenceObservationKind.AVAILABILITY_CLEAR, 24),
        ("E6a", EvidenceObservationKind.RECENT_FORM, 72),
        ("E6b", EvidenceObservationKind.STRUCTURAL_CONTEXT, 72),
    ],
)
def test_observation_freshness_boundaries(requirement_id, kind, hours) -> None:
    snapshot = _complete_match()
    at_boundary = tuple(
        replace(fact, observed_at=CUTOFF - timedelta(hours=hours))
        if fact.kind is kind
        else fact
        for fact in snapshot.observations
    )
    stale = tuple(
        replace(fact, observed_at=CUTOFF - timedelta(hours=hours, microseconds=1))
        if fact.kind is kind
        else fact
        for fact in snapshot.observations
    )

    assert evaluate_requirement(
        requirement_id,
        replace(snapshot, observations=at_boundary),
        cutoff=CUTOFF,
    ).state is EvidenceState.COMPLETE
    status = evaluate_requirement(
        requirement_id,
        replace(snapshot, observations=stale),
        cutoff=CUTOFF,
    )
    assert status.state is EvidenceState.STALE
    assert status.stale_ref_tokens


@pytest.mark.parametrize("state", ["provisional", "ambiguous", "merged_away"])
def test_identity_requires_current_canonical_entities(state: str) -> None:
    snapshot = _complete_match()
    identity = replace(
        snapshot.identity,
        team_resolution_states=(state, "canonical"),
    )

    status = evaluate_requirement("E1", replace(snapshot, identity=identity), cutoff=CUTOFF)

    assert status.state is EvidenceState.MISSING
    assert status.missing_ref_tokens


def test_required_market_needs_official_and_resolved_international_snapshots() -> None:
    snapshot = _complete_match()
    official_only = tuple(
        fact for fact in snapshot.markets if fact.source_kind == "sporttery_official"
    )

    e3 = evaluate_requirement("E3", replace(snapshot, markets=official_only), cutoff=CUTOFF)
    e4 = evaluate_requirement("E4", replace(snapshot, markets=official_only), cutoff=CUTOFF)

    assert e3.state is EvidenceState.COMPLETE
    assert e4.state is EvidenceState.MISSING


def test_international_comparison_requires_one_fresh_source_per_match_not_per_market() -> None:
    snapshot = _complete_match()
    markets = (
        *snapshot.markets,
        MarketEvidence(
            ref_token="snapshot:official:hhad",
            market_definition_id="md-hhad",
            source_kind="sporttery_official",
            observed_at=CUTOFF - timedelta(hours=1),
            resolved_identity=True,
        ),
    )
    multi_market = replace(
        snapshot,
        offer=replace(
            snapshot.offer,
            market_definition_ids=("md-had", "md-hhad"),
        ),
        required_market_definition_ids=("md-had", "md-hhad"),
        markets=markets,
    )

    assert evaluate_requirement("E3", multi_market, cutoff=CUTOFF).state is (
        EvidenceState.COMPLETE
    )
    assert evaluate_requirement("E4", multi_market, cutoff=CUTOFF).state is (
        EvidenceState.COMPLETE
    )


def test_verified_two_source_claim_satisfies_availability_only_inside_validity() -> None:
    snapshot = _complete_match()
    away = snapshot.identity.team_ids[1]
    without_away_availability = tuple(
        fact
        for fact in snapshot.observations
        if not (
            fact.team_id == away
            and fact.kind is EvidenceObservationKind.AVAILABILITY_CLEAR
        )
    )
    claim = ClaimEvidence(
        ref_token="claim:away:availability",
        kind=EvidenceClaimKind.AVAILABILITY,
        team_id=away,
        predicate="availability",
        conflict_scope="person:person-1:availability",
        value_fingerprint="person-1:out:injury",
        status="verified",
        valid_from=CUTOFF - timedelta(hours=1),
        valid_to=CUTOFF + timedelta(hours=1),
        source_kinds=("credible_media", "club_official"),
        source_retrieval_ids=("retrieval:credible-news", "retrieval:official-team"),
        source_identity_tokens=(
            "credible_media:credible-news",
            "club_official:official-team",
        ),
        observed_at=CUTOFF - timedelta(hours=1),
    )
    eligible = replace(
        snapshot,
        observations=without_away_availability,
        claims=(claim,),
    )

    assert evaluate_requirement("E5", eligible, cutoff=CUTOFF).state is EvidenceState.COMPLETE
    stale = replace(eligible, claims=(replace(claim, valid_to=CUTOFF - timedelta(seconds=1)),))
    assert evaluate_requirement("E5", stale, cutoff=CUTOFF).state is EvidenceState.STALE

    with pytest.raises(ValueError, match="observed_at"):
        replace(claim, observed_at=None)


def test_corroborated_claim_counts_distinct_verified_source_identities() -> None:
    snapshot = _complete_match()
    away = snapshot.identity.team_ids[1]
    observations = tuple(
        fact
        for fact in snapshot.observations
        if not (
            fact.team_id == away
            and fact.kind is EvidenceObservationKind.AVAILABILITY_CLEAR
        )
    )
    claim = ClaimEvidence(
        ref_token="claim:away:two-retrievals",
        kind=EvidenceClaimKind.AVAILABILITY,
        team_id=away,
        predicate="availability",
        conflict_scope="person:person-1:availability",
        value_fingerprint="person-1:out:injury",
        status="verified",
        valid_from=CUTOFF - timedelta(hours=1),
        valid_to=CUTOFF + timedelta(hours=1),
        source_kinds=("credible_media",),
        source_retrieval_ids=("retrieval:first", "retrieval:second"),
        source_identity_tokens=("credible_media:publisher-a",),
        observed_at=CUTOFF - timedelta(hours=1),
    )

    same_source_twice = replace(snapshot, observations=observations, claims=(claim,))
    assert evaluate_requirement("E5", same_source_twice, cutoff=CUTOFF).state is (
        EvidenceState.STALE
    )

    eligible_claim = replace(
        claim,
        source_identity_tokens=(
            "credible_media:publisher-a",
            "credible_media:publisher-b",
        ),
    )
    eligible = replace(snapshot, observations=observations, claims=(eligible_claim,))
    assert evaluate_requirement("E5", eligible, cutoff=CUTOFF).state is (
        EvidenceState.COMPLETE
    )

    duplicated_identity = replace(
        eligible_claim,
        source_identity_tokens=(
            "credible_media:publisher-a",
            "credible_media:publisher-a",
        ),
    )
    status = evaluate_requirement(
        "E5",
        replace(eligible, claims=(duplicated_identity,)),
        cutoff=CUTOFF,
    )
    assert status.state is EvidenceState.STALE


def test_single_official_observation_satisfies_availability() -> None:
    snapshot = _complete_match()
    observations = tuple(
        replace(fact, source_kinds=("club_official",))
        if fact.kind is EvidenceObservationKind.AVAILABILITY_CLEAR
        else fact
        for fact in snapshot.observations
    )

    status = evaluate_requirement(
        "E5",
        replace(snapshot, observations=observations),
        cutoff=CUTOFF,
    )

    assert status.state is EvidenceState.COMPLETE


@pytest.mark.parametrize(
    ("requirement_id", "kind"),
    [
        ("E5", EvidenceObservationKind.AVAILABILITY_CLEAR),
        ("E6b", EvidenceObservationKind.STRUCTURAL_CONTEXT),
    ],
)
def test_official_observation_requires_official_source_provenance(
    requirement_id: str,
    kind: EvidenceObservationKind,
) -> None:
    snapshot = _complete_match()
    observations = tuple(
        replace(fact, source_kinds=("credible_media",))
        if fact.kind is kind
        else fact
        for fact in snapshot.observations
    )

    status = evaluate_requirement(
        requirement_id,
        replace(snapshot, observations=observations),
        cutoff=CUTOFF,
    )

    assert status.state is EvidenceState.STALE


def test_adjudicated_observation_requires_governed_adjudication_lineage() -> None:
    snapshot = _complete_match()
    observations = tuple(
        replace(
            fact,
            verification_method="adjudicated",
            source_kinds=("credible_media",),
            adjudication_ref_tokens=(),
        )
        if fact.kind is EvidenceObservationKind.AVAILABILITY_CLEAR
        else fact
        for fact in snapshot.observations
    )

    missing = evaluate_requirement(
        "E5",
        replace(snapshot, observations=observations),
        cutoff=CUTOFF,
    )
    governed = tuple(
        replace(fact, adjudication_ref_tokens=("action:verify-claim",))
        if fact.kind is EvidenceObservationKind.AVAILABILITY_CLEAR
        else fact
        for fact in observations
    )

    assert missing.state is EvidenceState.STALE
    assert evaluate_requirement(
        "E5",
        replace(snapshot, observations=governed),
        cutoff=CUTOFF,
    ).state is EvidenceState.COMPLETE


def test_recent_form_requires_authoritative_result_lineage() -> None:
    snapshot = _complete_match()
    observations = tuple(
        replace(fact, source_kinds=("credible_media",))
        if fact.kind is EvidenceObservationKind.RECENT_FORM
        else fact
        for fact in snapshot.observations
    )

    status = evaluate_requirement(
        "E6a",
        replace(snapshot, observations=observations),
        cutoff=CUTOFF,
    )

    assert status.state is EvidenceState.STALE


def test_positive_clear_observations_satisfy_empty_availability_and_structure() -> None:
    statuses = evaluate_match_requirements(_complete_match(), cutoff=CUTOFF)

    assert statuses["E5"].state is EvidenceState.COMPLETE
    assert statuses["E6b"].state is EvidenceState.COMPLETE


def test_conflicting_non_retracted_claim_values_block_until_retraction() -> None:
    snapshot = _complete_match()
    team_id = snapshot.identity.team_ids[0]
    first = ClaimEvidence(
        ref_token="claim:structure:1",
        kind=EvidenceClaimKind.STRUCTURAL_CONTEXT,
        team_id=team_id,
        predicate="structural_context",
        conflict_scope=f"team:{team_id}:structure:formation",
        value_fingerprint="formation:present:4-3-3",
        status="verified",
        valid_from=CUTOFF - timedelta(hours=1),
        valid_to=CUTOFF + timedelta(hours=1),
        source_kinds=("credible_media", "club_official"),
        observed_at=CUTOFF - timedelta(hours=1),
    )
    second = replace(
        first,
        ref_token="claim:structure:2",
        value_fingerprint="formation:present:3-5-2",
        status="disputed",
    )
    conflicted = replace(snapshot, claims=(first, second))

    status = evaluate_requirement("EC", conflicted, cutoff=CUTOFF)

    assert status.state is EvidenceState.CONFLICT
    assert status.conflict_ref_tokens == (first.ref_token, second.ref_token)
    cleared = replace(conflicted, claims=(first, replace(second, status="retracted")))
    assert evaluate_requirement("EC", cleared, cutoff=CUTOFF).state is EvidenceState.COMPLETE


def test_observation_and_non_retracted_claim_conflict_blocks() -> None:
    snapshot = _complete_match()
    team_id = snapshot.identity.team_ids[0]
    observation = ObservationEvidence(
        ref_token="observation:person-1:availability",
        kind=EvidenceObservationKind.PERSON_AVAILABILITY,
        team_id=team_id,
        observed_at=CUTOFF - timedelta(hours=1),
        valid_from=CUTOFF - timedelta(hours=1),
        valid_to=CUTOFF + timedelta(hours=1),
        verification_method="official",
        source_kinds=("club_official",),
        authoritative_sample_ref_tokens=(),
        value_fingerprint="person-1:out:injury",
    )
    claim = ClaimEvidence(
        ref_token="claim:person-1:availability",
        kind=EvidenceClaimKind.AVAILABILITY,
        team_id=team_id,
        predicate="availability",
        conflict_scope=f"team:{team_id}:person_availability",
        value_fingerprint="person-1:available:selection",
        status="verified",
        valid_from=CUTOFF - timedelta(hours=1),
        valid_to=CUTOFF + timedelta(hours=1),
        source_kinds=("credible_media", "club_official"),
        observed_at=CUTOFF - timedelta(hours=1),
    )

    status = evaluate_requirement(
        "EC",
        replace(snapshot, observations=(*snapshot.observations, observation), claims=(claim,)),
        cutoff=CUTOFF,
    )

    assert status.state is EvidenceState.CONFLICT
    assert {observation.ref_token, claim.ref_token}.issubset(status.conflict_ref_tokens)


def test_distinct_claim_scopes_do_not_create_false_conflicts() -> None:
    snapshot = _complete_match()
    team_id = snapshot.identity.team_ids[0]
    first = ClaimEvidence(
        ref_token="claim:availability:person-1",
        kind=EvidenceClaimKind.AVAILABILITY,
        team_id=team_id,
        predicate="availability",
        conflict_scope="person:person-1:availability",
        value_fingerprint="person-1:out:injury",
        status="verified",
        valid_from=CUTOFF - timedelta(hours=1),
        valid_to=CUTOFF + timedelta(hours=1),
        source_kinds=("credible_news", "official_team"),
        observed_at=CUTOFF - timedelta(hours=1),
    )
    second = replace(
        first,
        ref_token="claim:availability:person-2",
        conflict_scope="person:person-2:availability",
        value_fingerprint="person-2:available:selection",
    )

    status = evaluate_requirement(
        "EC",
        replace(
            snapshot,
            observations=tuple(
                fact
                for fact in snapshot.observations
                if not (
                    fact.team_id == team_id
                    and fact.kind is EvidenceObservationKind.AVAILABILITY_CLEAR
                )
            ),
            claims=(first, second),
        ),
        cutoff=CUTOFF,
    )

    assert status.state is EvidenceState.COMPLETE


def test_equivalent_clear_and_recent_form_observations_do_not_conflict_on_lineage() -> None:
    snapshot = _complete_match()
    team_id = snapshot.identity.team_ids[0]
    clear = next(
        item
        for item in snapshot.observations
        if item.team_id == team_id
        and item.kind is EvidenceObservationKind.AVAILABILITY_CLEAR
    )
    recent_form = next(
        item
        for item in snapshot.observations
        if item.team_id == team_id and item.kind is EvidenceObservationKind.RECENT_FORM
    )
    clear = replace(
        clear,
        value_fingerprint=(
            '{"checked_source_kinds":["club_official"],"finding_count":0,'
            '"lookback_ended_at":"2026-09-04T09:00:00+00:00",'
            '"lookback_started_at":"2026-09-03T09:00:00+00:00",'
            f'"team_token":"{team_id}"}}'
        ),
    )
    recent_form = replace(
        recent_form,
        value_fingerprint=(
            '{"draws":1,"goals_against":1,"goals_for":3,"losses":0,'
            '"sample_match_tokens":["result-1","result-2"],'
            f'"team_token":"{team_id}","wins":1}}'
        ),
    )
    same_clear = replace(
        clear,
        ref_token="observation:home:availability-clear:refreshed",
        observed_at=CUTOFF - timedelta(minutes=30),
        source_kinds=("club_official", "credible_media"),
        value_fingerprint=(
            '{"checked_source_kinds":["club_official","credible_media"],'
            '"finding_count":0,"lookback_ended_at":"2026-09-04T09:30:00+00:00",'
            '"lookback_started_at":"2026-09-03T09:30:00+00:00",'
            f'"team_token":"{team_id}"}}'
        ),
    )
    same_recent_form = replace(
        recent_form,
        ref_token="observation:home:recent-form:refreshed",
        observed_at=CUTOFF - timedelta(minutes=45),
        authoritative_sample_ref_tokens=("result-3", "result-4"),
        value_fingerprint=(
            '{"draws":1,"goals_against":1,"goals_for":3,"losses":0,'
            '"sample_match_tokens":["result-3","result-4"],'
            f'"team_token":"{team_id}","wins":1}}'
        ),
    )

    status = evaluate_requirement(
        "EC",
        replace(
            snapshot,
            observations=tuple(
                same_clear
                if fact.ref_token == clear.ref_token
                else same_recent_form
                if fact.ref_token == recent_form.ref_token
                else fact
                for fact in snapshot.observations
            )
            + (clear, recent_form),
        ),
        cutoff=CUTOFF,
    )

    assert status.state is EvidenceState.COMPLETE


def test_team_availability_clear_conflicts_with_person_unavailable() -> None:
    snapshot = _complete_match()
    team_id = snapshot.identity.team_ids[0]
    person_unavailable = ObservationEvidence(
        ref_token="observation:person-1:out",
        kind=EvidenceObservationKind.PERSON_AVAILABILITY,
        team_id=team_id,
        observed_at=CUTOFF - timedelta(hours=1),
        valid_from=CUTOFF - timedelta(hours=1),
        valid_to=CUTOFF + timedelta(hours=1),
        verification_method="official",
        source_kinds=("club_official",),
        authoritative_sample_ref_tokens=(),
        value_fingerprint="person-1:out:injury",
    )

    status = evaluate_requirement(
        "EC",
        replace(snapshot, observations=(*snapshot.observations, person_unavailable)),
        cutoff=CUTOFF,
    )

    assert status.state is EvidenceState.CONFLICT
    assert status.conflict_ref_tokens == tuple(
        sorted(
            (
                "observation:match-1:home:availability-clear",
                person_unavailable.ref_token,
            )
        )
    )


def test_coverage_receipts_alone_never_grant_readiness() -> None:
    snapshot = replace(_complete_match(), observations=(), claims=())

    statuses = evaluate_match_requirements(snapshot, cutoff=CUTOFF)

    assert statuses["E5"].state is EvidenceState.MISSING
    assert statuses["E6a"].state is EvidenceState.MISSING
    assert statuses["E6b"].state is EvidenceState.MISSING


def test_team_requirement_uses_only_registered_evidence_for_its_scope() -> None:
    snapshot = _complete_match()
    home, away = snapshot.identity.team_ids
    home_clear = next(
        item
        for item in snapshot.observations
        if item.team_id == home and item.kind is EvidenceObservationKind.AVAILABILITY_CLEAR
    )
    scoped = replace(
        snapshot,
        coverage=(
            EvidenceCoverage(
                requirement_id="E5",
                subject_scope=home,
                evidence_ref_tokens=(home_clear.ref_token,),
            ),
            EvidenceCoverage(
                requirement_id="E5",
                subject_scope=away,
                evidence_ref_tokens=(home_clear.ref_token,),
            ),
        ),
    )

    status = evaluate_requirement("E5", scoped, cutoff=CUTOFF)

    assert status.state is EvidenceState.MISSING
    assert f"E5:{snapshot.match_id}:{away}" in status.missing_ref_tokens


def test_team_requirement_rejects_evidence_registered_for_another_requirement() -> None:
    snapshot = _complete_match()
    home = snapshot.identity.team_ids[0]
    home_clear = next(
        item
        for item in snapshot.observations
        if item.team_id == home and item.kind is EvidenceObservationKind.AVAILABILITY_CLEAR
    )
    wrong_requirement = replace(
        snapshot,
        coverage=(
            EvidenceCoverage(
                requirement_id="E6a",
                subject_scope=home,
                evidence_ref_tokens=(home_clear.ref_token,),
            ),
        ),
    )

    status = evaluate_requirement("E5", wrong_requirement, cutoff=CUTOFF)

    assert status.state is EvidenceState.MISSING


def test_whole_task_requires_fourteen_zucai_matches_and_open_jczq_only() -> None:
    zucai = TaskEvidenceSnapshot(
        lane="zucai",
        matches=tuple(_complete_match(f"match-{index}") for index in range(1, 15)),
    )
    jczq = TaskEvidenceSnapshot(
        lane="jczq",
        matches=(
            _complete_match("open-1"),
            _complete_match("open-2"),
            replace(_complete_match("closed"), required_for_evidence=False),
        ),
    )

    zucai_status = evaluate_task_evidence(zucai, cutoff=CUTOFF)
    jczq_status = evaluate_task_evidence(jczq, cutoff=CUTOFF)

    assert zucai_status.ready
    assert (zucai_status.complete_match_count, zucai_status.required_match_count) == (14, 14)
    assert jczq_status.ready
    assert (jczq_status.complete_match_count, jczq_status.required_match_count) == (2, 2)

    short = replace(zucai, matches=zucai.matches[:-1])
    short_status = evaluate_task_evidence(short, cutoff=CUTOFF)
    assert not short_status.ready
    assert short_status.required_match_count == 14


def test_zucai_readiness_excludes_cancelled_offers_from_evidence_scope() -> None:
    task = TaskEvidenceSnapshot(
        lane="zucai",
        matches=tuple(_complete_match(f"match-{index}") for index in range(1, 15)),
    )
    cancelled = replace(
        task.matches[-1],
        offer=replace(task.matches[-1].offer, source_status="cancelled"),
    )

    status = evaluate_task_evidence(
        replace(task, matches=(*task.matches[:-1], cancelled)),
        cutoff=CUTOFF,
    )

    assert status.ready
    assert (status.complete_match_count, status.required_match_count) == (13, 13)


def test_zucai_service_evaluates_at_real_issue_cutoff_not_query_as_of() -> None:
    issue_cutoff = CUTOFF + timedelta(hours=8)
    matches = tuple(
        replace(
            match := _complete_match(f"match-{index}"),
            offer=replace(
                match.offer,
                valid_to=(
                    issue_cutoff
                    if index == 1
                    else issue_cutoff + timedelta(hours=1)
                ),
                sale_deadline_at=(
                    issue_cutoff
                    if index == 1
                    else issue_cutoff + timedelta(hours=1)
                ),
            ),
            markets=tuple(
                replace(market, observed_at=issue_cutoff - timedelta(hours=6))
                for market in match.markets
            ),
        )
        for index in range(1, 15)
    )
    snapshot = TaskEvidenceSnapshot(lane="zucai", matches=matches)

    class StaticSnapshotService(OperatorEvidenceService):
        def load_task_snapshot(self, *, lane, business_key, as_of):
            return snapshot

    service = StaticSnapshotService(repository=None, unit_of_work_factory=None)

    status = service.evaluate_task(
        lane="zucai",
        business_key="26120",
        as_of=CUTOFF,
    )

    for match_status in status.matches:
        requirements = {
            requirement.requirement_id: requirement
            for requirement in match_status.requirements
        }
        assert requirements["E3"].state is EvidenceState.COMPLETE
        assert requirements["E4"].state is EvidenceState.COMPLETE


def test_jczq_evaluates_each_open_offer_at_its_own_deadline() -> None:
    early_deadline = CUTOFF + timedelta(hours=1)
    late_deadline = CUTOFF + timedelta(hours=8)
    early = _complete_match("early")
    early = replace(
        early,
        offer=replace(
            early.offer,
            valid_to=early_deadline,
            sale_deadline_at=early_deadline,
        ),
        markets=tuple(
            replace(market, observed_at=CUTOFF - timedelta(hours=5))
            for market in early.markets
        ),
    )
    late = _complete_match("late")
    late = replace(
        late,
        offer=replace(
            late.offer,
            valid_to=late_deadline,
            sale_deadline_at=late_deadline,
        ),
        markets=tuple(
            replace(market, observed_at=CUTOFF - timedelta(hours=1))
            for market in late.markets
        ),
    )

    status = evaluate_task_evidence(
        TaskEvidenceSnapshot(lane="jczq", matches=(early, late)),
        cutoff=CUTOFF,
    )

    assert not status.ready
    assert status.required_match_count == 2
    assert status.matches[0].complete
    late_requirements = {
        requirement.requirement_id: requirement
        for requirement in status.matches[1].requirements
    }
    assert late_requirements["E3"].state is EvidenceState.STALE
    assert late_requirements["E4"].state is EvidenceState.STALE


def test_jczq_scope_excludes_offer_closed_at_as_of_even_if_flagged_required() -> None:
    closed = _complete_match("closed")
    closed = replace(
        closed,
        offer=replace(
            closed.offer,
            valid_to=CUTOFF,
            sale_deadline_at=CUTOFF,
        ),
    )
    open_match = _complete_match("open")

    status = evaluate_task_evidence(
        TaskEvidenceSnapshot(lane="jczq", matches=(closed, open_match)),
        cutoff=CUTOFF,
    )

    assert status.ready
    assert status.required_match_count == 1
    assert tuple(match.match_id for match in status.matches) == ("open",)
