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

from nutmeg.analytics.forecast_projection import ForecastScoresProjector
from nutmeg.analytics.scorecards import ForecastScorecardProjector
from nutmeg.analytics.substrate import AnalyticsProjectionBuilder
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
        return CalibrateResult(
            run_id=result.run_id,
            status=result.status,
            high_watermark=result.high_watermark,
            scorecards=names,
            scorecard_count=count,
        )
