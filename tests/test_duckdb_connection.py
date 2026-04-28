from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.storage.bootstrap import create_analytics_schema


def test_create_analytics_schema_waits_for_existing_duckdb_connection_lock(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / 'data'
    db_path = data_dir / 'analytics' / 'analytics.duckdb'
    held_path = tmp_path / 'held.txt'

    child_script = f"""
from pathlib import Path
import time

from nutmeg.storage.duckdb_utils import connect_analytics_db

db_path = Path({str(db_path)!r})
held_path = Path({str(held_path)!r})

with connect_analytics_db(db_path):
    held_path.write_text('held', encoding='utf-8')
    time.sleep(0.35)
"""
    process = subprocess.Popen([sys.executable, '-c', child_script])
    try:
        deadline = time.monotonic() + 3
        while not held_path.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert held_path.exists()

        started_at = time.monotonic()
        create_analytics_schema(AppSettings(data_dir=data_dir))

        assert time.monotonic() - started_at >= 0.2
    finally:
        process.wait(timeout=3)
        assert process.returncode == 0
