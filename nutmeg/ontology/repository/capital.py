from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from sqlalchemy import Connection, insert, select

from nutmeg.ontology.actions.models import canonical_json
from nutmeg.ontology.repository import schema_capital as sc


@dataclass(frozen=True, slots=True)
class CapitalPlanRow:
    plan_id: str
    issue: str
    day: str
    supersedes: str | None
    cap_source: str
    adjudication_ref: str | None
    caps: dict
    jczq_used_today: int
    frontier_refs: dict
    max_p_matrix: float | None
    max_p_strict: float | None
    chosen_p: float | None
    gate_cost_pp: float | None
    chosen: list
    verdict_refs: list
    actor_id: str
    committed_at: str


_FLOATS = ("max_p_matrix", "max_p_strict", "chosen_p", "gate_cost_pp")
_JSON_FIELDS = ("caps", "frontier_refs", "chosen", "verdict_refs")


class CapitalRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def insert_plan(self, row: CapitalPlanRow) -> None:
        values = asdict(row)
        for key in _JSON_FIELDS:
            values[f"{key}_json"] = canonical_json(values.pop(key))
        for key in _FLOATS:
            values[key] = None if values[key] is None else repr(float(values[key]))
        self._connection.execute(insert(sc.zucai_capital_plans).values(**values))

    def plans(self, issue: str) -> list[CapitalPlanRow]:
        table = sc.zucai_capital_plans
        rows = (
            self._connection.execute(
                select(table)
                .where(table.c.issue == issue)
                .order_by(table.c.committed_at, table.c.plan_id)
            )
            .mappings()
            .all()
        )
        return [self._row(row) for row in rows]

    def latest_plan(self, issue: str) -> CapitalPlanRow | None:
        plans = self.plans(issue)
        if not plans:
            return None
        superseded = {plan.supersedes for plan in plans if plan.supersedes}
        leaves = [plan for plan in plans if plan.plan_id not in superseded]
        return leaves[-1]

    def all_latest(self) -> list[CapitalPlanRow]:
        table = sc.zucai_capital_plans
        issues = self._connection.execute(select(table.c.issue).distinct()).scalars().all()
        return [
            plan
            for issue in sorted(issues)
            if (plan := self.latest_plan(issue)) is not None
        ]

    @staticmethod
    def _row(row) -> CapitalPlanRow:
        values = dict(row)
        for key in _JSON_FIELDS:
            values[key] = json.loads(values.pop(f"{key}_json"))
        for key in _FLOATS:
            values[key] = None if values[key] is None else float(values[key])
        return CapitalPlanRow(**values)
