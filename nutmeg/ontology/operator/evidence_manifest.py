"""Strict external evidence intake contract for the operator workbench."""

from __future__ import annotations

import hashlib
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from nutmeg.ontology.actions.models import canonical_json

Lane = Literal["jczq", "zucai"]
SubjectType = Literal["match", "team", "person"]
VerificationMethodName = Literal[
    "deterministic",
    "official",
    "corroborated",
    "adjudicated",
]
SourceKind = Literal[
    "sporttery_official",
    "club_official",
    "league_official",
    "api_football",
    "international_market",
    "authoritative_results",
    "credible_media",
    "okooo_manual",
]
RequirementId = Literal["E1", "E2", "E3", "E4", "E5", "E6a", "E6b", "EC"]
AvailabilityName = Literal[
    "expected",
    "available",
    "doubtful",
    "out",
    "suspended",
    "returned",
]
StatusKindName = Literal[
    "injury",
    "suspension",
    "rotation",
    "selection",
    "coach_status",
]
ContextKind = Literal["formation", "cohesion", "material_squad_change"]
ContextState = Literal["present", "absent"]


class StrictManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _bounded_unique(values: list[str], label: str) -> list[str]:
    if any(not value.strip() or len(value) > 500 for value in values):
        raise ValueError(f"{label} must contain bounded non-empty values")
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {label}")
    return values


class PersonAvailabilityObservationValueV1(StrictManifest):
    kind: Literal["person_availability_v1"]
    team_token: str = Field(min_length=1, max_length=500)
    person_token: str = Field(min_length=1, max_length=500)
    availability: AvailabilityName
    status_kind: StatusKindName


class TeamAvailabilityClearObservationValueV1(StrictManifest):
    kind: Literal["team_availability_clear_v1"]
    team_token: str = Field(min_length=1, max_length=500)
    checked_source_kinds: list[SourceKind] = Field(min_length=1, max_length=20)
    lookback_started_at: AwareDatetime
    lookback_ended_at: AwareDatetime
    finding_count: Literal[0]

    @field_validator("checked_source_kinds")
    @classmethod
    def _source_kinds_are_unique(cls, value: list[SourceKind]) -> list[SourceKind]:
        if len(value) != len(set(value)):
            raise ValueError("duplicate checked source kind")
        return value

    @model_validator(mode="after")
    def _lookback_is_ordered(self):
        if self.lookback_started_at > self.lookback_ended_at:
            raise ValueError("lookback start must not follow end")
        return self


class RecentFormObservationValueV1(StrictManifest):
    kind: Literal["recent_form_v1"]
    team_token: str = Field(min_length=1, max_length=500)
    sample_match_tokens: list[str] = Field(min_length=1, max_length=100)
    wins: int = Field(ge=0)
    draws: int = Field(ge=0)
    losses: int = Field(ge=0)
    goals_for: int = Field(ge=0)
    goals_against: int = Field(ge=0)

    @field_validator("sample_match_tokens")
    @classmethod
    def _samples_are_unique(cls, value: list[str]) -> list[str]:
        return _bounded_unique(value, "sample match reference")

    @model_validator(mode="after")
    def _result_total_matches_samples(self):
        if self.wins + self.draws + self.losses != len(self.sample_match_tokens):
            raise ValueError("recent-form result total must equal distinct samples")
        return self


class StructuralContextObservationValueV1(StrictManifest):
    kind: Literal["structural_context_v1"]
    team_token: str = Field(min_length=1, max_length=500)
    context_kind: ContextKind
    state: ContextState
    fact_text: str = Field(min_length=1, max_length=2000)


RegisteredObservationValueV1 = Annotated[
    PersonAvailabilityObservationValueV1
    | TeamAvailabilityClearObservationValueV1
    | RecentFormObservationValueV1
    | StructuralContextObservationValueV1,
    Field(discriminator="kind"),
]


class AvailabilityClaimValueV1(StrictManifest):
    kind: Literal["availability_claim_v1"]
    team_token: str = Field(min_length=1, max_length=500)
    person_token: str = Field(min_length=1, max_length=500)
    availability: AvailabilityName
    status_kind: StatusKindName


