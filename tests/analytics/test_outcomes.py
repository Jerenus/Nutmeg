from nutmeg.analytics.outcomes import outcome_one_hot


def test_had_one_hot() -> None:
    keys = ["home", "draw", "away"]
    assert outcome_one_hot("had", keys, "2-1") == {"home": 1.0, "draw": 0.0, "away": 0.0}
    assert outcome_one_hot("had", keys, "1-1") == {"home": 0.0, "draw": 1.0, "away": 0.0}
    assert outcome_one_hot("had", keys, "0-3") == {"home": 0.0, "draw": 0.0, "away": 1.0}


def test_non_had_returns_none() -> None:
    assert outcome_one_hot("ttg", ["total_0", "total_1"], "2-1") is None
