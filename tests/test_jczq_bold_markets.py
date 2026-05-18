"""Tests for the bold engine's 体彩 multi-market math (pure, no I/O)."""

from nutmeg.services.jczq_bold_markets import (
    aggregate_crs_to_had,
    crs_scoreline_distribution,
)


def test_crs_scoreline_distribution_devigs_exact_and_other() -> None:
    # Three exact scorelines + one 其他 bucket; equal odds → equal de-vigged mass.
    crs_odds = {"s01s00": 4.0, "s00s00": 4.0, "s00s01": 4.0, "s1sa": 4.0}

    exact, other = crs_scoreline_distribution(crs_odds)

    assert set(exact) == {(1, 0), (0, 0), (0, 1)}
    assert set(other) == {"away"}
    total = sum(exact.values()) + sum(other.values())
    assert abs(total - 1.0) < 1e-9          # de-vigged over ALL crs outcomes
    assert abs(exact[(1, 0)] - 0.25) < 1e-9


def test_aggregate_crs_to_had_sums_by_sign() -> None:
    # 1:0 → home, 0:0 → draw, 0:1 → away, 其他负 → away. Equal mass 0.25 each.
    crs_odds = {"s01s00": 4.0, "s00s00": 4.0, "s00s01": 4.0, "s1sa": 4.0}

    had = aggregate_crs_to_had(*crs_scoreline_distribution(crs_odds))

    assert abs(had["home"] - 0.25) < 1e-9
    assert abs(had["draw"] - 0.25) < 1e-9
    assert abs(had["away"] - 0.50) < 1e-9   # 0:1 + 其他负
    assert abs(sum(had.values()) - 1.0) < 1e-9
