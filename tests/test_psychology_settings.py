from __future__ import annotations

from nutmeg.config.settings import AppSettings


def test_default_psychology_layer_disabled(monkeypatch) -> None:
    monkeypatch.delenv("NUTMEG_PSYCHOLOGY_LAYER_ENABLED", raising=False)
    s = AppSettings()
    assert s.psychology_layer_enabled is False


def test_conviction_threshold_default(monkeypatch) -> None:
    monkeypatch.delenv("NUTMEG_PSYCHOLOGY_CONVICTION_THRESHOLD", raising=False)
    s = AppSettings()
    assert s.psychology_conviction_threshold == 0.7


def test_provider_enabled_csv(monkeypatch) -> None:
    monkeypatch.setenv("NUTMEG_PSYCHOLOGY_PROVIDER_ENABLED", "tournament_stage,reflexive_tactic")
    s = AppSettings()
    assert s.psychology_provider_enabled == ["tournament_stage", "reflexive_tactic"]
