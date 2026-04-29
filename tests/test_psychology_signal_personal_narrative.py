from __future__ import annotations
from unittest.mock import MagicMock
from nutmeg.services.psychology.llm import FakeLLMCompleter
from nutmeg.services.psychology.signals.base import SignalContext
from nutmeg.services.psychology.signals.personal_narrative import PersonalNarrativeSignal

def _ctx(fixtures: list[dict]) -> SignalContext:
    return SignalContext(date="2026-04-29", fixtures=fixtures, snapshots={}, odds={})

def test_story_present_and_advantage_emits_reading() -> None:
    rss = MagicMock(); rss.fetch.return_value = [{"title": "Kompany 拜仁欧冠首秀", "link": "u"}]
    sig = PersonalNarrativeSignal(rss=rss, llm=FakeLLMCompleter(responses=['{"story_present":true,"team_advantaged":"away","conviction":0.55,"story_summary":"Kompany debut narrative"}']))
    [r] = sig.evaluate(_ctx([{"id":"f1","home_team_name":"PSG","away_team_name":"Bayern"}]))
    assert r.outcome_view == "away_win"
    assert r.conviction == 0.55

def test_no_story_abstains() -> None:
    rss = MagicMock(); rss.fetch.return_value = [{"title":"random","link":""}]
    sig = PersonalNarrativeSignal(rss=rss, llm=FakeLLMCompleter(responses=['{"story_present":false,"team_advantaged":"none","conviction":0.0,"story_summary":""}']))
    [r] = sig.evaluate(_ctx([{"id":"f1","home_team_name":"A","away_team_name":"B"}]))
    assert r.outcome_view is None

def test_empty_rss_results_abstain_without_llm() -> None:
    rss = MagicMock(); rss.fetch.return_value = []
    sig = PersonalNarrativeSignal(rss=rss, llm=FakeLLMCompleter(responses=[]))
    [r] = sig.evaluate(_ctx([{"id":"f1","home_team_name":"A","away_team_name":"B"}]))
    assert r.outcome_view is None
    assert "no rss" in (r.abstain_reason or "").lower()

def test_llm_failure_abstains() -> None:
    rss = MagicMock(); rss.fetch.return_value = [{"title":"x","link":""}]
    sig = PersonalNarrativeSignal(rss=rss, llm=FakeLLMCompleter(responses=["not json"]))
    [r] = sig.evaluate(_ctx([{"id":"f1","home_team_name":"A","away_team_name":"B"}]))
    assert r.outcome_view is None
