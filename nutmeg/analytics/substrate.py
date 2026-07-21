"""DuckDB projection substrate: re-computable analytics, never business truth.

A build freezes the SQLite high-watermark, runs each registered projector *in memory*
first, then writes all projection rows in one DuckDB transaction that replaces the
prior rows for that ``projection_version``. Every row carries the six provenance
columns. If any projector raises, the build records a ``failed`` run and touches no
projection rows — the last good projection stays intact. Nothing reads the wall clock:
``built_at`` is passed in, so rebuilding at the same watermark reproduces the rows.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine

from nutmeg.analytics.high_watermark import high_watermark as read_high_watermark
from nutmeg.storage.duckdb_utils import connect_analytics_db

PROVENANCE_COLUMNS = (
    'projection_name',
    'projection_version',
    'source_high_watermark',
    'built_at',
    'cohort_definition_version',
    'metric_version',
)

_PROVENANCE_TYPES = {
    'projection_name': 'VARCHAR',
    'projection_version': 'VARCHAR',
    'source_high_watermark': 'BIGINT',
    'built_at': 'VARCHAR',
    'cohort_definition_version': 'VARCHAR',
    'metric_version': 'VARCHAR',
}


_COUNTED_TABLES = {
    'projection_run_count': 'projection_runs',
    'scorecard_count': 'forecast_scorecards',
    'factor_estimate_count': 'factor_estimates',
    'regime_vector_count': 'regime_vectors',
    'lifecycle_proposal_count': 'factor_lifecycle_proposals',
}


def projection_counts(analytics_path: Path) -> dict[str, int]:
    """Projection counts keyed by status field; all 0 when analytics is absent.

    Read-only: never creates ``analytics.duckdb``. Missing tables count as 0.
    """
    counts = {key: 0 for key in _COUNTED_TABLES}
    if not analytics_path.exists():
        return counts
    with connect_analytics_db(analytics_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                'SELECT table_name FROM information_schema.tables'
            ).fetchall()
        }
        for key, table in _COUNTED_TABLES.items():
            if table in tables:
                counts[key] = int(
                    connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
                )
    return counts


def _infer_type(value: object) -> str:
    if isinstance(value, bool):
        return 'BOOLEAN'
    if isinstance(value, int):
        return 'BIGINT'
    if isinstance(value, float):
        return 'DOUBLE'
    return 'VARCHAR'


@dataclass(frozen=True, slots=True)
class ProjectionRunResult:
    run_id: str
    status: str
    high_watermark: int


class ProjectionContext:
    def __init__(
        self,
        projection_name: str,
        projection_version: str,
        source_high_watermark: int,
        built_at: str,
        cohort_definition_version: str,
        metric_version: str,
    ) -> None:
        self.projection_name = projection_name
        self.projection_version = projection_version
        self.source_high_watermark = source_high_watermark
        self.built_at = built_at
        self.cohort_definition_version = cohort_definition_version
        self.metric_version = metric_version
        self._writes: list[tuple[str, dict[str, str] | None, list[dict[str, object]]]] = []

    def write(
        self,
        table: str,
        rows: Sequence[dict[str, object]],
        column_types: dict[str, str] | None = None,
    ) -> None:
        self._writes.append((table, column_types, list(rows)))

    def provenance(self) -> dict[str, object]:
        return {
            'projection_name': self.projection_name,
            'projection_version': self.projection_version,
            'source_high_watermark': self.source_high_watermark,
            'built_at': self.built_at,
            'cohort_definition_version': self.cohort_definition_version,
            'metric_version': self.metric_version,
        }


Projector = tuple[str, str, Callable[[ProjectionContext], None]]


class AnalyticsProjectionBuilder:
    def __init__(
        self,
        engine: Engine,
        analytics_path: Path,
        cohort_definition_version: str = 'cohort-v1',
        metric_version: str = 'scoring-v1',
    ) -> None:
        self._engine = engine
        self._path = analytics_path
        self._cohort_definition_version = cohort_definition_version
        self._metric_version = metric_version

    def build(
        self,
        projectors: Sequence[Projector],
        built_at: str,
        high_watermark: int | None = None,
    ) -> ProjectionRunResult:
        watermark = (
            high_watermark if high_watermark is not None else read_high_watermark(self._engine)
        )
        run_id = f'{built_at}:{watermark}'
        contexts: list[tuple[str, str, ProjectionContext]] = []
        failure: tuple[str, str, Exception] | None = None
        for name, version, projector in projectors:
            context = ProjectionContext(
                name, version, watermark, built_at,
                self._cohort_definition_version, self._metric_version,
            )
            try:
                projector(context)
            except Exception as error:   # noqa: BLE001 — recorded as a failed run
                failure = (name, version, error)
                break
            contexts.append((name, version, context))

        with connect_analytics_db(self._path) as connection:
            self._ensure_runs_table(connection)
            if failure is not None:
                name, version, error = failure
                self._insert_run(
                    connection, run_id, name, version, watermark, 'failed', built_at, 0, str(error)
                )
                return ProjectionRunResult(run_id=run_id, status='failed', high_watermark=watermark)
            connection.execute('BEGIN')
            try:
                for name, version, context in contexts:
                    row_count = 0
                    provenance = context.provenance()
                    for table, column_types, rows in context._writes:
                        self._write_table(connection, table, column_types, rows, provenance)
                        row_count += len(rows)
                    self._insert_run(
                        connection, run_id, name, version, watermark,
                        'succeeded', built_at, row_count, None,
                    )
                connection.execute('COMMIT')
            except Exception:
                connection.execute('ROLLBACK')
                raise
        return ProjectionRunResult(run_id=run_id, status='succeeded', high_watermark=watermark)

    def _ensure_runs_table(self, connection) -> None:
        connection.execute(
            'CREATE TABLE IF NOT EXISTS projection_runs ('
            'run_id VARCHAR, projection_name VARCHAR, projection_version VARCHAR, '
            'source_high_watermark BIGINT, status VARCHAR, started_at VARCHAR, '
            'finished_at VARCHAR, row_count BIGINT, error VARCHAR)'
        )

    def _insert_run(
        self, connection, run_id, name, version, watermark, status, at, row_count, error
    ) -> None:
        connection.execute(
            'INSERT INTO projection_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            [run_id, name, version, watermark, status, at, at, row_count, error],
        )

    def _write_table(self, connection, table, column_types, rows, provenance) -> None:
        if column_types is not None:
            data_columns = list(column_types.keys())
            types = dict(column_types)
        elif rows:
            data_columns = list(rows[0].keys())
            types = {c: _infer_type(rows[0][c]) for c in data_columns}
        else:
            return   # nothing to create and nothing to write
        all_columns = data_columns + list(_PROVENANCE_TYPES.keys())
        column_defs = ', '.join(
            f'"{c}" {types.get(c) or _PROVENANCE_TYPES.get(c)}' for c in all_columns
        )
        connection.execute(f'CREATE TABLE IF NOT EXISTS "{table}" ({column_defs})')
        connection.execute(
            f'DELETE FROM "{table}" WHERE projection_version = ?',
            [provenance['projection_version']],
        )
        if not rows:
            return
        placeholders = ', '.join(['?'] * len(all_columns))
        params = [
            [row.get(c) for c in data_columns] + [provenance[c] for c in _PROVENANCE_TYPES]
            for row in rows
        ]
        connection.executemany(f'INSERT INTO "{table}" VALUES ({placeholders})', params)
