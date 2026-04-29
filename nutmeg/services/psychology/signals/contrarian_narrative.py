from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from nutmeg.services.psychology.llm import LLMCompleter, LLMCompletionError
from nutmeg.services.psychology.schemas import SignalReading
from nutmeg.services.psychology.signals.base import SignalContext
from nutmeg.services.psychology.sources.rss_provider import RssProvider
from nutmeg.services.psychology.sources.zhilio_provider import ZhilioProvider

MIN_SAMPLE = 5
INTENSITY_GATE = 0.6
CONVICTION_CAP = 0.75
SYSTEM_PROMPT = "Return JSON with consensus home|away|draw|mixed and intensity 0..1."


def _opposite(consensus: str) -> str | None:
    if consensus == "home":
        return "away_win"
    if consensus == "away":
        return "home_win"
    return None


@dataclass(slots=True)
class ContrarianNarrativeSignal:
    zhilio: ZhilioProvider
    rss: RssProvider
    llm: LLMCompleter
    name: str = "contrarian_narrative"

    def evaluate(self, ctx: SignalContext) -> list[SignalReading]:
        out: list[SignalReading] = []
        for fx in ctx.fixtures:
            fixture_id = str(fx.get("id"))
            query = f"{fx.get('home_team_name') or ''} {fx.get('away_team_name') or ''}".strip()
            items: list[dict[str, Any]] = []
            items.extend(self.zhilio.search_news(query=query, date=ctx.date) or [])
            items.extend(self.zhilio.hotlist(date=ctx.date) or [])
            items.extend(self.rss.fetch(date=ctx.date, query=query) or [])
            if len(items) < MIN_SAMPLE:
                out.append(self._abstain(fixture_id, "insufficient sample"))
                continue
            user_prompt = "\n".join(f"- {it.get('title', '')}" for it in items[:25])
            try:
                payload = json.loads(self.llm.complete(system=SYSTEM_PROMPT, user=user_prompt))
                consensus = str(payload.get("consensus"))
                intensity = float(payload.get("intensity", 0.0))
            except (LLMCompletionError, ValueError, TypeError, json.JSONDecodeError):
                out.append(self._abstain(fixture_id, "llm parse failed"))
                continue
            if intensity < INTENSITY_GATE or consensus not in {"home", "away"}:
                out.append(self._abstain(fixture_id, f"intensity below gate ({intensity:.2f})"))
                continue
            contrarian = _opposite(consensus)
            if contrarian is None:
                out.append(self._abstain(fixture_id, "no contrarian outcome"))
                continue
            out.append(
                SignalReading(
                    self.name,
                    fixture_id,
                    "HHAD",
                    contrarian,
                    min(intensity, CONVICTION_CAP),
                    [f"Public consensus leans {consensus} at intensity {intensity:.2f}"],
                    [str(it.get("link") or it.get("url") or "") for it in items[:5]],
                    None,
                )
            )
        return out

    def _abstain(self, fixture_id: str, reason: str) -> SignalReading:
        return SignalReading(self.name, fixture_id, "HHAD", None, 0.0, [], [], reason)
