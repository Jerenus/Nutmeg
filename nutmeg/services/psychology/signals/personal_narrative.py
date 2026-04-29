from __future__ import annotations

import json
from dataclasses import dataclass

from nutmeg.services.psychology.llm import LLMCompleter, LLMCompletionError
from nutmeg.services.psychology.schemas import SignalReading
from nutmeg.services.psychology.signals.base import SignalContext
from nutmeg.services.psychology.sources.rss_provider import RssProvider

STORY_KEYWORDS = ["复仇", "首秀", "末战", "回归", "重逢", "里程碑"]
SYSTEM_PROMPT = (
    "Return JSON with story_present, team_advantaged home|away|none, conviction, story_summary."
)


@dataclass(slots=True)
class PersonalNarrativeSignal:
    rss: RssProvider
    llm: LLMCompleter
    name: str = "personal_narrative"

    def evaluate(self, ctx: SignalContext) -> list[SignalReading]:
        out: list[SignalReading] = []
        for fx in ctx.fixtures:
            fixture_id = str(fx.get("id"))
            home = str(fx.get("home_team_name") or "")
            away = str(fx.get("away_team_name") or "")
            items = self.rss.fetch(date=ctx.date, query=home) or []
            items += self.rss.fetch(date=ctx.date, query=away) or []
            for kw in STORY_KEYWORDS:
                items += self.rss.fetch(date=ctx.date, query=kw) or []
            if not items:
                out.append(self._abstain(fixture_id, "no RSS items"))
                continue
            headlines = "\n".join(f"- {it.get('title', '')}" for it in items[:30])
            user = f"Home: {home}\nAway: {away}\nHeadlines:\n{headlines}"
            try:
                payload = json.loads(self.llm.complete(system=SYSTEM_PROMPT, user=user))
                story_present = bool(payload.get("story_present"))
                team = str(payload.get("team_advantaged"))
                conviction = float(payload.get("conviction", 0.0))
                summary = str(payload.get("story_summary", ""))
            except (LLMCompletionError, ValueError, TypeError, json.JSONDecodeError):
                out.append(self._abstain(fixture_id, "llm parse failed"))
                continue
            if not story_present or team not in {"home", "away"}:
                out.append(self._abstain(fixture_id, "no actionable story"))
                continue
            outcome = "home_win" if team == "home" else "away_win"
            out.append(
                SignalReading(
                    self.name,
                    fixture_id,
                    "HHAD",
                    outcome,
                    max(0.0, min(conviction, 0.7)),
                    [summary] if summary else ["personal narrative present"],
                    [str(it.get("link") or "") for it in items[:5]],
                    None,
                )
            )
        return out

    def _abstain(self, fixture_id: str, reason: str) -> SignalReading:
        return SignalReading(self.name, fixture_id, "HHAD", None, 0.0, [], [], reason)
