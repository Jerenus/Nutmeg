"""Deterministic candidate audit policy (`nutmeg.discovery.audit`).

These cases used to run through the retired `CandidateGenerationWorker`; they
exercise `_audit_candidate` (and, where the assertion is about ordering, the
partition `enumerate_candidates` derives from an ERROR finding) directly.
"""

from __future__ import annotations

import pytest

from nutmeg.discovery import audit as discovery_audit
from nutmeg.discovery.audit import _audit_candidate, _CandidateAuditOffer
from nutmeg.discovery.candidates import (
    CandidateDraft,
    CandidateGenerationInput,
    CandidateStructureTemplate,
    CandidateTicket,
    CandidateTicketLeg,
    FaceBundleOption,
    OfferCandidateInput,
    enumerate_candidates,
)

# 与 tests/ontology/operator/test_judgment_actions.py 的 PRIOR 同值：主 40 / 平 30 / 客 30。
# 被排的第三面 30% > C14 的 20% 阈值，所以默认排面就是"昂贵排除"。
PRIOR = (
    ("3", "0.400000000000"),
    ("1", "0.300000000000"),
    ("0", "0.300000000000"),
)
DROPPED_MODAL_BELIEF = (
    ("3", "0.200000000000"),
    ("1", "0.300000000000"),
    ("0", "0.500000000000"),
)


def _leg(
    *,
    selection_codes: tuple[str, ...] = ("3", "1"),
    official_match_no: str = "001",
    market_definition_id: str = "md-had",
) -> CandidateTicketLeg:
    return CandidateTicketLeg(
        official_offer_revision_id="offer-revision-1",
        official_match_no=official_match_no,
        match_id="match-1",
        market_definition_id=market_definition_id,
        selection_codes=selection_codes,
        quote_ids=tuple(f"quote-{code}" for code in selection_codes),
        booked_decimal_odds=tuple("2.500000000000" for _ in selection_codes),
        settlement_parameter_decimal=None,
    )


def _draft(
    *tickets: CandidateTicket,
    stake_minor: int = 200,
    composition_hash: str = "d" * 64,
) -> CandidateDraft:
    return CandidateDraft(
        tickets=tickets,
        stake_minor=stake_minor,
        composition_hash=composition_hash,
    )


def _ticket(
    legs: tuple[CandidateTicketLeg, ...],
    *,
    composition_hash: str = "1" * 64,
    stake_minor: int = 200,
) -> CandidateTicket:
    return CandidateTicket(
        ticket_kind="jczq_pass",
        structure_code="single-1",
        group_code="001",
        currency="CNY",
        unit_stake_minor=200,
        unit_count=1,
        stake_minor=stake_minor,
        fixed_prize_policy_revision_id=None,
        legs=legs,
        composition_hash=composition_hash,
    )


def _audit_offer(
    *,
    belief: tuple[tuple[str, str], ...] = PRIOR,
    prescribed_faces: tuple[str, ...] = ("3", "1"),
    anchor_integrity: str = "pass",
    face_precedents: tuple[tuple[str, str, str], ...] = (),
) -> _CandidateAuditOffer:
    return _CandidateAuditOffer(
        official_match_no="001",
        market_definition_id="md-had",
        belief=belief,
        prior=PRIOR,
        prescribed_face_bundles=(frozenset(prescribed_faces),),
        rule_ids=("k",),
        anchor_integrity=anchor_integrity,
        face_precedents=face_precedents,
    )


def _leg_findings(findings) -> set[tuple[str, str]]:
    return {
        (item.code, item.severity) for item in findings if item.audit_kind == "legs"
    }


def test_candidate_audit_records_shared_dead_face_across_tickets() -> None:
    leg = CandidateTicketLeg(
        official_offer_revision_id="offer-1",
        official_match_no="001",
        match_id="match-1",
        market_definition_id="md-had",
        selection_codes=("3", "1"),
        quote_ids=("quote-3", "quote-1"),
        booked_decimal_odds=("2.000000000000", "3.000000000000"),
        settlement_parameter_decimal=None,
    )
    tickets = tuple(
        CandidateTicket(
            ticket_kind="jczq_pass",
            structure_code=f"single-{index}",
            group_code=None,
            currency="CNY",
            unit_stake_minor=200,
            unit_count=1,
            stake_minor=200,
            fixed_prize_policy_revision_id=None,
            legs=(leg,),
            composition_hash=str(index) * 64,
        )
        for index in (1, 2)
    )

    findings = _audit_candidate(
        CandidateDraft(
            tickets=tickets,
            stake_minor=400,
            composition_hash="d" * 64,
        ),
        lane="jczq",
        offers=(),
        capital_cap_minor=10_000,
    )

    shared = [item for item in findings if item.code == "shared_dead_face_exposure"]
    assert len(shared) == 1
    assert shared[0].severity == "WARN"
    assert shared[0].audit_kind == "deployment"
    assert shared[0].official_match_no == "001"
    assert "0" in shared[0].message


