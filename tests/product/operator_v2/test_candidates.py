from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from nutmeg.product.operator_candidates import (
    CandidateGenerationInput,
    CandidateSpaceLimitError,
    CandidateStructureTemplate,
    FaceBundleOption,
    OfferCandidateInput,
    enumerate_candidates,
    union_probability,
)


def _offer(
    match_no: str,
    *bundles: tuple[str, tuple[str, ...]],
    omission_allowed: bool = False,
    lane: str = "jczq",
    market_definition_id: str = "md-had",
    probabilities: tuple[tuple[str, str], ...] = (
        ("3", "0.500000000000"),
        ("1", "0.300000000000"),
        ("0", "0.200000000000"),
    ),
) -> OfferCandidateInput:
    faces = tuple(face for face, _value in probabilities)
    return OfferCandidateInput(
        official_match_no=match_no,
        official_offer_revision_id=f"offer-{match_no}",
        match_id=f"match-{match_no}",
        market_definition_id=market_definition_id,
        probabilities=probabilities,
        allowed_face_bundles=tuple(
            FaceBundleOption(bundle_code=code, face_codes=face_codes)
            for code, face_codes in bundles
        ),
        omission_allowed=omission_allowed,
        quote_ids_by_face=(
            tuple((face, f"quote-{match_no}-{face}") for face in faces)
            if lane == "jczq"
            else ()
        ),
        booked_decimal_odds_by_face=(
            tuple((face, "2.000000000000") for face in faces)
            if lane == "jczq"
            else ()
        ),
    )


def _generation_input(
    *,
    lane: str,
    ticket_kind: str,
    offers: tuple[OfferCandidateInput, ...],
    templates: tuple[CandidateStructureTemplate, ...],
    capital_cap_minor: int = 10_000,
    maximum_ticket_count: int = 1,
    maximum_exhaustive_candidate_count: int = 100,
    official_median_bonus_minor: int | None = None,
) -> CandidateGenerationInput:
    return CandidateGenerationInput(
        lane=lane,
        ticket_kind=ticket_kind,
        currency="CNY",
        capital_cap_minor=capital_cap_minor,
        unit_stake_minor=200,
        maximum_ticket_count=maximum_ticket_count,
        maximum_exhaustive_candidate_count=maximum_exhaustive_candidate_count,
        offers=offers,
        templates=templates,
        fixed_prize_policy_revision_id=(
            "fixed-policy-renjiu-v1" if lane == "zucai" else None
        ),
        official_median_bonus_minor=official_median_bonus_minor,
    )


def test_union_probability_uses_exact_inclusion_exclusion() -> None:
    probabilities = {
        "1": {
            "3": Decimal("0.500000000000"),
            "1": Decimal("0.300000000000"),
            "0": Decimal("0.200000000000"),
        },
        "2": {
            "3": Decimal("0.600000000000"),
            "1": Decimal("0.250000000000"),
            "0": Decimal("0.150000000000"),
        },
    }
    tickets = (
        {"1": frozenset({"3"}), "2": frozenset({"3", "1"})},
        {"1": frozenset({"3", "1"}), "2": frozenset({"3"})},
    )

    assert union_probability(tickets, probabilities) == Decimal("0.605000000000")


def test_incompatible_ticket_intersection_contributes_zero() -> None:
    probabilities = {
        "1": {
            "3": Decimal("0.500000000000"),
            "1": Decimal("0.300000000000"),
            "0": Decimal("0.200000000000"),
        }
    }
    tickets = (
        {"1": frozenset({"3"})},
        {"1": frozenset({"0"})},
    )

    assert union_probability(tickets, probabilities) == Decimal("0.700000000000")


def test_jczq_enumeration_covers_the_complete_declared_space() -> None:
    inputs = _generation_input(
        lane="jczq",
        ticket_kind="jczq_pass",
        offers=(
            _offer("1", ("home", ("3",)), ("home-draw", ("3", "1"))),
            _offer("2", ("away", ("0",)), ("draw-away", ("1", "0"))),
        ),
        templates=(
            CandidateStructureTemplate(
                kind="jczq_pass",
                structure_code="2x1",
                eligible_official_match_nos=("1", "2"),
                required_offer_count=2,
                maximum_groups=1,
                pass_size=2,
            ),
        ),
        maximum_exhaustive_candidate_count=20,
    )

    result = enumerate_candidates(inputs)

    assert result.calculated_candidate_count == 4
    assert len(result.candidates) == 4
    assert len({candidate.content_hash for candidate in result.candidates}) == 4
    assert all(len(candidate.tickets) == 1 for candidate in result.candidates)
    assert {candidate.tickets[0].unit_count for candidate in result.candidates} == {
        1,
        2,
        4,
    }


