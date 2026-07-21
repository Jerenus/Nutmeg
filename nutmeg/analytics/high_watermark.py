"""SQLite high-watermark: the frozen input version a projection build reads from.

The ``actions`` log is append-only, so SQLite's implicit ``rowid`` is a monotone
sequence of committed writes. A build stamps its projections with this watermark;
rebuilding at the same watermark reproduces byte-identical projection rows.
"""
from __future__ import annotations

from sqlalchemy import Engine, text


def high_watermark(engine: Engine) -> int:
    with engine.connect() as connection:
        value = connection.execute(text('SELECT max(rowid) FROM actions')).scalar_one_or_none()
    return int(value) if value is not None else 0
