from __future__ import annotations

from datetime import UTC, datetime

from nutmeg.domain.value import ValueCandidate
from nutmeg.services.jczq_diagnostics import check_same_match_pool_legality
from nutmeg.services.jczq_parlay_constructor import (
    ParlayConstructor,
    confidence_tier,
    value_candidate_to_parlay_leg,
)
from nutmeg.services.jczq_value_bridge import JczqMatchConflicts, JczqValueReport


def _candidate(
    *,
    fixture_id: str = "fx",
    market_key: str = "match_winner",
    outcome_key: str = "home",
    outcome_name: str = "Home",
    edge: float = 0.12,
    best_odds: float = 2.2,
    kelly: float = 0.03,
) -> ValueCandidate:
    return ValueCandidate(
        fixture_id=fixture_id,
        kickoff_at=datetime(2026, 5, 17, 14, 0, tzinfo=UTC),
        home_team="Arsenal",
        away_team="Tottenham",
        outcome_key=outcome_key,
        outcome_name=outcome_name,
        model_probability=0.55,
        market_probability=0.43,
        edge=edge,
        best_odds=best_odds,
        expected_value=round(0.55 * best_odds - 1, 4),
        quarter_kelly_fraction=kelly,
        rating="strong" if edge >= 0.08 else "watchlist",
        model_name="dixon-coles-lite",
        market_key=market_key,
    )


def _entry(
    match_no: str, conflicts: list[ValueCandidate]
) -> JczqMatchConflicts:
    return JczqMatchConflicts(
        match_no=match_no,
        league="英超",
        home_team="阿森纳",
        away_team="热刺",
        aligned=True,
        fixture_id="fx-" + match_no,
        conflicts=conflicts,
    )


def test_confidence_tier_thresholds() -> None:
    assert confidence_tier(0.16) == "high"
    assert confidence_tier(0.10) == "medium"
    assert confidence_tier(0.04) == "low"


def test_market_key_maps_to_jczq_pool() -> None:
    leg = value_candidate_to_parlay_leg(
        "周六001", _candidate(market_key="match_winner", outcome_key="home")
    )
    assert leg.pool == "had"
    assert leg.pick == "胜"

    ttg = value_candidate_to_parlay_leg(
        "周六002",
        _candidate(market_key="total_goals", outcome_key="total_2", outcome_name="2"),
    )
    assert ttg.pool == "ttg"
    assert ttg.pick == "2"

    crs = value_candidate_to_parlay_leg(
        "周六003",
        _candidate(
            market_key="correct_score", outcome_key="score_2_1", outcome_name="2:1"
        ),
    )
    assert crs.pool == "crs"
    assert crs.pick == "2:1"

    hhad = value_candidate_to_parlay_leg(
        "周六004",
        _candidate(market_key="handicap_home_minus_1", outcome_key="away"),
    )
    assert hhad.pool == "hhad"
    assert hhad.pick == "负"


def test_constructs_two_three_four_fold_parlays() -> None:
    report = JczqValueReport(
        matches=[
            _entry("周六001", [_candidate(edge=0.18, best_odds=2.0)]),
            _entry("周六002", [_candidate(edge=0.15, best_odds=2.4)]),
            _entry("周六003", [_candidate(edge=0.13, best_odds=1.8)]),
            _entry("周六004", [_candidate(edge=0.11, best_odds=3.0)]),
        ]
    )
    constructor = ParlayConstructor()

    parlays = constructor.build(report)

    folds = {p.fold for p in parlays}
    assert folds == {2, 3, 4}
    # combined odds is the product of leg odds
    four = next(p for p in parlays if p.fold == 4)
    expected = 2.0 * 2.4 * 1.8 * 3.0
    assert abs(four.combined_odds - expected) < 1e-6


