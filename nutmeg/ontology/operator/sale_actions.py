"""Strict typed Actions for official dual-lane sale slates and schedule checks."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select

from nutmeg.ontology.actions.models import (
    ActionCommand,
    ActionOutcome,
    ActorRole,
    ObjectRef,
    canonical_json,
)
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.operator.models import (
    OfficialOfferFamilyRow,
    OfficialOfferRevisionRow,
    OfficialSaleSlateRevisionRow,
    OfficialScheduleCheckReceiptRow,
    SaleImportCountReceiptRow,
    SaleImportResult,
)
from nutmeg.ontology.repository import schema, schema_identity, schema_market

_Lane = Literal["jczq", "zucai"]
_OfferStatus = Literal["scheduled", "on_sale", "sale_closed", "cancelled"]
_CheckState = Literal["slate_imported", "confirmed_no_sale", "failed"]
_ParserContract = Literal["sporttery-official-sale-parser-v1"]
_JCZQ_MARKETS = frozenset({"md-had", "md-hhad", "md-ttg", "md-crs"})
_ZUCAI_MARKETS = frozenset({"md-had"})
_SCHEDULE_ERROR_CODES = frozenset(
    {
        "invalid_response_error",
        "network_error",
        "official_source_unavailable",
        "source_unavailable",
        "timeout_error",
    }
)


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _datetime_contract(value: object, name: str) -> object:
    if not isinstance(value, (str, datetime)):
        raise ValueError(f"{name} must be an ISO 8601 datetime string")
    return value


def _required(value: str, name: str) -> str:
    if not value.strip():
        raise ValueError(f"{name} is required")
    return value


def _digest(document: object) -> str:
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


def _slate_content(manifest: "OfficialSaleSlateManifestV1") -> dict[str, object]:
    offers = sorted(
        (
            {
                "canonical_match_id": offer.canonical_match_id,
                "official_match_no": offer.official_match_no,
                "market_definition_ids": list(offer.market_definition_ids),
                "sale_opens_at": offer.sale_opens_at.astimezone(UTC).isoformat(),
                "sale_deadline_at": offer.sale_deadline_at.astimezone(UTC).isoformat(),
                "status": offer.status,
            }
            for offer in manifest.offers
        ),
        key=lambda offer: (offer["official_match_no"], offer["canonical_match_id"]),
    )
    return {
        "lane": manifest.lane,
        "business_key": manifest.business_key,
        "offers": offers,
    }


def official_sale_parser_receipt_document(
    *,
    lane: _Lane,
    business_key: str,
    published_at: datetime,
    offers: list["OfficialOfferManifestV1"],
) -> dict[str, object]:
    """Build the trusted parser's canonical sale receipt."""
    return {
        "schema_version": "sporttery-official-sale-parser-v1",
        "lane": lane,
        "business_key": business_key,
        "published_at": published_at.astimezone(UTC).isoformat(),
        "offers": _slate_content(
            _ParserReceiptSlate(lane=lane, business_key=business_key, offers=offers)
        )["offers"],
    }


def official_sale_parser_receipt_hash(
    *,
    lane: _Lane,
    business_key: str,
    published_at: datetime,
    offers: list["OfficialOfferManifestV1"],
) -> str:
    """Hash the trusted parser's canonical sale receipt."""
    return _digest(
        official_sale_parser_receipt_document(
            lane=lane,
            business_key=business_key,
            published_at=published_at,
            offers=offers,
        )
    )


def official_empty_schedule_parser_receipt_hash(*, lane: _Lane) -> str:
    """Hash a trusted parser receipt that observed no sale business keys."""
    return _digest(
        {
            "schema_version": "sporttery-official-sale-parser-v1",
            "lane": lane,
            "observed_business_keys": [],
        }
    )


@dataclass(frozen=True, slots=True)
class _ParserReceiptSlate:
    lane: _Lane
    business_key: str
    offers: list["OfficialOfferManifestV1"]


