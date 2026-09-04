"""Typed persistence for protected ticket batches and placement confirmation."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from sqlalchemy import Connection, func, insert, select, update

from nutmeg.ontology.actions.models import canonical_json
from nutmeg.ontology.errors import OptimisticConcurrencyError
from nutmeg.ontology.operator.models import (
    ArtifactTerminalReceiptRow,
    ArtifactWorkItemLinkRow,
    ConfirmationChallengeHeadRow,
    ConfirmationChallengeRevisionRow,
    ProtectedArtifactBindingRow,
    ProtectedArtifactOfferRevisionLinkRow,
)
from nutmeg.ontology.repository import schema_tickets as st


@dataclass(frozen=True, slots=True)
class TicketBatchRevisionRow:
    ticket_batch_revision_id: str
    ticket_batch_id: str
    revision_no: int
    supersedes_revision_id: str | None
    run_date: str
    channel: str
    account_id: str
    currency: str
    deadline_at: str
    input_legs: list[dict[str, object]]
    composition: dict[str, object]
    audit_findings: list[dict[str, object]]
    state: str
    content_hash: str
    source_artifact_id: str
    created_at: str
    created_by_action_id: str


@dataclass(frozen=True, slots=True)
class AuditedTicketArtifactRow:
    ticket_artifact_id: str
    ticket_batch_revision_id: str
    ticket_index: int
    ticket_hash: str
    source_artifact_id: str
    amount: float
    currency: str
    channel: str
    deadline_at: str
    payload: dict[str, object]
    approved_at: str
    approved_by_action_id: str


@dataclass(frozen=True, slots=True)
class ConfirmationChallengeRow:
    confirmation_id: str
    ticket_artifact_id: str
    nonce_hash: str
    ticket_hash: str
    amount: float
    currency: str
    channel: str
    issued_at: str
    expires_at: str
    consumed_at: str | None
    consumed_by_action_id: str | None


@dataclass(frozen=True, slots=True)
class TicketPlacementRow:
    ticket_placement_id: str
    ticket_artifact_id: str
    ticket_id: str
    placement_mode: str
    external_reference: str
    receipt_artifact_id: str | None
    receipt_retrieval_id: str | None
    placed_at: str
    action_id: str


@dataclass(frozen=True, slots=True)
class TicketShadowRow:
    ticket_shadow_id: str
    ticket_artifact_id: str
    confirmation_id: str
    reason: str
    deadline_at: str
    marked_at: str
    action_id: str


class TicketWorkbenchRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def insert_artifact_work_item_link(self, row: ArtifactWorkItemLinkRow) -> None:
        self._connection.execute(
            insert(st.operator_artifact_work_item_links).values(**asdict(row))
        )

    def artifact_work_item_link(
        self, ticket_artifact_id: str
    ) -> ArtifactWorkItemLinkRow | None:
        row = (
            self._connection.execute(
                select(st.operator_artifact_work_item_links).where(
                    st.operator_artifact_work_item_links.c.ticket_artifact_id
                    == ticket_artifact_id
                )
            )
            .mappings()
            .first()
        )
        return ArtifactWorkItemLinkRow(**dict(row)) if row is not None else None

    def artifact_work_item_links_for_work_item(
        self, work_item_id: str
    ) -> tuple[ArtifactWorkItemLinkRow, ...]:
        rows = self._connection.execute(
            select(st.operator_artifact_work_item_links)
            .where(st.operator_artifact_work_item_links.c.work_item_id == work_item_id)
            .order_by(st.operator_artifact_work_item_links.c.ticket_artifact_id)
        ).mappings()
        return tuple(ArtifactWorkItemLinkRow(**dict(row)) for row in rows)

    def insert_protected_artifact_binding(
        self, row: ProtectedArtifactBindingRow
    ) -> None:
        self._connection.execute(
            insert(st.operator_protected_artifact_bindings).values(**asdict(row))
        )

    def protected_artifact_binding(
        self, ticket_artifact_id: str
    ) -> ProtectedArtifactBindingRow | None:
        row = (
            self._connection.execute(
                select(st.operator_protected_artifact_bindings).where(
                    st.operator_protected_artifact_bindings.c.ticket_artifact_id
                    == ticket_artifact_id
                )
            )
            .mappings()
            .first()
        )
        return ProtectedArtifactBindingRow(**dict(row)) if row is not None else None

    def insert_protected_artifact_offer_revision_link(
        self, row: ProtectedArtifactOfferRevisionLinkRow
    ) -> None:
        self._connection.execute(
            insert(st.operator_protected_artifact_offer_revision_links).values(
                **asdict(row)
            )
        )

    def protected_artifact_offer_revision_links(
        self, ticket_artifact_id: str
    ) -> tuple[ProtectedArtifactOfferRevisionLinkRow, ...]:
        rows = self._connection.execute(
            select(st.operator_protected_artifact_offer_revision_links)
            .where(
                st.operator_protected_artifact_offer_revision_links.c.ticket_artifact_id
                == ticket_artifact_id
            )
            .order_by(
                st.operator_protected_artifact_offer_revision_links.c.offer_index
            )
        ).mappings()
        return tuple(
            ProtectedArtifactOfferRevisionLinkRow(**dict(row)) for row in rows
        )

    def insert_confirmation_challenge_revision(
        self, row: ConfirmationChallengeRevisionRow
    ) -> None:
        self._connection.execute(
            insert(st.operator_confirmation_challenge_revisions).values(**asdict(row))
        )

    def confirmation_challenge_revision(
        self, challenge_revision_id: str
    ) -> ConfirmationChallengeRevisionRow | None:
        row = (
            self._connection.execute(
                select(st.operator_confirmation_challenge_revisions).where(
                    st.operator_confirmation_challenge_revisions.c.challenge_revision_id
                    == challenge_revision_id
                )
            )
            .mappings()
            .first()
        )
        return (
            ConfirmationChallengeRevisionRow(**dict(row))
            if row is not None
            else None
        )

    def insert_confirmation_challenge_head(
        self, row: ConfirmationChallengeHeadRow
    ) -> None:
        self._connection.execute(
            insert(st.operator_confirmation_challenge_heads).values(**asdict(row))
        )

    def confirmation_challenge_head(
        self, ticket_artifact_id: str
    ) -> ConfirmationChallengeHeadRow | None:
        row = (
            self._connection.execute(
                select(st.operator_confirmation_challenge_heads).where(
                    st.operator_confirmation_challenge_heads.c.ticket_artifact_id
                    == ticket_artifact_id
                )
            )
            .mappings()
            .first()
        )
        return ConfirmationChallengeHeadRow(**dict(row)) if row is not None else None

    def insert_artifact_terminal_receipt(
        self, row: ArtifactTerminalReceiptRow
    ) -> None:
        self._connection.execute(
            insert(st.operator_artifact_terminal_receipts).values(**asdict(row))
        )

    def artifact_terminal_receipt(
        self, ticket_artifact_id: str
    ) -> ArtifactTerminalReceiptRow | None:
        row = (
            self._connection.execute(
                select(st.operator_artifact_terminal_receipts).where(
                    st.operator_artifact_terminal_receipts.c.ticket_artifact_id
                    == ticket_artifact_id
                )
            )
            .mappings()
            .first()
        )
        return ArtifactTerminalReceiptRow(**dict(row)) if row is not None else None

    def insert_batch_revision(self, row: TicketBatchRevisionRow) -> None:
        self._connection.execute(
            insert(st.ticket_batch_revisions).values(
                ticket_batch_revision_id=row.ticket_batch_revision_id,
                ticket_batch_id=row.ticket_batch_id,
                revision_no=row.revision_no,
                supersedes_revision_id=row.supersedes_revision_id,
                run_date=row.run_date,
                channel=row.channel,
                account_id=row.account_id,
                currency=row.currency,
                deadline_at=row.deadline_at,
                input_legs_json=canonical_json(row.input_legs),
                composition_json=canonical_json(row.composition),
                audit_findings_json=canonical_json(row.audit_findings),
                state=row.state,
                content_hash=row.content_hash,
                source_artifact_id=row.source_artifact_id,
                created_at=row.created_at,
                created_by_action_id=row.created_by_action_id,
            )
        )

    def batch_revision(self, revision_id: str) -> TicketBatchRevisionRow | None:
        row = (
            self._connection.execute(
                select(st.ticket_batch_revisions).where(
                    st.ticket_batch_revisions.c.ticket_batch_revision_id == revision_id
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else self._batch_row(row)

    def current_batch_revision(self, batch_id: str) -> TicketBatchRevisionRow | None:
        row = (
            self._connection.execute(
                select(st.ticket_batch_revisions)
                .where(st.ticket_batch_revisions.c.ticket_batch_id == batch_id)
                .order_by(st.ticket_batch_revisions.c.revision_no.desc())
                .limit(1)
            )
            .mappings()
            .first()
        )
        return None if row is None else self._batch_row(row)

    def assert_current_revision(
        self, batch_id: str, expected_revision_no: int
    ) -> TicketBatchRevisionRow:
        current = self.current_batch_revision(batch_id)
        if current is None:
            raise ValueError(f"ticket batch {batch_id} does not exist")
        if current.revision_no != expected_revision_no:
            raise OptimisticConcurrencyError(
                f"ticket batch {batch_id} is at revision {current.revision_no}, "
                f"expected {expected_revision_no}"
            )
        return current

    def batch_history(self, batch_id: str) -> list[TicketBatchRevisionRow]:
        rows = (
            self._connection.execute(
                select(st.ticket_batch_revisions)
                .where(st.ticket_batch_revisions.c.ticket_batch_id == batch_id)
                .order_by(st.ticket_batch_revisions.c.revision_no)
            )
            .mappings()
            .all()
        )
        return [self._batch_row(row) for row in rows]

    def insert_ticket_artifact(self, row: AuditedTicketArtifactRow) -> None:
        self._connection.execute(
            insert(st.audited_ticket_artifacts).values(
                ticket_artifact_id=row.ticket_artifact_id,
                ticket_batch_revision_id=row.ticket_batch_revision_id,
                ticket_index=row.ticket_index,
                ticket_hash=row.ticket_hash,
                source_artifact_id=row.source_artifact_id,
                amount=row.amount,
                currency=row.currency,
                channel=row.channel,
                deadline_at=row.deadline_at,
                payload_json=canonical_json(row.payload),
                approved_at=row.approved_at,
                approved_by_action_id=row.approved_by_action_id,
            )
        )

    def ticket_artifacts_for_revision(
        self, revision_id: str
    ) -> list[AuditedTicketArtifactRow]:
        rows = (
            self._connection.execute(
                select(st.audited_ticket_artifacts)
                .where(
                    st.audited_ticket_artifacts.c.ticket_batch_revision_id
                    == revision_id
                )
                .order_by(st.audited_ticket_artifacts.c.ticket_index)
            )
            .mappings()
            .all()
        )
        return [self._artifact_row(row) for row in rows]

    def ticket_artifact(self, artifact_id: str) -> AuditedTicketArtifactRow | None:
        row = (
            self._connection.execute(
                select(st.audited_ticket_artifacts).where(
                    st.audited_ticket_artifacts.c.ticket_artifact_id == artifact_id
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else self._artifact_row(row)

    def insert_confirmation(self, row: ConfirmationChallengeRow) -> None:
        self._connection.execute(
            insert(st.ticket_confirmation_challenges).values(**asdict(row))
        )

    def confirmation(self, confirmation_id: str) -> ConfirmationChallengeRow | None:
        row = (
            self._connection.execute(
                select(st.ticket_confirmation_challenges).where(
                    st.ticket_confirmation_challenges.c.confirmation_id
                    == confirmation_id
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else ConfirmationChallengeRow(**dict(row))

    def confirmation_by_nonce_hash(
        self, nonce_hash: str
    ) -> ConfirmationChallengeRow | None:
        row = (
            self._connection.execute(
                select(st.ticket_confirmation_challenges).where(
                    st.ticket_confirmation_challenges.c.nonce_hash == nonce_hash
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else ConfirmationChallengeRow(**dict(row))

    def consume_confirmation(
        self, confirmation_id: str, consumed_at: str, action_id: str
    ) -> None:
        result = self._connection.execute(
            update(st.ticket_confirmation_challenges)
            .where(
                st.ticket_confirmation_challenges.c.confirmation_id == confirmation_id,
                st.ticket_confirmation_challenges.c.consumed_at.is_(None),
            )
            .values(consumed_at=consumed_at, consumed_by_action_id=action_id)
        )
        if result.rowcount != 1:
            raise OptimisticConcurrencyError(
                f"confirmation {confirmation_id} is already consumed"
            )

    def invalidate_open_confirmations(
        self, ticket_artifact_id: str, consumed_at: str, action_id: str
    ) -> None:
        self._connection.execute(
            update(st.ticket_confirmation_challenges)
            .where(
                st.ticket_confirmation_challenges.c.ticket_artifact_id
                == ticket_artifact_id,
                st.ticket_confirmation_challenges.c.consumed_at.is_(None),
            )
            .values(consumed_at=consumed_at, consumed_by_action_id=action_id)
        )

    def insert_placement(self, row: TicketPlacementRow) -> None:
        self._connection.execute(insert(st.ticket_placements).values(**asdict(row)))

    def placement_for_artifact(self, artifact_id: str) -> TicketPlacementRow | None:
        row = (
            self._connection.execute(
                select(st.ticket_placements).where(
                    st.ticket_placements.c.ticket_artifact_id == artifact_id
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else TicketPlacementRow(**dict(row))

    def insert_shadow(self, row: TicketShadowRow) -> None:
        self._connection.execute(insert(st.ticket_shadow_records).values(**asdict(row)))

    def shadow_for_artifact(self, artifact_id: str) -> TicketShadowRow | None:
        row = (
            self._connection.execute(
                select(st.ticket_shadow_records).where(
                    st.ticket_shadow_records.c.ticket_artifact_id == artifact_id
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else TicketShadowRow(**dict(row))

    def due_shadow_candidates(self, as_of: str) -> list[tuple[str, str]]:
        rows = self._connection.execute(
            select(
                st.audited_ticket_artifacts.c.ticket_artifact_id,
                func.max(st.ticket_confirmation_challenges.c.confirmation_id),
            )
            .join(
                st.ticket_confirmation_challenges,
                st.ticket_confirmation_challenges.c.ticket_artifact_id
                == st.audited_ticket_artifacts.c.ticket_artifact_id,
            )
            .outerjoin(
                st.ticket_placements,
                st.ticket_placements.c.ticket_artifact_id
                == st.audited_ticket_artifacts.c.ticket_artifact_id,
            )
            .outerjoin(
                st.ticket_shadow_records,
                st.ticket_shadow_records.c.ticket_artifact_id
                == st.audited_ticket_artifacts.c.ticket_artifact_id,
            )
            .where(
                st.audited_ticket_artifacts.c.deadline_at <= as_of,
                st.ticket_placements.c.ticket_placement_id.is_(None),
                st.ticket_shadow_records.c.ticket_shadow_id.is_(None),
            )
            .group_by(st.audited_ticket_artifacts.c.ticket_artifact_id)
            .order_by(st.audited_ticket_artifacts.c.ticket_artifact_id)
        ).all()
        return [(str(row[0]), str(row[1])) for row in rows]

    def count_batches(self) -> int:
        return int(
            self._connection.execute(
                select(func.count(func.distinct(st.ticket_batch_revisions.c.ticket_batch_id)))
            ).scalar_one()
        )

    def count_artifacts(self) -> int:
        return int(
            self._connection.execute(
                select(func.count()).select_from(st.audited_ticket_artifacts)
            ).scalar_one()
        )

    def count_placements(self) -> int:
        return int(
            self._connection.execute(
                select(func.count()).select_from(st.ticket_placements)
            ).scalar_one()
        )

    @staticmethod
    def _batch_row(row) -> TicketBatchRevisionRow:
        return TicketBatchRevisionRow(
            ticket_batch_revision_id=row["ticket_batch_revision_id"],
            ticket_batch_id=row["ticket_batch_id"],
            revision_no=row["revision_no"],
            supersedes_revision_id=row["supersedes_revision_id"],
            run_date=row["run_date"],
            channel=row["channel"],
            account_id=row["account_id"],
            currency=row["currency"],
            deadline_at=row["deadline_at"],
            input_legs=json.loads(row["input_legs_json"]),
            composition=json.loads(row["composition_json"]),
            audit_findings=json.loads(row["audit_findings_json"]),
            state=row["state"],
            content_hash=row["content_hash"],
            source_artifact_id=row["source_artifact_id"],
            created_at=row["created_at"],
            created_by_action_id=row["created_by_action_id"],
        )

    @staticmethod
    def _artifact_row(row) -> AuditedTicketArtifactRow:
        return AuditedTicketArtifactRow(
            ticket_artifact_id=row["ticket_artifact_id"],
            ticket_batch_revision_id=row["ticket_batch_revision_id"],
            ticket_index=row["ticket_index"],
            ticket_hash=row["ticket_hash"],
            source_artifact_id=row["source_artifact_id"],
            amount=row["amount"],
            currency=row["currency"],
            channel=row["channel"],
            deadline_at=row["deadline_at"],
            payload=json.loads(row["payload_json"]),
            approved_at=row["approved_at"],
            approved_by_action_id=row["approved_by_action_id"],
        )
