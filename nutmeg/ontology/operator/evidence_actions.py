"""Atomic typed Action for strict operator evidence intake."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select

from nutmeg.ontology.actions.models import (
    ActionCommand,
    ActorRole,
    ObjectRef,
    canonical_json,
)
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.evidence.models import ClaimStatus
from nutmeg.ontology.operator.evidence_manifest import (
    EvidenceIntakeManifestV1,
    MatchEvidenceIntakeV1,
    RecentFormObservationValueV1,
    TypedClaimIntakeV1,
    TypedObservationIntakeV1,
)
from nutmeg.ontology.operator.models import (
    EvidenceCoverageReceiptRow,
    EvidenceIntakeObjectRow,
    EvidenceIntakeReceiptRow,
    EvidenceIntakeResult,
)
from nutmeg.ontology.repository import (
    schema,
    schema_context,
    schema_evidence,
    schema_identity,
)
from nutmeg.ontology.repository.evidence import (
    ClaimEvidenceSpanRow,
    ClaimRow,
    ObservationRow,
)


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _stable_id(prefix: str, *parts: object) -> str:
    material = canonical_json(list(parts)).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(material).hexdigest()}"


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class IngestOperatorEvidenceRequest:
    manifest: EvidenceIntakeManifestV1
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _aware(self.requested_at, "requested_at")
        if not self.actor_id.strip():
            raise ValueError("actor_id is required")
        if not self.idempotency_key.strip():
            raise ValueError("idempotency_key is required")


class EvidenceActions:
    def __init__(self, action_service: ActionService) -> None:
        self._action_service = action_service

    def ingest_operator_evidence_manifest(
        self,
        request: IngestOperatorEvidenceRequest,
    ) -> EvidenceIntakeResult:
        manifest = EvidenceIntakeManifestV1.model_validate(
            request.manifest.model_dump(mode="python")
        )
        if manifest.captured_at > request.requested_at:
            raise ValueError("manifest captured_at must not follow requested_at")
        object_count = sum(
            len(match.observations) + len(match.claims) for match in manifest.matches
        )
        with self._action_service.unit_of_work() as uow:
            task_snapshot_hash = self._preflight(
                uow,
                manifest,
                require_current_slate=False,
            )
        command = ActionCommand.create(
            action_type="ingest_operator_evidence_manifest",
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            requested_at=request.requested_at,
            payload={
                "schema_version": manifest.schema_version,
                "lane": manifest.lane,
                "business_key": manifest.business_key,
                "slate_revision_id": manifest.slate_revision_id,
                "task_snapshot_hash": task_snapshot_hash,
                "manifest_sha256": manifest.manifest_sha256,
                "match_count": len(manifest.matches),
                "object_count": object_count,
            },
        )
        receipt_id = _stable_id("evidence-intake", manifest.manifest_sha256)

        def handler(uow, action_command) -> tuple[ObjectRef, ...]:
            if self._preflight(uow, manifest) != task_snapshot_hash:
                raise ValueError("evidence task snapshot changed during intake")
            retrieval_ids = tuple(
                sorted(
                    {
                        source.artifact_retrieval_id
                        for match in manifest.matches
                        for source in match.source_receipts
                    }
                )
            )
            receipt = EvidenceIntakeReceiptRow(
                intake_receipt_id=receipt_id,
                action_id=action_command.action_id,
                lane=manifest.lane,
                business_key=manifest.business_key,
                slate_revision_id=manifest.slate_revision_id,
                task_snapshot_hash=task_snapshot_hash,
                captured_at=_utc(manifest.captured_at),
                manifest_sha256=manifest.manifest_sha256,
                source_retrieval_ids=retrieval_ids,
                committed_count=object_count,
                rejected_count=0,
                skipped_count=0,
                persisted_count=object_count,
                created_at=_utc(request.requested_at),
            )
            uow.operator_decision.insert_evidence_intake_receipt(receipt)

            object_index = 0
            for match_index, match in enumerate(manifest.matches):
                local_refs: dict[str, str] = {}
                sources = {
                    source.artifact_retrieval_id: source
                    for source in match.source_receipts
                }
                for index, observation in enumerate(match.observations):
                    object_id = _stable_id(
                        "obs",
                        manifest.manifest_sha256,
                        match_index,
                        "observation",
                        index,
                    )
                    self._insert_observation(
                        uow,
                        object_id,
                        match,
                        observation,
                        request.requested_at,
                    )
                    local_refs[f"observation:{index}"] = object_id
                    uow.operator_decision.insert_evidence_intake_object(
                        EvidenceIntakeObjectRow(
                            intake_object_id=_stable_id("intake-object", receipt_id, object_index),
                            intake_receipt_id=receipt_id,
                            match_id=match.canonical_match_id,
                            object_kind="observation",
                            object_id=object_id,
                            object_index=object_index,
                            observed_at=_utc(observation.observed_at),
                            source_retrieval_ids=tuple(observation.artifact_retrieval_ids),
                            source_kinds=tuple(
                                sorted(
                                    {
                                        sources[retrieval_id].source_kind
                                        for retrieval_id in observation.artifact_retrieval_ids
                                    }
                                )
                            ),
                        )
                    )
                    object_index += 1
                for index, claim in enumerate(match.claims):
                    object_id = _stable_id(
                        "claim",
                        manifest.manifest_sha256,
                        match_index,
                        "claim",
                        index,
                    )
                    self._insert_claim(
                        uow,
                        object_id,
                        match,
                        claim,
                        request.requested_at,
                        action_command.action_id,
                    )
                    local_refs[f"claim:{index}"] = object_id
                    claim_retrieval_ids = tuple(
                        sorted({span.artifact_retrieval_id for span in claim.spans})
                    )
                    uow.operator_decision.insert_evidence_intake_object(
                        EvidenceIntakeObjectRow(
                            intake_object_id=_stable_id("intake-object", receipt_id, object_index),
                            intake_receipt_id=receipt_id,
                            match_id=match.canonical_match_id,
                            object_kind="claim",
                            object_id=object_id,
                            object_index=object_index,
                            observed_at=_utc(
                                min(
                                    sources[retrieval_id].captured_at
                                    for retrieval_id in claim_retrieval_ids
                                )
                            ),
                            source_retrieval_ids=claim_retrieval_ids,
                            source_kinds=tuple(
                                sorted(
                                    {
                                        sources[retrieval_id].source_kind
                                        for retrieval_id in claim_retrieval_ids
                                    }
                                )
                            ),
                        )
                    )
                    object_index += 1
                for coverage_index, coverage in enumerate(match.coverage_receipts):
                    normalized_refs = tuple(
                        local_refs.get(token, token) for token in coverage.evidence_ref_tokens
                    )
                    uow.operator_decision.insert_evidence_coverage_receipt(
                        EvidenceCoverageReceiptRow(
                            coverage_receipt_id=_stable_id(
                                "evidence-coverage",
                                receipt_id,
                                match_index,
                                coverage_index,
                            ),
                            intake_receipt_id=receipt_id,
                            match_id=match.canonical_match_id,
                            requirement_id=coverage.requirement_id,
                            subject_scope=coverage.subject_scope,
                            evidence_ref_tokens=normalized_refs,
                        )
                    )

            persisted_count = uow.operator_decision.evidence_intake_object_count(receipt_id)
            concrete_count = (
                uow.operator_decision.evidence_intake_concrete_object_count(receipt_id)
            )
            if persisted_count != object_count or concrete_count != object_count:
                raise ValueError(
                    "operator evidence persisted count does not match committed count"
                )
            return (ObjectRef("operator_evidence_intake_receipt", receipt_id),)

        outcome = self._action_service.execute(command, handler)
        receipt = None
        if outcome.is_success:
            with self._action_service.unit_of_work() as uow:
                receipt = uow.operator_decision.evidence_intake_receipt_for_action(
                    outcome.action_id
                )
            if receipt is None:
                raise RuntimeError("committed evidence intake is missing its receipt")
        return EvidenceIntakeResult(outcome=outcome, receipt=receipt)

    @staticmethod
    def _preflight(
        uow,
        manifest: EvidenceIntakeManifestV1,
        *,
        require_current_slate: bool = True,
    ) -> str:
        slate = uow.operator_sale.slate_revision(manifest.slate_revision_id)
        current = uow.operator_sale.current_slate(manifest.lane, manifest.business_key)
        if slate is None or (
            slate.lane != manifest.lane or slate.business_key != manifest.business_key
        ):
            raise ValueError("evidence manifest slate does not match its lane and business key")
        if require_current_slate and (
            current is None or current.slate_revision_id != manifest.slate_revision_id
        ):
            raise ValueError("evidence manifest must bind the current official slate")
        offer_rows = uow.operator_sale.offer_revisions_for_slate(
            manifest.slate_revision_id
        )
        task_snapshot_hash = EvidenceActions._task_snapshot_hash(
            slate,
            offer_rows,
            manifest.captured_at,
        )
        offers = {(offer.official_match_no, offer.match_id) for offer in offer_rows}
        for match in manifest.matches:
            if (match.official_match_no, match.canonical_match_id) not in offers:
                raise ValueError("evidence match does not belong to the official slate")
            EvidenceActions._preflight_match(
                uow,
                match,
                captured_at=manifest.captured_at,
            )
        return task_snapshot_hash

    @staticmethod
    def _task_snapshot_hash(slate, offers, as_of: datetime) -> str:
        def sort_key(offer) -> tuple[str, int, str, str, str]:
            match = re.fullmatch(r"(?P<prefix>.*?)(?P<number>[0-9]+)", offer.official_match_no)
            prefix = match.group("prefix") if match else offer.official_match_no
            number = int(match.group("number")) if match else 0
            return (
                prefix,
                number,
                offer.official_match_no,
                offer.official_offer_family_id,
                offer.official_offer_revision_id,
            )

        def state(offer) -> str:
            opens_at = datetime.fromisoformat(offer.sale_opens_at)
            deadline_at = datetime.fromisoformat(offer.sale_deadline_at)
            if offer.status == "cancelled":
                return "cancelled"
            if offer.status == "sale_closed" or deadline_at <= as_of:
                return "closed"
            if as_of < opens_at:
                return "upcoming"
            return "open"

        document = {
            "lane": slate.lane,
            "business_key": slate.business_key,
            "slate_revision_id": slate.slate_revision_id,
            "slate_content_hash": slate.content_hash,
            "offers": [
                {
                    "official_offer_family_id": offer.official_offer_family_id,
                    "official_offer_revision_id": offer.official_offer_revision_id,
                    "match_id": offer.match_id,
                    "official_match_no": offer.official_match_no,
                    "market_definition_ids": list(offer.market_definition_ids),
                    "sale_opens_at": datetime.fromisoformat(
                        offer.sale_opens_at
                    ).astimezone(UTC).isoformat(),
                    "sale_deadline_at": datetime.fromisoformat(
                        offer.sale_deadline_at
                    ).astimezone(UTC).isoformat(),
                    "source_status": offer.status,
                    "derived_state": state(offer),
                }
                for offer in sorted(offers, key=sort_key)
            ],
            "no_ticket_closures": [],
        }
        return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()

    @staticmethod
    def _preflight_match(
        uow,
        match: MatchEvidenceIntakeV1,
        *,
        captured_at: datetime,
    ) -> None:
        declared_retrievals: dict[str, str] = {}
        declared_source_kinds: dict[str, str] = {}
        for source in match.source_receipts:
            row = (
                uow.connection.execute(
                    select(
                        schema.artifact_retrievals.c.artifact_id,
                        schema.artifact_retrievals.c.source_run_id,
                        schema.artifact_retrievals.c.source_name,
                        schema.artifact_retrievals.c.source_type,
                        schema.artifact_retrievals.c.retrieved_at,
                        schema.artifact_retrievals.c.status,
                        schema.source_runs.c.source_name.label("run_source_name"),
                        schema.source_runs.c.source_type.label("run_source_type"),
                        schema.source_runs.c.status.label("run_status"),
                    )
                    .select_from(
                        schema.artifact_retrievals.join(
                            schema.source_runs,
                            schema.artifact_retrievals.c.source_run_id
                            == schema.source_runs.c.source_run_id,
                        )
                    )
                    .where(
                        schema.artifact_retrievals.c.artifact_retrieval_id
                        == source.artifact_retrieval_id
                    )
                )
                .mappings()
                .first()
            )
            if row is None or row["source_run_id"] != source.source_run_id:
                raise ValueError("evidence source run does not match artifact retrieval")
            if (
                row["source_name"] != row["run_source_name"]
                or row["source_type"] != row["run_source_type"]
            ):
                raise ValueError("evidence retrieval provenance does not match its source run")
            if row["source_type"] != source.source_kind:
                raise ValueError(
                    "evidence manifest source kind does not match retrieval provenance"
                )
            if row["status"] != "stored" or row["run_status"] != "succeeded":
                raise ValueError("evidence source retrieval must be stored by a successful run")
            if datetime.fromisoformat(row["retrieved_at"]).astimezone(UTC) != (
                source.captured_at.astimezone(UTC)
            ):
                raise ValueError("evidence source captured_at does not match retrieval")
            if source.captured_at > captured_at:
                raise ValueError("evidence source captured_at follows manifest captured_at")
            declared_retrievals[source.artifact_retrieval_id] = row["artifact_id"]
            declared_source_kinds[source.artifact_retrieval_id] = source.source_kind

        for observation in match.observations:
            EvidenceActions._assert_subject(
                uow,
                observation.subject_type,
                observation.canonical_subject_id,
            )
            EvidenceActions._assert_value_tokens(uow, observation.value)
            EvidenceActions._assert_match_team(
                uow,
                match.canonical_match_id,
                observation.value.team_token,
            )
            if isinstance(observation.value, RecentFormObservationValueV1) and not any(
                declared_source_kinds[retrieval_id] == "authoritative_results"
                for retrieval_id in observation.artifact_retrieval_ids
            ):
                raise ValueError(
                    "recent-form evidence requires an authoritative_results source"
                )
        for claim in match.claims:
            EvidenceActions._assert_subject(uow, claim.subject_type, claim.canonical_subject_id)
            EvidenceActions._assert_value_tokens(uow, claim.value)
            EvidenceActions._assert_match_team(
                uow,
                match.canonical_match_id,
                claim.value.team_token,
            )
            for span in claim.spans:
                if declared_retrievals.get(span.artifact_retrieval_id) != span.artifact_id:
                    raise ValueError("evidence span artifact does not match retrieval")

        local_refs = {
            *(f"observation:{index}" for index in range(len(match.observations))),
            *(f"claim:{index}" for index in range(len(match.claims))),
        }
        for coverage in match.coverage_receipts:
            for token in coverage.evidence_ref_tokens:
                if token in local_refs:
                    continue
                candidates = []
                for table, id_column in (
                    (
                        schema_evidence.observations,
                        schema_evidence.observations.c.observation_id,
                    ),
                    (schema_evidence.claims, schema_evidence.claims.c.claim_id),
                ):
                    row = uow.connection.execute(
                        select(
                            table.c.scope_match_id,
                            table.c.subject_type,
                            table.c.subject_id,
                        ).where(id_column == token)
                    ).first()
                    if row is not None:
                        candidates.append(row)
                if not candidates:
                    raise ValueError("coverage references unknown evidence")
                if len(candidates) != 1:
                    raise ValueError("coverage references ambiguous evidence")
                evidence = candidates[0]
                belongs_to_match = evidence.scope_match_id == match.canonical_match_id or (
                    evidence.scope_match_id is None
                    and evidence.subject_type == "match"
                    and evidence.subject_id == match.canonical_match_id
                )
                if not belongs_to_match:
                    raise ValueError("coverage evidence does not belong to manifest match")

    @staticmethod
    def _assert_subject(uow, subject_type: str, subject_id: str) -> None:
        table_column = {
            "match": schema_identity.matches.c.match_id,
            "team": schema_identity.teams.c.team_id,
            "person": schema_context.persons.c.person_id,
        }[subject_type]
        if uow.connection.scalar(
            select(table_column).where(table_column == subject_id)
        ) is None:
            raise ValueError(f"unknown canonical {subject_type} subject")

    @staticmethod
    def _assert_match_team(uow, match_id: str, team_id: str) -> None:
        participant = uow.connection.scalar(
            select(schema_identity.team_appearances.c.team_id).where(
                schema_identity.team_appearances.c.match_id == match_id,
                schema_identity.team_appearances.c.team_id == team_id,
            )
        )
        if participant is None:
            raise ValueError("evidence team does not participate in the manifest match")

    @staticmethod
    def _assert_value_tokens(uow, value) -> None:
        team_token = getattr(value, "team_token", None)
        if team_token is not None:
            EvidenceActions._assert_subject(uow, "team", team_token)
        person_token = getattr(value, "person_token", None)
        if person_token is not None:
            EvidenceActions._assert_subject(uow, "person", person_token)
        for sample in getattr(value, "sample_match_tokens", ()):
            EvidenceActions._assert_subject(uow, "match", sample)

    @staticmethod
    def _insert_observation(
        uow,
        observation_id: str,
        match: MatchEvidenceIntakeV1,
        observation: TypedObservationIntakeV1,
        requested_at: datetime,
    ) -> None:
        uow.evidence.insert_observation(
            ObservationRow(
                observation_id=observation_id,
                observation_type=observation.observation_schema,
                subject_type=observation.subject_type,
                subject_id=observation.canonical_subject_id,
                scope_match_id=match.canonical_match_id,
                value=observation.value.model_dump(mode="json"),
                schema_version="1",
                valid_from=_utc(observation.valid_from),
                valid_to=_utc(observation.valid_to) if observation.valid_to else None,
                observed_at=_utc(observation.observed_at),
                recorded_at=_utc(requested_at),
                verification_method=observation.verification_method,
                quality={"operator_evidence_policy": "operator-evidence-policy-v1"},
            ),
            artifact_retrieval_ids=tuple(observation.artifact_retrieval_ids),
        )

    @staticmethod
    def _insert_claim(
        uow,
        claim_id: str,
        match: MatchEvidenceIntakeV1,
        claim: TypedClaimIntakeV1,
        requested_at: datetime,
        action_id: str,
    ) -> None:
        at = _utc(requested_at)
        uow.evidence.insert_claim(
            ClaimRow(
                claim_id=claim_id,
                subject_type=claim.subject_type,
                subject_id=claim.canonical_subject_id,
                predicate=claim.predicate,
                value=claim.value.model_dump(mode="json"),
                scope_match_id=claim.scope_match_id or match.canonical_match_id,
                valid_from=_utc(claim.valid_from),
                valid_to=_utc(claim.valid_to) if claim.valid_to else None,
                status=ClaimStatus.PROVISIONAL.value,
                extractor=claim.extractor,
                extractor_version=claim.extractor_version,
                created_at=at,
                adjudicated_at=None,
            )
        )
        for span_index, span in enumerate(claim.spans):
            uow.evidence.insert_evidence_span(
                ClaimEvidenceSpanRow(
                    claim_evidence_span_id=_stable_id(
                        "span", claim_id, span_index, span.artifact_retrieval_id
                    ),
                    claim_id=claim_id,
                    artifact_id=span.artifact_id,
                    artifact_retrieval_id=span.artifact_retrieval_id,
                    quote=span.quote,
                    locator=span.locator,
                )
            )
        uow.evidence.insert_claim_status_event(
            _stable_id("cse", claim_id, action_id),
            claim_id,
            None,
            ClaimStatus.PROVISIONAL.value,
            action_id,
            at,
        )


__all__ = ["EvidenceActions", "IngestOperatorEvidenceRequest"]
