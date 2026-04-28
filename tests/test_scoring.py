from __future__ import annotations

import pytest

from nutmeg.models.scoring import brier_score_three_way


def test_brier_score_three_way_scores_probability_against_actual_outcome() -> None:
    score = brier_score_three_way(
        {'home': 0.60, 'draw': 0.25, 'away': 0.15},
        actual_outcome='home',
    )

    assert score == 0.245


def test_brier_score_three_way_rejects_non_normalized_probabilities() -> None:
    with pytest.raises(ValueError, match='sum to 1'):
        brier_score_three_way({'home': 0.7, 'draw': 0.2, 'away': 0.2}, actual_outcome='home')

