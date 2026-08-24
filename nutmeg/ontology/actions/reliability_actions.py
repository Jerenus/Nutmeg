"""Governed Actions for immutable reliability evidence."""
from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime

from nutmeg.ontology.actions.models import (
    ActionCommand,
    ActionOutcome,
    ActorRole,
    ObjectRef,
    canonical_json,
)
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.reliability.models import ReliabilityEvidenceRow
from nutmeg.reliability.contracts import (
    EVIDENCE_KINDS,
    validate_evidence_report,
    validate_json_value,
)


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class RecordReliabilityEvidenceRequest:
    evidence_kind: str
    workflow: str | None
    business_date: str | None
    observed_from: datetime
    observed_to: datetime
    status: str
    report: dict[str, object]
    source_refs: list[ObjectRef]
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for value, name in (
            (self.observed_from, "observed_from"),
            (self.observed_to, "observed_to"),
            (self.requested_at, "requested_at"),
        ):
            _aware(value, name)
        if self.observed_from > self.observed_to:
            raise ValueError("observed_from cannot be after observed_to")
        if self.evidence_kind not in EVIDENCE_KINDS:
            raise ValueError(f"unknown evidence_kind {self.evidence_kind}")
        if self.status not in {"passed", "failed"}:
            raise ValueError("status must be passed or failed")
        if not isinstance(self.report, dict):
            raise ValueError("report must be an object")
        validate_json_value(self.report)
        if not self.source_refs:
            raise ValueError("source_refs cannot be empty")
        if any(
            not ref.object_type.strip() or not ref.object_id.strip()
            for ref in self.source_refs
        ):
            raise ValueError("source_refs must contain non-blank object refs")
        if not self.actor_id.strip():
            raise ValueError("actor_id is required")

        if self.evidence_kind == "soak_run":
            if self.workflow not in {"jczq", "zucai"}:
                raise ValueError("soak workflow must be jczq or zucai")
            if self.business_date is None:
                raise ValueError("soak business_date is required")
            try:
                parsed_date = datetime.strptime(self.business_date, "%Y-%m-%d")
            except ValueError as error:
                raise ValueError("business_date must use YYYY-MM-DD") from error
            if parsed_date.strftime("%Y-%m-%d") != self.business_date:
                raise ValueError("business_date must use YYYY-MM-DD")
        else:
            if self.workflow != "system":
                raise ValueError("non-soak workflow must be system")
            if self.business_date is not None:
                raise ValueError("non-soak business_date must be null")

        result = validate_evidence_report(self.evidence_kind, self.report)
        expected_status = "passed" if result.passed else "failed"
        if self.status != expected_status:
            message = (
                "all checks are true" if result.passed else ", ".join(result.failures)
            )
            raise ValueError(f"status must be {expected_status}: {message}")

        source_refs = [ref.to_dict() for ref in self.source_refs]
        material = {
            "evidence_kind": self.evidence_kind,
            "workflow": self.workflow,
            "business_date": self.business_date,
            "observed_from": self.observed_from.astimezone(UTC).isoformat(),
            "observed_to": self.observed_to.astimezone(UTC).isoformat(),
            "status": self.status,
            "report": self.report,
            "source_refs": source_refs,
        }
        object.__setattr__(
            self,
            "content_hash",
            hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest(),
        )


class ReliabilityActions:
    def __init__(self, action_service: ActionService) -> None:
        self._action_service = action_service

    def record_evidence(
        self, request: RecordReliabilityEvidenceRequest
    ) -> ActionOutcome:
        source_refs = [ref.to_dict() for ref in request.source_refs]
        report = copy.deepcopy(request.report)
        payload = {
            "evidence_kind": request.evidence_kind,
            "workflow": request.workflow,
            "business_date": request.business_date,
            "observed_from": request.observed_from.astimezone(UTC).isoformat(),
            "observed_to": request.observed_to.astimezone(UTC).isoformat(),
            "status": request.status,
            "report": report,
            "source_refs": source_refs,
            "content_hash": request.content_hash,
        }
        command = ActionCommand.create(
            action_type="record_reliability_evidence",
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload=payload,
            requested_at=request.requested_at,
        )

        def handler(uow, action) -> tuple[ObjectRef, ...]:
            existing = uow.reliability.evidence_by_hash(request.content_hash)
            if existing is not None:
                return (
                    ObjectRef(
                        "reliability_evidence", existing.reliability_evidence_id
                    ),
                )
            evidence_id = f"rel-{request.content_hash[:32]}"
            uow.reliability.insert_evidence(
                ReliabilityEvidenceRow(
                    reliability_evidence_id=evidence_id,
                    evidence_kind=request.evidence_kind,
                    workflow=request.workflow,
                    business_date=request.business_date,
                    observed_from=payload["observed_from"],
                    observed_to=payload["observed_to"],
                    status=request.status,
                    report=report,
                    source_refs=source_refs,
                    content_hash=request.content_hash,
                    recorded_at=action.requested_at,
                    action_id=action.action_id,
                )
            )
            return (ObjectRef("reliability_evidence", evidence_id),)

        return self._action_service.execute(command, handler)