def test_audit_reports_a_deployment_finding_for_every_unsupported_market(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every candidate leg without a registered settlement grader is an ERROR."""
    monkeypatch.setitem(
        discovery_audit._SUPPORTED_SETTLEMENT_MARKETS,
        "jczq",
        frozenset(),
    )

    findings = _audit_candidate(
        _draft(_ticket((_leg(),))),
        lane="jczq",
        offers=(_audit_offer(),),
        capital_cap_minor=10_000,
    )

    deployment = [item for item in findings if item.audit_kind == "deployment"]
    assert {(item.code, item.severity) for item in deployment} == {
        ("unsupported_settlement_market", "ERROR")
    }
    assert [item.official_match_no for item in deployment] == ["001"]


def test_audit_reports_the_capital_cap_as_a_budget_error() -> None:
    findings = _audit_candidate(
        _draft(_ticket((_leg(),), stake_minor=400), stake_minor=400),
        lane="jczq",
        offers=(_audit_offer(),),
        capital_cap_minor=300,
    )

    assert ("capital_cap_exceeded", "ERROR", "budget") in {
        (item.code, item.severity, item.audit_kind) for item in findings
    }


def test_leg_audit_reads_the_operator_anchor_and_precedent_facts() -> None:
    """C14 clears only when Jun recorded the death proofs the rule demands."""
    findings = _audit_candidate(
        _draft(_ticket((_leg(),))),
        lane="jczq",
        offers=(
            _audit_offer(
                anchor_integrity="pass",
                face_precedents=(("0", "2026-05-12 same venue 1:0", "dead"),),
            ),
        ),
        capital_cap_minor=10_000,
    )

    assert not any(
        code == "expensive_exclusion" for code, _severity in _leg_findings(findings)
    )


def test_leg_audit_warns_when_the_expensive_exclusion_has_no_death_proof() -> None:
    findings = _audit_candidate(
        _draft(_ticket((_leg(),))),
        lane="jczq",
        offers=(_audit_offer(anchor_integrity="pass", face_precedents=()),),
        capital_cap_minor=10_000,
    )

    assert ("expensive_exclusion", "WARN") in _leg_findings(findings)


def test_broken_anchor_single_blocks_the_candidate_as_an_audit_error() -> None:
    """C5 —— 26102 本菲卡：锚方 FAIL 还裸单是 ERROR，不是提醒。"""
    findings = _audit_candidate(
        _draft(_ticket((_leg(selection_codes=("3",)),))),
        lane="jczq",
        offers=(
            _audit_offer(
                prescribed_faces=("3",),
                anchor_integrity="fail",
                face_precedents=(
                    ("1", "2026-05-12 same venue 1:0", "dead"),
                    ("0", "2026-04-20 same venue 2:0", "dead"),
                ),
            ),
        ),
        capital_cap_minor=10_000,
    )

    assert ("broken_anchor_single", "ERROR") in _leg_findings(findings)


def test_live_precedent_on_an_excluded_face_warns_under_rule_r3() -> None:
    findings = _audit_candidate(
        _draft(_ticket((_leg(),))),
        lane="jczq",
        offers=(
            _audit_offer(
                anchor_integrity="pass",
                face_precedents=(("0", "2026-05-12 same venue 1:1", "alive"),),
            ),
        ),
        capital_cap_minor=10_000,
    )

    assert ("excluded_face_live_precedent", "WARN") in _leg_findings(findings)


def test_broken_anchor_double_warns_when_a_face_is_dropped_on_a_holed_anchor() -> None:
    """C13 —— 26118 场8：锚方有洞的场只许全包或丢整场。"""
    findings = _audit_candidate(
        _draft(_ticket((_leg(),))),
        lane="jczq",
        offers=(
            _audit_offer(
                anchor_integrity="fail",
                face_precedents=(("0", "2026-05-12 same venue 1:0", "dead"),),
            ),
        ),
        capital_cap_minor=10_000,
    )

    assert ("broken_anchor_double", "WARN") in _leg_findings(findings)


def test_dropping_the_modal_face_is_an_error_that_blocks_the_candidate() -> None:
    """The leg audit runs before ordering: an ERROR partitions the candidate away."""
    audit_offer = _audit_offer(belief=DROPPED_MODAL_BELIEF)
    findings = _audit_candidate(
        _draft(_ticket((_leg(),))),
        lane="jczq",
        offers=(audit_offer,),
        capital_cap_minor=10_000,
    )
    assert ("modal_face_dropped", "ERROR") in _leg_findings(findings)
    assert [
        item.official_match_no
        for item in findings
        if item.code == "modal_face_dropped"
    ] == ["001"]

    inputs = CandidateGenerationInput(
        lane="jczq",
        ticket_kind="jczq_pass",
        currency="CNY",
        capital_cap_minor=20_000,
        unit_stake_minor=200,
        maximum_ticket_count=1,
        maximum_exhaustive_candidate_count=10,
        offers=(
            OfferCandidateInput(
                official_match_no="001",
                official_offer_revision_id="offer-revision-1",
                match_id="match-1",
                market_definition_id="md-had",
                probabilities=DROPPED_MODAL_BELIEF,
                allowed_face_bundles=(FaceBundleOption("home_draw", ("3", "1")),),
                omission_allowed=False,
                quote_ids_by_face=(
                    ("3", "quote-3"),
                    ("1", "quote-1"),
                    ("0", "quote-0"),
                ),
                booked_decimal_odds_by_face=(
                    ("3", "2.500000000000"),
                    ("1", "3.200000000000"),
                    ("0", "3.400000000000"),
                ),
            ),
        ),
        templates=(
            CandidateStructureTemplate(
                kind="jczq_pass",
                structure_code="single-1",
                eligible_official_match_nos=("001",),
                required_offer_count=1,
                maximum_groups=1,
                pass_size=1,
            ),
        ),
    )
    result = enumerate_candidates(
        inputs,
        set_kind="judgment_bound",
        generator_version="operator-candidate-v1",
        audit_candidate=lambda draft: _audit_candidate(
            draft,
            lane="jczq",
            offers=(audit_offer,),
            capital_cap_minor=inputs.capital_cap_minor,
        ),
    )

    assert [candidate.partition for candidate in result.candidates] == ["audit_blocked"]
    assert all(candidate.rank is None for candidate in result.candidates)
