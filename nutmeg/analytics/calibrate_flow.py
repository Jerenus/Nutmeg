"""CalibrateService: rebuild the analytical projections and read back the scorecards.

calibrate is read-only over SQLite and writes only DuckDB. It registers the
forecast_scores and forecast_scorecards projectors, builds them at the frozen
high-watermark (keep-last-good on failure), and returns the scorecard names and
count. Factor learning and regime projectors join this registration in Package 4B.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine

from nutmeg.analytics.factor_projection import (
    FactorContributionsProjector,
    FactorEstimatesProjector,
)
from nutmeg.analytics.forecast_projection import ForecastScoresProjector
from nutmeg.analytics.integrity_action import IntegrityActionScorecardProjector
from nutmeg.analytics.lifecycle import FactorLifecycleProjector
from nutmeg.analytics.regime import RegimePostmatchProjector, RegimeVectorProjector
from nutmeg.analytics.scorecards import ForecastScorecardProjector
from nutmeg.analytics.substrate import AnalyticsProjectionBuilder, projection_counts
from nutmeg.storage.duckdb_utils import connect_analytics_db


@dataclass(frozen=True, slots=True)
class CalibrateRequest:
    as_of: str
    built_at: str
    high_watermark: int | None = None


@dataclass(frozen=True, slots=True)
class CalibrateResult:
    run_id: str
    status: str
    high_watermark: int
    scorecards: tuple[str, ...]
    scorecard_count: int
    factor_estimate_count: int
    lifecycle_proposal_count: int
    regime_vector_count: int


class CalibrateService:
    def __init__(self, engine: Engine, analytics_path: Path) -> None:
        self._engine = engine
        self._path = analytics_path

    def build(self, request: CalibrateRequest) -> CalibrateResult:
        builder = AnalyticsProjectionBuilder(self._engine, self._path)
        result = builder.build(
            [
                ('forecast_scores', 'fs-v1', ForecastScoresProjector(self._engine).project),
                ('forecast_scorecards', 'sc-v1', ForecastScorecardProjector(self._engine).project),
                ('factor_score_contributions', 'fc-v1',
                 FactorContributionsProjector(self._engine).project),
                ('factor_estimates', 'fe-v1', FactorEstimatesProjector(self._engine).project),
                ('factor_lifecycle_proposals', 'lc-v1',
                 FactorLifecycleProjector(self._engine).project),
                ('integrity_action_scorecards', 'ia-v1',
                 IntegrityActionScorecardProjector(self._engine).project),
                ('regime_vectors', 'rv-v1', RegimeVectorProjector(self._engine).project),
                ('regime_postmatch_labels', 'rp-v1',
                 RegimePostmatchProjector(self._engine).project),
            ],
            built_at=request.built_at,
            high_watermark=request.high_watermark,
        )
        names: tuple[str, ...] = ()
        count = 0
        with connect_analytics_db(self._path) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    'SELECT table_name FROM information_schema.tables'
                ).fetchall()
            }
            if 'forecast_scorecards' in tables:
                names = tuple(
                    row[0]
                    for row in connection.execute(
                        'SELECT DISTINCT scorecard FROM forecast_scorecards ORDER BY scorecard'
                    ).fetchall()
                )
                count = int(
                    connection.execute(
                        'SELECT count(*) FROM forecast_scorecards'
                    ).fetchone()[0]
                )
        counts = projection_counts(self._path)
        return CalibrateResult(
            run_id=result.run_id,
            status=result.status,
            high_watermark=result.high_watermark,
            scorecards=names,
            scorecard_count=count,
            factor_estimate_count=counts['factor_estimate_count'],
            lifecycle_proposal_count=counts['lifecycle_proposal_count'],
            regime_vector_count=counts['regime_vector_count'],
        )
