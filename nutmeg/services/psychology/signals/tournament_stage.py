from __future__ import annotations

from dataclasses import dataclass

from nutmeg.services.psychology.schemas import SignalReading
from nutmeg.services.psychology.signals.base import SignalContext

UCL_LIKE = {"UCL", "UEL", "UECL"}


@dataclass(slots=True)
class TournamentStageSignal:
    name: str = "tournament_stage"

    def evaluate(self, ctx: SignalContext) -> list[SignalReading]:
        readings: list[SignalReading] = []
        for fx in ctx.fixtures:
            fixture_id = str(fx.get("id"))
            comp = str(fx.get("competition_code") or "")
            stage = str(fx.get("stage") or "")
            leg = fx.get("leg")
            tier_h = fx.get("tier_home")
            tier_a = fx.get("tier_away")
            agg_diff = fx.get("aggregate_score_diff")
            matched = False
            if (
                comp in UCL_LIKE
                and stage == "knockout"
                and leg == 1
                and tier_h == 1
                and tier_a == 1
            ):
                readings.append(
                    SignalReading(
                        self.name,
                        fixture_id,
                        "HHAD",
                        "draw",
                        0.65,
                        ["UCL/UEL knockout 1st leg, both top-tier teams - conservative"],
                        ["rule:ucl_first_leg_low_block"],
                        None,
                    )
                )
                readings.append(
                    SignalReading(
                        self.name,
                        fixture_id,
                        "TTG",
                        "under_2_5",
                        0.65,
                        ["First-leg compactness historically suppresses goals"],
                        ["rule:ucl_first_leg_low_block"],
                        None,
                    )
                )
                matched = True
            if comp in UCL_LIKE and stage == "knockout" and leg == 2 and agg_diff == 0:
                readings.append(
                    SignalReading(
                        self.name,
                        fixture_id,
                        "HHAD",
                        "home_win",
                        0.55,
                        ["2nd leg with tied aggregate - home pushes for decisive win"],
                        ["rule:ucl_2nd_leg_tied_aggregate"],
                        None,
                    )
                )
                matched = True
            if stage == "cup" and tier_h is not None and tier_a is not None and tier_h > tier_a:
                readings.append(
                    SignalReading(
                        self.name,
                        fixture_id,
                        "handicap",
                        "home_plus_one",
                        0.45,
                        ["Cup tie with lower-tier home - upset volatility"],
                        ["rule:cup_lower_tier_home"],
                        None,
                    )
                )
                matched = True
            if stage == "final_round" and bool(fx.get("away_has_stakes")):
                readings.append(
                    SignalReading(
                        self.name,
                        fixture_id,
                        "HHAD",
                        "away_win",
                        0.50,
                        ["Final round, away team still has table stakes; home decided"],
                        ["rule:league_final_round_motivation_gap"],
                        None,
                    )
                )
                matched = True
            if not matched:
                readings.append(
                    SignalReading(
                        self.name, fixture_id, "HHAD", None, 0.0, [], [], "no rule matched"
                    )
                )
        return readings
