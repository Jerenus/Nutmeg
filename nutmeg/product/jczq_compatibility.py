"""One-way compatibility views for the authoritative JCZQ ontology workflow."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from nutmeg.ontology.actions.models import canonical_json
from nutmeg.product.jczq_board_workflow import JczqBoardWorkflow

_MARKET_CODES = {
    "md-had": "had",
    "md-hhad": "hhad",
    "md-ttg": "ttg",
    "md-crs": "crs",
}
_SELECTION_CODES = {"3": "home", "1": "draw", "0": "away"}


@dataclass(frozen=True, slots=True)
class JczqCompatibilityProjection:
    business_date: str
    reads: list[dict[str, object]]
    legs: list[dict[str, object]]
    handoff: dict[str, object]


class JczqCompatibilityProjector:
    def __init__(self, action_service, *, output_dir: str | Path) -> None:
        self._action_service = action_service
        self._output_dir = Path(output_dir)

    def export_day(self, business_date: str) -> JczqCompatibilityProjection:
        projection = self._build_day(business_date)
        day_dir = self._output_dir / "daily" / business_date
        day_dir.mkdir(parents=True, exist_ok=True)
        for name, value in (
            ("reads.json", projection.reads),
            ("legs.json", projection.legs),
            ("nutmeg-handoff.json", projection.handoff),
        ):
            target = day_dir / name
            temporary = target.with_suffix(target.suffix + ".tmp")
            temporary.write_text(
                json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(target)
        return projection

    def verify_day(self, business_date: str) -> None:
        expected = self._build_day(business_date)
        day_dir = self._output_dir / "daily" / business_date
        for name, value in (
            ("reads.json", expected.reads),
            ("legs.json", expected.legs),
            ("nutmeg-handoff.json", expected.handoff),
        ):
            path = day_dir / name
            if not path.is_file():
                raise ValueError(f"compatibility projection is missing: {name}")
            actual = json.loads(path.read_text(encoding="utf-8"))
            if canonical_json(actual) != canonical_json(value):
                raise ValueError(f"compatibility projection has drifted: {name}")

    def _build_day(self, business_date: str) -> JczqCompatibilityProjection:
        terminal = JczqBoardWorkflow(self._action_service).require_terminal_state(
            business_date
        )
        task_family_id = f"jczq:{business_date}"
        with self._action_service.unit_of_work() as uow:
            judgments = (
                uow.operator_decision.current_operator_match_judgments_for_task_family(
                    task_family_id
                )
            )
            forecast_by_id = {
                row.forecast_revision_id: row
                for row in uow.decision.iter_committed_revisions()
            }
            reads = []
            for judgment in judgments:
                forecast = forecast_by_id.get(judgment.forecast_revision_id)
                if forecast is None:
                    raise ValueError("committed judgment forecast is missing")
                reads.append(
                    {
                        "read_id": judgment.operator_match_judgment_revision_id,
                        "judgment_revision_id": (
                            judgment.operator_match_judgment_revision_id
                        ),
                        "forecast_revision_id": judgment.forecast_revision_id,
                        "match_id": judgment.match_id,
                        "market": _MARKET_CODES.get(
                            judgment.market_definition_id,
                            judgment.market_definition_id,
                        ),
                        "prior": forecast.prior_distribution,
                        "belief": forecast.belief_distribution,
                        "made_at": forecast.made_at,
                        "judge": forecast.actor_id,
                        "falsifier": judgment.falsifier,
                    }
                )

            legs: list[dict[str, object]] = []
            candidate_revision_id = None
            if terminal.selection_revision_id is not None:
                [selection] = (
                    row
                    for row in uow.operator_decision.current_candidate_selections_for_task_family(
                        task_family_id
                    )
                    if row.candidate_selection_id == terminal.selection_revision_id
                )
                candidate_revision_id = selection.candidate_revision_id
                for ticket in uow.operator_result.candidate_tickets(
                    selection.candidate_revision_id
                ):
                    for leg in uow.operator_result.candidate_ticket_legs(
                        ticket.candidate_ticket_id
                    ):
                        legs.append(
                            {
                                "match_id": leg.match_id,
                                "market": _MARKET_CODES.get(
                                    leg.market_definition_id,
                                    leg.market_definition_id,
                                ),
                                "selection": _SELECTION_CODES.get(
                                    leg.selection_code,
                                    leg.selection_code,
                                ),
                                "odds": (
                                    None
                                    if leg.booked_decimal_odds is None
                                    else float(leg.booked_decimal_odds)
                                ),
                                "bucket": "main",
                                "line": (
                                    None
                                    if leg.settlement_parameter_decimal is None
                                    else float(leg.settlement_parameter_decimal)
                                ),
                                "candidate_ticket_id": ticket.candidate_ticket_id,
                                "candidate_revision_id": selection.candidate_revision_id,
                                "candidate_set_revision_id": (
                                    selection.candidate_set_revision_id
                                ),
                                "selection_revision_id": selection.candidate_selection_id,
                                "forecast_revision_id": next(
                                    (
                                        item.forecast_revision_id
                                        for item in judgments
                                        if item.match_id == leg.match_id
                                        and item.market_definition_id
                                        == leg.market_definition_id
                                    ),
                                    None,
                                ),
                            }
                        )

        handoff: dict[str, object] = {
            "run_date": business_date,
            "status": "frozen",
            "position": "ready" if terminal.kind == "selected" else "abstain",
            "summary": (
                "Ontology-selected JCZQ candidate"
                if terminal.kind == "selected"
                else "Formal ontology no-ticket decision"
            ),
            "selection_revision_id": terminal.selection_revision_id,
            "no_ticket_revision_id": terminal.no_ticket_revision_id,
            "candidate_set_revision_id": terminal.candidate_set_revision_id,
            "candidate_revision_id": candidate_revision_id,
            "audit_complete": terminal.audit_complete,
            "explicit_empty_reason": (
                "formal_no_ticket" if terminal.kind == "no_ticket" else ""
            ),
            "projection_only": True,
        }
        return JczqCompatibilityProjection(
            business_date=business_date,
            reads=reads,
            legs=legs,
            handoff=handoff,
        )


__all__ = ["JczqCompatibilityProjection", "JczqCompatibilityProjector"]
