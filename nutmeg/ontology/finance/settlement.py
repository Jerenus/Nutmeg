"""Single-market settlement grading used by the kernel reconcile path."""

from __future__ import annotations

from nutmeg.decision.faces import FACE_OF
from nutmeg.decision.match_results import outcome_90
from nutmeg.ontology.finance.models import SettlementGrade


def _had_result_code(home_score: int, away_score: int) -> str:
    return FACE_OF[outcome_90(home_score, away_score)]


def grade_had(
    selection_outcome_key: str,
    home_score: int,
    away_score: int,
) -> SettlementGrade:
    """Grade a 90-minute had (win/draw/loss) selection against the final score."""
    result = _had_result_code(home_score, away_score)
    return (
        SettlementGrade.WIN
        if selection_outcome_key == result
        else SettlementGrade.LOSS
    )


__all__ = ["grade_had"]
