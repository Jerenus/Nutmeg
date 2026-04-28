from __future__ import annotations


def implied_probability(decimal_odds: float) -> float:
    if decimal_odds <= 1:
        raise ValueError('decimal odds must be greater than 1')
    return 1.0 / decimal_odds


def no_vig_probabilities(decimal_odds: list[float]) -> list[float]:
    raw = [implied_probability(odds) for odds in decimal_odds]
    total = sum(raw)
    if total <= 0:
        raise ValueError('probability total must be positive')
    return [value / total for value in raw]


def fair_odds(probability: float) -> float:
    if not 0 < probability < 1:
        raise ValueError('probability must be between 0 and 1')
    return round(1.0 / probability, 3)


def quarter_kelly_fraction(true_probability: float, decimal_odds: float) -> float:
    if not 0 < true_probability < 1:
        raise ValueError('true probability must be between 0 and 1')
    if decimal_odds <= 1:
        raise ValueError('decimal odds must be greater than 1')
    edge = (decimal_odds - 1) * true_probability - (1 - true_probability)
    full_kelly = edge / (decimal_odds - 1)
    return max(full_kelly, 0.0) / 4.0