def test_zucai_sfc_requires_all_fourteen_declared_offers() -> None:
    offers = tuple(
        _offer(str(index), ("single", ("3",)), lane="zucai")
        for index in range(1, 15)
    )
    inputs = _generation_input(
        lane="zucai",
        ticket_kind="sfc",
        offers=offers,
        templates=(
            CandidateStructureTemplate(
                kind="zucai_group",
                structure_code="sfc-14",
                eligible_official_match_nos=tuple(str(index) for index in range(1, 15)),
                required_offer_count=14,
                maximum_groups=1,
            ),
        ),
        maximum_exhaustive_candidate_count=2,
    )

    result = enumerate_candidates(inputs)

    assert len(result.candidates) == 1
    assert result.candidates[0].tickets[0].ticket_kind == "sfc"
    assert len(result.candidates[0].tickets[0].legs) == 14
    assert result.candidates[0].tickets[0].unit_count == 1


def test_renjiu_enumerates_exact_nine_offer_groups_and_multi_ticket_batches() -> None:
    offers = tuple(
        _offer(
            str(index),
            ("single", ("3",)),
            omission_allowed=True,
            lane="zucai",
        )
        for index in range(1, 11)
    )
    inputs = _generation_input(
        lane="zucai",
        ticket_kind="renjiu",
        offers=offers,
        templates=(
            CandidateStructureTemplate(
                kind="zucai_group",
                structure_code="r9",
                eligible_official_match_nos=tuple(str(index) for index in range(1, 11)),
                required_offer_count=9,
                maximum_groups=2,
            ),
        ),
        maximum_ticket_count=2,
    )

    result = enumerate_candidates(inputs)

    assert result.calculated_candidate_count == 55
    assert sum(len(candidate.tickets) == 1 for candidate in result.candidates) == 10
    assert sum(len(candidate.tickets) == 2 for candidate in result.candidates) == 45
    assert all(
        len(ticket.legs) == 9
        for candidate in result.candidates
        for ticket in candidate.tickets
    )


def test_template_maximum_groups_limits_batches_from_that_template() -> None:
    offers = tuple(
        _offer(str(index), ("single", ("3",)), omission_allowed=True)
        for index in range(1, 4)
    )
    inputs = _generation_input(
        lane="jczq",
        ticket_kind="jczq_pass",
        offers=offers,
        templates=(
            CandidateStructureTemplate(
                kind="jczq_pass",
                structure_code="1x1",
                eligible_official_match_nos=("1", "2", "3"),
                required_offer_count=1,
                maximum_groups=1,
                pass_size=1,
            ),
        ),
        maximum_ticket_count=2,
    )

    result = enumerate_candidates(inputs)

    assert result.calculated_candidate_count == 3
    assert all(len(candidate.tickets) == 1 for candidate in result.candidates)


def test_enumeration_bound_is_checked_before_materializing_candidates() -> None:
    inputs = _generation_input(
        lane="jczq",
        ticket_kind="jczq_pass",
        offers=tuple(
            _offer(str(index), ("single", ("3",)), omission_allowed=True)
            for index in range(1, 6)
        ),
        templates=(
            CandidateStructureTemplate(
                kind="jczq_pass",
                structure_code="1x1",
                eligible_official_match_nos=tuple(str(index) for index in range(1, 6)),
                required_offer_count=1,
                maximum_groups=2,
                pass_size=1,
            ),
        ),
        maximum_ticket_count=2,
        maximum_exhaustive_candidate_count=9,
    )

    with pytest.raises(CandidateSpaceLimitError, match="15.*9"):
        enumerate_candidates(inputs)


def test_zero_cap_is_rejected_instead_of_reporting_zero_utilization() -> None:
    with pytest.raises(ValueError, match="capital_cap_minor.*at least 1"):
        _generation_input(
            lane="jczq",
            ticket_kind="jczq_pass",
            capital_cap_minor=0,
            offers=(_offer("1", ("home", ("3",))),),
            templates=(
                CandidateStructureTemplate(
                    kind="jczq_pass",
                    structure_code="1x1",
                    eligible_official_match_nos=("1",),
                    required_offer_count=1,
                    maximum_groups=1,
                    pass_size=1,
                ),
            ),
        )


def test_duplicate_bundle_face_sets_are_rejected_before_counting() -> None:
    with pytest.raises(ValueError, match="face sets must be unique"):
        _offer(
            "1",
            ("home-draw", ("3", "1")),
            ("draw-home", ("1", "3")),
        )


