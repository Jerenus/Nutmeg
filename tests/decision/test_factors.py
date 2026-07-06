# tests/decision/test_factors.py
from nutmeg.decision.factors import ACTIVE_CAP, active_factor_ids, load_seed_factors


def test_seed_has_six_probation_factors():
    seed = load_seed_factors()
    assert len(seed) == 6
    assert all(f.status == "probation" for f in seed)
    ids = {f.factor_id for f in seed}
    assert {"seeding_incentive", "bunker_profile", "lineup_news_gap",
            "league_bias", "market_line_error", "fatigue_discount"} <= ids


def test_seed_factors_carry_born_from():
    assert all(f.born_from for f in load_seed_factors())   # 出生证必填


def test_active_ids_filters_status():
    from nutmeg.decision.ontology import Factor
    factors = [
        Factor("a", "A", "d", "2026-07-06", "x", status="active"),
        Factor("b", "B", "d", "2026-07-06", "x", status="probation"),
        Factor("c", "C", "d", "2026-07-06", "x", status="retired"),
    ]
    assert active_factor_ids(factors) == {"a"}


def test_active_cap_is_twelve():
    assert ACTIVE_CAP == 12
