from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterator

from nutmeg.config.settings import AppSettings

try:
    from langsmith import Client, trace
    from langsmith.run_helpers import tracing_context
except ImportError:  # pragma: no cover - import guarded by package dependency.
    Client = None
    trace = None
    tracing_context = None


def _json_safe_metadata(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe_metadata(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_json_safe_metadata(item) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


@dataclass(slots=True, frozen=True)
class TraceContext:
    enabled: bool
    project: str
    user_id: str
    tags: list[str]


def build_trace_context(settings: AppSettings, user_id: str) -> TraceContext:
    return TraceContext(
        enabled=settings.langsmith_enabled and bool(settings.langsmith_api_key),
        project=settings.langsmith_project,
        user_id=user_id,
        tags=[settings.app_env, user_id],
    )


@contextmanager
def traced_operation(
    settings: AppSettings,
    *,
    operation_name: str,
    user_id: str,
    tags: list[str] | None = None,
    metadata: dict[str, object] | None = None,
) -> Iterator[None]:
    trace_context = build_trace_context(settings, user_id)
    if not trace_context.enabled or Client is None or trace is None or tracing_context is None:
        with nullcontext():
            yield
        return

    previous_tracing = os.environ.get('LANGSMITH_TRACING')
    previous_api_key = os.environ.get('LANGSMITH_API_KEY')
    os.environ['LANGSMITH_TRACING'] = 'true'
    os.environ['LANGSMITH_API_KEY'] = settings.langsmith_api_key or ''
    client = Client(api_key=settings.langsmith_api_key)
    active_tags = trace_context.tags + (tags or [])
    active_metadata = {**_json_safe_metadata(metadata or {}), 'user_id': user_id}
    try:
        with tracing_context(enabled=True):
            with trace(
                operation_name,
                project_name=settings.langsmith_project,
                client=client,
                tags=active_tags,
                metadata=active_metadata,
            ):
                yield
    finally:
        client.flush()
        if previous_tracing is None:
            os.environ.pop('LANGSMITH_TRACING', None)
        else:
            os.environ['LANGSMITH_TRACING'] = previous_tracing
        if previous_api_key is None:
            os.environ.pop('LANGSMITH_API_KEY', None)
        else:
            os.environ['LANGSMITH_API_KEY'] = previous_api_key
