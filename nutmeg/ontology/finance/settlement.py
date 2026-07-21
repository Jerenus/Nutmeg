"""Pure settlement grading.

The 90-minute score maps to a home/draw/away result; a had leg wins when its
selection key matches that result. hhad/ttg/crs grading is a documented follow-on
within Package 3B — the had representative is graded here.
"""
from __future__ import annotations

from nutmeg.ontology.finance.models import SettlementGrade


def _result_key(home_score: int, away_score: int) -> str:
    if home_score > away_score:
        return 'home'
    if home_score < away_score:
        return 'away'
    return 'draw'


def grade_had(selection_outcome_key: str, home_score: int, away_score: int) -> SettlementGrade:
    result = _result_key(home_score, away_score)
    return SettlementGrade.WIN if selection_outcome_key == result else SettlementGrade.LOSS
