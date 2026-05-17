from __future__ import annotations

from dataclasses import dataclass
from math import exp, factorial

MODEL_NAME = 'dixon-coles-lite-poisson'

# Total-goals exact buckets are 0..6 plus a 7+ residual tail.
_MAX_TOTAL_GOALS_BUCKET = 7

# Integer handicap lines applied to the home side's goal tally.
# A negative line gives the home side a deficit (e.g. -1 = home must win by 2+).
_HANDICAP_LINES: tuple[int, ...] = (-2, -1, 0, 1, 2)

# Home-advantage multiplier for expected goals: the home side's goal
# expectation is scaled up and the away side's down by the same factor.
# ~1.18 reflects the roughly 55/45 home/away goal split in major European
# leagues, kept slightly conservative. A named constant so it is easy to
# re-tune from backtests.
_HOME_ADVANTAGE = 1.18


@dataclass(slots=True, frozen=True)
class ExpectedGoals:
    home: float
    away: float
    source: str = 'manual'


@dataclass(slots=True, frozen=True)
class ModelProbabilities:
    home_win: float
    draw: float
    away_win: float
    model_name: str
    expected_home_goals: float
    expected_away_goals: float
    expected_goals_source: str

    def as_dict(self) -> dict[str, float]:
        return {
            'home': self.home_win,
            'draw': self.draw,
            'away': self.away_win,
        }


@dataclass(slots=True, frozen=True)
class MatchPricingInput:
    home_attack: float
    away_attack: float
    home_defense: float
    away_defense: float


@dataclass(slots=True, frozen=True)
class MarketProbabilities:
    """Model probabilities across the value-board markets.

    Derived from the same Dixon-Coles score grid that powers `price()`.
    ``match_winner`` is identical to ``DixonColesLiteModel.price().as_dict()``.
    """

    match_winner: dict[str, float]
    total_goals: dict[str, float]
    correct_score: dict[str, float]
    handicap: dict[str, dict[str, float]]
    model_name: str
    expected_home_goals: float
    expected_away_goals: float
    expected_goals_source: str


class DixonColesLiteModel:
    """Small deterministic match-winner model for value-board diagnostics."""

    def __init__(self, *, max_goals: int = 10, rho: float = -0.05) -> None:
        self._max_goals = max_goals
        self._rho = rho

    def price(self, expected_goals: ExpectedGoals) -> ModelProbabilities:
        home_lambda, away_lambda, grid = self._score_grid(expected_goals)

        home_win = 0.0
        draw = 0.0
        away_win = 0.0
        for home_goals, row in enumerate(grid):
            for away_goals, probability in enumerate(row):
                if home_goals > away_goals:
                    home_win += probability
                elif home_goals == away_goals:
                    draw += probability
                else:
                    away_win += probability

        total = home_win + draw + away_win
        if total <= 0:
            raise ValueError('model probability total must be positive')

        normalized = {
            'home': home_win / total,
            'draw': draw / total,
            'away': away_win / total,
        }
        rounded = _round_and_normalize(normalized)
        return ModelProbabilities(
            home_win=rounded['home'],
            draw=rounded['draw'],
            away_win=rounded['away'],
            model_name=MODEL_NAME,
            expected_home_goals=home_lambda,
            expected_away_goals=away_lambda,
            expected_goals_source=expected_goals.source,
        )

    def price_markets(self, expected_goals: ExpectedGoals) -> MarketProbabilities:
        """Price the value-board markets from a single Dixon-Coles score grid.

        Returns probabilities for match-winner, total goals (exact buckets),
        correct score, and integer handicap lines. The ``match_winner`` field is
        identical to ``price().as_dict()`` — the legacy path is untouched.
        """
        legacy = self.price(expected_goals)
        _, _, grid = self._score_grid(expected_goals)
        total = sum(sum(row) for row in grid)
        if total <= 0:
            raise ValueError('model probability total must be positive')

        return MarketProbabilities(
            match_winner=legacy.as_dict(),
            total_goals=self._total_goals_probabilities(grid, total),
            correct_score=self._correct_score_probabilities(grid, total),
            handicap=self._handicap_probabilities(grid, total),
            model_name=MODEL_NAME,
            expected_home_goals=legacy.expected_home_goals,
            expected_away_goals=legacy.expected_away_goals,
            expected_goals_source=expected_goals.source,
        )

    def _score_grid(
        self,
        expected_goals: ExpectedGoals,
    ) -> tuple[float, float, list[list[float]]]:
        home_lambda = _bounded_goal_rate(expected_goals.home)
        away_lambda = _bounded_goal_rate(expected_goals.away)
        home_masses = _poisson_masses(home_lambda, self._max_goals)
        away_masses = _poisson_masses(away_lambda, self._max_goals)
        grid = [
            [
                home_mass * away_mass * self._low_score_adjustment(
                    home_goals,
                    away_goals,
                    home_lambda,
                    away_lambda,
                )
                for away_goals, away_mass in enumerate(away_masses)
            ]
            for home_goals, home_mass in enumerate(home_masses)
        ]
        return home_lambda, away_lambda, grid

    def _total_goals_probabilities(
        self,
        grid: list[list[float]],
        total: float,
    ) -> dict[str, float]:
        buckets = {f'total_{count}': 0.0 for count in range(_MAX_TOTAL_GOALS_BUCKET)}
        buckets[f'total_{_MAX_TOTAL_GOALS_BUCKET}_plus'] = 0.0
        for home_goals, row in enumerate(grid):
            for away_goals, probability in enumerate(row):
                goals = home_goals + away_goals
                if goals >= _MAX_TOTAL_GOALS_BUCKET:
                    buckets[f'total_{_MAX_TOTAL_GOALS_BUCKET}_plus'] += probability
                else:
                    buckets[f'total_{goals}'] += probability
        return _normalize_bucket_map({key: value / total for key, value in buckets.items()})

    def _correct_score_probabilities(
        self,
        grid: list[list[float]],
        total: float,
    ) -> dict[str, float]:
        scores = {
            f'score_{home_goals}_{away_goals}': probability / total
            for home_goals, row in enumerate(grid)
            for away_goals, probability in enumerate(row)
        }
        return _normalize_bucket_map(scores)

    def _handicap_probabilities(
        self,
        grid: list[list[float]],
        total: float,
    ) -> dict[str, dict[str, float]]:
        handicap: dict[str, dict[str, float]] = {}
        for line in _HANDICAP_LINES:
            home = 0.0
            draw = 0.0
            away = 0.0
            for home_goals, row in enumerate(grid):
                for away_goals, probability in enumerate(row):
                    adjusted = home_goals + line - away_goals
                    if adjusted > 0:
                        home += probability
                    elif adjusted == 0:
                        draw += probability
                    else:
                        away += probability
            handicap[_handicap_key(line)] = _normalize_bucket_map(
                {
                    'home': home / total,
                    'draw': draw / total,
                    'away': away / total,
                }
            )
        return handicap

    def _low_score_adjustment(
        self,
        home_goals: int,
        away_goals: int,
        home_lambda: float,
        away_lambda: float,
    ) -> float:
        if home_goals == 0 and away_goals == 0:
            return max(0.01, 1 - (home_lambda * away_lambda * self._rho))
        if home_goals == 0 and away_goals == 1:
            return max(0.01, 1 + (home_lambda * self._rho))
        if home_goals == 1 and away_goals == 0:
            return max(0.01, 1 + (away_lambda * self._rho))
        if home_goals == 1 and away_goals == 1:
            return max(0.01, 1 - self._rho)
        return 1.0


