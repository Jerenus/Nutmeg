from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from nutmeg.config.settings import AppSettings
from nutmeg.storage.state_models import Base


def ensure_storage_paths(settings: AppSettings) -> None:
    for path in (settings.data_dir, settings.state_dir, settings.analytics_dir):
        Path(path).mkdir(parents=True, exist_ok=True)


def build_state_engine(settings: AppSettings) -> Engine:
    ensure_storage_paths(settings)
    return create_engine(settings.state_db_url, future=True)


def create_state_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)


