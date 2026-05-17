"""Calibration check for the conflict-engine model.

Measures whether the Dixon-Coles model's match-winner view tracks the market
rather than systematically fading the favorite. Used as the acceptance gate
for the model-calibration work (see the calibration spec §5). Pure functions
only — no I/O, no network — so it is unit-testable; the live data is gathered
by the acceptance run.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class MatchWinnerView:
    """One fixture's match-winner probabilities, from model and from market."""

    fixture_id: str
    model_home: float
    model_draw: float
    model_away: float
    market_home: float
    market_draw: float
    market_away: float


@dataclass(slots=True, frozen=True)
class CalibrationStats:
    """Aggregate calibration metrics over a set of fixtures."""

    fixtures: int
    direction_agreement: float  # share where model argmax == market argmax
    home_prob_correlation: float  # Pearson r of model vs market P(home win)


def _argmax3(home: float, draw: float, away: float) -> str:
    return max(
        (('home', home), ('draw', draw), ('away', away)),
        key=lambda pair: pair[1],
    )[0]


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x == 0.0 or var_y == 0.0:
        return 0.0
    return cov / (var_x ** 0.5 * var_y ** 0.5)


def calibration_stats(views: list[MatchWinnerView]) -> CalibrationStats:
    """Direction-agreement rate and P(home) correlation between model and market.

    A calibrated model agrees with the market favorite most of the time and its
    home-win probabilities track the market's. A model that fades the favorite
    scores low agreement and zero/negative correlation.
    """
    if not views:
        return CalibrationStats(
            fixtures=0, direction_agreement=0.0, home_prob_correlation=0.0
        )
    agree = sum(
        1
        for v in views
        if _argmax3(v.model_home, v.model_draw, v.model_away)
        == _argmax3(v.market_home, v.market_draw, v.market_away)
    )
    correlation = _pearson(
        [v.model_home for v in views],
        [v.market_home for v in views],
    )
    return CalibrationStats(
        fixtures=len(views),
        direction_agreement=round(agree / len(views), 4),
        home_prob_correlation=round(correlation, 4),
    )
