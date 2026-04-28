from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from nutmeg.domain.evals import PredictionReviewSummary
from nutmeg.models.scoring import brier_score_three_way
from nutmeg.storage.state_models import PredictionRecord


class PredictionNotFoundError(LookupError):
    pass


class SqlAlchemyPredictionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def record_prediction(
        self,
        *,
        user_id: str,
        fixture_id: str,
        league: str,
        home_team: str,
        away_team: str,
        probabilities: dict[str, float],
        picked_outcome: str,
        notes: str | None = None,
        created_at: datetime | None = None,
    ) -> int:
        brier_score_three_way(probabilities, actual_outcome=picked_outcome)
        record = PredictionRecord(
            user_id=user_id,
            fixture_id=fixture_id,
            league=league,
            home_team=home_team,
            away_team=away_team,
            home_probability=float(probabilities['home']),
            draw_probability=float(probabilities['draw']),
            away_probability=float(probabilities['away']),
            picked_outcome=picked_outcome,
            actual_outcome=None,
            notes=notes,
            created_at=created_at or datetime.now(UTC),
            resolved_at=None,
        )
        self._session.add(record)
        self._session.commit()
        return int(record.id)

    def record_outcome(
        self,
        *,
        prediction_id: int,
        actual_outcome: str,
        resolved_at: datetime | None = None,
    ) -> None:
        record = self._session.get(PredictionRecord, prediction_id)
        if record is None:
            raise PredictionNotFoundError(f'Prediction `{prediction_id}` was not found.')
        brier_score_three_way(_probabilities(record), actual_outcome=actual_outcome)
        record.actual_outcome = actual_outcome
        record.resolved_at = resolved_at or datetime.now(UTC)
        self._session.commit()

    def review(self, *, user_id: str) -> PredictionReviewSummary:
        records = (
            self._session.query(PredictionRecord)
            .filter(PredictionRecord.user_id == user_id)
            .order_by(PredictionRecord.created_at.asc())
            .all()
        )
        resolved = [record for record in records if record.actual_outcome is not None]
        scores = [
            brier_score_three_way(
                _probabilities(record),
                actual_outcome=str(record.actual_outcome),
            )
            for record in resolved
        ]
        correct = [
            record
            for record in resolved
            if record.picked_outcome == record.actual_outcome
        ]
        return PredictionReviewSummary(
            total_predictions=len(records),
            resolved_predictions=len(resolved),
            average_brier_score=round(sum(scores) / len(scores), 6) if scores else None,
            pick_accuracy=round(len(correct) / len(resolved), 6) if resolved else None,
        )


def _probabilities(record: PredictionRecord) -> dict[str, float]:
    return {
        'home': float(record.home_probability),
        'draw': float(record.draw_probability),
        'away': float(record.away_probability),
    }

