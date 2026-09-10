"""Pure, versionable settlement grading and exact payout arithmetic."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation, localcontext
from typing import Literal, Sequence

from nutmeg.ontology.finance.models import SettlementGrade

LegGrade = Literal["won", "lost", "void"]
NoteGrade = Literal["won", "lost", "void"]

_DECIMAL_CONTEXT = Context(prec=50)
_MARKET_KINDS = frozenset({"had", "hhad", "ttg", "crs"})
_HAD_CODES = frozenset({"home", "draw", "away"})
_ZHUCAI_TIERS = {
    "sfc": {14: "sfc_first", 13: "sfc_second"},
    "renjiu": {9: "renjiu_first"},
}


@dataclass(frozen=True, slots=True)
class MarketLegGrade:
    market_result_code: str
    leg_grade: LegGrade


@dataclass(frozen=True, slots=True)
class ZucaiNoteGrade:
    note_grade: Literal["won", "lost"]
    prize_tier_code: str | None


def _had_result_code(home_score: int | Decimal, away_score: int | Decimal) -> str:
    if home_score > away_score:
        return "home"
    if home_score < away_score:
        return "away"
    return "draw"


def _canonical_decimal(value: str, *, positive: bool) -> Decimal:
    if not isinstance(value, str):
        raise ValueError("value must be a canonical positive decimal")
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise ValueError("value must be a canonical positive decimal") from error
    if not parsed.is_finite() or format(parsed, ".12f") != value:
        raise ValueError("value must be a canonical positive decimal")
    if positive and parsed <= 0:
        raise ValueError("value must be a canonical positive decimal")
    return parsed


def crs_result_code(
    home_90: int,
    away_90: int,
    exact_codes: frozenset[str],
) -> str:
    exact = f"{home_90}:{away_90}"
    if exact in exact_codes:
        return exact
    if home_90 > away_90:
        return "win_other"
    if home_90 < away_90:
        return "loss_other"
    return "draw_other"


def _validate_market_leg_input(
    *,
    market_kind: str,
    selection_code: str,
    settlement_parameter_decimal: str | None,
    crs_exact_codes: frozenset[str],
) -> Decimal | None:
    if market_kind not in _MARKET_KINDS:
        raise ValueError("unsupported settlement market")
    if market_kind == "had":
        if selection_code not in _HAD_CODES:
            raise ValueError("unsupported HAD selection")
        return None
    if market_kind == "hhad":
        if selection_code not in _HAD_CODES:
            raise ValueError("unsupported HHAD selection")
        if settlement_parameter_decimal is None:
            raise ValueError("HHAD requires its persisted settlement line")
        return _canonical_decimal(settlement_parameter_decimal, positive=False)
    if market_kind == "ttg":
        if selection_code not in {f"total_{value}" for value in range(8)}:
            raise ValueError("unsupported TTG selection")
        return None
    allowed = crs_exact_codes | frozenset(
        {"win_other", "draw_other", "loss_other"}
    )
    if selection_code == "other" or selection_code not in allowed:
        raise ValueError("unsupported CRS selection")
    return None


def grade_market_leg(
    *,
    market_kind: str,
    selection_code: str,
    result_disposition: str,
    home_90: int | None,
    away_90: int | None,
    settlement_parameter_decimal: str | None = None,
    crs_exact_codes: frozenset[str] = frozenset(),
) -> MarketLegGrade:
    """Grade one JCZQ leg from persisted result and booking-time parameters."""
    line = _validate_market_leg_input(
        market_kind=market_kind,
        selection_code=selection_code,
        settlement_parameter_decimal=settlement_parameter_decimal,
        crs_exact_codes=crs_exact_codes,
    )
    if result_disposition == "official_void":
        if home_90 is not None or away_90 is not None:
            raise ValueError("official void result forbids scores")
        return MarketLegGrade("official_void", "void")
    if result_disposition != "played_90":
        raise ValueError("result disposition is not settleable")
    if (
        isinstance(home_90, bool)
        or isinstance(away_90, bool)
        or not isinstance(home_90, int)
        or not isinstance(away_90, int)
        or home_90 < 0
        or away_90 < 0
    ):
        raise ValueError("played result requires non-negative integer scores")

    if market_kind == "had":
        result_code = _had_result_code(home_90, away_90)
    elif market_kind == "hhad":
        assert line is not None
        with localcontext(_DECIMAL_CONTEXT):
            adjusted_home = Decimal(home_90) + line
        result_code = _had_result_code(adjusted_home, Decimal(away_90))
    elif market_kind == "ttg":
        total = home_90 + away_90
        result_code = f"total_{min(total, 7)}"
    else:
        result_code = crs_result_code(home_90, away_90, crs_exact_codes)

    return MarketLegGrade(
        market_result_code=result_code,
        leg_grade="won" if selection_code == result_code else "lost",
    )


def jczq_note_grade(grades: Sequence[str]) -> NoteGrade:
    values = tuple(grades)
    if not values or any(value not in {"won", "lost", "void"} for value in values):
        raise ValueError("JCZQ note leg grades are invalid")
    if "lost" in values:
        return "lost"
    if "won" in values:
        return "won"
    return "void"


def jczq_note_payout_minor(
    *,
    stake_minor: int,
    leg_grades: Sequence[str],
    booked_decimal_odds: Sequence[str | None],
) -> int:
    """Apply ``cn_sporttery_jczq_v1`` and round half-up once per note."""
    if isinstance(stake_minor, bool) or not isinstance(stake_minor, int) or stake_minor <= 0:
        raise ValueError("stake_minor must be a positive integer")
    grades = tuple(leg_grades)
    odds = tuple(booked_decimal_odds)
    if len(grades) != len(odds):
        raise ValueError("leg grades and odds must have equal length")
    state = jczq_note_grade(grades)
    if state == "lost":
        return 0
    if state == "void":
        return stake_minor
    with localcontext(_DECIMAL_CONTEXT):
        payout = Decimal(stake_minor)
        for grade, booked in zip(grades, odds, strict=True):
            if grade == "void":
                continue
            if grade != "won" or booked is None:
                raise ValueError("winning JCZQ leg requires booked odds")
            payout *= _canonical_decimal(booked, positive=True)
        return int(payout.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def zucai_note_grade(*, ticket_kind: str, correct_leg_count: int) -> ZucaiNoteGrade:
    tiers = _ZHUCAI_TIERS.get(ticket_kind)
    if tiers is None:
        raise ValueError("unsupported Zucai ticket kind")
    maximum = 14 if ticket_kind == "sfc" else 9
    if (
        isinstance(correct_leg_count, bool)
        or not isinstance(correct_leg_count, int)
        or not 0 <= correct_leg_count <= maximum
    ):
        raise ValueError("correct_leg_count is outside the ticket shape")
    tier = tiers.get(correct_leg_count)
    return ZucaiNoteGrade(
        note_grade="won" if tier is not None else "lost",
        prize_tier_code=tier,
    )


def zucai_note_payout_minor(
    *,
    unit_count: int,
    payout_minor_per_winning_note: int,
    won: bool,
) -> int:
    if (
        isinstance(unit_count, bool)
        or not isinstance(unit_count, int)
        or unit_count <= 0
        or isinstance(payout_minor_per_winning_note, bool)
        or not isinstance(payout_minor_per_winning_note, int)
        or payout_minor_per_winning_note < 0
        or not isinstance(won, bool)
    ):
        raise ValueError("Zucai payout inputs are invalid")
    return unit_count * payout_minor_per_winning_note if won else 0


def grade_had(
    selection_outcome_key: str,
    home_score: int,
    away_score: int,
) -> SettlementGrade:
    """Compatibility adapter for the pre-v2 single-market settlement service."""
    result = _had_result_code(home_score, away_score)
    return (
        SettlementGrade.WIN
        if selection_outcome_key == result
        else SettlementGrade.LOSS
    )


__all__ = [
    "MarketLegGrade",
    "ZucaiNoteGrade",
    "crs_result_code",
    "grade_had",
    "grade_market_leg",
    "jczq_note_grade",
    "jczq_note_payout_minor",
    "zucai_note_grade",
    "zucai_note_payout_minor",
]
