from __future__ import annotations

import pytest

from nutmeg.product.operator_candidates import (
    CandidateGenerationInput,
    CandidateStructureTemplate,
    FaceBundleOption,
    OfferCandidateInput,
    enumerate_band_candidates,
)
from nutmeg.product.operator_contracts import CandidateSetComparisonView


def _input_with_combined_odds(odds: str) -> CandidateGenerationInput:
    offer = OfferCandidateInput(
        official_match_no="001",
        official_offer_revision_id="offer-001",
        match_id="match-001",
        market_definition_id="md-had",
        probabilities=(
            ("3", "0.500000000000"),
            ("1", "0.300000000000"),
            ("0", "0.200000000000"),
        ),
        allowed_face_bundles=(FaceBundleOption("home", ("3",)),),
        omission_allowed=False,
        quote_ids_by_face=(("3", "quote-3"), ("1", "quote-1"), ("0", "quote-0")),
        booked_decimal_odds_by_face=(
            ("3", odds),
            ("1", "3.000000000000"),
            ("0", "4.000000000000"),
        ),
    )
    return CandidateGenerationInput(
        lane="jczq",
        ticket_kind="jczq_pass",
        currency="CNY",
        capital_cap_minor=10_000,
        unit_stake_minor=200,
        maximum_ticket_count=1,
        maximum_exhaustive_candidate_count=10,
        offers=(offer,),
        templates=(
            CandidateStructureTemplate(
                kind="jczq_pass",
                structure_code="1x1",
                eligible_official_match_nos=("001",),
                required_offer_count=1,
                maximum_groups=1,
                pass_size=1,
            ),
        ),
    )


@pytest.mark.parametrize(
    ("odds", "band"),
    [
        ("10.000000000000", "10x"),
        ("19.900000000000", "20x"),
        ("49.500000000000", "50x"),
        ("101.000000000000", "100x"),
    ],
)
def test_candidate_is_assigned_to_declared_band(odds: str, band: str) -> None:
    result = enumerate_band_candidates(_input_with_combined_odds(odds))

    outcome = result.by_band[band]
    assert outcome.status == "candidates"
    assert outcome.candidates[0].combined_decimal_odds == odds
    assert outcome.candidates[0].odds_band == band


def test_empty_band_is_explicit_not_omitted() -> None:
    result = enumerate_band_candidates(
        _input_with_combined_odds("10.000000000000")
    )

    assert result.by_band["20x"].status == "no_feasible_candidate"
    assert result.by_band["20x"].reason_code == "candidate_space_empty"


def test_outside_band_candidate_is_retained_only_for_counterfactual_comparison() -> None:
    inputs = _input_with_combined_odds("2.500000000000")

    judgment = enumerate_band_candidates(inputs, set_kind="judgment_bound")
    counterfactual = enumerate_band_candidates(
        inputs,
        set_kind="conditional_market_counterfactual",
    )

    assert judgment.candidates == ()
    assert len(counterfactual.candidates) == 1
    assert counterfactual.candidates[0].odds_band is None
    assert counterfactual.candidates[0].deployable is False


def test_contract_allows_explicit_all_empty_band_outcomes() -> None:
    view = CandidateSetComparisonView(
        label="judgment bands",
        comparison_only=False,
        candidates=[],
        band_outcomes=[
            {
                "odds_band": band,
                "status": "no_feasible_candidate",
                "candidate_count": 0,
                "reason_code": "candidate_space_empty",
            }
            for band in ("10x", "20x", "50x", "100x")
        ],
    )

    assert len(view.band_outcomes) == 4
