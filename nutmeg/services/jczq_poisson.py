"""Independent-Poisson scoreline model for fair-odds derivation.

Given the market's three-way had odds, infer per-team scoring rates
(home_lambda, away_lambda) such that the implied (vig-removed) win/draw/loss
probabilities best match a Poisson scoreline grid. The fitted lambdas can then
be projected into ttg/hafu/crs fair odds and compared to the market price.

This is intentionally a small, dependency-free implementation so it works in
the test environment without numpy/scipy. The grid search uses 36 candidate
lambda pairs which is plenty of precision for the +/- 0.5 goal world JCZQ
deals with.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

DEFAULT_MAX_GOALS = 6


def _vig_normalize(home_odd: float, draw_odd: float, away_odd: float) -> tuple[float, float, float]:
    raw = [1.0 / home_odd, 1.0 / draw_odd, 1.0 / away_odd]
    total = sum(raw)
    if total <= 0:
        return (0.33, 0.34, 0.33)
    return raw[0] / total, raw[1] / total, raw[2] / total


def _poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam**k) / math.factorial(k)


def _dixon_coles_tau(
    h: int, a: int, lam_h: float, lam_a: float, rho: float
) -> float:
    """F1 (5/14): Dixon-Coles 1997 low-score correction multiplier.

    Modifies independent-Poisson grid only at (0,0) / (0,1) / (1,0) / (1,1).

    rho > 0 → tau(0,0) < 1 (deflate 0:0); use when historical data shows
              Poisson over-prices low scoring (JCZQ case: crs 0:0 实测
              1/16 vs implied 8-15%).
    rho < 0 → tau(0,0) > 1 (inflate 0:0); textbook D-C default for
              European football where 0:0 is under-predicted.
    rho = 0 → tau = 1 everywhere (backward-compatible no-op).

    Result is clamped to [0, +inf) so multiplied probability never goes
    negative (extreme rho values can otherwise push tau < 0).
    """

    if rho == 0.0:
        return 1.0
    if h == 0 and a == 0:
        return max(0.0, 1.0 - lam_h * lam_a * rho)
    if h == 0 and a == 1:
        return max(0.0, 1.0 + lam_h * rho)
    if h == 1 and a == 0:
        return max(0.0, 1.0 + lam_a * rho)
    if h == 1 and a == 1:
        return max(0.0, 1.0 - rho)
    return 1.0


@dataclass(frozen=True, slots=True)
class ScoreGrid:
    home_lambda: float
    away_lambda: float
    grid: dict[tuple[int, int], float]


def build_score_grid(
    home_lambda: float,
    away_lambda: float,
    *,
    max_goals: int = DEFAULT_MAX_GOALS,
    dc_rho: float = 0.0,
) -> ScoreGrid:
    """Build joint score probability grid via independent Poisson + optional
    Dixon-Coles tau correction.

    F1 (5/14): when `dc_rho != 0`, applies _dixon_coles_tau multiplier to
    (0,0) / (0,1) / (1,0) / (1,1) entries, then renormalizes the grid so
    total probability mass stays ~1.0. dc_rho=0.0 (default) preserves the
    pre-F1 independent-Poisson behavior for backward compatibility.
    """

    grid: dict[tuple[int, int], float] = {}
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            base = _poisson_pmf(h, home_lambda) * _poisson_pmf(a, away_lambda)
            if dc_rho != 0.0:
                base = base * _dixon_coles_tau(h, a, home_lambda, away_lambda, dc_rho)
            grid[(h, a)] = base
    if dc_rho != 0.0:
        # Renormalize so the probability mass sums back to ~1.0 (the tau
        # correction does not preserve total mass).
        total = sum(grid.values())
        if total > 0:
            grid = {k: v / total for k, v in grid.items()}
    return ScoreGrid(home_lambda=home_lambda, away_lambda=away_lambda, grid=grid)


HAFU_FIRST_HALF_SHARE = 0.45  # empirical first-half goal share in football


def derive_market_probs(grid: ScoreGrid) -> dict[str, dict[str, float]]:
    """Aggregate the score grid into pool-wise probabilities.

    HAD / TTG / CRS are aggregated directly from the score grid. HAFU requires
    a proper joint distribution: we split each team's λ into halves using
    `HAFU_FIRST_HALF_SHARE`, model halftime and second-half goals as
    independent Poissons, then sum P(HT outcome AND FT outcome) for each of
    the nine hafu states.
    """

    had = {"胜": 0.0, "平": 0.0, "负": 0.0}
    ttg: dict[str, float] = {f"{n}球": 0.0 for n in range(7)}
    crs: dict[str, float] = {}

    for (h, a), prob in grid.grid.items():
        if h > a:
            had["胜"] += prob
        elif h < a:
            had["负"] += prob
        else:
            had["平"] += prob
        total_goals = h + a
        bucket = f"{min(total_goals, 6)}球"
        ttg[bucket] += prob
        score_key = f"{h}:{a}"
        crs[score_key] = crs.get(score_key, 0.0) + prob

    hafu = _compute_hafu_probs(
        grid.home_lambda,
        grid.away_lambda,
        max_goals=DEFAULT_MAX_GOALS,
    )

    return {"had": had, "ttg": ttg, "hafu": hafu, "crs": crs}


def _compute_hafu_probs(
    home_lambda: float,
    away_lambda: float,
    *,
    max_goals: int = DEFAULT_MAX_GOALS,
    first_half_share: float = HAFU_FIRST_HALF_SHARE,
) -> dict[str, float]:
    """Joint halftime × fulltime distribution under independent Poissons."""

    h1_lambda = home_lambda * first_half_share
    h2_lambda = home_lambda * (1.0 - first_half_share)
    a1_lambda = away_lambda * first_half_share
    a2_lambda = away_lambda * (1.0 - first_half_share)

    hafu = {key: 0.0 for key in (
        "胜/胜", "胜/平", "胜/负",
        "平/胜", "平/平", "平/负",
        "负/胜", "负/平", "负/负",
    )}

    # Pre-compute pmfs once
    h1_pmf = [_poisson_pmf(k, h1_lambda) for k in range(max_goals + 1)]
    a1_pmf = [_poisson_pmf(k, a1_lambda) for k in range(max_goals + 1)]
    h2_pmf = [_poisson_pmf(k, h2_lambda) for k in range(max_goals + 1)]
    a2_pmf = [_poisson_pmf(k, a2_lambda) for k in range(max_goals + 1)]

    for h1 in range(max_goals + 1):
        for a1 in range(max_goals + 1):
            ht_prob = h1_pmf[h1] * a1_pmf[a1]
            if ht_prob == 0:
                continue
            ht_outcome = "胜" if h1 > a1 else "负" if h1 < a1 else "平"
            for h2 in range(max_goals + 1):
                for a2 in range(max_goals + 1):
                    ft_prob = h2_pmf[h2] * a2_pmf[a2]
                    if ft_prob == 0:
                        continue
                    home_total = h1 + h2
                    away_total = a1 + a2
                    if home_total > away_total:
                        ft_outcome = "胜"
                    elif home_total < away_total:
                        ft_outcome = "负"
                    else:
                        ft_outcome = "平"
                    hafu[f"{ht_outcome}/{ft_outcome}"] += ht_prob * ft_prob
    return hafu


@dataclass(frozen=True, slots=True)
class FittedModel:
    home_lambda: float
    away_lambda: float
    fitted_probs: dict[str, dict[str, float]]
    market_probs: dict[str, float]
    error: float


def fit_lambdas_from_market(
    home_odd: float,
    draw_odd: float,
    away_odd: float,
    *,
    max_lambda: float = 4.0,
    step: float = 0.1,
    dc_rho: float = 0.0,
) -> FittedModel:
    """Find (home_lambda, away_lambda) minimizing squared distance to had probs.

    F1 (5/14): `dc_rho` propagates Dixon-Coles tau correction into the score
    grid used during fitting (and the fitted_probs returned). Default 0.0
    keeps backward compatibility (no correction).
    """

    target = _vig_normalize(home_odd, draw_odd, away_odd)
    market = {"胜": target[0], "平": target[1], "负": target[2]}
    best: FittedModel | None = None
    lambdas = []
    value = step
    while value <= max_lambda + 1e-9:
        lambdas.append(round(value, 2))
        value += step
    for hl in lambdas:
        for al in lambdas:
            grid = build_score_grid(
                hl, al, max_goals=DEFAULT_MAX_GOALS, dc_rho=dc_rho
            )
            probs = derive_market_probs(grid)
            err = sum(
                (probs["had"][outcome] - market[outcome]) ** 2 for outcome in ("胜", "平", "负")
            )
            if best is None or err < best.error:
                best = FittedModel(
                    home_lambda=hl,
                    away_lambda=al,
                    fitted_probs=probs,
                    market_probs=market,
                    error=err,
                )
    assert best is not None  # guaranteed since lambdas non-empty
    return best


def fair_odds(model: FittedModel, *, pool: str, pick: str) -> float | None:
    pool_probs = model.fitted_probs.get(pool) or {}
    prob = pool_probs.get(pick)
    if prob is None or prob <= 0:
        return None
    return round(1.0 / prob, 3)


# R7 (5/08): hhad pricing — Poisson grid + handicap adjustment.
# goal_line semantics from the home perspective: -1 = home gives 1 goal,
# +1 = home receives 1 goal. Half-goal lines eliminate the tie outcome.


def _compute_hhad_probs(
    grid: ScoreGrid,
    *,
    goal_line: float,
) -> dict[str, float]:
    """Probabilities for 让胜 / 让平 / 让负 given handicap.

    Integer goal_line yields 让胜 / 让平 / 让负 probabilities. Half-goal
    lines (e.g., -0.5, +1.5) collapse 让平 to zero — no way for the
    adjusted score to tie.
    """

    integer_line = goal_line == int(goal_line)
    let_win = let_tie = let_loss = 0.0
    for (h, a), prob in grid.grid.items():
        adj_diff = (h + goal_line) - a
        if adj_diff > 0:
            let_win += prob
        elif integer_line and adj_diff == 0:
            let_tie += prob
        else:
            let_loss += prob
    if integer_line:
        return {"让胜": let_win, "让平": let_tie, "让负": let_loss}
    return {"让胜": let_win, "让负": let_loss}


def fair_odds_hhad(
    model: FittedModel,
    *,
    pick: str,
    goal_line: float,
    max_goals: int = DEFAULT_MAX_GOALS,
    dc_rho: float = 0.0,
) -> float | None:
    """Fair odds for an hhad pick given a handicap goal_line.

    Reconstructs the score grid from the fitted lambdas and aggregates
    the handicap-adjusted outcome probabilities. Returns None when the
    pick is not produced for the given line (e.g., 让平 with a half line).

    F1 (5/14): `dc_rho` propagates the Dixon-Coles tau correction; default
    0.0 keeps backward compatibility.
    """

    grid = build_score_grid(
        model.home_lambda, model.away_lambda, max_goals=max_goals, dc_rho=dc_rho,
    )
    probs = _compute_hhad_probs(grid, goal_line=goal_line)
    prob = probs.get(pick)
    if prob is None or prob <= 0:
        return None
    return round(1.0 / prob, 3)


def edge_vs_market(
    model: FittedModel,
    *,
    pool: str,
    pick: str,
    market_odd: float,
    goal_line: float | None = None,
    dc_rho: float = 0.0,
) -> float | None:
    if pool == "hhad":
        if goal_line is None:
            return None
        fair = fair_odds_hhad(
            model, pick=pick, goal_line=goal_line, dc_rho=dc_rho,
        )
    else:
        fair = fair_odds(model, pool=pool, pick=pick)
    if fair is None or market_odd <= 0:
        return None
    return round(market_odd / fair - 1.0, 4)
