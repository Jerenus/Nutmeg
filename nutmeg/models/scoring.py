from __future__ import annotations

MATCH_WINNER_OUTCOMES: tuple[str, ...] = ('home', 'draw', 'away')


def brier_score_three_way(probabilities: dict[str, float], *, actual_outcome: str) -> float:
    missing = [outcome for outcome in MATCH_WINNER_OUTCOMES if outcome not in probabilities]
    if missing:
        raise ValueError(f'missing probability outcomes: {", ".join(missing)}')
    if actual_outcome not in MATCH_WINNER_OUTCOMES:
        raise ValueError('actual_outcome must be one of home, draw, away')
    total = sum(float(probabilities[outcome]) for outcome in MATCH_WINNER_OUTCOMES)
    if abs(total - 1.0) > 0.000001:
        raise ValueError('match-winner probabilities must sum to 1')
    score = sum(
        (
            float(probabilities[outcome])
            - (1.0 if outcome == actual_outcome else 0.0)
        )
        ** 2
        for outcome in MATCH_WINNER_OUTCOMES
    )
    return round(score, 6)

