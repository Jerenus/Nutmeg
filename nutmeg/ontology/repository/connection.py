"""SQLite engine construction and connection policy for the ontology kernel.

Every connection to the operational database enables foreign keys, a bounded
busy timeout and WAL journalling, so the single-writer Unit of Work stays
correct under concurrent readers without the caller having to remember to set
pragmas.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event


def _apply_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute('PRAGMA foreign_keys=ON')
        cursor.execute('PRAGMA busy_timeout=5000')
        cursor.execute('PRAGMA journal_mode=WAL')
    finally:
        cursor.close()


def build_ontology_engine(database_path: Path | str) -> Engine:
    database_path = Path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f'sqlite+pysqlite:///{database_path.resolve()}',
        future=True,
        connect_args={'check_same_thread': False},
    )
    event.listen(engine, 'connect', _apply_sqlite_pragmas)
    return engine
