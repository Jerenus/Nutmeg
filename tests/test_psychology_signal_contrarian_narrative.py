from __future__ import annotations

from unittest.mock import MagicMock

from nutmeg.services.psychology.llm import FakeLLMCompleter
from nutmeg.services.psychology.signals.base import SignalContext
from nutmeg.services.psychology.signals.contrarian_narrative import ContrarianNarrativeSignal


def _fixture() -> dict:
    return {"id": "psg-bay", "home_team_name": "巴黎圣日耳曼", "away_team_name": "拜仁慕尼黑"}


def test_high_intensity_home_consensus_emits_away_lean() -> None:
    z = MagicMock()
    z.search_news.return_value = [{"title": f"PSG carry t{i}", "link": "u"} for i in range(6)]
    z.hotlist.return_value = []
    r = MagicMock()
    r.fetch.return_value = []
    sig = ContrarianNarrativeSignal(
        zhilio=z, rss=r, llm=FakeLLMCompleter(responses=['{"consensus": "home", "intensity": 0.8}'])
    )
    [reading] = sig.evaluate(
        SignalContext(date="2026-04-29", fixtures=[_fixture()], snapshots={}, odds={})
    )
    assert reading.outcome_view == "away_win"
    assert 0.75 >= reading.conviction >= 0.6


def test_low_intensity_yields_abstain() -> None:
    z = MagicMock()
    z.search_news.return_value = [{"title": f"a{i}", "link": "u"} for i in range(6)]
    z.hotlist.return_value = []
    r = MagicMock()
    r.fetch.return_value = []
    sig = ContrarianNarrativeSignal(
        zhilio=z, rss=r, llm=FakeLLMCompleter(responses=['{"consensus": "home", "intensity": 0.4}'])
    )
    [reading] = sig.evaluate(
        SignalContext(date="2026-04-29", fixtures=[_fixture()], snapshots={}, odds={})
    )
    assert reading.outcome_view is None
    assert "intensity" in (reading.abstain_reason or "")


def test_insufficient_sample_yields_abstain() -> None:
    z = MagicMock()
    z.search_news.return_value = [{"title": "x", "link": "u"}]
    z.hotlist.return_value = []
    r = MagicMock()
    r.fetch.return_value = []
    sig = ContrarianNarrativeSignal(zhilio=z, rss=r, llm=FakeLLMCompleter(responses=[]))
    [reading] = sig.evaluate(
        SignalContext(date="2026-04-29", fixtures=[_fixture()], snapshots={}, odds={})
    )
    assert reading.outcome_view is None
    assert "sample" in (reading.abstain_reason or "")


def test_llm_invalid_json_abstains() -> None:
    z = MagicMock()
    z.search_news.return_value = [{"title": "x", "link": "u"}] * 6
    z.hotlist.return_value = []
    r = MagicMock()
    r.fetch.return_value = []
    sig = ContrarianNarrativeSignal(zhilio=z, rss=r, llm=FakeLLMCompleter(responses=["not json"]))
    [reading] = sig.evaluate(
        SignalContext(date="2026-04-29", fixtures=[_fixture()], snapshots={}, odds={})
    )
    assert reading.outcome_view is None
    assert "parse" in (reading.abstain_reason or "")