def test_metrics_use_decimal_probability_coverage_and_report_only_median() -> None:
    inputs = _generation_input(
        lane="jczq",
        ticket_kind="jczq_pass",
        capital_cap_minor=1_000,
        official_median_bonus_minor=2_000,
        offers=(
            _offer("1", ("home-draw", ("3", "1"))),
            _offer(
                "2",
                ("home", ("3",)),
                probabilities=(
                    ("3", "0.600000000000"),
                    ("1", "0.250000000000"),
                    ("0", "0.150000000000"),
                ),
            ),
        ),
        templates=(
            CandidateStructureTemplate(
                kind="jczq_pass",
                structure_code="2x1",
                eligible_official_match_nos=("1", "2"),
                required_offer_count=2,
                maximum_groups=1,
                pass_size=2,
            ),
        ),
        maximum_exhaustive_candidate_count=2,
    )

    (candidate,) = enumerate_candidates(inputs).candidates

    assert candidate.ticket_count == 1
    assert candidate.distinct_note_count == 2
    assert candidate.paid_note_unit_count == 2
    assert candidate.probability_kind == "all_required_legs"
    assert candidate.tickets[0].unit_count == 2
    assert candidate.stake_minor == 400
    assert candidate.cap_utilization_decimal == "0.400000000000"
    assert candidate.objective_label == "P(all required legs correct)"
    assert candidate.objective_probability_decimal == "0.480000000000"
    assert candidate.expected_broken_legs_decimal == "0.600000000000"
    assert candidate.common_dead_faces == (
        ("1", ("0",)),
        ("2", ("1", "0")),
    )
    assert candidate.break_even_bonus_minor == 834
    assert candidate.break_even_to_median_decimal == "0.417000000000"


def test_candidate_hash_covers_unrounded_probabilities_and_set_kind() -> None:
    template = CandidateStructureTemplate(
        kind="jczq_pass",
        structure_code="1x1",
        eligible_official_match_nos=("1",),
        required_offer_count=1,
        maximum_groups=1,
        pass_size=1,
    )
    first = _generation_input(
        lane="jczq",
        ticket_kind="jczq_pass",
        offers=(_offer("1", ("home", ("3",))),),
        templates=(template,),
    )
    changed = _generation_input(
        lane="jczq",
        ticket_kind="jczq_pass",
        offers=(
            _offer(
                "1",
                ("home", ("3",)),
                probabilities=(
                    ("3", "0.5000000000001"),
                    ("1", "0.2999999999999"),
                    ("0", "0.2000000000000"),
                ),
            ),
        ),
        templates=(template,),
    )

    judgment = enumerate_candidates(first).candidates[0]
    probability_changed = enumerate_candidates(changed).candidates[0]
    conditional = enumerate_candidates(
        first,
        set_kind="conditional_market_counterfactual",
    ).candidates[0]

    assert judgment.objective_probability_decimal == (
        probability_changed.objective_probability_decimal
    )
    assert judgment.content_hash != probability_changed.content_hash
    assert judgment.content_hash != conditional.content_hash


@pytest.mark.parametrize(
    ("ticket_kind", "required_offer_count", "message"),
    [
        ("sfc", 13, "exactly fourteen"),
        ("renjiu", 8, "exactly nine"),
    ],
)
def test_zucai_structure_requires_official_match_count(
    ticket_kind: str,
    required_offer_count: int,
    message: str,
) -> None:
    offer_count = 14 if ticket_kind == "sfc" else 9
    offers = tuple(
        _offer(
            str(index),
            ("single", ("3",)),
            omission_allowed=ticket_kind == "renjiu",
            lane="zucai",
        )
        for index in range(1, offer_count + 1)
    )
    template = CandidateStructureTemplate(
        kind="zucai_group",
        structure_code=f"{ticket_kind}-invalid",
        eligible_official_match_nos=tuple(str(index) for index in range(1, offer_count + 1)),
        required_offer_count=required_offer_count,
        maximum_groups=1,
    )

    with pytest.raises(ValueError, match=message):
        _generation_input(
            lane="zucai",
            ticket_kind=ticket_kind,
            offers=offers,
            templates=(template,),
        )


def test_jczq_pass_size_must_equal_required_offer_count() -> None:
    offers = (
        _offer("1", ("home", ("3",))),
        _offer("2", ("away", ("0",))),
    )
    template = CandidateStructureTemplate(
        kind="jczq_pass",
        structure_code="invalid-2x1",
        eligible_official_match_nos=("1", "2"),
        required_offer_count=2,
        maximum_groups=1,
        pass_size=1,
    )

    with pytest.raises(ValueError, match="pass size"):
        _generation_input(
            lane="jczq",
            ticket_kind="jczq_pass",
            offers=offers,
            templates=(template,),
        )


def test_conditional_set_keeps_three_way_partition_but_is_not_deployable() -> None:
    inputs = _generation_input(
        lane="jczq",
        ticket_kind="jczq_pass",
        offers=(_offer("1", ("home", ("3",))),),
        templates=(
            CandidateStructureTemplate(
                kind="jczq_pass",
                structure_code="1x1",
                eligible_official_match_nos=("1",),
                required_offer_count=1,
                maximum_groups=1,
                pass_size=1,
            ),
        ),
    )

    result = enumerate_candidates(inputs, set_kind="conditional_market_counterfactual")

    assert result.comparison_only is True
    assert result.candidates[0].partition == "eligible"
    assert result.candidates[0].rank == 1
    assert result.candidates[0].deployable is False
    assert result.selected_candidate_hash is None


