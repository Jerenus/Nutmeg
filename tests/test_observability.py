from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.observability import langsmith as langsmith_module
from nutmeg.observability.langsmith import traced_operation


class FakeClient:
    def __init__(self, api_key: str | None) -> None:
        self.api_key = api_key
        self.flushed = False

    def flush(self) -> None:
        self.flushed = True


class FakeTrace:
    def __init__(self, sink: dict[str, object], **kwargs: object) -> None:
        self._sink = sink
        self._kwargs = kwargs

    def __enter__(self):
        self._sink.update(self._kwargs)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class FakeTracingContext:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def _settings() -> AppSettings:
    return AppSettings(
        langsmith_enabled=True,
        LANGSMITH_API_KEY='test-key',
        langsmith_project='nutmeg-test',
    )


def test_traced_operation_metadata_keeps_internal_user_id(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(langsmith_module, 'Client', FakeClient)
    monkeypatch.setattr(
        langsmith_module,
        'trace',
        lambda name, **kwargs: FakeTrace(captured, name=name, **kwargs),
    )
    monkeypatch.setattr(
        langsmith_module,
        'tracing_context',
        lambda **kwargs: FakeTracingContext(**kwargs),
    )

    with traced_operation(
        _settings(),
        operation_name='cli.test',
        user_id='owner',
        metadata={'user_id': 'spoofed', 'fixture_id': 'epl-001'},
    ):
        pass

    metadata = captured['metadata']
    assert isinstance(metadata, dict)
    assert metadata['user_id'] == 'owner'
    assert metadata['fixture_id'] == 'epl-001'


def test_traced_operation_metadata_is_json_safe(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(langsmith_module, 'Client', FakeClient)
    monkeypatch.setattr(
        langsmith_module,
        'trace',
        lambda name, **kwargs: FakeTrace(captured, name=name, **kwargs),
    )
    monkeypatch.setattr(
        langsmith_module,
        'tracing_context',
        lambda **kwargs: FakeTracingContext(**kwargs),
    )

    with traced_operation(
        _settings(),
        operation_name='cli.test',
        user_id='owner',
        metadata={
            'when': datetime(2026, 4, 25, 12, 0, tzinfo=UTC),
            'path': Path('.nutmeg-data'),
            'nested': {'fixture': Path('epl-001')},
        },
    ):
        pass

    metadata = captured['metadata']
    assert isinstance(metadata, dict)
    assert metadata['when'] == '2026-04-25T12:00:00+00:00'
    assert metadata['path'] == '.nutmeg-data'
    assert metadata['nested'] == {'fixture': 'epl-001'}
