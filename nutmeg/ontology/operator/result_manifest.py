"""Strict three-source result and official prize intake contract."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal, Sequence

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)

from nutmeg.ontology.actions.models import canonical_json

Lane = Literal["jczq", "zucai"]
ResultSourceKind = Literal["api_football", "sporttery_game90", "okooo_manual"]
ReceiptState = Literal["missing", "invalid", "available"]
ResultDisposition = Literal["played_90", "postponed", "official_void"]
InvalidCode = Literal[
    "artifact_unreadable",
    "schema_mismatch",
    "invalid_score",
    "source_identity_mismatch",
    "unsupported_status",
]
AgreementState = Literal["missing", "conflict", "agreed"]

RESULT_SOURCE_KINDS = frozenset(
    {"api_football", "sporttery_game90", "okooo_manual"}
)
_PRIZE_TIER_IDENTITIES = {
    "sfc_first": ("sfc", 14),
    "sfc_second": ("sfc", 13),
    "renjiu_first": ("renjiu", 9),
}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _datetime_contract(value: object, field_name: str) -> object:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be an ISO-8601 datetime string")
    return value


class ResultSourceManifestV1(_StrictModel):
    source_kind: ResultSourceKind
    receipt_state: ReceiptState
    artifact_retrieval_id: str | None = Field(default=None, min_length=1, max_length=500)
    captured_at: AwareDatetime | None = None
    source_disposition: ResultDisposition | None = None
    home_90: StrictInt | None = Field(default=None, ge=0)
    away_90: StrictInt | None = Field(default=None, ge=0)
    invalid_code: InvalidCode | None = None

    @field_validator("captured_at", mode="before")
    @classmethod
    def _captured_at_uses_datetime_contract(cls, value: object):
        if value is None:
            return None
        return _datetime_contract(value, "captured_at")

    @model_validator(mode="after")
    def _state_fields_are_closed(self):
        audit_fields = (self.artifact_retrieval_id, self.captured_at)
        scores = (self.home_90, self.away_90)
        if self.receipt_state == "missing":
            if any(
                value is not None
                for value in (*audit_fields, self.source_disposition, *scores, self.invalid_code)
            ):
                raise ValueError("missing source receipt forbids evidence and result fields")
            return self
        if any(value is None for value in audit_fields):
            raise ValueError("available source artifact and capture time are required")
        if self.receipt_state == "invalid":
            if (
                self.invalid_code is None
                or self.source_disposition is not None
                or any(value is not None for value in scores)
            ):
                raise ValueError("invalid source receipt fields are inconsistent")
            return self
        if self.invalid_code is not None or self.source_disposition is None:
            raise ValueError("available source receipt fields are inconsistent")
        if self.source_disposition == "played_90":
            if any(value is None for value in scores):
                raise ValueError("played result requires both 90-minute scores")
        elif any(value is not None for value in scores):
            raise ValueError("non-played result forbids scores")
        return self


class MatchResultEvidenceManifestV1(_StrictModel):
    official_match_no: str = Field(min_length=1, max_length=100)
    canonical_match_id: str = Field(min_length=1, max_length=500)
    sources: list[ResultSourceManifestV1]

    @model_validator(mode="after")
    def _source_set_is_exact(self):
        kinds = [source.source_kind for source in self.sources]
        if len(kinds) != len(set(kinds)) or set(kinds) != RESULT_SOURCE_KINDS:
            raise ValueError("exactly three configured result sources are required")
        return self


class ZucaiPrizeTierManifestV1(_StrictModel):
    tier_code: Literal["sfc_first", "sfc_second", "renjiu_first"]
    ticket_kind: Literal["sfc", "renjiu"]
    required_correct_count: StrictInt = Field(ge=0)
    official_winning_note_count: StrictInt = Field(ge=0)
    payout_minor_per_winning_note: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def _identity_matches_tier(self):
        if (self.ticket_kind, self.required_correct_count) != _PRIZE_TIER_IDENTITIES[
            self.tier_code
        ]:
            raise ValueError("prize tier identity does not match the closed policy")
        return self


class ZucaiPrizeTableManifestV1(_StrictModel):
    issue: str = Field(min_length=1, max_length=100)
    currency: Literal["CNY"]
    published_at: AwareDatetime
    official_artifact_retrieval_id: str = Field(min_length=1, max_length=500)
    supersedes_prize_table_token: str | None = Field(
        default=None,
        min_length=1,
        max_length=2_000,
    )
    tiers: list[ZucaiPrizeTierManifestV1]

    @field_validator("published_at", mode="before")
    @classmethod
    def _published_at_uses_datetime_contract(cls, value: object):
        return _datetime_contract(value, "published_at")

    @model_validator(mode="after")
    def _tier_set_is_exact(self):
        codes = [tier.tier_code for tier in self.tiers]
        if len(codes) != len(set(codes)) or set(codes) != set(_PRIZE_TIER_IDENTITIES):
            raise ValueError("prize table requires exactly the closed tier set")
        return self


class ResultEvidenceManifestV1(_StrictModel):
    schema_version: Literal["result-evidence-v1"]
    lane: Lane
    business_key: str = Field(min_length=1, max_length=100)
    task_snapshot_token: str = Field(min_length=1, max_length=2_000)
    slate_revision_token: str = Field(min_length=1, max_length=2_000)
    result_cutoff_at: AwareDatetime
    supersedes_result_set_token: str | None = Field(
        default=None,
        min_length=1,
        max_length=2_000,
    )
    matches: list[MatchResultEvidenceManifestV1] = Field(min_length=1, max_length=500)
    zucai_prize_table: ZucaiPrizeTableManifestV1 | None = None

    @field_validator("result_cutoff_at", mode="before")
    @classmethod
    def _cutoff_uses_datetime_contract(cls, value: object):
        return _datetime_contract(value, "result_cutoff_at")

    @model_validator(mode="after")
    def _manifest_shape_is_consistent(self):
        numbers = [match.official_match_no for match in self.matches]
        identities = [match.canonical_match_id for match in self.matches]
        if len(numbers) != len(set(numbers)) or len(identities) != len(set(identities)):
            raise ValueError("duplicate match in result manifest")
        if self.lane == "jczq" and self.zucai_prize_table is not None:
            raise ValueError("JCZQ forbids a Zucai prize table")
        if (
            self.zucai_prize_table is not None
            and self.zucai_prize_table.issue != self.business_key
        ):
            raise ValueError("prize table issue does not match the task")
        for match in self.matches:
            for source in match.sources:
                if source.captured_at is not None and source.captured_at > self.result_cutoff_at:
                    raise ValueError("source capture follows the result cutoff")
        return self

    @property
    def manifest_sha256(self) -> str:
        document = self.model_dump(mode="json")
        return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


class NormalizedResult(_StrictModel):
    agreement_state: AgreementState
    result_disposition: ResultDisposition | None = None
    home_90: int | None = None
    away_90: int | None = None


def normalize_match_result(
    receipts: Sequence[ResultSourceManifestV1],
) -> NormalizedResult:
    by_kind = {row.source_kind: row for row in receipts}
    if len(receipts) != 3 or set(by_kind) != RESULT_SOURCE_KINDS:
        raise ValueError("exactly three configured result sources are required")
    if any(row.receipt_state == "missing" for row in receipts):
        return NormalizedResult(agreement_state="missing")
    if any(row.receipt_state != "available" for row in receipts):
        return NormalizedResult(agreement_state="conflict")
    official = by_kind["sporttery_game90"]
    if official.source_disposition == "official_void" and all(
        row.source_disposition in {"postponed", "official_void"}
        for row in receipts
    ):
        return NormalizedResult(
            agreement_state="agreed",
            result_disposition="official_void",
        )
    facts = {
        (row.source_disposition, row.home_90, row.away_90)
        for row in receipts
    }
    if len(facts) != 1:
        return NormalizedResult(agreement_state="conflict")
    disposition, home_90, away_90 = facts.pop()
    return NormalizedResult(
        agreement_state="agreed",
        result_disposition=disposition,
        home_90=home_90,
        away_90=away_90,
    )


__all__ = [
    "RESULT_SOURCE_KINDS",
    "MatchResultEvidenceManifestV1",
    "NormalizedResult",
    "ResultEvidenceManifestV1",
    "ResultSourceManifestV1",
    "ZucaiPrizeTableManifestV1",
    "ZucaiPrizeTierManifestV1",
    "normalize_match_result",
]