def test_candidate_order_is_probability_then_stake_then_hash() -> None:
    inputs = _generation_input(
        lane="jczq",
        ticket_kind="jczq_pass",
        offers=(
            _offer(
                "1",
                ("home", ("3",)),
                ("home-draw", ("3", "1")),
                omission_allowed=True,
            ),
            _offer(
                "2",
                ("home", ("3",)),
                ("home-draw", ("3", "1")),
                omission_allowed=True,
            ),
        ),
        templates=(
            CandidateStructureTemplate(
                kind="jczq_pass",
                structure_code="1x1",
                eligible_official_match_nos=("1", "2"),
                required_offer_count=1,
                maximum_groups=1,
                pass_size=1,
            ),
        ),
        maximum_exhaustive_candidate_count=10,
    )

    result = enumerate_candidates(inputs)

    keys = [
        (
            Decimal(candidate.objective_probability_decimal),
            candidate.stake_minor,
            candidate.content_hash,
        )
        for candidate in result.candidates
    ]
    assert keys == sorted(keys, key=lambda row: (-row[0], row[1], row[2]))
    assert [candidate.rank for candidate in result.candidates] == [1, 2, 3, 4]
    assert result.selected_candidate_hash is None


def test_generic_crs_other_is_never_deployable() -> None:
    with pytest.raises(ValueError, match="direction-specific CRS aggregate"):
        _offer(
            "1",
            ("legacy-other", ("other",)),
            market_definition_id="md-crs",
            probabilities=(
                ("1:0", "0.500000000000"),
                ("win_other", "0.200000000000"),
                ("draw_other", "0.100000000000"),
                ("loss_other", "0.100000000000"),
                ("other", "0.100000000000"),
            ),
        )


def test_zucai_candidate_forbids_settlement_line() -> None:
    offer = OfferCandidateInput(
        official_match_no="1",
        official_offer_revision_id="offer-1",
        match_id="match-1",
        market_definition_id="md-had",
        probabilities=(("3", "1.000000000000"),),
        allowed_face_bundles=(FaceBundleOption("single", ("3",)),),
        omission_allowed=False,
        settlement_parameter_decimal="1.000000000000",
    )
    with pytest.raises(ValueError, match="must not contain quote odds or line"):
        _generation_input(
            lane="zucai",
            ticket_kind="renjiu",
            offers=(offer,),
            templates=(
                CandidateStructureTemplate(
                    kind="zucai_group",
                    structure_code="r1-test",
                    eligible_official_match_nos=("1",),
                    required_offer_count=1,
                    maximum_groups=1,
                ),
            ),
        )


def test_26111_u864_family_replays_exact_recorded_probabilities() -> None:
    fixture_path = (
        Path(__file__).parents[1]
        / "fixtures"
        / "operator"
        / "26111-u864-candidates.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    versions = fixture["versions"]
    allowed_faces = {
        match_no: tuple(
            dict.fromkeys(
                version["faces"][match_no]
                for version in versions
            )
        )
        for match_no in fixture["probabilities"]
    }
    offers = tuple(
        _offer(
            match_no,
            *tuple(
                (f"faces-{faces}", tuple(faces))
                for faces in allowed_faces[match_no]
            ),
            lane="zucai",
            probabilities=tuple(fixture["probabilities"][match_no].items()),
        )
        for match_no in fixture["probabilities"]
    )
    inputs = _generation_input(
        lane="zucai",
        ticket_kind="renjiu",
        offers=offers,
        templates=(
            CandidateStructureTemplate(
                kind="zucai_group",
                structure_code="renjiu-u864-family",
                eligible_official_match_nos=tuple(fixture["probabilities"]),
                required_offer_count=9,
                maximum_groups=1,
            ),
        ),
        capital_cap_minor=fixture["capital_cap_minor"],
        maximum_exhaustive_candidate_count=8,
    )

    result = enumerate_candidates(inputs)
    candidates_by_faces = {
        tuple(
            (leg.official_match_no, "".join(leg.selection_codes))
            for leg in candidate.tickets[0].legs
        ): candidate
        for candidate in result.candidates
    }

    assert result.calculated_candidate_count == 8
    for version in versions:
        key = tuple(version["faces"].items())
        candidate = candidates_by_faces[key]
        assert candidate.stake_minor == version["stake_minor"]
        assert (
            candidate.objective_probability_decimal
            == version["objective_probability_decimal"]
        )
