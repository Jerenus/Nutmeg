from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from nutmeg.storage.prediction_repository import SqlAlchemyPredictionRepository
from nutmeg.storage.state_models import Base


def test_prediction_repository_records_outcomes_and_review_summary() -> None:
    engine = create_engine('sqlite:///:memory:', future=True)
    Base.metadata.create_all(engine)
    session = Session(engine)
    repository = SqlAlchemyPredictionRepository(session)

    prediction_id = repository.record_prediction(
        user_id='owner',
        fixture_id='fx-1',
        league='epl',
        home_team='Arsenal',
        away_team='Tottenham Hotspur',
        probabilities={'home': 0.60, 'draw': 0.25, 'away': 0.15},
        picked_outcome='home',
        notes='value-board',
        created_at=datetime(2026, 4, 25, 10, 0, tzinfo=UTC),
    )
    repository.record_outcome(
        prediction_id=prediction_id,
        actual_outcome='home',
        resolved_at=datetime(2026, 4, 26, 18, 0, tzinfo=UTC),
    )

    summary = repository.review(user_id='owner')

    assert summary.total_predictions == 1
    assert summary.resolved_predictions == 1
    assert summary.average_brier_score == 0.245
    assert summary.pick_accuracy == 1.0

