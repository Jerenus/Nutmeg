"""Typed persistence for governed workflow objects."""
from __future__ import annotations

from sqlalchemy import Connection, func, insert, select, update

from nutmeg.ontology.actions.models import canonical_json
from nutmeg.ontology.repository import schema_decision as sd
from nutmeg.ontology.repository import schema_finance as sf
from nutmeg.ontology.repository import schema_identity as si
from nutmeg.ontology.repository import schema_workflow as sw
from nutmeg.ontology.repository.rows import from_row
from nutmeg.ontology.workflow.models import (
    AdjudicationRow,
    FlagInstanceRow,
    PredictionRow,
    PredictionStatus,
)


class WorkflowRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def insert_adjudication(self, row: AdjudicationRow) -> None:
        self._connection.execute(
            insert(sw.adjudications).values(
                adjudication_id=row.adjudication_id,
                subject_type=row.subject_type,
                subject_id=row.subject_id,
                decision=row.decision,
                actor_id=row.actor_id,
                reason=row.reason,
                evidence_rejected_json=canonical_json(row.evidence_rejected),
                alternative_json=canonical_json(row.alternative),
                created_at=row.created_at,
                supersedes_adjudication_id=row.supersedes_adjudication_id,
            )
        )

    def count_adjudications(self) -> int:
        return self._connection.execute(
            select(func.count()).select_from(sw.adjudications)
        ).scalar_one()

    def iter_adjudications(self) -> list[AdjudicationRow]:
        rows = (
            self._connection.execute(
                select(sw.adjudications).order_by(
                    sw.adjudications.c.created_at,
                    sw.adjudications.c.adjudication_id,
                )
            )
            .mappings()
            .all()
        )
        return [
            from_row(AdjudicationRow, row, ('evidence_rejected', 'alternative'))
            for row in rows
        ]

    def iter_flag_instances(self) -> list[FlagInstanceRow]:
        rows = (
            self._connection.execute(
                select(sw.flag_instances).order_by(
                    sw.flag_instances.c.created_at,
                    sw.flag_instances.c.flag_instance_id,
                )
            )
            .mappings()
            .all()
        )
        return [from_row(FlagInstanceRow, row, ('evidence_refs',)) for row in rows]

    def insert_prediction(self, row: PredictionRow) -> None:
        self._connection.execute(
            insert(sw.predictions).values(
                prediction_id=row.prediction_id,
                match_id=row.match_id,
                subject_type=row.subject_type,
                subject_id=row.subject_id,
                claim=row.claim,
                falsifier=row.falsifier,
                status=row.status.value,
                outcome=row.outcome,
                registered_at=row.registered_at,
                settled_at=row.settled_at,
            )
        )

    def get_prediction(self, prediction_id: str) -> PredictionRow:
        row = self._connection.execute(
            select(sw.predictions).where(sw.predictions.c.prediction_id == prediction_id)
        ).mappings().one()
        return from_row(PredictionRow, row, status=PredictionStatus)

    def update_prediction_outcome(
        self, prediction_id: str, outcome: str, status: str, settled_at: str
    ) -> None:
        self._connection.execute(
            update(sw.predictions)
            .where(sw.predictions.c.prediction_id == prediction_id)
            .values(status=status, outcome=outcome, settled_at=settled_at)
        )

    def iter_predictions(self) -> list[PredictionRow]:
        rows = (
            self._connection.execute(
                select(sw.predictions).order_by(
                    sw.predictions.c.registered_at,
                    sw.predictions.c.prediction_id,
                )
            )
            .mappings()
            .all()
        )
        return [from_row(PredictionRow, row, status=PredictionStatus) for row in rows]

    def match_for_subject(self, subject_type: str, subject_id: str) -> str | None:
        if subject_type == 'match':
            return self._connection.execute(
                select(si.matches.c.match_id).where(si.matches.c.match_id == subject_id)
            ).scalar_one_or_none()
        if subject_type in {'forecast', 'forecast_revision'}:
            return self._connection.execute(
                select(sd.forecast_series.c.match_id)
                .select_from(
                    sd.forecast_revisions.join(
                        sd.forecast_series,
                        sd.forecast_revisions.c.forecast_series_id
                        == sd.forecast_series.c.forecast_series_id,
                    )
                )
                .where(sd.forecast_revisions.c.forecast_revision_id == subject_id)
            ).scalar_one_or_none()
        if subject_type == 'prediction':
            return self._connection.execute(
                select(sw.predictions.c.match_id).where(
                    sw.predictions.c.prediction_id == subject_id
                )
            ).scalar_one_or_none()
        if subject_type == 'flag_instance':
            return self._connection.execute(
                select(sw.flag_instances.c.match_id).where(
                    sw.flag_instances.c.flag_instance_id == subject_id
                )
            ).scalar_one_or_none()
        if subject_type == 'ticket':
            match_ids = self._connection.execute(
                select(sf.bet_legs.c.match_id)
                .where(sf.bet_legs.c.ticket_id == subject_id)
                .distinct()
            ).scalars().all()
            return match_ids[0] if len(match_ids) == 1 else None
        return None
