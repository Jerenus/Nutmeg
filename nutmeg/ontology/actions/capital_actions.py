"""Governed Action for append-only Zucai capital plans."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from nutmeg.decision.capital_rules import validate_caps
from nutmeg.ontology.actions.models import ActionCommand, ActionOutcome, ActorRole, ObjectRef
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository.capital import CapitalPlanRow

_CAP_SOURCES = ("baseline", "override", "brake")


@dataclass(frozen=True, slots=True)
class CommitCapitalPlanRequest:
    issue: str
    day: str
    cap_source: str
    adjudication_ref: str | None
    caps: dict
    jczq_used_today: int
    frontier_refs: dict
    max_p_matrix: float | None
    max_p_strict: float | None
    chosen_p: float | None
    chosen: list
    verdict_refs: list
    supersedes: str | None
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime


class CapitalActions:
    def __init__(self, action_service: ActionService) -> None:
        self._service = action_service

    def commit_capital_plan(self, request: CommitCapitalPlanRequest) -> ActionOutcome:
        if request.cap_source not in _CAP_SOURCES:
            raise ValueError(f"cap_source must be one of {_CAP_SOURCES}")
        if request.cap_source == "override" and not request.adjudication_ref:
            raise ValueError("override requires adjudication_ref")
        validate_caps(request.caps, jczq_used_today=request.jczq_used_today)
        gate_cost = (
            None
            if request.max_p_matrix is None or request.max_p_strict is None
            else (request.max_p_matrix - request.max_p_strict) * 100.0
        )
        command = ActionCommand.create(
            action_type="zucai_commit_capital_plan",
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload={
                "issue": request.issue,
                "cap_source": request.cap_source,
                "caps": dict(request.caps),
                "supersedes": request.supersedes,
            },
            requested_at=request.requested_at,
        )

        def handler(uow, _command) -> tuple[ObjectRef, ...]:
            if request.supersedes and not any(
                plan.plan_id == request.supersedes
                for plan in uow.capital.plans(request.issue)
            ):
                raise ValueError(f"supersedes {request.supersedes} is not an existing plan")
            plan_id = f"zcp-{uuid.uuid4().hex[:12]}"
            chosen = [{**item, "slip_id": item.get("slip_id")} for item in request.chosen]
            uow.capital.insert_plan(
                CapitalPlanRow(
                    plan_id=plan_id,
                    issue=request.issue,
                    day=request.day,
                    supersedes=request.supersedes,
                    cap_source=request.cap_source,
                    adjudication_ref=request.adjudication_ref,
                    caps=dict(request.caps),
                    jczq_used_today=int(request.jczq_used_today),
                    frontier_refs=dict(request.frontier_refs),
                    max_p_matrix=request.max_p_matrix,
                    max_p_strict=request.max_p_strict,
                    chosen_p=request.chosen_p,
                    gate_cost_pp=gate_cost,
                    chosen=chosen,
                    verdict_refs=list(request.verdict_refs),
                    actor_id=request.actor_id,
                    committed_at=request.requested_at.isoformat(timespec="seconds"),
                )
            )
            return (ObjectRef("zucai_capital_plan", plan_id),)

        return self._service.execute(command, handler)
