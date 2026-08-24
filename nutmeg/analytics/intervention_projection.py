"""Intervention coverage and preregistered counterfactual replay projections."""
from __future__ import annotations

import math
from collections import Counter
from datetime import datetime

from sqlalchemy import Engine

from nutmeg.analytics.outcomes import outcome_one_hot
from nutmeg.analytics.scoring import brier
from nutmeg.analytics.substrate import ProjectionContext
from nutmeg.ontology.decision.distributions import validate_simplex
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

INTERVENTION_COLUMNS = {
    "object_type": "VARCHAR",
    "metric": "VARCHAR",
    "group_key": "VARCHAR",
    "count": "BIGINT",
    "numerator": "BIGINT",
    "denominator": "BIGINT",
    "rate": "DOUBLE",
}

COUNTERFACTUAL_COLUMNS = {
    "adjudication_id": "VARCHAR",
    "subject_type": "VARCHAR",
    "subject_id": "VARCHAR",
    "match_id": "VARCHAR",
    "outcome_id": "VARCHAR",
    "market_definition_id": "VARCHAR",
    "label": "VARCHAR",
    "eligibility_code": "VARCHAR",
    "brier": "DOUBLE",
    "adjudication_created_at": "VARCHAR",
    "outcome_recorded_at": "VARCHAR",
}


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _count_row(
    object_type: str,
    metric: str,
    count: int,
    *,
    group_key: str = "all",
) -> dict[str, object]:
    return {
        "object_type": object_type,
        "metric": metric,
        "group_key": group_key,
        "count": count,
        "numerator": None,
        "denominator": None,
        "rate": None,
    }


def _coverage_row(
    object_type: str,
    metric: str,
    numerator: int,
    denominator: int,
) -> dict[str, object]:
    return {
        "object_type": object_type,
        "metric": metric,
        "group_key": "all",
        "count": None,
        "numerator": numerator,
        "denominator": denominator,
        "rate": _rate(numerator, denominator),
    }


def _parse_at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("projection timestamp must be timezone-aware")
    return parsed


def _counterfactual_row(adjudication, uow) -> dict[str, object]:
    base: dict[str, object] = {
        "adjudication_id": adjudication.adjudication_id,
        "subject_type": adjudication.subject_type,
        "subject_id": adjudication.subject_id,
        "match_id": None,
        "outcome_id": None,
        "market_definition_id": None,
        "label": None,
        "eligibility_code": "not_preregistered",
        "brier": None,
        "adjudication_created_at": adjudication.created_at,
        "outcome_recorded_at": None,
    }
    candidate = adjudication.alternative.get("counterfactual")
    if not isinstance(candidate, dict):
        return base
    if set(candidate) != {"market_definition_id", "distribution", "label"}:
        base["eligibility_code"] = "invalid_counterfactual"
        return base

    match_id = uow.workflow.match_for_subject(
        adjudication.subject_type, adjudication.subject_id
    )
    base["match_id"] = match_id
    if match_id is None:
        base["eligibility_code"] = "unlinked_subject"
        return base

    outcome = uow.finance.current_outcome(match_id)
    if outcome is None:
        base["eligibility_code"] = "missing_outcome"
        return base
    base["outcome_id"] = outcome.outcome_id
    base["outcome_recorded_at"] = outcome.recorded_at
    if _parse_at(adjudication.created_at) > _parse_at(outcome.recorded_at):
        base["eligibility_code"] = "recorded_after_outcome"
        return base

    market_definition_id = candidate.get("market_definition_id")
    label = candidate.get("label")
    distribution = candidate.get("distribution")
    base["market_definition_id"] = market_definition_id
    base["label"] = label
    if (
        not isinstance(market_definition_id, str)
        or not market_definition_id.strip()
        or not isinstance(label, str)
        or not label.strip()
        or not isinstance(distribution, dict)
    ):
        base["eligibility_code"] = "invalid_counterfactual"
        return base

    try:
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in distribution.values()
        ):
            raise ValueError("probabilities must be finite numbers")
        normalized = {str(key): float(value) for key, value in distribution.items()}
        validate_simplex(normalized)
    except (TypeError, ValueError):
        base["eligibility_code"] = "invalid_distribution"
        return base
    market_kind = uow.market.market_kind(market_definition_id)
    if market_kind != "had" or set(normalized) != {"home", "draw", "away"}:
        base["eligibility_code"] = "unsupported_market"
        return base
    actual = outcome_one_hot(market_kind, list(normalized), outcome.score_90)
    if actual is None:
        base["eligibility_code"] = "unsupported_market"
        return base
    base["eligibility_code"] = "eligible"
    base["brier"] = brier(normalized, actual)
    return base


