"""Explicit, versioned import of legacy operator artifacts.

Legacy files are evidence for replay, never task-discovery authority.  The
importer validates the complete selected contract before writing any Action,
stores the source in CAS, maps only existing typed workflow Actions, and keeps
every historical ticket candidate non-deployable.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationError,
    field_validator,
    model_validator,
)

from nutmeg.decision.rx_ingest import map_rx_adjudications, map_rx_predictions
from nutmeg.ontology.actions.artifact_ingest import (
    ArtifactIngestRequest,
    ArtifactIngestService,
)
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.workflow_actions import (
    RecordAdjudicationRequest,
    RegisterPredictionRequest,
    WorkflowActions,
)
from nutmeg.product.operator_artifacts import (
    PrepAlignment,
    PrepScreens,
    ZucaiIssueDocument,
    parse_shanghai,
)

LEGACY_RX_V2_CONTRACT = "zucai-legacy-rx-v2"
LEGACY_RX_V3_CONTRACT = "zucai-legacy-rx-v3"
LEGACY_ISSUE_CONTRACT = "zucai-legacy-issue-v1"
LEGACY_PREP_CONTRACT = "zucai-legacy-prep-v1"

_KNOWN_CONTRACTS = frozenset(
    {
        LEGACY_RX_V2_CONTRACT,
        LEGACY_RX_V3_CONTRACT,
        LEGACY_ISSUE_CONTRACT,
        LEGACY_PREP_CONTRACT,
    }
)
_FILE_PATTERN = re.compile(
    r"^(?P<issue>\d{5})-(?P<kind>rx|issue|prep(?:-[A-Za-z0-9_-]+)?)\.json$"
)
_MATCH_NUMBERS = tuple(str(index) for index in range(1, 15))


class _StrictLegacyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class LegacyPredictionInput(_StrictLegacyModel):
    id: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    falsifier: str = Field(min_length=1)
    outcome: str | None = None


class LegacyAdjudicationInput(_StrictLegacyModel):
    id: str = Field(min_length=1)
    status: str
    q: str
    options: str | None = None
    default: str | None = None
    reason: str | None = None
    resolution: str | None = None
    note: str | None = None
    evidence_rejected: str | None = None


class LegacyPrescriptionV2A(_StrictLegacyModel):
    singles: dict[str, str]
    doubles: dict[str, str]
    fulls: list[str]
    expected_broken_legs: float
    p_all: float
    difficulty_price_cny: int
    audit_P14: str


class LegacyPrescriptionV2B(_StrictLegacyModel):
    singles: dict[str, str]
    doubles: dict[str, str]
    fulls: list[str]
    note: str
    compliant_min_price_cny: int
    in_cap_compliant_count: int


class _LegacyRxBase(_StrictLegacyModel):
    issue: str = Field(pattern=r"^\d{5}$")
    registered_at: str
    decision: str
    pending_adjudications: list[LegacyAdjudicationInput]
    predictions: list[LegacyPredictionInput]

    @field_validator("registered_at", mode="after")
    @classmethod
    def require_aware_registered_at(cls, value: str) -> str:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("registered_at must be a timezone-aware ISO 8601 string")
        return value

    @model_validator(mode="after")
    def require_unique_workflow_ids(self):
        prediction_ids = [item.id for item in self.predictions]
        adjudication_ids = [item.id for item in self.pending_adjudications]
        if len(prediction_ids) != len(set(prediction_ids)):
            raise ValueError("legacy prediction IDs must be unique")
        if len(adjudication_ids) != len(set(adjudication_ids)):
            raise ValueError("legacy adjudication IDs must be unique")
        return self


class LegacyZucaiRxV2(_LegacyRxBase):
    prescription_P14: LegacyPrescriptionV2A | LegacyPrescriptionV2B
    ticket_versions: dict[str, str]
    capital_report: dict[str, str]
    notes: str
    outcomes: dict[str, JsonValue] | None = None
    supplementary_research: dict[str, JsonValue] | None = None
    two_to_one_analysis: dict[str, JsonValue] | None = None
    final_ticket_evolution: dict[str, JsonValue] | None = None


class LegacyCandidateInput(_StrictLegacyModel):
    id: str = Field(min_length=1)
    faces: dict[str, str] | None = None
    audit: str | None = None
    audit_est: str | None = None
    break_even: float | None = None
    break_even_bonus: float | None = None
    break_even_to_median: float | None = None
    capital_util: float | None = None
    drop: list[int] | None = None
    expected_broken: float | None = None
    gate: str | None = None
    multiple: float | None = None
    multiple_new_anchor: float | None = None
    note: str | None = None
    notes: int | None = None
    p_model: float | None = None
    p_model_market: float | None = None
    p_model_mech: float | None = None
    stake_yuan: float | None = None
    status: str | None = None

    @field_validator("faces", mode="after")
    @classmethod
    def validate_faces(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is None:
            return None
        if not value:
            raise ValueError("legacy candidate faces must not be empty")
        for match_no, faces in value.items():
            if match_no not in _MATCH_NUMBERS:
                raise ValueError("legacy candidate face keys must be match numbers 1 to 14")
            if (
                not faces
                or any(face not in "310" for face in faces)
                or len(set(faces)) != len(faces)
            ):
                raise ValueError("legacy candidate faces must contain unique 3, 1, or 0")
        return value

    @model_validator(mode="after")
    def require_face_drop_partition(self):
        if self.faces is None:
            if self.drop:
                raise ValueError("faceless legacy candidate cannot declare dropped matches")
            return self
        if self.drop is None:
            raise ValueError("face-bearing legacy candidate requires dropped matches")
        face_numbers = {int(value) for value in self.faces}
        drop_numbers = set(self.drop)
        if (
            len(drop_numbers) != len(self.drop)
            or face_numbers & drop_numbers
            or face_numbers | drop_numbers != set(range(1, 15))
        ):
            raise ValueError("legacy candidate faces and drops must partition matches 1 to 14")
        return self


class LegacyZucaiRxV3(_LegacyRxBase):
    prescription_P14: str
    board_diagnosis: dict[str, JsonValue] | None = None
    capital_report: dict[str, JsonValue]
    ticket_versions: list[LegacyCandidateInput]
    notes: list[str]

    @model_validator(mode="after")
    def require_unique_candidate_ids(self):
        candidate_ids = [item.id for item in self.ticket_versions]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("legacy candidate IDs must be unique within an issue")
        return self


class LegacyProbabilityTriple(_StrictLegacyModel):
    home: float = Field(ge=0, le=1)
    draw: float = Field(ge=0, le=1)
    away: float = Field(ge=0, le=1)


class LegacyFullPrepRecord(_StrictLegacyModel):
    name: str
    league: str
    kickoff_bj: str
    match_date: str
    sporttery_match_num: str | None
    fair_had: LegacyProbabilityTriple
    sporttery_had_date: str | None
    hhad_line: str | None = None
    ttg_anchor: bool
    lambdas: list[float] = Field(alias="lambda", min_length=3, max_length=3)
    fit_loss: float
    dc_had: list[float] = Field(min_length=3, max_length=3)
    top_scores: list[list[str | float]]
    ttg_bands: dict[str, float]
    over25: float = Field(ge=0, le=1)
    margin: dict[str, float]
    home_by_2plus: float = Field(ge=0, le=1)
    away_by_2plus: float = Field(ge=0, le=1)
    hhad_cover: dict[str, float | str] | None

    @field_validator("top_scores", mode="after")
    @classmethod
    def validate_score_pairs(cls, value: list[list[str | float]]) -> list[list[str | float]]:
        if any(
            len(item) != 2
            or not isinstance(item[0], str)
            or isinstance(item[1], bool)
            or not isinstance(item[1], (int, float))
            for item in value
        ):
            raise ValueError("legacy top_scores must contain [score, probability] pairs")
        return value


class LegacyPrepSummaryRecord(_StrictLegacyModel):
    name: str


class LegacyZucaiPrepV1(_StrictLegacyModel):
    issue: str = Field(pattern=r"^\d{5}$")
    run_date: str
    slot: str
    captured_at: str
    n_matches: int
    alignment: PrepAlignment
    screens: PrepScreens
    records: dict[str, LegacyFullPrepRecord | LegacyPrepSummaryRecord]
    judgment: None

    @field_validator("captured_at", mode="after")
    @classmethod
    def require_datetime(cls, value: str) -> str:
        parse_shanghai(value)
        return value

    @model_validator(mode="after")
    def require_official_order(self):
        if self.n_matches != 14 or tuple(self.records) != _MATCH_NUMBERS:
            raise ValueError("legacy prep must preserve official order 1 through 14")
        if any(not record for record in self.records.values()):
            raise ValueError("legacy prep records must be non-empty objects")
        return self


class LegacyCandidateDraft(_StrictLegacyModel):
    draft_id: str
    label: str
    deployable: Literal[False] = False
    reason_code: Literal["legacy_faces_missing", "legacy_audit_required"]
    faces: dict[str, str] | None
    legacy_text: str | None = None


class LegacyImportReceipt(_StrictLegacyModel):
    kind: Literal["legacy_import_receipt_v1"] = "legacy_import_receipt_v1"
    status: Literal["imported"] = "imported"
    contract_version: str
    document_kind: Literal["rx", "issue", "prep"]
    business_key: str
    source_sha256: str
    source_action_id: str
    source_artifact_id: str
    source_artifact_retrieval_id: str
    provenance_state: Literal["legacy_replay"] = "legacy_replay"
    prediction_count: int = 0
    adjudication_total_count: int = 0
    adjudication_committed_count: int = 0
    adjudication_skipped_count: int = 0
    adjudication_skips: tuple[str, ...] = ()
    record_count: int = 0
    official_match_nos: tuple[str, ...] = ()
    candidate_drafts: tuple[LegacyCandidateDraft, ...] = ()
    workflow_action_ids: tuple[str, ...] = ()
    committed_at: AwareDatetime


class LegacyQuarantineReport(_StrictLegacyModel):
    kind: Literal["legacy_quarantine_report_v1"] = "legacy_quarantine_report_v1"
    status: Literal["quarantined"] = "quarantined"
    contract_version: str
    source_sha256: str
    reason_code: Literal[
        "unknown_contract_version",
        "manifest_invalid",
        "issue_binding_mismatch",
        "source_unreadable",
    ]
    detail: str
    business_key: str | None = None
    committed_workflow_action_count: Literal[0] = 0


@dataclass(frozen=True, slots=True)
class _ValidatedImport:
    document_kind: Literal["rx", "issue", "prep"]
    issue: str
    published_at: str | None
    recorded_at: datetime
    prediction_requests: tuple[RegisterPredictionRequest, ...]
    adjudication_requests: tuple[RecordAdjudicationRequest, ...]
    adjudication_total_count: int
    adjudication_skipped_count: int
    adjudication_skips: tuple[str, ...]
    official_match_nos: tuple[str, ...]
    record_count: int
    candidate_drafts: tuple[LegacyCandidateDraft, ...]


class LegacyOperatorImporter:
    def __init__(
        self,
        *,
        artifact_ingest: ArtifactIngestService,
        workflow: WorkflowActions,
    ) -> None:
        self._artifact_ingest = artifact_ingest
        self._workflow = workflow

    def import_path(
        self,
        path: Path,
        *,
        contract_version: str,
        imported_at: datetime,
    ) -> LegacyImportReceipt | LegacyQuarantineReport:
        if imported_at.tzinfo is None or imported_at.utcoffset() is None:
            raise ValueError("imported_at must be timezone-aware")
        source_path = Path(path).expanduser()
        try:
            content = source_path.read_bytes()
        except OSError as error:
            return self._quarantine(
                contract_version,
                b"",
                "source_unreadable",
                str(error),
            )
        digest = hashlib.sha256(content).hexdigest()
        if contract_version not in _KNOWN_CONTRACTS:
            return self._quarantine(
                contract_version,
                content,
                "unknown_contract_version",
                "legacy contract version is not allowlisted",
            )
        raw: object = None
        try:
            raw = json.loads(content)
            if not isinstance(raw, dict):
                raise ValueError("legacy manifest root must be an object")
            validated = self._validate(
                raw,
                filename=source_path.name,
                contract_version=contract_version,
            )
        except _IssueBindingError as error:
            return self._quarantine(
                contract_version,
                content,
                "issue_binding_mismatch",
                str(error),
                business_key=error.issue,
            )
        except (json.JSONDecodeError, ValidationError, ValueError) as error:
            issue = raw.get("issue") or raw.get("issue_id") if isinstance(raw, dict) else None
            return self._quarantine(
                contract_version,
                content,
                "manifest_invalid",
                str(error),
                business_key=issue if isinstance(issue, str) else None,
            )

        workflow_operations = tuple(
            self._workflow.prepare_register_prediction(
                request,
                action_id=_stable_action_id(request.idempotency_key),
            )
            for request in validated.prediction_requests
        ) + tuple(
            self._workflow.prepare_record_adjudication(
                request,
                action_id=_stable_action_id(request.idempotency_key),
            )
            for request in validated.adjudication_requests
        )
        workflow_action_ids = tuple(
            command.action_id for command, _handler in workflow_operations
        )
        source_key = f"legacy-operator:{contract_version}:{digest}"
        source_action_id = _stable_action_id(source_key)
        source_artifact_id = f"sha256:{digest}"
        retrieval_id = "RET-" + hashlib.sha256(source_key.encode("utf-8")).hexdigest()[:32]
        durable_receipt = {
            "kind": "legacy_import_receipt_v1",
            "status": "imported",
            "contract_version": contract_version,
            "document_kind": validated.document_kind,
            "business_key": validated.issue,
            "source_sha256": digest,
            "source_action_id": source_action_id,
            "source_artifact_id": source_artifact_id,
            "source_artifact_retrieval_id": retrieval_id,
            "provenance_state": "legacy_replay",
            "prediction_count": len(validated.prediction_requests),
            "adjudication_total_count": validated.adjudication_total_count,
            "adjudication_committed_count": len(validated.adjudication_requests),
            "adjudication_skipped_count": validated.adjudication_skipped_count,
            "adjudication_skips": list(validated.adjudication_skips),
            "record_count": validated.record_count,
            "official_match_nos": list(validated.official_match_nos),
            "candidate_drafts": [
                draft.model_dump(mode="json") for draft in validated.candidate_drafts
            ],
            "workflow_action_ids": list(workflow_action_ids),
        }
        source_operation = self._artifact_ingest.prepare(
            ArtifactIngestRequest(
                content=content,
                content_type="application/json",
                source_name="nutmeg_legacy_operator",
                source_type=contract_version,
                actor_id="operator:jun",
                actor_role=ActorRole.JUDGE_OPERATOR,
                idempotency_key=source_key,
                retrieved_at=validated.recorded_at,
                requested_url=f"legacy://{source_path.name}",
                published_at=validated.published_at,
            ),
            action_id=source_action_id,
            payload_extension={"legacy_import_receipt": durable_receipt},
        )
        outcomes = self._artifact_ingest.execute_batch(
            (source_operation, *workflow_operations)
        )
        source = outcomes[0]
        if not all(outcome.is_success for outcome in outcomes):
            raise RuntimeError("legacy operator Action batch was not committed")
        committed_values = [
            datetime.fromisoformat(outcome.committed_at)
            for outcome in outcomes
            if outcome.committed_at is not None
        ]
        committed_at = max(committed_values, default=validated.recorded_at)
        return LegacyImportReceipt(
            contract_version=contract_version,
            document_kind=validated.document_kind,
            business_key=validated.issue,
            source_sha256=digest,
            source_action_id=source.action_id,
            source_artifact_id=source_artifact_id,
            source_artifact_retrieval_id=retrieval_id,
            prediction_count=len(validated.prediction_requests),
            adjudication_total_count=validated.adjudication_total_count,
            adjudication_committed_count=len(validated.adjudication_requests),
            adjudication_skipped_count=validated.adjudication_skipped_count,
            adjudication_skips=validated.adjudication_skips,
            record_count=validated.record_count,
            official_match_nos=validated.official_match_nos,
            candidate_drafts=validated.candidate_drafts,
            workflow_action_ids=workflow_action_ids,
            committed_at=committed_at,
        )

    @staticmethod
    def _validate(
        raw: dict[str, object],
        *,
        filename: str,
        contract_version: str,
    ) -> _ValidatedImport:
        if contract_version == LEGACY_RX_V2_CONTRACT:
            rx: LegacyZucaiRxV2 | LegacyZucaiRxV3 = LegacyZucaiRxV2.model_validate(raw)
            drafts = tuple(
                classify_legacy_candidate(rx.issue, label, None, legacy_text=summary)
                for label, summary in rx.ticket_versions.items()
            )
            return _validated_rx(rx, filename, drafts)
        if contract_version == LEGACY_RX_V3_CONTRACT:
            rx = LegacyZucaiRxV3.model_validate(raw)
            drafts = tuple(
                classify_legacy_candidate(
                    rx.issue,
                    item.id,
                    item.faces,
                    legacy_text=(
                        json.dumps(
                            item.model_dump(mode="json", exclude_none=True),
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        if item.faces is None
                        else None
                    ),
                )
                for item in rx.ticket_versions
            )
            return _validated_rx(rx, filename, drafts)
        if contract_version == LEGACY_ISSUE_CONTRACT:
            issue = ZucaiIssueDocument.model_validate(raw)
            _assert_filename_binding(filename, issue.issue_id, "issue")
            if not issue.sources:
                raise ValueError("legacy issue requires at least one recorded source")
            order = tuple(str(match.match_no) for match in issue.matches)
            if order != _MATCH_NUMBERS:
                raise ValueError("legacy issue must preserve official order 1 through 14")
            return _ValidatedImport(
                document_kind="issue",
                issue=issue.issue_id,
                published_at=issue.sources[0].captured_at,
                recorded_at=parse_shanghai(issue.sources[0].captured_at),
                prediction_requests=(),
                adjudication_requests=(),
                adjudication_total_count=0,
                adjudication_skipped_count=0,
                adjudication_skips=(),
                official_match_nos=order,
                record_count=len(order),
                candidate_drafts=(),
            )
        prep = LegacyZucaiPrepV1.model_validate(raw)
        _assert_filename_binding(filename, prep.issue, "prep")
        return _ValidatedImport(
            document_kind="prep",
            issue=prep.issue,
            published_at=parse_shanghai(prep.captured_at).isoformat(),
            recorded_at=parse_shanghai(prep.captured_at),
            prediction_requests=(),
            adjudication_requests=(),
            adjudication_total_count=0,
            adjudication_skipped_count=0,
            adjudication_skips=(),
            official_match_nos=tuple(prep.records),
            record_count=len(prep.records),
            candidate_drafts=(),
        )

    @staticmethod
    def _quarantine(
        contract_version: str,
        content: bytes,
        reason_code: Literal[
            "unknown_contract_version",
            "manifest_invalid",
            "issue_binding_mismatch",
            "source_unreadable",
        ],
        detail: str,
        *,
        business_key: str | None = None,
    ) -> LegacyQuarantineReport:
        return LegacyQuarantineReport(
            contract_version=contract_version,
            source_sha256=hashlib.sha256(content).hexdigest(),
            reason_code=reason_code,
            detail=detail,
            business_key=business_key,
        )


class _IssueBindingError(ValueError):
    def __init__(self, issue: str, message: str) -> None:
        super().__init__(message)
        self.issue = issue


def _assert_filename_binding(filename: str, issue: str, expected_kind: str) -> None:
    match = _FILE_PATTERN.fullmatch(filename)
    actual_kind = match.group("kind").split("-", 1)[0] if match else None
    if match is None or match.group("issue") != issue or actual_kind != expected_kind:
        raise _IssueBindingError(issue, "legacy filename and payload binding do not match")


def _validated_rx(
    rx: LegacyZucaiRxV2 | LegacyZucaiRxV3,
    filename: str,
    drafts: tuple[LegacyCandidateDraft, ...],
) -> _ValidatedImport:
    _assert_filename_binding(filename, rx.issue, "rx")
    raw = rx.model_dump(mode="python", exclude_none=True)
    recorded_at = datetime.fromisoformat(rx.registered_at)
    prediction_rows = map_rx_predictions(raw, rx.issue)
    adjudication_rows, skipped = map_rx_adjudications(raw, rx.issue)
    prediction_requests = tuple(
        RegisterPredictionRequest(
            **{key: value for key, value in row.items() if key != "alias_ids"},
            actor_id="operator:jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            requested_at=recorded_at,
        )
        for row in prediction_rows
    )
    adjudication_requests = tuple(
        RecordAdjudicationRequest(
            **row,
            supersedes_adjudication_id=None,
            actor_id="operator:jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            requested_at=recorded_at,
        )
        for row in adjudication_rows
    )
    return _ValidatedImport(
        document_kind="rx",
        issue=rx.issue,
        published_at=rx.registered_at,
        recorded_at=recorded_at,
        prediction_requests=prediction_requests,
        adjudication_requests=adjudication_requests,
        adjudication_total_count=len(rx.pending_adjudications),
        adjudication_skipped_count=len(skipped),
        adjudication_skips=tuple(skipped),
        official_match_nos=(),
        record_count=0,
        candidate_drafts=drafts,
    )


def classify_legacy_candidate(
    issue: str,
    label: str,
    faces: dict[str, str] | None,
    *,
    legacy_text: str | None = None,
) -> LegacyCandidateDraft:
    return LegacyCandidateDraft(
        draft_id=f"{issue}:{label}",
        label=label,
        deployable=False,
        reason_code=("legacy_faces_missing" if faces is None else "legacy_audit_required"),
        faces=faces,
        legacy_text=legacy_text,
    )


def _stable_action_id(idempotency_key: str) -> str:
    digest = hashlib.sha256(f"legacy-action:{idempotency_key}".encode("utf-8")).hexdigest()
    return f"ACT-{digest[:32]}"


__all__ = [
    "LEGACY_ISSUE_CONTRACT",
    "LEGACY_PREP_CONTRACT",
    "LEGACY_RX_V2_CONTRACT",
    "LEGACY_RX_V3_CONTRACT",
    "LegacyCandidateDraft",
    "LegacyImportReceipt",
    "LegacyOperatorImporter",
    "LegacyQuarantineReport",
    "LegacyZucaiRxV2",
    "LegacyZucaiRxV3",
    "classify_legacy_candidate",
]
