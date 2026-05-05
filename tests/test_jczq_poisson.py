"""Tests for the JCZQ bivariate-Poisson scoreline model."""

from __future__ import annotations

from nutmeg.services.jczq_poisson import (
    build_score_grid,
    derive_market_probs,
    edge_vs_market,
    fair_odds,
    fit_lambdas_from_market,
)


def test_build_score_grid_returns_normalized_distribution() -> None:
    grid = build_score_grid(1.4, 1.0, max_goals=4)
    total = sum(grid.grid.values())
    assert 0.94 <= total <= 1.0


def test_derive_market_probs_includes_had_ttg_hafu() -> None:
    grid = build_score_grid(1.6, 1.1, max_goals=5)
    probs = derive_market_probs(grid)

    assert {"胜", "平", "负"} <= set(probs["had"].keys())
    assert sum(probs["had"].values()) > 0.95
    assert any(probs["ttg"][f"{k}球"] > 0.05 for k in range(0, 5))
    assert any(value > 0 for value in probs["hafu"].values())


def test_fit_lambdas_recovers_reasonable_strong_favorite_shape() -> None:
    # ~ Real Madrid at home vs Espanyol with 1.55 / 4.00 / 6.50
    fitted = fit_lambdas_from_market(1.55, 4.00, 6.50, max_lambda=3.0, step=0.2)
    assert fitted.home_lambda >= fitted.away_lambda
    assert fitted.error < 0.03
    fair_home = fair_odds(fitted, pool="had", pick="胜")
    assert fair_home is not None
    assert 1.30 <= fair_home <= 1.85


def test_edge_vs_market_positive_when_market_underprices() -> None:
    fitted = fit_lambdas_from_market(2.20, 3.30, 3.10, max_lambda=2.5, step=0.2)
    fair_home = fair_odds(fitted, pool="had", pick="胜")
    assert fair_home is not None

    inflated_market = fair_home * 1.10  # market gives +10% edge
    edge = edge_vs_market(fitted, pool="had", pick="胜", market_odd=inflated_market)
    assert edge is not None
    assert edge > 0.05