def compute_counterfactual_rows(engine: Engine) -> list[dict[str, object]]:
    with OntologyUnitOfWork(engine) as uow:
        return [
            _counterfactual_row(adjudication, uow)
            for adjudication in uow.workflow.iter_adjudications()
        ]


def compute_intervention_scorecard_rows(engine: Engine) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with OntologyUnitOfWork(engine) as uow:
        predictions = uow.workflow.iter_predictions()
        flags = uow.workflow.iter_flag_instances()
        adjudications = uow.workflow.iter_adjudications()
        counterfactuals = [
            _counterfactual_row(adjudication, uow)
            for adjudication in adjudications
        ]

        rows.append(_count_row("prediction", "total", len(predictions)))
        prediction_statuses = Counter(item.status.value for item in predictions)
        for status in ("confirmed", "refuted", "void", "pending"):
            rows.append(
                _count_row("prediction", status, prediction_statuses.get(status, 0))
            )
        settled_predictions = sum(item.settled_at is not None for item in predictions)
        rows.append(
            _coverage_row(
                "prediction",
                "settled_coverage",
                settled_predictions,
                len(predictions),
            )
        )

        rows.append(_count_row("flag_instance", "total", len(flags)))
        covered_flags = sum(
            uow.finance.current_outcome(item.match_id) is not None for item in flags
        )
        rows.append(
            _coverage_row(
                "flag_instance", "outcome_coverage", covered_flags, len(flags)
            )
        )
        for flag_type, count in sorted(Counter(item.flag_type for item in flags).items()):
            rows.append(_count_row("flag_instance", "type", count, group_key=flag_type))
        for status, count in sorted(Counter(item.status for item in flags).items()):
            rows.append(_count_row("flag_instance", "status", count, group_key=status))
        for direction, count in sorted(
            Counter(item.direction or "none" for item in flags).items()
        ):
            rows.append(
                _count_row("flag_instance", "direction", count, group_key=direction)
            )

        rows.append(_count_row("adjudication", "total", len(adjudications)))
        rejected = sum(bool(item.evidence_rejected) for item in adjudications)
        rows.append(
            _coverage_row(
                "adjudication",
                "rejected_evidence_coverage",
                rejected,
                len(adjudications),
            )
        )
        for decision, count in sorted(
            Counter(item.decision for item in adjudications).items()
        ):
            rows.append(
                _count_row("adjudication", "decision", count, group_key=decision)
            )

        eligible = sum(
            item["eligibility_code"] == "eligible" for item in counterfactuals
        )
        rows.append(
            _coverage_row(
                "counterfactual",
                "eligible_coverage",
                eligible,
                len(counterfactuals),
            )
        )
    return rows


class InterventionQualityProjector:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def project(self, context: ProjectionContext) -> None:
        context.write(
            "intervention_scorecards",
            compute_intervention_scorecard_rows(self._engine),
            column_types=INTERVENTION_COLUMNS,
        )
        context.write(
            "counterfactual_replays",
            compute_counterfactual_rows(self._engine),
            column_types=COUNTERFACTUAL_COLUMNS,
        )
