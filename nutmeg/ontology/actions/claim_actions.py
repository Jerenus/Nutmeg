"""Claim Actions: AI extraction (provisional) and operator adjudication.

`extract_claim` is the ai_extractor-only path: it records an immutable provisional
Claim with evidence spans and an initial status event — it can never mark a fact
verified. Conflicting claims for the same subject coexist; nothing is
auto-overwritten. Adjudication (verify/dispute/retract) is a separate operator
Action that appends a replayable status event.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from nutmeg.ontology.actions.models import ActionCommand, ActionOutcome, ActorRole, ObjectRef
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.evidence.models import ClaimStatus, mint_evidence_id
from nutmeg.ontology.repository.evidence import ClaimEvidenceSpanRow, ClaimRow


@dataclass(frozen=True, slots=True)
class EvidenceSpanInput:
    artifact_id: str
    artifact_retrieval_id: str
    quote: str
    locator: str | None


@dataclass(frozen=True, slots=True)
class ExtractClaimRequest:
    subject_type: str
    subject_id: str
    predicate: str
    value: dict[str, object]
    scope_match_id: str | None
    valid_from: str
    extractor: str
    extractor_version: str
    spans: list[EvidenceSpanInput]
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError('requested_at must be timezone-aware')
        if not self.subject_id.strip() or not self.predicate.strip():
            raise ValueError('subject_id and predicate are required')
        if not self.extractor.strip():
            raise ValueError('extractor is required')
        if not self.spans:
            raise ValueError('at least one evidence span is required')
        if not self.idempotency_key.strip():
            raise ValueError('idempotency_key is required')


@dataclass(frozen=True, slots=True)
class ClaimAdjudicationRequest:
    claim_id: str
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError('requested_at must be timezone-aware')
        if not self.claim_id.strip():
            raise ValueError('claim_id is required')
        if not self.idempotency_key.strip():
            raise ValueError('idempotency_key is required')


class ClaimActions:
    def __init__(self, action_service: ActionService) -> None:
        self._action_service = action_service

    def extract_claim(self, request: ExtractClaimRequest) -> ActionOutcome:
        payload: dict[str, object] = {
            'subject_type': request.subject_type,
            'subject_id': request.subject_id,
            'predicate': request.predicate,
            'extractor': request.extractor,
            'extractor_version': request.extractor_version,
            'span_count': len(request.spans),
        }
        command = ActionCommand.create(
            action_type='extract_claim',
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload=payload,
            requested_at=request.requested_at,
        )

        def handler(uow, _command) -> tuple[ObjectRef, ...]:
            at = request.requested_at.astimezone(UTC).isoformat()
            claim_id = mint_evidence_id('claim')
            uow.evidence.insert_claim(
                ClaimRow(
                    claim_id=claim_id,
                    subject_type=request.subject_type,
                    subject_id=request.subject_id,
                    predicate=request.predicate,
                    value=request.value,
                    scope_match_id=request.scope_match_id,
                    valid_from=request.valid_from,
                    valid_to=None,
                    status=ClaimStatus.PROVISIONAL.value,
                    extractor=request.extractor,
                    extractor_version=request.extractor_version,
                    created_at=at,
                    adjudicated_at=None,
                )
            )
            for span in request.spans:
                uow.evidence.insert_evidence_span(
                    ClaimEvidenceSpanRow(
                        claim_evidence_span_id=mint_evidence_id('span'),
                        claim_id=claim_id,
                        artifact_id=span.artifact_id,
                        artifact_retrieval_id=span.artifact_retrieval_id,
                        quote=span.quote,
                        locator=span.locator,
                    )
                )
            uow.evidence.insert_claim_status_event(
                mint_evidence_id('cse'),
                claim_id,
                None,
                ClaimStatus.PROVISIONAL.value,
                _command.action_id,
                at,
            )
            return (ObjectRef('claim', claim_id),)

        return self._action_service.execute(command, handler)

    def verify_claim(self, request: ClaimAdjudicationRequest) -> ActionOutcome:
        return self._adjudicate(request, 'verify_claim', ClaimStatus.VERIFIED)

    def dispute_claim(self, request: ClaimAdjudicationRequest) -> ActionOutcome:
        return self._adjudicate(request, 'dispute_claim', ClaimStatus.DISPUTED)

    def retract_claim(self, request: ClaimAdjudicationRequest) -> ActionOutcome:
        return self._adjudicate(request, 'retract_claim', ClaimStatus.RETRACTED)

    def _adjudicate(
        self,
        request: ClaimAdjudicationRequest,
        action_type: str,
        to_status: ClaimStatus,
    ) -> ActionOutcome:
        command = ActionCommand.create(
            action_type=action_type,
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload={'claim_id': request.claim_id, 'to_status': to_status.value},
            requested_at=request.requested_at,
        )

        def handler(uow, _command) -> tuple[ObjectRef, ...]:
            at = request.requested_at.astimezone(UTC).isoformat()
            from_status = uow.evidence.claim_status(request.claim_id)
            uow.evidence.update_claim_status(request.claim_id, to_status.value, at)
            uow.evidence.insert_claim_status_event(
                mint_evidence_id('cse'),
                request.claim_id,
                from_status,
                to_status.value,
                _command.action_id,
                at,
            )
            return (ObjectRef('claim', request.claim_id),)

        return self._action_service.execute(command, handler)
