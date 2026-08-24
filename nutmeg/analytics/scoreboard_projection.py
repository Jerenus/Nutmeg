"""Deterministic scoreboard projection over the independent score planes."""
from __future__ import annotations

import json
from collections import Counter

from sqlalchemy import Engine, func, select

from nutmeg.analytics.forecast_projection import compute_forecast_score_rows
from nutmeg.analytics.integrity_action import compute_integrity_action_rows
from nutmeg.analytics.intervention_projection import (
    compute_intervention_scorecard_rows,
)
from nutmeg.analytics.lifecycle import compute_lifecycle_proposal_rows
from nutmeg.analytics.scorecards import compute_scorecard_rows
from nutmeg.analytics.substrate import ProjectionContext
from nutmeg.ontology.actions.models import canonical_json
from nutmeg.ontology.repository import schema_decision as sd
from nutmeg.ontology.repository import schema_finance as sf
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

SCOREBOARD_COLUMNS = {
    "plane": "VARCHAR",
    "group_key": "VARCHAR",
    "metric_key": "VARCHAR",
    "value": "DOUBLE",
    "numerator": "DOUBLE",
    "denominator": "DOUBLE",
    "unit": "VARCHAR",
    "status": "VARCHAR",
    "tally": "VARCHAR",
    "detail": "VARCHAR",
    "source_refs_json": "VARCHAR",
}


def _metric(
    plane: str,
    group_key: str,
    metric_key: str,
    value: float | int | None,
    *,
    numerator: float | int | None = None,
    denominator: float | int | None = None,
    unit: str | None = None,
    status: str | None = None,
    tally: str | None = None,
    detail: str | None = None,
    source_refs: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "plane": plane,
        "group_key": group_key,
        "metric_key": metric_key,
        "value": value,
        "numerator": numerator,
        "denominator": denominator,
        "unit": unit,
        "status": status or ("available" if value is not None else "unscored"),
        "tally": tally,
        "detail": detail,
        "source_refs_json": canonical_json(source_refs or []),
    }


def _forecast_rows(engine: Engine) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    totals = Counter(
        row["market_definition_id"] for row in compute_forecast_score_rows(engine)
    )
    for card in compute_scorecard_rows(engine):
        group = f"{card['scorecard']}:{card['cohort_value']}"
        n = int(card["n"])
        coverage = float(card["coverage"])
        denominator = totals[str(card["cohort_value"])]
        refs = [
            {
                "object_type": "market_definition",
                "object_id": str(card["cohort_value"]),
            }
        ]
        rows.append(
            _metric(
                "forecast",
                group,
                "sample_size",
                n,
                unit="count",
                source_refs=refs,
            )
        )
        rows.append(
            _metric(
                "forecast",
                group,
                "coverage",
                coverage,
                numerator=n,
                denominator=denominator,
                unit="ratio",
                source_refs=refs,
            )
        )
        for metric_key in (
            "raw_brier",
            "prior_brier",
            "brier_skill",
            "skill_low",
            "skill_high",
        ):
            rows.append(
                _metric(
                    "forecast",
                    group,
                    metric_key,
                    card[metric_key],
                    unit="score",
                    source_refs=refs,
                )
            )
        for metric_key, value in json.loads(card["extra_json"]).items():
            rows.append(
                _metric(
                    "forecast",
                    group,
                    metric_key,
                    value,
                    unit="count" if isinstance(value, int) else "score",
                    source_refs=refs,
                )
            )
    return rows


