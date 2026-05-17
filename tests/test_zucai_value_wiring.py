from __future__ import annotations

from nutmeg.config.settings import AppSettings
from nutmeg.services.zucai_value_bridge import ZucaiValueBridge
from nutmeg.services.zucai_value_wiring import build_zucai_value_bridge


def _settings(**overrides) -> AppSettings:
    return AppSettings(**overrides)


def test_wiring_returns_none_without_api_key() -> None:
    bridge = build_zucai_value_bridge(
        settings=_settings(api_football_key=""),
        run_date="2026-05-17",
        value_service_factory=lambda: object(),  # never called
    )
    assert bridge is None


def test_wiring_returns_none_without_value_factory() -> None:
    bridge = build_zucai_value_bridge(
        settings=_settings(api_football_key="abc123"),
        run_date="2026-05-17",
        value_service_factory=None,
    )
    assert bridge is None


def test_wiring_builds_bridge_with_key_and_factory() -> None:
    sentinel_value_service = object()
    bridge = build_zucai_value_bridge(
        settings=_settings(api_football_key="abc123"),
        run_date="2026-05-17",
        value_service_factory=lambda: sentinel_value_service,
    )
    assert isinstance(bridge, ZucaiValueBridge)


def test_wiring_degrades_to_none_on_factory_failure() -> None:
    def _boom():
        raise RuntimeError("db down")

    bridge = build_zucai_value_bridge(
        settings=_settings(api_football_key="abc123"),
        run_date="2026-05-17",
        value_service_factory=_boom,
    )
    assert bridge is None
