"""Typed persistence for operator evidence and decision revisions."""

from __future__ import annotations

import json

from sqlalchemy import Connection, and_, func, insert, or_, select

from nutmeg.ontology.actions.models import canonical_json
from nutmeg.ontology.operator.models import (
    EvidenceCoverageReceiptRow,
    EvidenceIntakeObjectRow,
    EvidenceIntakeReceiptRow,
)
from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository import schema_evidence as se
from nutmeg.ontology.repository import schema_operator_decision as sod

_EVIDENCE_SOURCE_KINDS = frozenset(
    {
        "sporttery_official",
        "club_official",
        "league_official",
        "api_football",
        "international_market",
        "authoritative_results",
        "credible_media",
        "okooo_manual",
    }
)


class OperatorDecisionRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def insert_evidence_intake_receipt(self, row: EvidenceIntakeReceiptRow) -> None:
        values = _row_fields(row)
        values["source_retrieval_ids_json"] = canonical_json(
            list(row.source_retrieval_ids)
        )
        values.pop("source_retrieval_ids")
        self._connection.execute(
            insert(sod.operator_evidence_intake_receipts).values(**values)
        )

    def insert_evidence_intake_object(self, row: EvidenceIntakeObjectRow) -> None:
        values = _row_fields(row)
        values["source_retrieval_ids_json"] = canonical_json(
            list(row.source_retrieval_ids)
        )
        values["source_kinds_json"] = canonical_json(list(row.source_kinds))
        values.pop("source_retrieval_ids")
        values.pop("source_kinds")
        values.pop("source_identities")
        self._connection.execute(
            insert(sod.operator_evidence_intake_objects).values(**values)
        )

    def insert_evidence_coverage_receipt(self, row: EvidenceCoverageReceiptRow) -> None:
        values = _row_fields(row)
        values["evidence_ref_tokens_json"] = canonical_json(
            list(row.evidence_ref_tokens)
        )
        values.pop("evidence_ref_tokens")
        self._connection.execute(
            insert(sod.operator_evidence_coverage_receipts).values(**values)
        )

    def evidence_intake_receipt_for_action(
        self, action_id: str
    ) -> EvidenceIntakeReceiptRow | None:
        row = (
            self._connection.execute(
                select(sod.operator_evidence_intake_receipts).where(
                    sod.operator_evidence_intake_receipts.c.action_id == action_id
                )
            )
            .mappings()
            .first()
        )
        return self._receipt(row) if row is not None else None

    def evidence_intake_receipt(
        self, intake_receipt_id: str
    ) -> EvidenceIntakeReceiptRow | None:
        row = (
            self._connection.execute(
                select(sod.operator_evidence_intake_receipts).where(
                    sod.operator_evidence_intake_receipts.c.intake_receipt_id
                    == intake_receipt_id
                )
            )
            .mappings()
            .first()
        )
        return self._receipt(row) if row is not None else None

    def evidence_intake_object_count(self, intake_receipt_id: str) -> int:
        return int(
            self._connection.execute(
                select(func.count())
                .select_from(
                    sod.operator_evidence_intake_objects.outerjoin(
                        se.observations,
                        and_(
                            sod.operator_evidence_intake_objects.c.object_kind
                            == "observation",
                            sod.operator_evidence_intake_objects.c.object_id
                            == se.observations.c.observation_id,
                        ),
                    ).outerjoin(
                        se.claims,
                        and_(
                            sod.operator_evidence_intake_objects.c.object_kind == "claim",
                            sod.operator_evidence_intake_objects.c.object_id
                            == se.claims.c.claim_id,
                        ),
                    )
                )
                .where(
                    sod.operator_evidence_intake_objects.c.intake_receipt_id
                    == intake_receipt_id,
                    or_(
                        se.observations.c.observation_id.is_not(None),
                        se.claims.c.claim_id.is_not(None),
                    ),
                )
            ).scalar_one()
        )

    def evidence_intake_concrete_object_count(self, intake_receipt_id: str) -> int:
        links = sod.operator_evidence_intake_objects
        observation_count = self._connection.scalar(
            select(func.count())
            .select_from(
                links.join(
                    se.observations,
                    links.c.object_id == se.observations.c.observation_id,
                )
            )
            .where(
                links.c.intake_receipt_id == intake_receipt_id,
                links.c.object_kind == "observation",
            )
        )
        claim_count = self._connection.scalar(
            select(func.count())
            .select_from(
                links.join(
                    se.claims,
                    links.c.object_id == se.claims.c.claim_id,
                )
            )
            .where(
                links.c.intake_receipt_id == intake_receipt_id,
                links.c.object_kind == "claim",
            )
        )
        return int(observation_count or 0) + int(claim_count or 0)

    def evidence_intake_objects_for_match(
        self,
        match_id: str,
        *,
        as_of: str,
        lane: str,
        business_key: str,
        slate_revision_id: str,
        task_snapshot_hash: str,
    ) -> tuple[EvidenceIntakeObjectRow, ...]:
        rows = (
            self._connection.execute(
                select(sod.operator_evidence_intake_objects)
                .select_from(
                    sod.operator_evidence_intake_objects.join(
                        sod.operator_evidence_intake_receipts,
                        sod.operator_evidence_intake_objects.c.intake_receipt_id
                        == sod.operator_evidence_intake_receipts.c.intake_receipt_id,
                    )
                )
                .where(
                    sod.operator_evidence_intake_objects.c.match_id == match_id,
                    sod.operator_evidence_intake_receipts.c.lane == lane,
                    sod.operator_evidence_intake_receipts.c.business_key == business_key,
                    sod.operator_evidence_intake_receipts.c.slate_revision_id
                    == slate_revision_id,
                    sod.operator_evidence_intake_receipts.c.task_snapshot_hash
                    == task_snapshot_hash,
                    func.julianday(sod.operator_evidence_intake_receipts.c.created_at)
                    <= func.julianday(as_of),
                )
                .order_by(
                    sod.operator_evidence_intake_receipts.c.created_at,
                    sod.operator_evidence_intake_objects.c.object_index,
                )
            )
            .mappings()
            .all()
        )
        return tuple(self._intake_object(row) for row in rows)

    def evidence_coverage_ref_tokens_for_match(
        self,
        match_id: str,
        *,
        as_of: str,
        lane: str,
        business_key: str,
        slate_revision_id: str,
        task_snapshot_hash: str,
    ) -> tuple[str, ...]:
        rows = self.evidence_coverage_receipts_for_match(
            match_id,
            as_of=as_of,
            lane=lane,
            business_key=business_key,
            slate_revision_id=slate_revision_id,
            task_snapshot_hash=task_snapshot_hash,
        )
        return tuple(
            sorted(
                {
                    str(token)
                    for row in rows
                    for token in row.evidence_ref_tokens
                }
            )
        )

    def evidence_coverage_receipts_for_match(
        self,
        match_id: str,
        *,
        as_of: str,
        lane: str,
        business_key: str,
        slate_revision_id: str,
        task_snapshot_hash: str,
    ) -> tuple[EvidenceCoverageReceiptRow, ...]:
        rows = (
            self._connection.execute(
                select(sod.operator_evidence_coverage_receipts)
                .select_from(
                    sod.operator_evidence_coverage_receipts.join(
                        sod.operator_evidence_intake_receipts,
                        sod.operator_evidence_coverage_receipts.c.intake_receipt_id
                        == sod.operator_evidence_intake_receipts.c.intake_receipt_id,
                    )
                )
                .where(
                    sod.operator_evidence_coverage_receipts.c.match_id == match_id,
                    sod.operator_evidence_intake_receipts.c.lane == lane,
                    sod.operator_evidence_intake_receipts.c.business_key == business_key,
                    sod.operator_evidence_intake_receipts.c.slate_revision_id
                    == slate_revision_id,
                    sod.operator_evidence_intake_receipts.c.task_snapshot_hash
                    == task_snapshot_hash,
                    func.julianday(sod.operator_evidence_intake_receipts.c.created_at)
                    <= func.julianday(as_of),
                )
                .order_by(
                    sod.operator_evidence_intake_receipts.c.created_at,
                    sod.operator_evidence_coverage_receipts.c.coverage_receipt_id,
                )
            )
            .mappings()
            .all()
        )
        return tuple(self._coverage_receipt(row) for row in rows)

    def evidence_lineage_for_refs(
        self,
        match_id: str,
        object_ids: tuple[str, ...],
        *,
        as_of: str,
    ) -> tuple[EvidenceIntakeObjectRow, ...]:
        rows: list[EvidenceIntakeObjectRow] = []
        for object_index, object_id in enumerate(object_ids):
            claim_created_at: str | None = None
            observation = self._connection.execute(
                select(se.observations.c.observation_id, se.observations.c.observed_at).where(
                    se.observations.c.observation_id == object_id,
                    se.observations.c.scope_match_id == match_id,
                    func.julianday(se.observations.c.recorded_at) <= func.julianday(as_of),
                )
            ).mappings().first()
            if observation is not None:
                object_kind = "observation"
                observed_at = str(observation["observed_at"])
                retrieval_ids = tuple(
                    sorted(
                        self._connection.execute(
                            select(se.observation_sources.c.artifact_retrieval_id).where(
                                se.observation_sources.c.observation_id == object_id
                            )
                        ).scalars()
                    )
                )
            else:
                claim = self._connection.execute(
                    select(se.claims.c.claim_id, se.claims.c.created_at).where(
                        se.claims.c.claim_id == object_id,
                        se.claims.c.scope_match_id == match_id,
                        func.julianday(se.claims.c.created_at) <= func.julianday(as_of),
                    )
                ).mappings().first()
                if claim is None:
                    continue
                object_kind = "claim"
                claim_created_at = str(claim["created_at"])
                retrieval_ids = tuple(
                    sorted(
                        set(
                            self._connection.execute(
                                select(
                                    se.claim_evidence_spans.c.artifact_retrieval_id
                                ).where(se.claim_evidence_spans.c.claim_id == object_id)
                            ).scalars()
                        )
                    )
                )
            retrieval_ids, source_kinds, source_identities = (
                self._verified_sources_for_retrievals(retrieval_ids)
            )
            if object_kind == "claim":
                retrieved_at = tuple(
                    self._connection.execute(
                        select(schema.artifact_retrievals.c.retrieved_at).where(
                            schema.artifact_retrievals.c.artifact_retrieval_id.in_(
                                retrieval_ids
                            )
                        )
                    ).scalars()
                )
                observed_at = min(retrieved_at, default=claim_created_at or as_of)
            rows.append(
                EvidenceIntakeObjectRow(
                    intake_object_id=f"coverage-lineage:{object_kind}:{object_id}",
                    intake_receipt_id="",
                    match_id=match_id,
                    object_kind=object_kind,
                    object_id=object_id,
                    object_index=object_index,
                    observed_at=observed_at,
                    source_retrieval_ids=retrieval_ids,
                    source_kinds=source_kinds,
                    source_identities=source_identities,
                )
            )
        return tuple(rows)

    def _verified_sources_for_retrievals(
        self,
        retrieval_ids: tuple[str, ...],
    ) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        if not retrieval_ids:
            return (), (), ()
        rows = tuple(self._connection.execute(
            select(
                schema.artifact_retrievals.c.artifact_retrieval_id,
                schema.artifact_retrievals.c.source_name,
                schema.artifact_retrievals.c.source_type,
                schema.artifact_retrievals.c.status,
                schema.source_runs.c.source_name.label("run_source_name"),
                schema.source_runs.c.source_type.label("run_source_type"),
                schema.source_runs.c.status.label("run_status"),
            )
            .select_from(
                schema.artifact_retrievals.join(
                    schema.source_runs,
                    schema.artifact_retrievals.c.source_run_id
                    == schema.source_runs.c.source_run_id,
                )
            )
            .where(schema.artifact_retrievals.c.artifact_retrieval_id.in_(retrieval_ids))
        ).mappings())
        verified = tuple(
            row
            for row in rows
            if row["status"] == "stored"
            and row["run_status"] == "succeeded"
            and row["source_name"] == row["run_source_name"]
            and row["source_type"] == row["run_source_type"]
            and row["source_type"] in _EVIDENCE_SOURCE_KINDS
        )
        return (
            tuple(sorted(str(row["artifact_retrieval_id"]) for row in verified)),
            tuple(sorted({str(row["source_type"]) for row in verified})),
            tuple(
                sorted(
                    {
                        canonical_json(
                            {
                                "source_name": str(row["source_name"]),
                                "source_type": str(row["source_type"]),
                            }
                        )
                        for row in verified
                    }
                )
            ),
        )

    @staticmethod
    def _receipt(row) -> EvidenceIntakeReceiptRow:
        values = dict(row)
        values["source_retrieval_ids"] = tuple(
            json.loads(values.pop("source_retrieval_ids_json"))
        )
        return EvidenceIntakeReceiptRow(**values)

    def _intake_object(self, row) -> EvidenceIntakeObjectRow:
        values = dict(row)
        requested_retrieval_ids = tuple(
            json.loads(values.pop("source_retrieval_ids_json"))
        )
        values.pop("source_kinds_json")
        (
            values["source_retrieval_ids"],
            values["source_kinds"],
            values["source_identities"],
        ) = self._verified_sources_for_retrievals(requested_retrieval_ids)
        return EvidenceIntakeObjectRow(**values)

    @staticmethod
    def _coverage_receipt(row) -> EvidenceCoverageReceiptRow:
        values = dict(row)
        values["evidence_ref_tokens"] = tuple(
            json.loads(values.pop("evidence_ref_tokens_json"))
        )
        return EvidenceCoverageReceiptRow(**values)


def _row_fields(row) -> dict[str, object]:
    return {name: getattr(row, name) for name in row.__dataclass_fields__}


__all__ = ["OperatorDecisionRepository"]