def test_parlays_respect_rule_o_one_leg_per_match() -> None:
    # Same match offers two markets; a parlay must never take both.
    report = JczqValueReport(
        matches=[
            _entry(
                "周六001",
                [
                    _candidate(market_key="match_winner", edge=0.20),
                    _candidate(
                        market_key="total_goals",
                        outcome_key="total_3",
                        outcome_name="3",
                        edge=0.18,
                    ),
                ],
            ),
            _entry("周六002", [_candidate(edge=0.16)]),
            _entry("周六003", [_candidate(edge=0.14)]),
        ]
    )
    constructor = ParlayConstructor()

    parlays = constructor.build(report)

    for parlay in parlays:
        match_nos = [leg.match_no for leg in parlay.legs]
        assert len(match_nos) == len(set(match_nos)), "Rule O violated"
    # Sanity-check against the canonical diagnostics validator via plan adapter.
    for parlay in parlays:
        violations = check_same_match_pool_legality([parlay.as_plan()])
        assert violations == []


def test_concentration_cap_limits_match_appearances() -> None:
    report = JczqValueReport(
        matches=[
            _entry("周六001", [_candidate(edge=0.20)]),
            _entry("周六002", [_candidate(edge=0.18)]),
            _entry("周六003", [_candidate(edge=0.16)]),
            _entry("周六004", [_candidate(edge=0.14)]),
            _entry("周六005", [_candidate(edge=0.12)]),
        ]
    )
    constructor = ParlayConstructor(max_match_appearances=2)

    parlays = constructor.build(report)

    counts: dict[str, int] = {}
    for parlay in parlays:
        for leg in parlay.legs:
            counts[leg.match_no] = counts.get(leg.match_no, 0) + 1
    assert counts, "expected at least one parlay"
    assert max(counts.values()) <= 2


def test_skips_matches_with_no_conflicts() -> None:
    report = JczqValueReport(
        matches=[
            _entry("周六001", [_candidate(edge=0.18)]),
            _entry("周六002", []),  # aligned but no edge
            _entry("周六003", [_candidate(edge=0.15)]),
        ]
    )
    constructor = ParlayConstructor()

    parlays = constructor.build(report)

    used_matches = {leg.match_no for p in parlays for leg in p.legs}
    assert "周六002" not in used_matches


def test_no_parlays_when_fewer_than_two_legs() -> None:
    report = JczqValueReport(matches=[_entry("周六001", [_candidate(edge=0.20)])])
    constructor = ParlayConstructor()

    parlays = constructor.build(report)

    assert parlays == []


def test_parlays_tagged_by_tier_and_sorted_by_edge() -> None:
    report = JczqValueReport(
        matches=[
            _entry("周六001", [_candidate(edge=0.20)]),
            _entry("周六002", [_candidate(edge=0.17)]),
            _entry("周六003", [_candidate(edge=0.05)]),
            _entry("周六004", [_candidate(edge=0.04)]),
        ]
    )
    constructor = ParlayConstructor()

    parlays = constructor.build(report)

    # A 2串1 built from the two high-tier legs must be tagged "high".
    high = [p for p in parlays if p.tier == "high" and p.fold == 2]
    assert high
    # parlays are ordered by average leg edge descending
    avg_edges = [p.average_edge for p in parlays]
    assert avg_edges == sorted(avg_edges, reverse=True)


# --- render_parlay_section (Phase 3 piece 4) --------------------------------


def test_render_parlay_section_lists_candidates() -> None:
    from nutmeg.services.jczq_parlay_constructor import render_parlay_section

    report = JczqValueReport(
        matches=[
            _entry("周六001", [_candidate(edge=0.20)]),
            _entry("周六002", [_candidate(edge=0.17)]),
        ]
    )
    candidates = ParlayConstructor().build(report)

    text = render_parlay_section(candidates)

    assert "串关候选" in text
    assert "2串1" in text
    assert "周六001" in text and "周六002" in text


def test_render_parlay_section_handles_no_candidates() -> None:
    from nutmeg.services.jczq_parlay_constructor import render_parlay_section

    text = render_parlay_section([])

    # The section header stays so debate knows the slot exists.
    assert "串关候选" in text
    assert "无法构造串关" in text