class StructuralContextClaimValueV1(StrictManifest):
    kind: Literal["structural_context_claim_v1"]
    team_token: str = Field(min_length=1, max_length=500)
    context_kind: ContextKind
    state: ContextState
    fact_text: str = Field(min_length=1, max_length=2000)


RegisteredClaimValueV1 = Annotated[
    AvailabilityClaimValueV1 | StructuralContextClaimValueV1,
    Field(discriminator="kind"),
]


class EvidenceSourceReceiptV1(StrictManifest):
    source_kind: SourceKind
    source_run_id: str = Field(min_length=1, max_length=500)
    artifact_retrieval_id: str = Field(min_length=1, max_length=500)
    captured_at: AwareDatetime


class TypedObservationIntakeV1(StrictManifest):
    observation_schema: Literal[
        "person_availability_v1",
        "team_availability_clear_v1",
        "recent_form_v1",
        "structural_context_v1",
    ]
    subject_type: SubjectType
    canonical_subject_id: str = Field(min_length=1, max_length=500)
    valid_from: AwareDatetime
    valid_to: AwareDatetime | None
    observed_at: AwareDatetime
    verification_method: VerificationMethodName
    value: RegisteredObservationValueV1
    artifact_retrieval_ids: list[str] = Field(min_length=1, max_length=50)

    @field_validator("artifact_retrieval_ids")
    @classmethod
    def _retrievals_are_unique(cls, value: list[str]) -> list[str]:
        return _bounded_unique(value, "artifact retrieval reference")

    @model_validator(mode="after")
    def _schema_and_interval_are_consistent(self):
        if self.observation_schema != self.value.kind:
            raise ValueError("observation schema must match typed value kind")
        expected_subject = (
            ("person", self.value.person_token)
            if isinstance(self.value, PersonAvailabilityObservationValueV1)
            else ("team", self.value.team_token)
        )
        if (self.subject_type, self.canonical_subject_id) != expected_subject:
            raise ValueError("observation subject must match typed value subject")
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("valid_to must not precede valid_from")
        return self


class EvidenceSpanIntakeV1(StrictManifest):
    artifact_id: str = Field(min_length=1, max_length=500)
    artifact_retrieval_id: str = Field(min_length=1, max_length=500)
    quote: str = Field(min_length=1, max_length=4000)
    locator: str | None = Field(default=None, max_length=1000)


