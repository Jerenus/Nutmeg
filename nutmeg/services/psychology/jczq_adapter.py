from __future__ import annotations

from copy import deepcopy
from typing import Any

from nutmeg.services.psychology.schemas import DataLeg, FinalScheme, Scheme


def _fixture_id(leg: Any) -> str:
    return f"{leg.match_no}:{leg.home_team}:{leg.away_team}"


def _leg_id(idx: int) -> str:
    return f"L{idx + 1}"


def combination_to_data_scheme(combination: Any) -> Scheme:
    return Scheme(name=str(combination.name), legs=[DataLeg(_leg_id(idx), _fixture_id(leg), str(leg.play), str(leg.pick), float(leg.odds)) for idx, leg in enumerate(combination.legs)])


def apply_final_scheme_to_combination(combination: Any, final: FinalScheme) -> Any:
    updated = deepcopy(combination)
    final_by_leg = {leg.leg_id: leg for leg in final.legs}
    for idx, leg in enumerate(updated.legs):
        replacement = final_by_leg.get(_leg_id(idx))
        if replacement is None:
            continue
        leg.pick = replacement.outcome
        leg.odds = replacement.odds
    return updated
