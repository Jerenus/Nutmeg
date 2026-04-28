from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Iterator

import duckdb


@contextlib.contextmanager
def connect_analytics_db(database_path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = database_path.with_suffix(f'{database_path.suffix}.lock')
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with lock_path.open('a+', encoding='utf-8') as handle:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except ImportError:
            # Non-POSIX platforms still get the direct DuckDB behavior.
            pass
        try:
            with duckdb.connect(str(database_path)) as connection:
                yield connection
        finally:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except (ImportError, NameError, UnboundLocalError):
                pass