class OfficialOfferManifestV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    canonical_match_id: str = Field(min_length=1, max_length=500)
    official_match_no: str = Field(min_length=1, max_length=100)
    market_definition_ids: list[str] = Field(min_length=1, max_length=20)
    sale_opens_at: datetime
    sale_deadline_at: datetime
    status: _OfferStatus

    @field_validator("sale_opens_at", "sale_deadline_at", mode="before")
    @classmethod
    def _time_uses_datetime_contract(cls, value: object, info):
        return _datetime_contract(value, info.field_name)

    @field_validator("sale_opens_at", "sale_deadline_at")
    @classmethod
    def _time_is_aware(cls, value: datetime, info):
        return _aware(value, info.field_name)

    @field_validator("market_definition_ids")
    @classmethod
    def _markets_are_a_sorted_set(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 500 for item in value):
            raise ValueError("market definition IDs must be non-empty and bounded")
        if value != sorted(set(value)):
            raise ValueError("market definition IDs must be sorted and unique")
        return value

    @model_validator(mode="after")
    def _window_is_valid(self):
        if self.sale_opens_at >= self.sale_deadline_at:
            raise ValueError("sale_opens_at must be before sale_deadline_at")
        return self


class OfficialSaleSlateManifestV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["official-sale-slate-v1"]
    lane: _Lane
    business_key: str = Field(min_length=1, max_length=100)
    published_at: datetime
    retrieved_at: datetime
    parser_contract_version: _ParserContract
    official_source_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    official_source_artifact_retrieval_id: str = Field(min_length=1, max_length=500)
    supersedes_slate_revision_id: str | None = Field(max_length=500)
    offers: list[OfficialOfferManifestV1] = Field(min_length=1, max_length=500)

    @field_validator("published_at", "retrieved_at", mode="before")
    @classmethod
    def _time_uses_datetime_contract(cls, value: object, info):
        return _datetime_contract(value, info.field_name)

    @field_validator("published_at", "retrieved_at")
    @classmethod
    def _time_is_aware(cls, value: datetime, info):
        return _aware(value, info.field_name)

    @model_validator(mode="after")
    def _shape_is_valid(self):
        if self.lane == "jczq":
            try:
                business_date = date.fromisoformat(self.business_key)
            except ValueError as error:
                raise ValueError("JCZQ business key must be an ISO date") from error
            if business_date.isoformat() != self.business_key:
                raise ValueError("JCZQ business key must be an ISO date")
            allowed_markets = _JCZQ_MARKETS
            lane_label = "JCZQ"
        else:
            if re.fullmatch(r"[0-9]{5}", self.business_key) is None:
                raise ValueError("Zucai business key must be a five-digit issue")
            allowed_markets = _ZUCAI_MARKETS
            lane_label = "Zucai"
        if self.retrieved_at < self.published_at:
            raise ValueError("retrieved_at cannot precede published_at")
        match_numbers = [offer.official_match_no for offer in self.offers]
        match_ids = [offer.canonical_match_id for offer in self.offers]
        if len(match_numbers) != len(set(match_numbers)):
            raise ValueError("duplicate official match number")
        if len(match_ids) != len(set(match_ids)):
            raise ValueError("duplicate canonical match")
        if self.lane == "zucai":
            if len(self.offers) != 14:
                raise ValueError("zucai slate must contain exactly fourteen offers")
            if match_numbers != [str(index) for index in range(1, 15)]:
                raise ValueError("zucai slate must be ordered 1 through 14")
        for offer in self.offers:
            if not set(offer.market_definition_ids).issubset(allowed_markets):
                raise ValueError(f"{lane_label} market is outside the lane contract")
            if offer.status == "on_sale" and not (
                offer.sale_opens_at <= self.published_at < offer.sale_deadline_at
            ):
                raise ValueError("on_sale offer is outside its source publication window")
        expected_receipt_hash = official_sale_parser_receipt_hash(
            lane=self.lane,
            business_key=self.business_key,
            published_at=self.published_at,
            offers=self.offers,
        )
        if self.official_source_content_hash != expected_receipt_hash:
            raise ValueError(
                "official source content hash must match the trusted parser receipt"
            )
        return self


