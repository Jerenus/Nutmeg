"""Typed persistence and deterministic reads for operator review lifecycle."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from sqlalchemy import Connection, exists, insert, select, text

from nutmeg.ontology.actions.models import canonical_json
from nutmeg.ontology.operator.models import OperatorWorkerJobRow, ReviewEligibilityFactRow
from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository import schema_decision as sd
from nutmeg.ontology.repository import schema_operator_decision as sod
from nutmeg.ontology.repository import schema_operator_result as sor
from nutmeg.ontology.repository import schema_operator_review as sov
from nutmeg.ontology.repository import schema_operator_sale as sos
from nutmeg.ontology.repository import schema_scoreboard as ss
from nutmeg.ontology.repository import schema_tickets as st
from nutmeg.ontology.repository import schema_workflow as sw


@dataclass(frozen=True, slots=True)
class ReviewItemRow:
    review_id: str
    review_eligibility_fact_id: str
    task_family_id: str
    work_item_id: str
    task_snapshot_hash: str
    lane: str
    business_key: str
    review_kind: str
    market_prior_baseline_revision_id: str | None
    outcome_revision_ids: tuple[str, ...]
    materialized_by_action_id: str
    materialized_at: str


@dataclass(frozen=True, slots=True)
class ScoreboardEffectDispositionRevisionRow:
    disposition_revision_id: str
    family_id: str
    revision_no: int
    supersedes_revision_id: str | None
    review_id: str
    disposition: str
    reason: str
    pre_update_legacy_sha256: str
    required_metric_keys: tuple[str, ...]
    created_by_action_id: str
    created_at: str


@dataclass(frozen=True, slots=True)
class ScoreboardReviewObservationLinkRow:
    observation_link_id: str
    review_id: str
    disposition_revision_id: str
    metric_key: str
    scoreboard_observation_id: str
    observation_action_id: str
    observed_legacy_sha256: str
    created_at: str


@dataclass(frozen=True, slots=True)
class ScoreboardReviewCompletionRequestRow:
    completion_request_id: str
    action_id: str
    review_id: str
    disposition_revision_id: str
    shadow_review_token: str
    shadow_review_id: str
    shadow_source_high_watermark: int
    compared_legacy_sha256: str
    metric_keys: tuple[str, ...]
    observation_action_ids: tuple[str, ...]
    requested_at: str


@dataclass(frozen=True, slots=True)
class ScoreboardReviewCompletionReceiptRow:
    completion_receipt_id: str
    review_id: str
    disposition_revision_id: str
    completion_request_id: str | None
    post_update_legacy_sha256: str | None
    observation_action_ids: tuple[str, ...]
    shadow_review_id: str | None
    shadow_source_high_watermark: int | None
    completed_by_action_id: str
    completed_at: str


@dataclass(frozen=True, slots=True)
class ReviewAdjudicationHistoryRow:
    decision: str
    reason: str
    rejected_evidence_count: int
    created_at: str


@dataclass(frozen=True, slots=True)
class ReviewScoreboardObservationHistoryRow:
    metric_key: str
    tally: str
    detail: str
    status: str
    numerator: float | None
    denominator: float | None
    value: float | None
    unit: str | None
    effective_at: str


class OperatorReviewRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def eligibility_fact(self, fact_id: str) -> ReviewEligibilityFactRow | None:
        row = (
            self._connection.execute(
                select(sor.operator_review_eligibility_facts).where(
                    sor.operator_review_eligibility_facts.c.review_eligibility_fact_id
                    == fact_id
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else ReviewEligibilityFactRow(**dict(row))

    def eligibility_lane_business_key(
        self,
        fact: ReviewEligibilityFactRow,
    ) -> tuple[str, str]:
        if fact.no_ticket_revision_id is not None:
            row = self._connection.execute(
                select(sos.official_sale_slate_revisions.c.lane,
                       sos.official_sale_slate_revisions.c.business_key)
                .select_from(
                    sod.operator_no_ticket_revisions.join(
                        sos.official_sale_slate_revisions,
                        sos.official_sale_slate_revisions.c.slate_revision_id
                        == sod.operator_no_ticket_revisions.c.slate_revision_id,
                    )
                )
                .where(
                    sod.operator_no_ticket_revisions.c.no_ticket_revision_id
                    == fact.no_ticket_revision_id
                )
            ).one_or_none()
        elif fact.artifact_terminal_receipt_id is not None:
            row = self._connection.execute(
                select(sos.official_sale_slate_revisions.c.lane,
                       sos.official_sale_slate_revisions.c.business_key)
                .select_from(
                    st.operator_artifact_terminal_receipts.join(
                        st.operator_artifact_work_item_links,
                        st.operator_artifact_work_item_links.c.ticket_artifact_id
                        == st.operator_artifact_terminal_receipts.c.ticket_artifact_id,
                    ).join(
                        sos.official_sale_slate_revisions,
                        sos.official_sale_slate_revisions.c.slate_revision_id
                        == st.operator_artifact_work_item_links.c.slate_revision_id,
                    )
                )
                .where(
                    st.operator_artifact_terminal_receipts.c.artifact_terminal_receipt_id
                    == fact.artifact_terminal_receipt_id
                )
            ).one_or_none()
        elif fact.settlement_run_id is not None:
            row = self._connection.execute(
                select(
                    sor.operator_result_set_revisions.c.lane,
                    sor.operator_result_set_revisions.c.business_key,
                )
                .select_from(
                    sor.operator_task_settlement_runs.join(
                        sor.operator_result_set_revisions,
                        sor.operator_result_set_revisions.c.result_set_revision_id
                        == sor.operator_task_settlement_runs.c.result_set_revision_id,
                    )
                )
                .where(
                    sor.operator_task_settlement_runs.c.settlement_run_id
                    == fact.settlement_run_id
                )
            ).one_or_none()
        else:
            row = None
        if row is None:
            raise ValueError("review eligibility source slate does not exist")
        return str(row.lane), str(row.business_key)

    def bound_outcome_revision_ids(
        self,
        fact: ReviewEligibilityFactRow,
    ) -> tuple[str, ...] | None:
        if fact.readiness_condition == "immediate":
            return ()
        baseline_id = fact.market_prior_baseline_revision_id
        if baseline_id is None:
            raise ValueError("outcomes-required review has no bound baseline")
        match_ids = tuple(
            str(value)
            for value in self._connection.execute(
                select(sod.operator_market_prior_baseline_probabilities.c.match_id)
                .where(
                    sod.operator_market_prior_baseline_probabilities.c.
                    market_prior_baseline_revision_id
                    == baseline_id
                )
                .distinct()
                .order_by(sod.operator_market_prior_baseline_probabilities.c.match_id)
            ).scalars()
        )
        if not match_ids:
            raise ValueError("review baseline has no match probabilities")
        outcomes = sor.operator_outcome_revisions
        children = outcomes.alias("review_outcome_children")
        bound: list[str] = []
        for match_id in match_ids:
            rows = tuple(
                str(value)
                for value in self._connection.execute(
                    select(outcomes.c.outcome_revision_id)
                    .join(schema.actions, schema.actions.c.action_id == outcomes.c.action_id)
                    .where(
                        outcomes.c.match_id == match_id,
                        schema.actions.c.status == "committed",
                        ~exists(
                            select(1).where(
                                children.c.supersedes_revision_id
                                == outcomes.c.outcome_revision_id
                            )
                        ),
                    )
                    .order_by(outcomes.c.outcome_revision_id)
                ).scalars()
            )
            if not rows:
                return None
            if len(rows) != 1:
                raise ValueError(f"match {match_id} has ambiguous current Outcomes")
            bound.append(rows[0])
        return tuple(bound)

    def insert_review_item(self, row: ReviewItemRow) -> None:
        values = asdict(row)
        values["outcome_revision_ids_json"] = canonical_json(
            list(values.pop("outcome_revision_ids"))
        )
        self._connection.execute(insert(sov.operator_review_items).values(**values))

    def review_item(self, review_id: str) -> ReviewItemRow | None:
        row = (
            self._connection.execute(
                select(sov.operator_review_items).where(
                    sov.operator_review_items.c.review_id == review_id
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else _review_item_row(row)

    def review_for_eligibility_fact(self, fact_id: str) -> ReviewItemRow | None:
        row = (
            self._connection.execute(
                select(sov.operator_review_items).where(
                    sov.operator_review_items.c.review_eligibility_fact_id == fact_id
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else _review_item_row(row)

    def review_items_for_task(
        self,
        task_family_id: str,
        *,
        work_item_id: str | None = None,
    ) -> tuple[ReviewItemRow, ...]:
        statement = select(sov.operator_review_items).where(
            sov.operator_review_items.c.task_family_id == task_family_id
        )
        if work_item_id is not None:
            statement = statement.where(
                sov.operator_review_items.c.work_item_id == work_item_id
            )
        rows = self._connection.execute(
            statement.order_by(
                sov.operator_review_items.c.materialized_at,
                sov.operator_review_items.c.review_id,
            )
        ).mappings()
        return tuple(_review_item_row(row) for row in rows)

    def pending_review_items_for_task(
        self,
        task_family_id: str,
        *,
        work_item_id: str | None = None,
    ) -> tuple[ReviewItemRow, ...]:
        receipts = sov.operator_scoreboard_review_completion_receipts
        statement = select(sov.operator_review_items).where(
            sov.operator_review_items.c.task_family_id == task_family_id,
            ~exists(
                select(1).where(
                    receipts.c.review_id == sov.operator_review_items.c.review_id
                )
            ),
        )
        if work_item_id is not None:
            statement = statement.where(
                sov.operator_review_items.c.work_item_id == work_item_id
            )
        rows = self._connection.execute(
            statement.order_by(
                sov.operator_review_items.c.materialized_at,
                sov.operator_review_items.c.review_id,
            )
        ).mappings()
        return tuple(_review_item_row(row) for row in rows)

    def insert_disposition(self, row: ScoreboardEffectDispositionRevisionRow) -> None:
        values = asdict(row)
        values["required_metric_keys_json"] = canonical_json(
            list(values.pop("required_metric_keys"))
        )
        self._connection.execute(
            insert(sov.operator_scoreboard_effect_disposition_revisions).values(**values)
        )

    def disposition(
        self,
        disposition_revision_id: str,
    ) -> ScoreboardEffectDispositionRevisionRow | None:
        row = (
            self._connection.execute(
                select(sov.operator_scoreboard_effect_disposition_revisions).where(
                    sov.operator_scoreboard_effect_disposition_revisions.c.
                    disposition_revision_id
                    == disposition_revision_id
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else _disposition_row(row)

    def current_disposition(
        self,
        review_id: str,
    ) -> ScoreboardEffectDispositionRevisionRow | None:
        revisions = sov.operator_scoreboard_effect_disposition_revisions
        children = revisions.alias("scoreboard_disposition_children")
        row = (
            self._connection.execute(
                select(revisions).where(
                    revisions.c.review_id == review_id,
                    ~exists(
                        select(1).where(
                            children.c.supersedes_revision_id
                            == revisions.c.disposition_revision_id
                        )
                    ),
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else _disposition_row(row)

    def registered_metric_keys(self) -> set[str]:
        keys = {
            str(value)
            for value in self._connection.execute(
                select(ss.scoreboard_observations.c.metric_key).distinct()
            ).scalars()
        }
        documents = self._connection.execute(
            select(ss.scoreboard_shadow_reviews.c.classification_json)
        ).scalars()
        for document in documents:
            for item in json.loads(str(document)):
                metric_key = item.get("metric_key")
                if isinstance(metric_key, str) and metric_key.strip():
                    keys.add(metric_key)
        return keys

    def adjudication_history(
        self,
        *,
        business_key: str,
        as_of: str,
    ) -> tuple[ReviewAdjudicationHistoryRow, ...]:
        rows = self._connection.execute(
            select(
                sw.adjudications.c.decision,
                sw.adjudications.c.reason,
                sw.adjudications.c.evidence_rejected_json,
                sw.adjudications.c.created_at,
            )
            .where(
                sw.adjudications.c.subject_type == "issue",
                sw.adjudications.c.subject_id == business_key,
                sw.adjudications.c.created_at <= as_of,
            )
            .order_by(
                sw.adjudications.c.created_at,
                sw.adjudications.c.adjudication_id,
            )
        ).mappings()
        return tuple(
            ReviewAdjudicationHistoryRow(
                decision=str(row["decision"]),
                reason=str(row["reason"]),
                rejected_evidence_count=len(
                    json.loads(str(row["evidence_rejected_json"]))
                ),
                created_at=str(row["created_at"]),
            )
            for row in rows
        )

    def factor_ids_for_task(
        self,
        task_family_id: str,
        *,
        as_of: str,
    ) -> tuple[str, ...]:
        rows = self._connection.execute(
            select(sd.factor_definitions.c.factor_family_id)
            .select_from(
                sod.operator_match_judgment_revisions.join(
                    sod.operator_match_judgment_factor_adjustments,
                    sod.operator_match_judgment_factor_adjustments.c.
                    operator_match_judgment_revision_id
                    == sod.operator_match_judgment_revisions.c.
                    operator_match_judgment_revision_id,
                ).join(
                    sd.factor_definitions,
                    sd.factor_definitions.c.factor_definition_id
                    == sod.operator_match_judgment_factor_adjustments.c.
                    factor_definition_id,
                )
            )
            .where(
                sod.operator_match_judgment_revisions.c.task_family_id
                == task_family_id,
                sod.operator_match_judgment_revisions.c.created_at <= as_of,
            )
            .distinct()
            .order_by(sd.factor_definitions.c.factor_family_id)
        ).scalars()
        return tuple(str(value) for value in rows)

    def insert_observation_link(self, row: ScoreboardReviewObservationLinkRow) -> None:
        self._connection.execute(
            insert(sov.operator_scoreboard_review_observation_links).values(**asdict(row))
        )

    def observation_links_for_disposition(
        self,
        disposition_revision_id: str,
    ) -> tuple[ScoreboardReviewObservationLinkRow, ...]:
        rows = self._connection.execute(
            select(sov.operator_scoreboard_review_observation_links)
            .where(
                sov.operator_scoreboard_review_observation_links.c.
                disposition_revision_id
                == disposition_revision_id
            )
            .order_by(sov.operator_scoreboard_review_observation_links.c.metric_key)
        ).mappings()
        return tuple(
            ScoreboardReviewObservationLinkRow(**dict(row)) for row in rows
        )

    def scoreboard_observation_history(
        self,
        disposition_revision_id: str,
    ) -> tuple[ReviewScoreboardObservationHistoryRow, ...]:
        links = sov.operator_scoreboard_review_observation_links
        observations = ss.scoreboard_observations
        rows = self._connection.execute(
            select(
                observations.c.metric_key,
                observations.c.tally,
                observations.c.detail,
                observations.c.status,
                observations.c.numerator,
                observations.c.denominator,
                observations.c.value,
                observations.c.unit,
                observations.c.effective_at,
            )
            .select_from(
                links.join(
                    observations,
                    observations.c.scoreboard_observation_id
                    == links.c.scoreboard_observation_id,
                )
            )
            .where(links.c.disposition_revision_id == disposition_revision_id)
            .order_by(observations.c.metric_key)
        ).mappings()
        return tuple(
            ReviewScoreboardObservationHistoryRow(**dict(row)) for row in rows
        )

    def insert_completion_request(
        self,
        row: ScoreboardReviewCompletionRequestRow,
    ) -> None:
        values = asdict(row)
        for name in ("metric_keys", "observation_action_ids"):
            values[f"{name}_json"] = canonical_json(list(values.pop(name)))
        self._connection.execute(
            insert(sov.operator_scoreboard_review_completion_requests).values(**values)
        )

    def completion_request(
        self,
        request_id: str,
    ) -> ScoreboardReviewCompletionRequestRow | None:
        row = (
            self._connection.execute(
                select(sov.operator_scoreboard_review_completion_requests).where(
                    sov.operator_scoreboard_review_completion_requests.c.
                    completion_request_id
                    == request_id
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else _completion_request_row(row)

    def completion_requests_for_review(
        self,
        review_id: str,
    ) -> tuple[ScoreboardReviewCompletionRequestRow, ...]:
        rows = self._connection.execute(
            select(sov.operator_scoreboard_review_completion_requests)
            .where(
                sov.operator_scoreboard_review_completion_requests.c.review_id
                == review_id
            )
            .order_by(
                sov.operator_scoreboard_review_completion_requests.c.requested_at,
                sov.operator_scoreboard_review_completion_requests.c.completion_request_id,
            )
        ).mappings()
        return tuple(_completion_request_row(row) for row in rows)

    def insert_completion_receipt(
        self,
        row: ScoreboardReviewCompletionReceiptRow,
    ) -> None:
        values = asdict(row)
        observation_ids = values.pop("observation_action_ids")
        values["observation_action_ids_json"] = (
            None if row.completion_request_id is None else canonical_json(list(observation_ids))
        )
        self._connection.execute(
            insert(sov.operator_scoreboard_review_completion_receipts).values(**values)
        )

    def completion_receipt_for_review(
        self,
        review_id: str,
    ) -> ScoreboardReviewCompletionReceiptRow | None:
        row = (
            self._connection.execute(
                select(sov.operator_scoreboard_review_completion_receipts).where(
                    sov.operator_scoreboard_review_completion_receipts.c.review_id
                    == review_id
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else _completion_receipt_row(row)

    def materialization_jobs_for_fact(
        self,
        fact_id: str,
    ) -> tuple[OperatorWorkerJobRow, ...]:
        return self._jobs_for_source(
            job_kind="review_materialization",
            source_object_type="operator_review_eligibility_fact",
            source_object_id=fact_id,
        )

    def completion_jobs_for_request(
        self,
        request_id: str,
    ) -> tuple[OperatorWorkerJobRow, ...]:
        return self._jobs_for_source(
            job_kind="scoreboard_review_completion",
            source_object_type="operator_scoreboard_review_completion_request",
            source_object_id=request_id,
        )

    def action_rowid(self, action_id: str) -> int | None:
        value = self._connection.execute(
            text("SELECT rowid FROM actions WHERE action_id = :action_id"),
            {"action_id": action_id},
        ).scalar_one_or_none()
        return None if value is None else int(value)

    def _jobs_for_source(
        self,
        *,
        job_kind: str,
        source_object_type: str,
        source_object_id: str,
    ) -> tuple[OperatorWorkerJobRow, ...]:
        rows = self._connection.execute(
            select(sod.operator_worker_jobs)
            .where(
                sod.operator_worker_jobs.c.job_kind == job_kind,
                sod.operator_worker_jobs.c.source_object_type == source_object_type,
                sod.operator_worker_jobs.c.source_object_id == source_object_id,
            )
            .order_by(sod.operator_worker_jobs.c.created_at)
        ).mappings()
        return tuple(OperatorWorkerJobRow(**dict(row)) for row in rows)


def _review_item_row(row) -> ReviewItemRow:
    values = dict(row)
    values["outcome_revision_ids"] = tuple(
        json.loads(values.pop("outcome_revision_ids_json"))
    )
    return ReviewItemRow(**values)


def _disposition_row(row) -> ScoreboardEffectDispositionRevisionRow:
    values = dict(row)
    values["required_metric_keys"] = tuple(
        json.loads(values.pop("required_metric_keys_json"))
    )
    return ScoreboardEffectDispositionRevisionRow(**values)


def _completion_request_row(row) -> ScoreboardReviewCompletionRequestRow:
    values = dict(row)
    for name in ("metric_keys", "observation_action_ids"):
        values[name] = tuple(json.loads(values.pop(f"{name}_json")))
    return ScoreboardReviewCompletionRequestRow(**values)


def _completion_receipt_row(row) -> ScoreboardReviewCompletionReceiptRow:
    values = dict(row)
    document = values.pop("observation_action_ids_json")
    values["observation_action_ids"] = (
        () if document is None else tuple(json.loads(document))
    )
    return ScoreboardReviewCompletionReceiptRow(**values)


__all__ = [
    "OperatorReviewRepository",
    "ReviewItemRow",
    "ReviewAdjudicationHistoryRow",
    "ReviewScoreboardObservationHistoryRow",
    "ScoreboardEffectDispositionRevisionRow",
    "ScoreboardReviewCompletionReceiptRow",
    "ScoreboardReviewCompletionRequestRow",
    "ScoreboardReviewObservationLinkRow",
]
