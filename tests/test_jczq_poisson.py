"""Tests for the JCZQ bivariate-Poisson scoreline model."""

from __future__ import annotations

from nutmeg.services.jczq_poisson import (
    build_score_grid,
    derive_market_probs,
    edge_vs_market,
    fair_odds,
    fair_odds_hhad,
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


# --------------------------------------------------------- R7 hhad pricing


def test_fair_odds_hhad_zero_handicap_matches_had_probabilities() -> None:
    """With goal_line=0, hhad let-win/let-tie/let-loss should equal
    had 胜/平/负 probabilities (the handicap collapses to no adjustment)."""
    fitted = fit_lambdas_from_market(2.20, 3.30, 3.10, max_lambda=2.5, step=0.2)
    fair_let_win = fair_odds_hhad(fitted, pick="让胜", goal_line=0.0)
    fair_let_tie = fair_odds_hhad(fitted, pick="让平", goal_line=0.0)
    fair_let_loss = fair_odds_hhad(fitted, pick="让负", goal_line=0.0)
    fair_had_win = fair_odds(fitted, pool="had", pick="胜")
    fair_had_tie = fair_odds(fitted, pool="had", pick="平")
    fair_had_loss = fair_odds(fitted, pool="had", pick="负")

    assert fair_let_win is not None and fair_had_win is not None
    assert abs(fair_let_win - fair_had_win) < 0.05
    assert fair_let_tie is not None and fair_had_tie is not None
    assert abs(fair_let_tie - fair_had_tie) < 0.05
    assert fair_let_loss is not None and fair_had_loss is not None
    assert abs(fair_let_loss - fair_had_loss) < 0.05


def test_fair_odds_hhad_negative_handicap_lowers_let_win_probability() -> None:
    """When home gives 1 goal (goal_line=-1), 让胜 means home wins by ≥2.
    For a heavy home favorite (lambda 2.0 vs 0.6), let-win should still be
    plausible (~40-50%) but its fair odds are higher than the unhandicapped
    had-win."""
    fitted = fit_lambdas_from_market(1.30, 5.50, 11.0, max_lambda=3.5, step=0.2)
    fair_had_win = fair_odds(fitted, pool="had", pick="胜")
    fair_let_win = fair_odds_hhad(fitted, pick="让胜", goal_line=-1.0)
    assert fair_had_win is not None and fair_let_win is not None
    # Negative handicap (home gives 1 goal) makes let-win harder → higher odds
    assert fair_let_win > fair_had_win


def test_fair_odds_hhad_half_goal_line_returns_no_let_tie() -> None:
    """Half-goal handicaps eliminate the tie outcome — there's no way to
    tie the adjusted score."""
    fitted = fit_lambdas_from_market(2.20, 3.30, 3.10, max_lambda=2.5, step=0.2)
    fair_let_tie_half = fair_odds_hhad(fitted, pick="让平", goal_line=-0.5)
    assert fair_let_tie_half is None


def test_edge_vs_market_handles_hhad_with_goal_line() -> None:
    """edge_vs_market should compute a Poisson edge for hhad legs when
    goal_line is provided; without goal_line the function should return None."""
    fitted = fit_lambdas_from_market(1.80, 3.50, 4.00, max_lambda=3.0, step=0.2)
    fair = fair_odds_hhad(fitted, pick="让胜", goal_line=-1.0)
    assert fair is not None

    edge_with_line = edge_vs_market(
        fitted, pool="hhad", pick="让胜", market_odd=fair * 1.10, goal_line=-1.0
    )
    assert edge_with_line is not None
    assert edge_with_line > 0.05

    # Missing goal_line → cannot price hhad
    edge_without_line = edge_vs_market(
        fitted, pool="hhad", pick="让胜", market_odd=fair * 1.10
    )
    assert edge_without_line is None
