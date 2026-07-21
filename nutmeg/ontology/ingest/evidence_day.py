"""Ingest one evidence day into typed context + evidence facts.

Attaches evidence to matches produced by a prior market-day ingest (2A) via the
supplied ``match_no -> match_id`` map. Availability rows become an upserted Person
plus an observation-backed PersonMatchStatus; weather becomes a deterministic
Observation; news becomes an AI-extracted provisional Claim with evidence spans.
Rows that cannot attach to a known match are **counted as skipped**, never
silently dropped. Idempotency keys are derived from the business date + ids, so a
rerun commits nothing new.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from nutmeg.ontology.actions.claim_actions import (
    ClaimActions,
    EvidenceSpanInput,
    ExtractClaimRequest,
)
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.observation_actions import (
    ObservationActions,
    PersonMatchStatusRequest,
    RecordObservationRequest,
)
from nutmeg.ontology.actions.person_actions import PersonActions, UpsertPersonRequest
from nutmeg.ontology.evidence.models import Availability, StatusKind, VerificationMethod
from nutmeg.ontology.ingest.lineup import parse_availability_snapshot


@dataclass(frozen=True, slots=True)
class EvidenceDayIngestRequest:
    business_date: str
    match_no_to_id: dict[str, str]
    availability: list[dict]
    actor_id: str
    actor_role: ActorRole
    requested_at: datetime
    weather: list[dict] = field(default_factory=list)
    news: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError('requested_at must be timezone-aware')
        if not self.business_date.strip():
            raise ValueError('business_date is required')


@dataclass(frozen=True, slots=True)
class EvidenceDayIngestResult:
    person_statuses: int
    observations: int
    claims: int
    skipped: int


class EvidenceDayIngestService:
    def __init__(
        self,
        *,
        person_actions: PersonActions,
        observation_actions: ObservationActions,
        claim_actions: ClaimActions,
    ) -> None:
        self._person_actions = person_actions
        self._observation_actions = observation_actions
        self._claim_actions = claim_actions

    def ingest(self, request: EvidenceDayIngestRequest) -> EvidenceDayIngestResult:
        person_statuses = 0
        observations = 0
        claims = 0
        skipped = 0

        for snapshot in request.availability:
            for row in parse_availability_snapshot(snapshot):
                match_id = request.match_no_to_id.get(row.match_no)
                availability = _as_availability(row.availability)
                status_kind = _as_status_kind(row.status_kind)
                if match_id is None or availability is None or status_kind is None:
                    skipped += 1
                    continue
                person_id = self._upsert_person(request, row.player_name, row.provider_id)
                self._observation_actions.record_person_match_status(
                    PersonMatchStatusRequest(
                        match_id=match_id,
                        person_id=person_id,
                        team_appearance_id=None,
                        availability=availability,
                        status_kind=status_kind,
                        valid_from=f'{request.business_date}T00:00:00+08:00',
                        observed_at=f'{request.business_date}T12:00:00+08:00',
                        actor_id=request.actor_id,
                        actor_role=request.actor_role,
                        idempotency_key=f'pms:{request.business_date}:{match_id}:{person_id}',
                        requested_at=request.requested_at,
                    )
                )
                person_statuses += 1

        for entry in request.weather:
            match_id = str(entry.get('match_id') or '')
            if not match_id:
                skipped += 1
                continue
            self._observation_actions.record_observation(
                RecordObservationRequest(
                    observation_type='weather',
                    subject_type='match',
                    subject_id=match_id,
                    scope_match_id=match_id,
                    value=entry.get('value') or {},
                    verification_method=VerificationMethod.OFFICIAL,
                    valid_from=str(entry.get('valid_from') or ''),
                    observed_at=str(entry.get('observed_at') or ''),
                    actor_id=request.actor_id,
                    actor_role=request.actor_role,
                    idempotency_key=f'weather:{request.business_date}:{match_id}',
                    requested_at=request.requested_at,
                )
            )
            observations += 1

        for entry in request.news:
            spans = [
                EvidenceSpanInput(
                    artifact_id=span['artifact_id'],
                    artifact_retrieval_id=span['artifact_retrieval_id'],
                    quote=span['quote'],
                    locator=span.get('locator'),
                )
                for span in entry.get('spans') or []
            ]
            if not spans:
                skipped += 1
                continue
            self._claim_actions.extract_claim(
                ExtractClaimRequest(
                    subject_type=entry['subject_type'],
                    subject_id=entry['subject_id'],
                    predicate=entry['predicate'],
                    value=entry.get('value') or {},
                    scope_match_id=entry.get('scope_match_id'),
                    valid_from=str(entry.get('valid_from') or ''),
                    extractor=str(entry.get('extractor') or 'news-nlp'),
                    extractor_version=str(entry.get('extractor_version') or '1'),
                    spans=spans,
                    actor_id='model:extractor',
                    actor_role=ActorRole.AI_EXTRACTOR,
                    idempotency_key=(
                        f'claim:{request.business_date}:{entry["subject_id"]}:{entry["predicate"]}'
                    ),
                    requested_at=request.requested_at,
                )
            )
            claims += 1

        return EvidenceDayIngestResult(
            person_statuses=person_statuses,
            observations=observations,
            claims=claims,
            skipped=skipped,
        )

    def _upsert_person(
        self, request: EvidenceDayIngestRequest, name: str, provider_id: str | None
    ) -> str:
        key_tail = provider_id or name.casefold()
        outcome = self._person_actions.upsert_person(
            UpsertPersonRequest(
                canonical_name=name,
                provider='adapter' if provider_id else None,
                external_id=provider_id,
                actor_id=request.actor_id,
                actor_role=request.actor_role,
                idempotency_key=f'person:{request.business_date}:{key_tail}',
                requested_at=request.requested_at,
            )
        )
        return outcome.result_refs[0].object_id


def _as_availability(value: str) -> Availability | None:
    try:
        return Availability(value)
    except ValueError:
        return None


def _as_status_kind(value: str) -> StatusKind | None:
    try:
        return StatusKind(value)
    except ValueError:
        return None
