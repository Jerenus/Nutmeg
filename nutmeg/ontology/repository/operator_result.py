"""Typed persistence for operator candidate and fixed-prize result rows."""

from __future__ import annotations

from sqlalchemy import Connection, insert, select

from nutmeg.ontology.operator.models import (
    CandidateAuditFindingRow,
    CandidateDeadFaceRow,
    CandidateMetricRow,
    CandidateTicketLegRow,
    CandidateTicketRow,
    TicketCandidateRow,
    TicketCandidateSetRevisionRow,
    ZucaiFixedPrizePolicyRevisionRow,
    ZucaiFixedPrizePolicyTierRow,
)
from nutmeg.ontology.repository import schema_operator_decision as sod
from nutmeg.ontology.repository import schema_operator_result as sor


class OperatorResultRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def insert_fixed_prize_policy_revision(
        self, row: ZucaiFixedPrizePolicyRevisionRow
    ) -> None:
        self._connection.execute(
            insert(sor.zucai_fixed_prize_policy_revisions).values(
                **_row_fields(row)
            )
        )

    def insert_fixed_prize_policy_tier(
        self, row: ZucaiFixedPrizePolicyTierRow
    ) -> None:
        self._connection.execute(
            insert(sor.zucai_fixed_prize_policy_tiers).values(**_row_fields(row))
        )

    def fixed_prize_policy_revision(
        self, revision_id: str
    ) -> ZucaiFixedPrizePolicyRevisionRow | None:
        row = (
            self._connection.execute(
                select(sor.zucai_fixed_prize_policy_revisions).where(
                    sor.zucai_fixed_prize_policy_revisions.c.
                    fixed_prize_policy_revision_id
                    == revision_id
                )
            )
            .mappings()
            .first()
        )
        return (
            ZucaiFixedPrizePolicyRevisionRow(**dict(row))
            if row is not None
            else None
        )

    def current_fixed_prize_policy(
        self, ticket_kind: str
    ) -> ZucaiFixedPrizePolicyRevisionRow | None:
        row = (
            self._connection.execute(
                select(sor.zucai_fixed_prize_policy_revisions)
                .where(
                    sor.zucai_fixed_prize_policy_revisions.c.ticket_kind
                    == ticket_kind
                )
                .order_by(
                    sor.zucai_fixed_prize_policy_revisions.c.revision_no.desc(),
                    sor.zucai_fixed_prize_policy_revisions.c.created_at.desc(),
                )
                .limit(1)
            )
            .mappings()
            .first()
        )
        return (
            ZucaiFixedPrizePolicyRevisionRow(**dict(row))
            if row is not None
            else None
        )

    def fixed_prize_policy_tiers(
        self, revision_id: str
    ) -> tuple[ZucaiFixedPrizePolicyTierRow, ...]:
        rows = self._connection.execute(
            select(sor.zucai_fixed_prize_policy_tiers)
            .where(
                sor.zucai_fixed_prize_policy_tiers.c.fixed_prize_policy_revision_id
                == revision_id
            )
            .order_by(sor.zucai_fixed_prize_policy_tiers.c.tier_index)
        ).mappings()
        return tuple(ZucaiFixedPrizePolicyTierRow(**dict(row)) for row in rows)

    def insert_candidate_set_revision(
        self, row: TicketCandidateSetRevisionRow
    ) -> None:
        self._connection.execute(
            insert(sod.operator_candidate_set_revisions).values(**_row_fields(row))
        )

    def candidate_set_revision(
        self, revision_id: str
    ) -> TicketCandidateSetRevisionRow | None:
        row = (
            self._connection.execute(
                select(sod.operator_candidate_set_revisions).where(
                    sod.operator_candidate_set_revisions.c.candidate_set_revision_id
                    == revision_id
                )
            )
            .mappings()
            .first()
        )
        return TicketCandidateSetRevisionRow(**dict(row)) if row is not None else None

    def candidate_sets_for_request(
        self, generation_request_id: str
    ) -> tuple[TicketCandidateSetRevisionRow, ...]:
        rows = self._connection.execute(
            select(sod.operator_candidate_set_revisions)
            .where(
                sod.operator_candidate_set_revisions.c.generation_request_id
                == generation_request_id
            )
            .order_by(sod.operator_candidate_set_revisions.c.set_kind)
        ).mappings()
        return tuple(TicketCandidateSetRevisionRow(**dict(row)) for row in rows)

    def candidate_set_for_request(
        self,
        *,
        generation_request_id: str,
        set_kind: str,
    ) -> TicketCandidateSetRevisionRow | None:
        row = (
            self._connection.execute(
                select(sod.operator_candidate_set_revisions).where(
                    sod.operator_candidate_set_revisions.c.generation_request_id
                    == generation_request_id,
                    sod.operator_candidate_set_revisions.c.set_kind == set_kind,
                )
            )
            .mappings()
            .first()
        )
        return TicketCandidateSetRevisionRow(**dict(row)) if row is not None else None

    def current_candidate_set(
        self,
        *,
        task_family_id: str,
        work_item_id: str,
        set_kind: str,
    ) -> TicketCandidateSetRevisionRow | None:
        row = (
            self._connection.execute(
                select(sod.operator_candidate_set_revisions)
                .where(
                    sod.operator_candidate_set_revisions.c.task_family_id
                    == task_family_id,
                    sod.operator_candidate_set_revisions.c.work_item_id
                    == work_item_id,
                    sod.operator_candidate_set_revisions.c.set_kind == set_kind,
                )
                .order_by(
                    sod.operator_candidate_set_revisions.c.revision_no.desc(),
                    sod.operator_candidate_set_revisions.c.created_at.desc(),
                )
                .limit(1)
            )
            .mappings()
            .first()
        )
        return TicketCandidateSetRevisionRow(**dict(row)) if row is not None else None

    def insert_candidate(self, row: TicketCandidateRow) -> None:
        self._connection.execute(
            insert(sod.operator_candidates).values(**_row_fields(row))
        )

    def candidate(self, revision_id: str) -> TicketCandidateRow | None:
        row = (
            self._connection.execute(
                select(sod.operator_candidates).where(
                    sod.operator_candidates.c.candidate_revision_id == revision_id
                )
            )
            .mappings()
            .first()
        )
        return TicketCandidateRow(**dict(row)) if row is not None else None

    def candidates_for_set(
        self, candidate_set_revision_id: str
    ) -> tuple[TicketCandidateRow, ...]:
        rows = self._connection.execute(
            select(sod.operator_candidates)
            .where(
                sod.operator_candidates.c.candidate_set_revision_id
                == candidate_set_revision_id
            )
            .order_by(sod.operator_candidates.c.candidate_index)
        ).mappings()
        return tuple(TicketCandidateRow(**dict(row)) for row in rows)

    def insert_candidate_ticket(self, row: CandidateTicketRow) -> None:
        self._connection.execute(
            insert(sor.operator_candidate_tickets).values(**_row_fields(row))
        )

    def candidate_tickets(
        self, candidate_revision_id: str
    ) -> tuple[CandidateTicketRow, ...]:
        rows = self._connection.execute(
            select(sor.operator_candidate_tickets)
            .where(
                sor.operator_candidate_tickets.c.candidate_revision_id
                == candidate_revision_id
            )
            .order_by(sor.operator_candidate_tickets.c.ticket_index)
        ).mappings()
        return tuple(CandidateTicketRow(**dict(row)) for row in rows)

    def insert_candidate_ticket_leg(self, row: CandidateTicketLegRow) -> None:
        self._connection.execute(
            insert(sor.operator_candidate_ticket_legs).values(**_row_fields(row))
        )

    def candidate_ticket_legs(
        self, candidate_ticket_id: str
    ) -> tuple[CandidateTicketLegRow, ...]:
        rows = self._connection.execute(
            select(sor.operator_candidate_ticket_legs)
            .where(
                sor.operator_candidate_ticket_legs.c.candidate_ticket_id
                == candidate_ticket_id
            )
            .order_by(sor.operator_candidate_ticket_legs.c.leg_index)
        ).mappings()
        return tuple(CandidateTicketLegRow(**dict(row)) for row in rows)

    def insert_candidate_metric(self, row: CandidateMetricRow) -> None:
        self._connection.execute(
            insert(sod.operator_candidate_metrics).values(**_row_fields(row))
        )

    def candidate_metric(self, candidate_revision_id: str) -> CandidateMetricRow | None:
        row = (
            self._connection.execute(
                select(sod.operator_candidate_metrics).where(
                    sod.operator_candidate_metrics.c.candidate_revision_id
                    == candidate_revision_id
                )
            )
            .mappings()
            .first()
        )
        return CandidateMetricRow(**dict(row)) if row is not None else None

    def insert_candidate_dead_face(self, row: CandidateDeadFaceRow) -> None:
        self._connection.execute(
            insert(sod.operator_candidate_dead_faces).values(**_row_fields(row))
        )

    def candidate_dead_faces(
        self, candidate_revision_id: str
    ) -> tuple[CandidateDeadFaceRow, ...]:
        rows = self._connection.execute(
            select(sod.operator_candidate_dead_faces)
            .where(
                sod.operator_candidate_dead_faces.c.candidate_revision_id
                == candidate_revision_id
            )
            .order_by(sod.operator_candidate_dead_faces.c.dead_face_index)
        ).mappings()
        return tuple(CandidateDeadFaceRow(**dict(row)) for row in rows)

    def insert_candidate_audit_finding(
        self, row: CandidateAuditFindingRow
    ) -> None:
        self._connection.execute(
            insert(sod.operator_candidate_audit_findings).values(**_row_fields(row))
        )

    def candidate_audit_findings(
        self, candidate_revision_id: str
    ) -> tuple[CandidateAuditFindingRow, ...]:
        rows = self._connection.execute(
            select(sod.operator_candidate_audit_findings)
            .where(
                sod.operator_candidate_audit_findings.c.candidate_revision_id
                == candidate_revision_id
            )
            .order_by(sod.operator_candidate_audit_findings.c.finding_index)
        ).mappings()
        return tuple(CandidateAuditFindingRow(**dict(row)) for row in rows)


def _row_fields(row) -> dict[str, object]:
    return {name: getattr(row, name) for name in row.__dataclass_fields__}


__all__ = ["OperatorResultRepository"]
