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


# ----------------------------------------- F1 Dixon-Coles (5/14 落库) ---
# Independent Poisson over-prices low-score lines (实证 crs 0:0 命中率 1/16
# vs implied 8-15%). F1 introduces Dixon-Coles 1997 tau correction parameter
# `dc_rho` to build_score_grid. rho > 0 deflates 0:0/1:1, inflates 0:1/1:0
# (use when historical data shows 0:0 over-represented in implied — JCZQ case).
# rho < 0 is the textbook D-C default for European football data.
# rho = 0 (default): no correction, backward compat with all existing code.


def test_f1_dixon_coles_tau_returns_1_when_rho_zero() -> None:
    """F1: dc_rho=0.0 keeps independent-Poisson behavior (backward compat)."""
    from nutmeg.services.jczq_poisson import _dixon_coles_tau

    for h in range(3):
        for a in range(3):
            assert _dixon_coles_tau(h, a, 1.5, 1.2, 0.0) == 1.0


def test_f1_dixon_coles_tau_inflates_zero_zero_when_rho_negative() -> None:
    """F1: rho < 0 (D-C textbook default) → tau(0,0) > 1, tau(0,1) < 1.
    Used when independent Poisson under-predicts 0:0 (typical European football)."""
    from nutmeg.services.jczq_poisson import _dixon_coles_tau

    rho = -0.05
    lam_h, lam_a = 1.5, 1.2
    tau_00 = _dixon_coles_tau(0, 0, lam_h, lam_a, rho)
    tau_01 = _dixon_coles_tau(0, 1, lam_h, lam_a, rho)
    tau_10 = _dixon_coles_tau(1, 0, lam_h, lam_a, rho)
    tau_11 = _dixon_coles_tau(1, 1, lam_h, lam_a, rho)
    assert tau_00 > 1.0, f"rho<0: tau(0,0) 应 > 1，实际 {tau_00}"
    assert tau_01 < 1.0, f"rho<0: tau(0,1) 应 < 1，实际 {tau_01}"
    assert tau_10 < 1.0, f"rho<0: tau(1,0) 应 < 1，实际 {tau_10}"
    assert tau_11 > 1.0, f"rho<0: tau(1,1) 应 > 1，实际 {tau_11}"


def test_f1_dixon_coles_tau_deflates_zero_zero_when_rho_positive() -> None:
    """F1: rho > 0 (JCZQ inverted use case) → tau(0,0) < 1.
    Used when 10-day data shows 0:0 over-represented in implied vs realized."""
    from nutmeg.services.jczq_poisson import _dixon_coles_tau

    rho = 0.05
    lam_h, lam_a = 1.5, 1.2
    tau_00 = _dixon_coles_tau(0, 0, lam_h, lam_a, rho)
    tau_11 = _dixon_coles_tau(1, 1, lam_h, lam_a, rho)
    assert tau_00 < 1.0, f"rho>0: tau(0,0) 应 < 1（deflate），实际 {tau_00}"
    assert tau_11 < 1.0, f"rho>0: tau(1,1) 应 < 1，实际 {tau_11}"


def test_f1_dixon_coles_tau_unchanged_for_high_scores() -> None:
    """F1: tau only modifies (0,0)/(0,1)/(1,0)/(1,1); high scores unchanged."""
    from nutmeg.services.jczq_poisson import _dixon_coles_tau

    rho = -0.10
    for (h, a) in [(2, 0), (2, 1), (3, 0), (2, 2), (3, 3)]:
        assert _dixon_coles_tau(h, a, 1.5, 1.2, rho) == 1.0, (
            f"F1: tau({h},{a}) 应 = 1.0（不在校正区），实际 "
            f"{_dixon_coles_tau(h, a, 1.5, 1.2, rho)}"
        )


def test_f1_build_score_grid_with_dc_correction_changes_zero_zero() -> None:
    """F1: build_score_grid(dc_rho=-0.05) changes 0:0 entry vs dc_rho=0."""
    from nutmeg.services.jczq_poisson import build_score_grid

    base = build_score_grid(1.5, 1.2, max_goals=4, dc_rho=0.0)
    corrected = build_score_grid(1.5, 1.2, max_goals=4, dc_rho=-0.05)
    p00_base = base.grid[(0, 0)]
    p00_corrected = corrected.grid[(0, 0)]
    assert p00_corrected != p00_base, (
        f"F1: dc_rho=-0.05 应改变 P(0:0)；base={p00_base:.4f}, "
        f"corrected={p00_corrected:.4f}"
    )
    # Higher score (e.g., 2:1) should NOT be directly tau-modified, but renorm
    # may move it slightly; the proportional change should be small.
    p21_base = base.grid[(2, 1)]
    p21_corrected = corrected.grid[(2, 1)]
    # Renorm shifts at most ~few percent
    assert abs(p21_corrected - p21_base) / max(p21_base, 1e-9) < 0.05, (
        f"F1: dc_rho changes high-score (2:1) only via renorm; "
        f"abs delta {abs(p21_corrected - p21_base):.5f}"
    )


def test_f1_build_score_grid_renormalizes_to_unit_mass() -> None:
    """F1: after tau correction, grid still sums to ~1.0 (renormalization)."""
    from nutmeg.services.jczq_poisson import build_score_grid

    for rho in (-0.10, -0.05, 0.0, 0.05, 0.10):
        grid = build_score_grid(1.5, 1.2, max_goals=6, dc_rho=rho)
        total = sum(grid.grid.values())
        assert 0.99 <= total <= 1.01, (
            f"F1 rho={rho}: grid 应归一化，实际 sum={total:.4f}"
        )


def test_f1_fit_lambdas_accepts_dc_rho_kwarg() -> None:
    """F1: fit_lambdas_from_market accepts dc_rho and propagates to grid."""
    from nutmeg.services.jczq_poisson import fit_lambdas_from_market

    fitted_default = fit_lambdas_from_market(1.55, 4.00, 6.50, max_lambda=3.0, step=0.2)
    fitted_dc = fit_lambdas_from_market(
        1.55, 4.00, 6.50, max_lambda=3.0, step=0.2, dc_rho=-0.05
    )
    # Both should fit; lambdas may differ slightly due to corrected score grid
    assert fitted_default.home_lambda > 0
    assert fitted_dc.home_lambda > 0