def expected_goals_from_snapshot(snapshot) -> ExpectedGoals:
    matchup = snapshot.matchup
    if matchup is not None and matchup.home_trend is not None and matchup.away_trend is not None:
        home_attack = _first_number(
            matchup.home_trend.xg_for_per_match,
            matchup.home_trend.goals_for_per_match,
        )
        away_defense = _first_number(
            matchup.away_trend.xg_against_per_match,
            matchup.away_trend.goals_against_per_match,
        )
        away_attack = _first_number(
            matchup.away_trend.xg_for_per_match,
            matchup.away_trend.goals_for_per_match,
        )
        home_defense = _first_number(
            matchup.home_trend.xg_against_per_match,
            matchup.home_trend.goals_against_per_match,
        )
        if (
            home_attack is not None
            and away_defense is not None
            and away_attack is not None
            and home_defense is not None
        ):
            return ExpectedGoals(
                home=round((home_attack + away_defense) / 2 * _HOME_ADVANTAGE, 2),
                away=round((away_attack + home_defense) / 2 / _HOME_ADVANTAGE, 2),
                source='recent-xg-matchup',
            )

    home_season = _season_xg_per_match(snapshot.home)
    away_season = _season_xg_per_match(snapshot.away)
    if home_season is not None and away_season is not None:
        return ExpectedGoals(
            home=round(home_season * 1.08, 2),
            away=round(away_season * 0.92, 2),
            source='season-xg-per-match',
        )

    raise ValueError('snapshot does not contain enough xG or goal trend data for pricing')


def _season_xg_per_match(team) -> float | None:
    metrics = team.season_metrics
    if metrics is None or metrics.matches in (None, 0):
        return None
    xg = _first_number(metrics.xg, metrics.goals)
    if xg is None:
        return None
    return xg / metrics.matches


def _first_number(*values: float | None) -> float | None:
    for value in values:
        if value is not None:
            return float(value)
    return None


def _bounded_goal_rate(value: float) -> float:
    return round(max(0.2, min(float(value), 4.0)), 3)


def _poisson_masses(rate: float, max_goals: int) -> list[float]:
    return [
        exp(-rate) * (rate ** goals) / factorial(goals)
        for goals in range(max_goals + 1)
    ]


def _round_and_normalize(values: dict[str, float]) -> dict[str, float]:
    rounded = {key: round(value, 6) for key, value in values.items()}
    delta = round(1.0 - sum(rounded.values()), 6)
    if delta:
        strongest = max(rounded, key=rounded.get)
        rounded[strongest] = round(rounded[strongest] + delta, 6)
    return rounded


def _normalize_bucket_map(values: dict[str, float]) -> dict[str, float]:
    """Round a probability map to 6 dp and absorb the rounding delta.

    Unlike `_round_and_normalize`, this keeps insertion order (useful for the
    score grid) and tolerates many small buckets.
    """
    if not values:
        return {}
    rounded = {key: round(value, 6) for key, value in values.items()}
    delta = round(1.0 - sum(rounded.values()), 6)
    if delta:
        strongest = max(rounded, key=rounded.get)
        rounded[strongest] = round(rounded[strongest] + delta, 6)
    return rounded


def _handicap_key(line: int) -> str:
    if line == 0:
        return 'handicap_home_0'
    sign = 'minus' if line < 0 else 'plus'
    return f'handicap_home_{sign}_{abs(line)}'