def _money_rows(engine: Engine) -> list[dict[str, object]]:
    action_card = next(
        row
        for row in compute_integrity_action_rows(engine)
        if row["scorecard"] == "action_finance"
    )
    metrics = json.loads(action_card["metrics_json"])
    rows = [
        _metric(
            "money",
            "ledger",
            key,
            value,
            unit="count" if key.endswith("count") else "CNY",
        )
        for key, value in sorted(metrics.items())
    ]
    with OntologyUnitOfWork(engine) as uow:
        settled_ids = set(
            uow.connection.execute(select(sf.ticket_settlements.c.ticket_id))
            .scalars()
            .all()
        )
        all_ids = set(
            uow.connection.execute(select(sf.tickets.c.ticket_id)).scalars().all()
        )
        pnl = uow.connection.execute(
            select(func.sum(sf.ticket_settlements.c.pnl_amount))
        ).scalar_one()
    rows.extend(
        (
            _metric("money", "settlement", "settled_ticket_count", len(settled_ids), unit="count"),
            _metric(
                "money",
                "settlement",
                "open_ticket_count",
                len(all_ids - settled_ids),
                unit="count",
            ),
            _metric("money", "settlement", "pnl_total", pnl, unit="CNY"),
        )
    )
    return rows


def _intervention_rows(engine: Engine) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in compute_intervention_scorecard_rows(engine):
        rows.append(
            _metric(
                "intervention",
                f"{item['object_type']}:{item['group_key']}",
                str(item["metric"]),
                item["rate"] if item["rate"] is not None else item["count"],
                numerator=item["numerator"],
                denominator=item["denominator"],
                unit="ratio" if item["rate"] is not None else "count",
            )
        )
    return rows


def _lifecycle_rows(engine: Engine) -> list[dict[str, object]]:
    proposals = compute_lifecycle_proposal_rows(engine)
    with OntologyUnitOfWork(engine) as uow:
        statuses = Counter(
            uow.connection.execute(select(sd.factor_definitions.c.status)).scalars().all()
        )
    rows = [
        _metric("lifecycle", "factor_status", status, count, unit="count")
        for status, count in sorted(statuses.items())
    ]
    rows.append(
        _metric(
            "lifecycle",
            "proposal",
            "pending_count",
            len(proposals),
            unit="count",
        )
    )
    for proposal in proposals:
        rows.append(
            _metric(
                "lifecycle",
                str(proposal["factor_definition_id"]),
                "proposed_transition",
                None,
                status="proposed",
                detail=f"{proposal['from_status']}->{proposal['to_status']}",
                source_refs=[
                    {
                        "object_type": "factor_definition",
                        "object_id": str(proposal["factor_definition_id"]),
                    }
                ],
            )
        )
    return rows


def _manual_rows(engine: Engine, as_of: str) -> list[dict[str, object]]:
    with OntologyUnitOfWork(engine) as uow:
        observations = uow.scoreboard.latest_observations(as_of)
    return [
        _metric(
            "manual",
            observation.group_key,
            observation.metric_key,
            observation.value,
            numerator=observation.numerator,
            denominator=observation.denominator,
            unit=observation.unit,
            status=observation.status,
            tally=observation.tally,
            detail=observation.detail,
            source_refs=[
                {
                    "object_type": "scoreboard_observation",
                    "object_id": observation.scoreboard_observation_id,
                },
                *observation.evidence_refs,
            ],
        )
        for observation in observations
    ]


def compute_scoreboard_metric_rows(
    engine: Engine, *, as_of: str
) -> list[dict[str, object]]:
    rows = [
        *_forecast_rows(engine),
        *_money_rows(engine),
        *_intervention_rows(engine),
        *_lifecycle_rows(engine),
        *_manual_rows(engine, as_of),
    ]
    return sorted(
        rows,
        key=lambda row: (
            str(row["plane"]),
            str(row["group_key"]),
            str(row["metric_key"]),
        ),
    )


class ScoreboardProjector:
    def __init__(self, engine: Engine, *, as_of: str) -> None:
        self._engine = engine
        self._as_of = as_of

    def project(self, context: ProjectionContext) -> None:
        context.write(
            "scoreboard_metrics",
            compute_scoreboard_metric_rows(self._engine, as_of=self._as_of),
            column_types=SCOREBOARD_COLUMNS,
        )
