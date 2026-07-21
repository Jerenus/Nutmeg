"""Evidence persistence: claims, status events, spans, observations.

Claims are immutable; ``update_claim_status`` moves the current-status projection
and ``insert_claim_status_event`` records the transition, so the adjudication
trail is replayable. Conflicting claims for the same subject coexist. Observations
serialize their value/quality through the canonical serializer and link to the
ArtifactRetrievals that back them.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import Connection, func, insert, select, update

from nutmeg.ontology.actions.models import canonical_json
from nutmeg.ontology.repository import schema_evidence as se


@dataclass(frozen=True, slots=True)
class ClaimRow:
    claim_id: str
    subject_type: str
    subject_id: str
    predicate: str
    value: dict[str, object]
    scope_match_id: str | None
    valid_from: str
    valid_to: str | None
    status: str
    extractor: str
    extractor_version: str
    created_at: str
    adjudicated_at: str | None


@dataclass(frozen=True, slots=True)
class ClaimEvidenceSpanRow:
    claim_evidence_span_id: str
    claim_id: str
    artifact_id: str
    artifact_retrieval_id: str
    quote: str
    locator: str | None


@dataclass(frozen=True, slots=True)
class ObservationRow:
    observation_id: str
    observation_type: str
    subject_type: str
    subject_id: str
    scope_match_id: str | None
    value: dict[str, object]
    schema_version: str
    valid_from: str
    valid_to: str | None
    observed_at: str
    recorded_at: str
    verification_method: str
    quality: dict[str, object]


class EvidenceRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def insert_claim(self, row: ClaimRow) -> None:
        self._connection.execute(
            insert(se.claims).values(
                claim_id=row.claim_id,
                subject_type=row.subject_type,
                subject_id=row.subject_id,
                predicate=row.predicate,
                value_json=canonical_json(row.value),
                scope_match_id=row.scope_match_id,
                valid_from=row.valid_from,
                valid_to=row.valid_to,
                status=row.status,
                extractor=row.extractor,
                extractor_version=row.extractor_version,
                created_at=row.created_at,
                adjudicated_at=row.adjudicated_at,
            )
        )

    def insert_claim_status_event(
        self,
        claim_status_event_id: str,
        claim_id: str,
        from_status: str | None,
        to_status: str,
        action_id: str,
        at: str,
    ) -> None:
        self._connection.execute(
            insert(se.claim_status_events).values(
                claim_status_event_id=claim_status_event_id,
                claim_id=claim_id,
                from_status=from_status,
                to_status=to_status,
                action_id=action_id,
                at=at,
            )
        )

    def insert_evidence_span(self, row: ClaimEvidenceSpanRow) -> None:
        self._connection.execute(
            insert(se.claim_evidence_spans).values(
                claim_evidence_span_id=row.claim_evidence_span_id,
                claim_id=row.claim_id,
                artifact_id=row.artifact_id,
                artifact_retrieval_id=row.artifact_retrieval_id,
                quote=row.quote,
                locator=row.locator,
            )
        )

    def update_claim_status(self, claim_id: str, to_status: str, adjudicated_at: str) -> None:
        self._connection.execute(
            update(se.claims)
            .where(se.claims.c.claim_id == claim_id)
            .values(status=to_status, adjudicated_at=adjudicated_at)
        )

    def insert_observation(
        self, row: ObservationRow, artifact_retrieval_ids: tuple[str, ...] = ()
    ) -> None:
        self._connection.execute(
            insert(se.observations).values(
                observation_id=row.observation_id,
                observation_type=row.observation_type,
                subject_type=row.subject_type,
                subject_id=row.subject_id,
                scope_match_id=row.scope_match_id,
                value_json=canonical_json(row.value),
                schema_version=row.schema_version,
                valid_from=row.valid_from,
                valid_to=row.valid_to,
                observed_at=row.observed_at,
                recorded_at=row.recorded_at,
                verification_method=row.verification_method,
                quality_json=canonical_json(row.quality),
            )
        )
        if artifact_retrieval_ids:
            self._connection.execute(
                insert(se.observation_sources),
                [
                    {'observation_id': row.observation_id, 'artifact_retrieval_id': retrieval_id}
                    for retrieval_id in artifact_retrieval_ids
                ],
            )

    def link_observation_claim(self, observation_id: str, claim_id: str) -> None:
        self._connection.execute(
            insert(se.observation_claims).values(
                observation_id=observation_id, claim_id=claim_id
            )
        )

    def claims_for(self, subject_type: str, subject_id: str) -> list[ClaimRow]:
        rows = (
            self._connection.execute(
                select(se.claims).where(
                    se.claims.c.subject_type == subject_type,
                    se.claims.c.subject_id == subject_id,
                )
            )
            .mappings()
            .all()
        )
        return [
            ClaimRow(
                claim_id=row['claim_id'],
                subject_type=row['subject_type'],
                subject_id=row['subject_id'],
                predicate=row['predicate'],
                value=json.loads(row['value_json']),
                scope_match_id=row['scope_match_id'],
                valid_from=row['valid_from'],
                valid_to=row['valid_to'],
                status=row['status'],
                extractor=row['extractor'],
                extractor_version=row['extractor_version'],
                created_at=row['created_at'],
                adjudicated_at=row['adjudicated_at'],
            )
            for row in rows
        ]

    def claim_status(self, claim_id: str) -> str:
        return self._connection.execute(
            select(se.claims.c.status).where(se.claims.c.claim_id == claim_id)
        ).scalar_one()

    def claim_status_history(self, claim_id: str) -> list[tuple[str | None, str]]:
        rows = self._connection.execute(
            select(se.claim_status_events.c.from_status, se.claim_status_events.c.to_status)
            .where(se.claim_status_events.c.claim_id == claim_id)
            .order_by(se.claim_status_events.c.at)
        ).all()
        return [(from_status, to_status) for from_status, to_status in rows]

    def count_claims(self) -> int:
        return self._connection.execute(select(func.count()).select_from(se.claims)).scalar_one()

    def count_observations(self) -> int:
        return self._connection.execute(
            select(func.count()).select_from(se.observations)
        ).scalar_one()
