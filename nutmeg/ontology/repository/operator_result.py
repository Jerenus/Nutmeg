"""Typed persistence for operator candidate and fixed-prize result rows."""

from __future__ import annotations

import json

from sqlalchemy import Connection, exists, insert, select

from nutmeg.ontology.actions.models import canonical_json
from nutmeg.ontology.operator.models import (
    CandidateAuditFindingRow,
    CandidateDeadFaceRow,
    CandidateGenerationOverrideLinkRow,
    CandidateMetricRow,
    CandidateTicketLegRow,
    CandidateTicketRow,
    NoTicketArtifactScopeRow,
    NoTicketCommandReceiptRow,
    NoTicketOfferScopeRow,
    NoTicketRevisionRow,
    ReviewEligibilityFactRow,
    TicketAuditOverrideReceiptRow,
    TicketCandidateRow,
    TicketCandidateSetRevisionRow,
    TicketDecisionLineageItemRow,
    TicketDecisionLineageRevisionRow,
    ZucaiFixedPrizePolicyRevisionRow,
    ZucaiFixedPrizePolicyTierRow,
)
from nutmeg.ontology.repository import schema_operator_decision as sod
from nutmeg.ontology.repository import schema_operator_result as sor


class OperatorResultRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def insert_ticket_decision_lineage_revision(
        self, row: TicketDecisionLineageRevisionRow
    ) -> None:
        self._connection.execute(
            insert(sod.operator_ticket_decision_lineage_revisions).values(
                **_row_fields(row)
            )
        )

    def ticket_decision_lineage_revision(
        self, lineage_revision_id: str
    ) -> TicketDecisionLineageRevisionRow | None:
        row = (
            self._connection.execute(
                select(sod.operator_ticket_decision_lineage_revisions).where(
                    sod.operator_ticket_decision_lineage_revisions.c.lineage_revision_id
                    == lineage_revision_id
                )
            )
            .mappings()
            .first()
        )
        return (
            TicketDecisionLineageRevisionRow(**dict(row))
            if row is not None
            else None
        )

    def ticket_decision_lineage_for_batch(
        self, ticket_batch_revision_id: str
    ) -> TicketDecisionLineageRevisionRow | None:
        row = (
            self._connection.execute(
                select(sod.operator_ticket_decision_lineage_revisions)
                .where(
                    sod.operator_ticket_decision_lineage_revisions.c.
                    ticket_batch_revision_id
                    == ticket_batch_revision_id
                )
                .order_by(
                    sod.operator_ticket_decision_lineage_revisions.c.revision_no.desc()
                )
                .limit(1)
            )
            .mappings()
            .first()
        )
        return (
            TicketDecisionLineageRevisionRow(**dict(row))
            if row is not None
            else None
        )

    def current_ticket_decision_lineage(
        self, lineage_family_id: str
    ) -> TicketDecisionLineageRevisionRow | None:
        revisions = sod.operator_ticket_decision_lineage_revisions
        children = revisions.alias("lineage_children")
        row = (
            self._connection.execute(
                select(revisions).where(
                    revisions.c.lineage_family_id == lineage_family_id,
                    ~exists(
                        select(1).where(
                            children.c.supersedes_revision_id
                            == revisions.c.lineage_revision_id
                        )
                    ),
                )
            )
            .mappings()
            .first()
        )
        return (
            TicketDecisionLineageRevisionRow(**dict(row))
            if row is not None
            else None
        )

    def insert_ticket_decision_lineage_item(
        self, row: TicketDecisionLineageItemRow
    ) -> None:
        self._connection.execute(
            insert(sod.operator_ticket_decision_lineage_items).values(
                **_row_fields(row)
            )
        )

    def ticket_decision_lineage_items(
        self, lineage_revision_id: str
    ) -> tuple[TicketDecisionLineageItemRow, ...]:
        rows = self._connection.execute(
            select(sod.operator_ticket_decision_lineage_items)
            .where(
                sod.operator_ticket_decision_lineage_items.c.lineage_revision_id
                == lineage_revision_id
            )
            .order_by(sod.operator_ticket_decision_lineage_items.c.item_index)
        ).mappings()
        return tuple(TicketDecisionLineageItemRow(**dict(row)) for row in rows)

    def insert_ticket_audit_override_receipt(
        self, row: TicketAuditOverrideReceiptRow
    ) -> None:
        values = _row_fields(row)
        values["rule_ids_json"] = canonical_json(list(values.pop("rule_ids")))
        values["evidence_rejected_json"] = canonical_json(
            list(values.pop("evidence_rejected"))
        )
        self._connection.execute(
            insert(sod.operator_ticket_audit_override_receipts).values(**values)
        )

    def ticket_audit_override_receipt(
        self, receipt_id: str
    ) -> TicketAuditOverrideReceiptRow | None:
        row = (
            self._connection.execute(
                select(sod.operator_ticket_audit_override_receipts).where(
                    sod.operator_ticket_audit_override_receipts.c.
                    ticket_audit_override_receipt_id
                    == receipt_id
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else _ticket_audit_override_row(row)

    def ticket_audit_override_receipts_for_batch(
        self, ticket_batch_revision_id: str
    ) -> tuple[TicketAuditOverrideReceiptRow, ...]:
        rows = self._connection.execute(
            select(sod.operator_ticket_audit_override_receipts)
            .where(
                sod.operator_ticket_audit_override_receipts.c.ticket_batch_revision_id
                == ticket_batch_revision_id
            )
            .order_by(
                sod.operator_ticket_audit_override_receipts.c.action_id,
                sod.operator_ticket_audit_override_receipts.c.receipt_index,
            )
        ).mappings()
        return tuple(_ticket_audit_override_row(row) for row in rows)

    def insert_candidate_generation_override_link(
        self, row: CandidateGenerationOverrideLinkRow
    ) -> None:
        self._connection.execute(
            insert(sod.operator_candidate_generation_override_links).values(
                **_row_fields(row)
            )
        )

    def candidate_generation_override_links(
        self, generation_request_id: str
    ) -> tuple[CandidateGenerationOverrideLinkRow, ...]:
        rows = self._connection.execute(
            select(sod.operator_candidate_generation_override_links)
            .where(
                sod.operator_candidate_generation_override_links.c.generation_request_id
                == generation_request_id
            )
            .order_by(
                sod.operator_candidate_generation_override_links.c.link_index
            )
        ).mappings()
        return tuple(CandidateGenerationOverrideLinkRow(**dict(row)) for row in rows)

    def candidate_generation_override_links_for_batch(
        self, ticket_batch_revision_id: str
    ) -> tuple[CandidateGenerationOverrideLinkRow, ...]:
        links = sod.operator_candidate_generation_override_links
        receipts = sod.operator_ticket_audit_override_receipts
        rows = self._connection.execute(
            select(links)
            .join(
                receipts,
                receipts.c.ticket_audit_override_receipt_id
                == links.c.override_receipt_id,
            )
            .where(receipts.c.ticket_batch_revision_id == ticket_batch_revision_id)
            .order_by(links.c.generation_request_id, links.c.link_index)
        ).mappings()
        return tuple(CandidateGenerationOverrideLinkRow(**dict(row)) for row in rows)

    def insert_review_eligibility_fact(
        self, row: ReviewEligibilityFactRow
    ) -> None:
        self._connection.execute(
            insert(sor.operator_review_eligibility_facts).values(**_row_fields(row))
        )

    def review_eligibility_facts_for_work_item(
        self, work_item_id: str
    ) -> tuple[ReviewEligibilityFactRow, ...]:
        rows = self._connection.execute(
            select(sor.operator_review_eligibility_facts)
            .where(
                sor.operator_review_eligibility_facts.c.work_item_id == work_item_id
            )
            .order_by(
                sor.operator_review_eligibility_facts.c.created_at,
                sor.operator_review_eligibility_facts.c.fact_index,
            )
        ).mappings()
        return tuple(ReviewEligibilityFactRow(**dict(row)) for row in rows)

    def insert_no_ticket_revision(self, row: NoTicketRevisionRow) -> None:
        values = _row_fields(row)
        for name in (
            "rule_ids",
            "missing_requirement_ids",
            "stale_requirement_ids",
            "conflicting_requirement_ids",
        ):
            values[f"{name}_json"] = canonical_json(list(values.pop(name)))
        self._connection.execute(
            insert(sod.operator_no_ticket_revisions).values(**values)
        )

    def no_ticket_revision(
        self, no_ticket_revision_id: str
    ) -> NoTicketRevisionRow | None:
        row = (
            self._connection.execute(
                select(sod.operator_no_ticket_revisions).where(
                    sod.operator_no_ticket_revisions.c.no_ticket_revision_id
                    == no_ticket_revision_id
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else _no_ticket_revision_row(row)

    def current_no_ticket_revision(
        self, no_ticket_family_id: str
    ) -> NoTicketRevisionRow | None:
        revisions = sod.operator_no_ticket_revisions
        children = revisions.alias("no_ticket_children")
        row = (
            self._connection.execute(
                select(revisions).where(
                    revisions.c.no_ticket_family_id == no_ticket_family_id,
                    ~exists(
                        select(1).where(
                            children.c.supersedes_revision_id
                            == revisions.c.no_ticket_revision_id
                        )
                    ),
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else _no_ticket_revision_row(row)

    def current_no_ticket_for_work_item(
        self, work_item_id: str
    ) -> NoTicketRevisionRow | None:
        revisions = sod.operator_no_ticket_revisions
        children = revisions.alias("work_item_no_ticket_children")
        row = (
            self._connection.execute(
                select(revisions).where(
                    revisions.c.work_item_id == work_item_id,
                    ~exists(
                        select(1).where(
                            children.c.supersedes_revision_id
                            == revisions.c.no_ticket_revision_id
                        )
                    ),
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else _no_ticket_revision_row(row)

    def current_no_ticket_revisions_for_task_family(
        self,
        task_family_id: str,
    ) -> tuple[NoTicketRevisionRow, ...]:
        revisions = sod.operator_no_ticket_revisions
        children = revisions.alias("task_family_no_ticket_children")
        rows = self._connection.execute(
            select(revisions)
            .where(
                revisions.c.task_family_id == task_family_id,
                ~exists(
                    select(1).where(
                        children.c.supersedes_revision_id
                        == revisions.c.no_ticket_revision_id
                    )
                ),
            )
            .order_by(revisions.c.recorded_at, revisions.c.no_ticket_revision_id)
        ).mappings()
        return tuple(_no_ticket_revision_row(row) for row in rows)

    def insert_no_ticket_offer_scope(self, row: NoTicketOfferScopeRow) -> None:
        self._connection.execute(
            insert(sod.operator_no_ticket_offer_scopes).values(**_row_fields(row))
        )

    def no_ticket_offer_scopes(
        self, no_ticket_revision_id: str
    ) -> tuple[NoTicketOfferScopeRow, ...]:
        rows = self._connection.execute(
            select(sod.operator_no_ticket_offer_scopes)
            .where(
                sod.operator_no_ticket_offer_scopes.c.no_ticket_revision_id
                == no_ticket_revision_id
            )
            .order_by(sod.operator_no_ticket_offer_scopes.c.scope_index)
        ).mappings()
        return tuple(NoTicketOfferScopeRow(**dict(row)) for row in rows)

    def insert_no_ticket_artifact_scope(
        self, row: NoTicketArtifactScopeRow
    ) -> None:
        self._connection.execute(
            insert(sod.operator_no_ticket_artifact_scopes).values(**_row_fields(row))
        )

    def no_ticket_artifact_scopes(
        self, no_ticket_revision_id: str
    ) -> tuple[NoTicketArtifactScopeRow, ...]:
        rows = self._connection.execute(
            select(sod.operator_no_ticket_artifact_scopes)
            .where(
                sod.operator_no_ticket_artifact_scopes.c.no_ticket_revision_id
                == no_ticket_revision_id
            )
            .order_by(sod.operator_no_ticket_artifact_scopes.c.scope_index)
        ).mappings()
        return tuple(NoTicketArtifactScopeRow(**dict(row)) for row in rows)

    def insert_no_ticket_command_receipt(
        self, row: NoTicketCommandReceiptRow
    ) -> None:
        self._connection.execute(
            insert(sod.operator_no_ticket_command_receipts).values(**_row_fields(row))
        )

    def no_ticket_command_receipt_for_action(
        self, action_id: str
    ) -> NoTicketCommandReceiptRow | None:
        row = (
            self._connection.execute(
                select(sod.operator_no_ticket_command_receipts).where(
                    sod.operator_no_ticket_command_receipts.c.action_id == action_id
                )
            )
            .mappings()
            .first()
        )
        return NoTicketCommandReceiptRow(**dict(row)) if row is not None else None

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

    def candidate_audit_finding(
        self, candidate_audit_finding_id: str
    ) -> CandidateAuditFindingRow | None:
        row = (
            self._connection.execute(
                select(sod.operator_candidate_audit_findings).where(
                    sod.operator_candidate_audit_findings.c.candidate_audit_finding_id
                    == candidate_audit_finding_id
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else CandidateAuditFindingRow(**dict(row))


def _row_fields(row) -> dict[str, object]:
    return {name: getattr(row, name) for name in row.__dataclass_fields__}


def _ticket_audit_override_row(row) -> TicketAuditOverrideReceiptRow:
    values = dict(row)
    values["rule_ids"] = tuple(json.loads(values.pop("rule_ids_json")))
    values["evidence_rejected"] = tuple(
        json.loads(values.pop("evidence_rejected_json"))
    )
    return TicketAuditOverrideReceiptRow(**values)


def _no_ticket_revision_row(row) -> NoTicketRevisionRow:
    values = dict(row)
    for name in (
        "rule_ids",
        "missing_requirement_ids",
        "stale_requirement_ids",
        "conflicting_requirement_ids",
    ):
        values[name] = tuple(json.loads(values.pop(f"{name}_json")))
    return NoTicketRevisionRow(**values)


__all__ = ["OperatorResultRepository"]
