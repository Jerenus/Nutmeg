from __future__ import annotations

import json
from dataclasses import dataclass

from nutmeg.services.psychology.llm import LLMCompleter, LLMCompletionError
from nutmeg.services.psychology.schemas import SignalReading
from nutmeg.services.psychology.signals.base import SignalContext

VALID_PICKS = {"home_win", "draw", "away_win"}
SYSTEM_PROMPT = 'Return JSON with second_order_pick home_win|draw|away_win, conviction, reasoning.'


@dataclass(slots=True)
class ReflexiveTacticSignal:
    llm: LLMCompleter
    name: str = "reflexive_tactic"

    def evaluate(self, ctx: SignalContext) -> list[SignalReading]:
        out: list[SignalReading] = []
        for fx in ctx.fixtures:
            fixture_id = str(fx.get("id"))
            snap = ctx.snapshots.get(fixture_id)
            if not snap:
                out.append(self._abstain(fixture_id, "no tactical snapshot")); continue
            user = f"Home: {fx.get('home_team_name', '')}, shape={snap.get('home_shape', '')}\nAway: {fx.get('away_team_name', '')}, shape={snap.get('away_shape', '')}"
            try:
                payload = json.loads(self.llm.complete(system=SYSTEM_PROMPT, user=user))
                pick = str(payload.get("second_order_pick"))
                conviction = float(payload.get("conviction", 0.0))
                reasoning = list(payload.get("reasoning") or [])
            except (LLMCompletionError, ValueError, TypeError, json.JSONDecodeError):
                out.append(self._abstain(fixture_id, "llm parse failed")); continue
            if pick not in VALID_PICKS:
                out.append(self._abstain(fixture_id, f"invalid pick {pick!r}")); continue
            out.append(SignalReading(self.name, fixture_id, "HHAD", pick, max(0.0, min(conviction, 1.0)), reasoning or [f"Second-order tactical surprise -> {pick}"], ["llm:reflexive_tactic"], None))
        return out

    def _abstain(self, fixture_id: str, reason: str) -> SignalReading:
        return SignalReading(self.name, fixture_id, "HHAD", None, 0.0, [], [], reason)