class OfficialScheduleCheckManifestV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["official-schedule-check-v1"]
    lane: _Lane
    shanghai_check_date: date
    checked_at: datetime
    source_run_id: str = Field(min_length=1, max_length=500)
    check_state: _CheckState
    parser_contract_version: _ParserContract | None
    official_source_content_hash: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    official_source_artifact_retrieval_id: str | None = Field(max_length=500)
    observed_business_keys: list[str] = Field(max_length=100)
    imported_business_keys: list[str] = Field(max_length=100)
    error_code: str | None = Field(max_length=100)

    @field_validator("checked_at", mode="before")
    @classmethod
    def _time_uses_datetime_contract(cls, value: object, info):
        return _datetime_contract(value, info.field_name)

    @field_validator("checked_at")
    @classmethod
    def _checked_at_is_aware(cls, value: datetime):
        return _aware(value, "checked_at")

    @field_validator("observed_business_keys", "imported_business_keys")
    @classmethod
    def _keys_are_a_sorted_set(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 100 for item in value):
            raise ValueError("imported business keys must be non-empty and bounded")
        if value != sorted(set(value)):
            raise ValueError("imported business keys must be sorted and unique")
        return value

    @field_validator("error_code")
    @classmethod
    def _error_code_is_closed(cls, value: str | None) -> str | None:
        if value is not None and value not in _SCHEDULE_ERROR_CODES:
            raise ValueError("error_code is outside the closed schedule-check vocabulary")
        return value

    @model_validator(mode="after")
    def _state_fields_are_consistent(self):
        if self.checked_at.astimezone(ZoneInfo("Asia/Shanghai")).date() != self.shanghai_check_date:
            raise ValueError("checked_at must fall on shanghai_check_date")
        if self.check_state == "slate_imported":
            if (
                not self.official_source_artifact_retrieval_id
                or self.parser_contract_version is None
                or self.official_source_content_hash is None
                or not self.observed_business_keys
                or self.imported_business_keys != self.observed_business_keys
            ):
                raise ValueError(
                    "slate_imported requires matching observed and imported business keys"
                )
            if self.error_code is not None:
                raise ValueError("slate_imported cannot carry an error code")
        elif self.check_state == "confirmed_no_sale":
            if (
                not self.official_source_artifact_retrieval_id
                or self.parser_contract_version is None
                or self.official_source_content_hash is None
            ):
                raise ValueError("confirmed_no_sale requires an official retrieval")
            if (
                self.observed_business_keys
                or self.imported_business_keys
                or self.error_code is not None
            ):
                raise ValueError("confirmed_no_sale requires an explicit empty observation")
            if self.official_source_content_hash != (
                official_empty_schedule_parser_receipt_hash(lane=self.lane)
            ):
                raise ValueError(
                    "confirmed_no_sale source hash must match the empty parser receipt"
                )
        elif (
            self.parser_contract_version is not None
            or self.official_source_content_hash is not None
            or self.observed_business_keys
            or self.imported_business_keys
            or self.error_code is None
        ):
            raise ValueError("failed requires no parser receipt, empty keys, and an error code")
        return self


@dataclass(frozen=True, slots=True)
class ImportOfficialSaleSlateRequest:
    manifest: OfficialSaleSlateManifestV1
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _aware(self.requested_at, "requested_at")
        _required(self.actor_id, "actor_id")


@dataclass(frozen=True, slots=True)
class RecordOfficialScheduleCheckRequest:
    manifest: OfficialScheduleCheckManifestV1
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _aware(self.requested_at, "requested_at")
        _required(self.actor_id, "actor_id")


