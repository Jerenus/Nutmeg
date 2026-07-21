from nutmeg.ontology.ingest.intl_odds import ParsedIntlQuote, parse_bold_odds

# Real bold_odds shape: top-level dict keyed by sporttery matchNumStr ("周日104"),
# each carrying match_winner.odds.{home,draw,away}.
BOLD_FIXTURE = {
    "周日104": {
        "match_winner": {"odds": {"home": 2.3138, "draw": 2.9923, "away": 3.5585}},
        "over_under": {"odds": {"over": 2.3, "under": 1.6182}},
    }
}


def test_bold_odds_carry_the_match_no_for_alignment() -> None:
    quotes = parse_bold_odds(BOLD_FIXTURE)
    assert all(isinstance(q, ParsedIntlQuote) for q in quotes)
    assert quotes[0].align_match_no == "周日104"
    assert {q.market_kind for q in quotes} == {"had"}
    assert {q.outcome_key for q in quotes} == {"home", "draw", "away"}
    home = next(q for q in quotes if q.outcome_key == "home")
    assert abs(home.decimal_odds - 2.3138) < 1e-9