class TypedClaimIntakeV1(StrictManifest):
    claim_schema: Literal["availability_claim_v1", "structural_context_claim_v1"]
    subject_type: SubjectType
    canonical_subject_id: str = Field(min_length=1, max_length=500)
    predicate: Literal["availability", "structural_context"]
    scope_match_id: str | None = Field(default=None, min_length=1, max_length=500)
    valid_from: AwareDatetime
    valid_to: AwareDatetime | None
    extractor: str = Field(min_length=1, max_length=500)
    extractor_version: str = Field(min_length=1, max_length=100)
    value: RegisteredClaimValueV1
    spans: list[EvidenceSpanIntakeV1] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def _schema_predicate_and_interval_are_consistent(self):
        if self.claim_schema != self.value.kind:
            raise ValueError("claim schema must match typed value kind")
        expected = {
            "availability_claim_v1": "availability",
            "structural_context_claim_v1": "structural_context",
        }[self.claim_schema]
        if self.predicate != expected:
            raise ValueError("claim predicate must match typed value kind")
        expected_subject = (
            ("person", self.value.person_token)
            if isinstance(self.value, AvailabilityClaimValueV1)
            else ("team", self.value.team_token)
        )
        if (self.subject_type, self.canonical_subject_id) != expected_subject:
            raise ValueError("claim subject must match typed value subject")
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("valid_to must not precede valid_from")
        identities = [
            (span.artifact_id, span.artifact_retrieval_id, span.locator)
            for span in self.spans
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate evidence span")
        return self


class EvidenceCoverageReceiptV1(StrictManifest):
    requirement_id: RequirementId
    subject_scope: str = Field(min_length=1, max_length=500)
    evidence_ref_tokens: list[str] = Field(min_length=1, max_length=100)

    @field_validator("evidence_ref_tokens")
    @classmethod
    def _evidence_refs_are_unique(cls, value: list[str]) -> list[str]:
        return _bounded_unique(value, "evidence reference")


class MatchEvidenceIntakeV1(StrictManifest):
    official_match_no: str = Field(min_length=1, max_length=100)
    canonical_match_id: str = Field(min_length=1, max_length=500)
    source_receipts: list[EvidenceSourceReceiptV1] = Field(default_factory=list, max_length=100)
    observations: list[TypedObservationIntakeV1] = Field(default_factory=list, max_length=500)
    claims: list[TypedClaimIntakeV1] = Field(default_factory=list, max_length=500)
    coverage_receipts: list[EvidenceCoverageReceiptV1] = Field(
        default_factory=list,
        max_length=500,
    )

    @model_validator(mode="after")
    def _references_are_unique_and_scoped(self):
        retrieval_ids = [item.artifact_retrieval_id for item in self.source_receipts]
        if len(retrieval_ids) != len(set(retrieval_ids)):
            raise ValueError("duplicate source receipt")
        for observation in self.observations:
            if not set(observation.artifact_retrieval_ids).issubset(retrieval_ids):
                raise ValueError("observation references an undeclared source receipt")
        for claim in self.claims:
            if claim.scope_match_id not in {None, self.canonical_match_id}:
                raise ValueError("claim scope does not match manifest match")
            if not {span.artifact_retrieval_id for span in claim.spans}.issubset(retrieval_ids):
                raise ValueError("claim references an undeclared source receipt")
        return self


class EvidenceIntakeManifestV1(StrictManifest):
    schema_version: Literal["evidence-intake-v1"]
    lane: Lane
    business_key: str = Field(min_length=1, max_length=100)
    slate_revision_id: str = Field(min_length=1, max_length=500)
    captured_at: AwareDatetime
    matches: list[MatchEvidenceIntakeV1] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _matches_are_unique(self):
        numbers = [match.official_match_no for match in self.matches]
        identities = [match.canonical_match_id for match in self.matches]
        if len(numbers) != len(set(numbers)) or len(identities) != len(set(identities)):
            raise ValueError("duplicate match in evidence manifest")
        for match in self.matches:
            for source in match.source_receipts:
                if source.captured_at > self.captured_at:
                    raise ValueError("source captured_at must not follow manifest captured_at")
            for observation in match.observations:
                if (
                    observation.observed_at > self.captured_at
                    or observation.valid_from > self.captured_at
                ):
                    raise ValueError("observation time must not follow manifest captured_at")
                lookback_ended_at = getattr(observation.value, "lookback_ended_at", None)
                if lookback_ended_at is not None and lookback_ended_at > self.captured_at:
                    raise ValueError(
                        "observation lookback must not follow manifest captured_at"
                    )
            for claim in match.claims:
                if claim.valid_from > self.captured_at:
                    raise ValueError("claim time must not follow manifest captured_at")
        return self

    @property
    def manifest_sha256(self) -> str:
        document = self.model_dump(mode="json")
        return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


def evidence_manifest_sha256(manifest: EvidenceIntakeManifestV1) -> str:
    """Return the canonical digest used by the Action and external callers."""
    return manifest.manifest_sha256


__all__ = [
    "AvailabilityClaimValueV1",
    "EvidenceCoverageReceiptV1",
    "EvidenceIntakeManifestV1",
    "EvidenceSourceReceiptV1",
    "EvidenceSpanIntakeV1",
    "MatchEvidenceIntakeV1",
    "PersonAvailabilityObservationValueV1",
    "RecentFormObservationValueV1",
    "RegisteredClaimValueV1",
    "RegisteredObservationValueV1",
    "StructuralContextClaimValueV1",
    "StructuralContextObservationValueV1",
    "TeamAvailabilityClearObservationValueV1",
    "TypedClaimIntakeV1",
    "TypedObservationIntakeV1",
    "evidence_manifest_sha256",
]