class SaleActions:
    def __init__(self, action_service: ActionService) -> None:
        self._action_service = action_service

    @staticmethod
    def _validated_slate(
        manifest: OfficialSaleSlateManifestV1,
    ) -> OfficialSaleSlateManifestV1:
        return OfficialSaleSlateManifestV1.model_validate(manifest.model_dump(mode="python"))

    @staticmethod
    def _validated_check(
        manifest: OfficialScheduleCheckManifestV1,
    ) -> OfficialScheduleCheckManifestV1:
        return OfficialScheduleCheckManifestV1.model_validate(manifest.model_dump(mode="python"))

    @staticmethod
    def _assert_official_retrieval(
        uow,
        retrieval_id: str,
        *,
        expected_content_hash: str | None,
        expected_retrieved_at: datetime | None = None,
        expected_source_run_id: str | None = None,
    ):
        row = (
            uow.connection.execute(
                select(
                    schema.artifact_retrievals.c.source_name,
                    schema.artifact_retrievals.c.source_type,
                    schema.artifact_retrievals.c.status,
                    schema.artifact_retrievals.c.source_run_id,
                    schema.artifact_retrievals.c.reported_content_type,
                    schema.artifact_retrievals.c.canonical_url,
                    schema.artifact_retrievals.c.retrieved_at,
                    schema.source_artifacts.c.content_hash,
                    schema.source_runs.c.source_name.label("run_source_name"),
                    schema.source_runs.c.source_type.label("run_source_type"),
                    schema.source_runs.c.status.label("run_status"),
                )
                .select_from(
                    schema.artifact_retrievals.join(
                        schema.source_artifacts,
                        schema.artifact_retrievals.c.artifact_id
                        == schema.source_artifacts.c.artifact_id,
                    ).join(
                        schema.source_runs,
                        schema.artifact_retrievals.c.source_run_id
                        == schema.source_runs.c.source_run_id,
                    )
                )
                .where(schema.artifact_retrievals.c.artifact_retrieval_id == retrieval_id)
            )
            .mappings()
            .first()
        )
        if row is None or (
            row["source_name"] != "sporttery"
            or row["source_type"] != "official_sale_schedule"
            or row["status"] != "stored"
            or row["reported_content_type"] != "application/json"
        ):
            raise ValueError("official Sporttery sale retrieval is required")
        hostname = urlsplit(row["canonical_url"] or "").hostname or ""
        if hostname != "sporttery.cn" and not hostname.endswith(".sporttery.cn"):
            raise ValueError("official Sporttery URL is required")
        if expected_content_hash is not None and row["content_hash"] != expected_content_hash:
            raise ValueError("official source content hash does not match retrieval")
        if expected_retrieved_at is not None and (
            datetime.fromisoformat(row["retrieved_at"]).astimezone(UTC)
            != expected_retrieved_at.astimezone(UTC)
        ):
            raise ValueError("manifest retrieved_at does not match official retrieval")
        if (
            row["run_source_name"] != "sporttery"
            or row["run_source_type"] != "official_schedule"
            or row["run_status"] != "succeeded"
        ):
            raise ValueError("successful official schedule source run is required")
        if expected_source_run_id is not None and row["source_run_id"] != expected_source_run_id:
            raise ValueError("official retrieval must belong to the declared source run")
        return row

    @staticmethod
    def _assert_official_schedule_run(
        uow,
        source_run_id: str,
        *,
        check_state: _CheckState,
        shanghai_check_date: date,
    ):
        row = (
            uow.connection.execute(
                select(
                    schema.source_runs.c.source_name,
                    schema.source_runs.c.source_type,
                    schema.source_runs.c.started_at,
                    schema.source_runs.c.finished_at,
                    schema.source_runs.c.status,
                ).where(schema.source_runs.c.source_run_id == source_run_id)
            )
            .mappings()
            .first()
        )
        if row is None or (
            row["source_name"] != "sporttery"
            or row["source_type"] != "official_schedule"
        ):
            raise ValueError("official schedule source run is required")
        expected_status = "failed" if check_state == "failed" else "succeeded"
        if row["status"] != expected_status:
            raise ValueError(f"{check_state} requires {expected_status} source run status")
        run_at = datetime.fromisoformat(row["finished_at"] or row["started_at"])
        _aware(run_at, "source run timestamp")
        if run_at.astimezone(ZoneInfo("Asia/Shanghai")).date() != shanghai_check_date:
            raise ValueError("source run must match the Shanghai check date")
        return row

    def import_official_sale_slate(
        self, request: ImportOfficialSaleSlateRequest
    ) -> SaleImportResult:
        manifest = self._validated_slate(request.manifest)
        payload = manifest.model_dump(mode="json")
        command = ActionCommand.create(
            action_type="import_official_sale_slate",
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload=payload,
            requested_at=request.requested_at,
        )

        created_family_count = 0

        def handler(uow, action) -> tuple[ObjectRef, ...]:
            nonlocal created_family_count
            self._assert_official_retrieval(
                uow,
                manifest.official_source_artifact_retrieval_id,
                expected_content_hash=manifest.official_source_content_hash,
                expected_retrieved_at=manifest.retrieved_at,
            )
            if manifest.retrieved_at > request.requested_at:
                raise ValueError("official retrieval cannot be later than the Action request")
            current = uow.operator_sale.current_slate(manifest.lane, manifest.business_key)
            expected_parent = current.slate_revision_id if current is not None else None
            if manifest.supersedes_slate_revision_id != expected_parent:
                raise ValueError("official slate must supersede the current slate")
            for offer in manifest.offers:
                match_exists = uow.connection.execute(
                    select(schema_identity.matches.c.match_id).where(
                        schema_identity.matches.c.match_id == offer.canonical_match_id
                    )
                ).scalar_one_or_none()
                if match_exists is None:
                    raise ValueError(f"match {offer.canonical_match_id} is unresolved")
                for market_id in offer.market_definition_ids:
                    market_exists = uow.connection.execute(
                        select(schema_market.market_definitions.c.market_definition_id).where(
                            schema_market.market_definitions.c.market_definition_id == market_id
                        )
                    ).scalar_one_or_none()
                    if market_exists is None:
                        raise ValueError(f"market definition {market_id} is invalid")

            content_hash = _digest(_slate_content(manifest))
            if (
                current is not None
                and content_hash != current.content_hash
                and manifest.retrieved_at
                <= datetime.fromisoformat(current.retrieved_at)
            ):
                raise ValueError("official slate retrieval must advance monotonically")
            if current is not None and current.content_hash == content_hash:
                current_offers = uow.operator_sale.offer_revisions_for_slate(
                    current.slate_revision_id
                )
                linked_counts = (1, len(current_offers), len(current_offers))
                refs = [
                    ObjectRef("official_sale_slate_revision", current.slate_revision_id),
                    *(
                        ObjectRef(
                            "official_offer_revision",
                            offer.official_offer_revision_id,
                        )
                        for offer in current_offers
                    ),
                    ObjectRef(
                        "official_sale_import_count",
                        f"{current.slate_revision_id}:"
                        f"{linked_counts[0]}:{linked_counts[1]}:{linked_counts[2]}:0:0:0",
                    ),
                ]
                return tuple(refs)
            slate_id = f"OSR-{uuid4().hex}"
            slate = OfficialSaleSlateRevisionRow(
                slate_revision_id=slate_id,
                slate_family_id=f"{manifest.lane}:{manifest.business_key}",
                lane=manifest.lane,
                business_key=manifest.business_key,
                revision_no=1 if current is None else current.revision_no + 1,
                source_artifact_retrieval_id=(manifest.official_source_artifact_retrieval_id),
                published_at=manifest.published_at.astimezone(UTC).isoformat(),
                retrieved_at=manifest.retrieved_at.astimezone(UTC).isoformat(),
                valid_from=action.requested_at,
                supersedes_slate_revision_id=manifest.supersedes_slate_revision_id,
                content_hash=content_hash,
            )
            uow.operator_sale.insert_slate_revision(slate)
            refs: list[ObjectRef] = [ObjectRef("official_sale_slate_revision", slate_id)]
            for offer in manifest.offers:
                family_material = {
                    "lane": manifest.lane,
                    "business_key": manifest.business_key,
                    "official_match_no": offer.official_match_no,
                    "canonical_match_id": offer.canonical_match_id,
                }
                family_id = f"OOF-{_digest(family_material)}"
                if uow.operator_sale.offer_family(family_id) is None:
                    created_family_count += 1
                    uow.operator_sale.insert_offer_family(
                        OfficialOfferFamilyRow(
                            official_offer_family_id=family_id,
                            lane=manifest.lane,
                            business_key=manifest.business_key,
                            official_match_no=offer.official_match_no,
                            match_id=offer.canonical_match_id,
                            created_at=action.requested_at,
                        )
                    )
                offer_revision_id = f"OOR-{uuid4().hex}"
                uow.operator_sale.insert_offer_revision(
                    OfficialOfferRevisionRow(
                        official_offer_revision_id=offer_revision_id,
                        official_offer_family_id=family_id,
                        slate_revision_id=slate_id,
                        match_id=offer.canonical_match_id,
                        official_match_no=offer.official_match_no,
                        market_definition_ids=tuple(offer.market_definition_ids),
                        sale_opens_at=offer.sale_opens_at.astimezone(UTC).isoformat(),
                        sale_deadline_at=offer.sale_deadline_at.astimezone(UTC).isoformat(),
                        status=offer.status,
                    )
                )
                refs.append(ObjectRef("official_offer_revision", offer_revision_id))
            persisted = uow.operator_sale.persisted_counts_for_slate(slate_id)
            expected = (1, len(manifest.offers), len(manifest.offers))
            if persisted != expected:
                raise ValueError("official sale committed and persisted counts differ")
            refs.append(
                ObjectRef(
                    "official_sale_import_count",
                    f"{slate_id}:1:{len(manifest.offers)}:{len(manifest.offers)}:"
                    f"1:{created_family_count}:{len(manifest.offers)}",
                )
            )
            return tuple(refs)

        outcome = self._action_service.execute(command, handler)
        return self._hydrate_import_result(outcome)

    def import_slate(self, request: ImportOfficialSaleSlateRequest) -> SaleImportResult:
        """Compatibility spelling for kernel callers; the Action name stays explicit."""
        return self.import_official_sale_slate(request)

    def _hydrate_import_result(self, outcome: ActionOutcome) -> SaleImportResult:
        if not outcome.status.is_success:
            return SaleImportResult(
                outcome=outcome,
                slate=None,
                offers=(),
                counts=SaleImportCountReceiptRow(0, 0, 0, 0, 0, 0),
            )
        slate_ref = next(
            ref for ref in outcome.result_refs if ref.object_type == "official_sale_slate_revision"
        )
        count_ref = next(
            ref for ref in outcome.result_refs if ref.object_type == "official_sale_import_count"
        )
        count_parts = count_ref.object_id.rsplit(":", 6)
        if len(count_parts) != 7 or any(not part.isdigit() for part in count_parts[1:]):
            raise ValueError("official sale count receipt is invalid")
        counts = SaleImportCountReceiptRow(*(int(part) for part in count_parts[1:]))
        with self._action_service.unit_of_work() as uow:
            slate = uow.operator_sale.slate_revision(slate_ref.object_id)
            offers = uow.operator_sale.offer_revisions_for_slate(slate_ref.object_id)
            persisted_counts = uow.operator_sale.persisted_counts_for_slate(
                slate_ref.object_id
            )
        linked_counts = (
            counts.slate_revision_count,
            counts.offer_family_count,
            counts.offer_revision_count,
        )
        if (
            slate is None
            or persisted_counts != linked_counts
            or len(offers) != counts.offer_revision_count
        ):
            raise ValueError("official sale result cannot be reconciled")
        return SaleImportResult(outcome=outcome, slate=slate, offers=offers, counts=counts)

    def record_schedule_check(self, request: RecordOfficialScheduleCheckRequest) -> ActionOutcome:
        manifest = self._validated_check(request.manifest)
        payload = manifest.model_dump(mode="json")
        command = ActionCommand.create(
            action_type="record_official_schedule_check",
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload=payload,
            requested_at=request.requested_at,
        )

        def handler(uow, action) -> tuple[ObjectRef, ...]:
            self._assert_official_schedule_run(
                uow,
                manifest.source_run_id,
                check_state=manifest.check_state,
                shanghai_check_date=manifest.shanghai_check_date,
            )
            retrieval_id = manifest.official_source_artifact_retrieval_id
            if retrieval_id is not None:
                retrieval = self._assert_official_retrieval(
                    uow,
                    retrieval_id,
                    expected_content_hash=manifest.official_source_content_hash or "",
                    expected_source_run_id=manifest.source_run_id,
                )
                retrieved_at = datetime.fromisoformat(retrieval["retrieved_at"])
                if (
                    retrieved_at.astimezone(ZoneInfo("Asia/Shanghai")).date()
                    != manifest.shanghai_check_date
                ):
                    raise ValueError("official retrieval must match the Shanghai check date")
                if manifest.checked_at < retrieved_at:
                    raise ValueError("schedule check cannot precede its official retrieval")
            if manifest.checked_at > request.requested_at:
                raise ValueError("schedule check cannot be later than the Action request")
            existing = uow.operator_sale.schedule_check_for_run_scope(
                manifest.source_run_id,
                manifest.lane,
                manifest.shanghai_check_date.isoformat(),
            )
            if existing is not None:
                raise ValueError("schedule check was already recorded for this run, lane, and date")
            persisted_keys = uow.operator_sale.business_keys_for_source_run(
                manifest.lane,
                manifest.source_run_id,
            )
            observed_keys = tuple(manifest.observed_business_keys)
            imported_keys = tuple(manifest.imported_business_keys)
            if manifest.check_state == "slate_imported" and (
                observed_keys != persisted_keys or imported_keys != persisted_keys
            ):
                raise ValueError("schedule check must report the complete business key set")
            if manifest.check_state == "confirmed_no_sale" and persisted_keys:
                raise ValueError("confirmed no sale conflicts with imported sale slates")
            receipt_id = f"OSC-{uuid4().hex}"
            uow.operator_sale.insert_schedule_check(
                OfficialScheduleCheckReceiptRow(
                    schedule_check_id=receipt_id,
                    action_id=action.action_id,
                    lane=manifest.lane,
                    shanghai_check_date=manifest.shanghai_check_date.isoformat(),
                    checked_at=manifest.checked_at.astimezone(UTC).isoformat(),
                    source_run_id=manifest.source_run_id,
                    check_state=manifest.check_state,
                    parser_contract_version=manifest.parser_contract_version,
                    official_source_content_hash=manifest.official_source_content_hash,
                    official_source_artifact_retrieval_id=retrieval_id,
                    observed_business_keys=observed_keys,
                    imported_business_keys=tuple(manifest.imported_business_keys),
                    error_code=manifest.error_code,
                )
            )
            return (ObjectRef("official_schedule_check_receipt", receipt_id),)

        return self._action_service.execute(command, handler)

    def record_official_schedule_check(
        self, request: RecordOfficialScheduleCheckRequest
    ) -> ActionOutcome:
        return self.record_schedule_check(request)


__all__ = [
    "ImportOfficialSaleSlateRequest",
    "OfficialOfferManifestV1",
    "OfficialSaleSlateManifestV1",
    "OfficialScheduleCheckManifestV1",
    "official_empty_schedule_parser_receipt_hash",
    "official_sale_parser_receipt_document",
    "official_sale_parser_receipt_hash",
    "SaleActions",
    "RecordOfficialScheduleCheckRequest",
]

OperatorSaleActions = SaleActions
