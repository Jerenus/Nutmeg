from nutmeg.models.betting import no_vig_probabilities, quarter_kelly_fraction


def test_no_vig_probabilities_sum_to_one() -> None:
    probs = no_vig_probabilities([2.0, 3.5, 4.0])

    assert round(sum(probs), 6) == 1.0
    assert all(0 < prob < 1 for prob in probs)


def test_quarter_kelly_fraction_is_non_negative() -> None:
    stake_fraction = quarter_kelly_fraction(true_probability=0.55, decimal_odds=2.2)

    assert stake_fraction > 0


def test_fair_odds_inverts_probability() -> None:
    from nutmeg.models.betting import fair_odds

    assert fair_odds(0.625) == 1.6
