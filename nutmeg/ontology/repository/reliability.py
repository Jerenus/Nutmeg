"""Typed persistence for immutable reliability and release records."""
from __future__ import annotations

import json
from dataclasses import asdict

from sqlalchemy import Connection, func, insert, select

from nutmeg.ontology.actions.models import canonical_json
from nutmeg.ontology.reliability.models import (
    ReleaseApprovalRow,
    ReliabilityEvidenceRow,
)
from nutmeg.ontology.repository import schema_reliability as sr


class ReliabilityRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def insert_evidence(self, row: ReliabilityEvidenceRow) -> None:
        values = asdict(row)
        values["report_json"] = canonical_json(values.pop("report"))
        values["source_refs_json"] = canonical_json(values.pop("source_refs"))
        self._connection.execute(insert(sr.reliability_evidence).values(**values))

    def evidence(self, evidence_id: str) -> ReliabilityEvidenceRow | None:
        row = (
            self._connection.execute(
                select(sr.reliability_evidence).where(
                    sr.reliability_evidence.c.reliability_evidence_id == evidence_id
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else self._evidence_row(row)

    def evidence_by_hash(self, content_hash: str) -> ReliabilityEvidenceRow | None:
        row = (
            self._connection.execute(
                select(sr.reliability_evidence).where(
                    sr.reliability_evidence.c.content_hash == content_hash
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else self._evidence_row(row)

    def list_evidence(
        self,
        *,
        kind: str | None = None,
        recorded_to: str | None = None,
    ) -> list[ReliabilityEvidenceRow]:
        query = select(sr.reliability_evidence)
        if kind is not None:
            query = query.where(sr.reliability_evidence.c.evidence_kind == kind)
        if recorded_to is not None:
            query = query.where(sr.reliability_evidence.c.recorded_at <= recorded_to)
        rows = (
            self._connection.execute(
                query.order_by(
                    sr.reliability_evidence.c.recorded_at.desc(),
                    sr.reliability_evidence.c.reliability_evidence_id.desc(),
                )
            )
            .mappings()
            .all()
        )
        return [self._evidence_row(row) for row in rows]

    def latest_by_kind(self, kind: str) -> ReliabilityEvidenceRow | None:
        rows = self.list_evidence(kind=kind)
        return rows[0] if rows else None

    def insert_approval(self, row: ReleaseApprovalRow) -> None:
        self._connection.execute(insert(sr.release_approvals).values(**asdict(row)))

    def approval_for_release(self, release_version: str) -> ReleaseApprovalRow | None:
        row = (
            self._connection.execute(
                select(sr.release_approvals).where(
                    sr.release_approvals.c.release_version == release_version
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else ReleaseApprovalRow(**dict(row))

    def count_evidence(self) -> int:
        return int(
            self._connection.execute(
                select(func.count()).select_from(sr.reliability_evidence)
            ).scalar_one()
        )

    def count_approvals(self) -> int:
        return int(
            self._connection.execute(
                select(func.count()).select_from(sr.release_approvals)
            ).scalar_one()
        )

    @staticmethod
    def _evidence_row(row) -> ReliabilityEvidenceRow:
        values = dict(row)
        values["report"] = json.loads(values.pop("report_json"))
        values["source_refs"] = json.loads(values.pop("source_refs_json"))
        return ReliabilityEvidenceRow(**values)
