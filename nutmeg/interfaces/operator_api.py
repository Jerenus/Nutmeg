"""Strict, closed HTTP boundary for the v2 operator workbench."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from nutmeg.ontology.actions.models import ActorRole
from nutmeg.product.contracts import ProductError
from nutmeg.product.operator_contracts import OperatorCommandReceipt
from nutmeg.product.operator_tokens import (
    OperatorCommandKind,
    OperatorSnapshotTokenError,
)


class OperatorCommandV2(BaseModel):
    """Base envelope used until each named business command is installed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["2"]
    kind: OperatorCommandKind
    expected_snapshot_token: str = Field(min_length=1, max_length=8192)
    idempotency_key: str = Field(min_length=1, max_length=500)


class FreezeEvidenceCommandV2(OperatorCommandV2):
    kind: Literal[OperatorCommandKind.FREEZE_EVIDENCE]
    task_key: str = Field(pattern=r"^(?:jczq:\d{4}-\d{2}-\d{2}|zucai:\d{5})$")
    requirement_revision_token: str = Field(min_length=1, max_length=8192)


class RebuildScoreboardProjectionCommandV2(OperatorCommandV2):
    kind: Literal[OperatorCommandKind.REBUILD_SCOREBOARD_PROJECTION]


class FaceProbabilityInputV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    face_code: str = Field(min_length=1, max_length=50)
    probability_decimal: str = Field(
        pattern=r"^(?:0\.\d{12}|1\.0{12})$",
    )


class FaceOffsetInputV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    face_code: str = Field(min_length=1, max_length=50)
    offset_probability_decimal: str = Field(
        pattern=r"^-?(?:0\.\d{12}|1\.0{12})$",
    )


class FactorAdjustmentInputV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    factor_id: str = Field(min_length=1, max_length=200)
    scope_key: str = Field(min_length=1, max_length=200)
    evidence_ref_tokens: list[str] = Field(min_length=1, max_length=100)
    offsets: list[FaceOffsetInputV2] = Field(min_length=1, max_length=100)


class FaceBundleInputV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    bundle_code: str = Field(min_length=1, max_length=100)
    face_codes: list[str] = Field(min_length=1, max_length=100)


class OfferConstraintInputV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    official_match_no: str = Field(min_length=1, max_length=20)
    market_code: str = Field(min_length=1, max_length=100)
    allowed_face_bundles: list[FaceBundleInputV2] = Field(min_length=1, max_length=100)
    omission_allowed: bool


class StructureTemplateInputV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["jczq_pass", "zucai_group"]
    structure_code: str = Field(min_length=1, max_length=100)
    eligible_official_match_nos: list[str] = Field(min_length=1, max_length=100)
    pass_size: int | None = Field(default=None, gt=0)
    required_offer_count: int = Field(gt=0)
    maximum_groups: int = Field(gt=0)


class RecordBaselineEnvelopeCommandV2(OperatorCommandV2):
    kind: Literal[OperatorCommandKind.RECORD_BASELINE_ENVELOPE]
    task_key: str = Field(pattern=r"^(?:jczq:\d{4}-\d{2}-\d{2}|zucai:\d{5})$")
    ticket_kind: Literal["jczq_pass", "sfc", "renjiu"]
    capital_cap_minor: int = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    maximum_ticket_count: int = Field(gt=0)
    offer_constraints: list[OfferConstraintInputV2] = Field(min_length=1, max_length=100)
    structure_templates: list[StructureTemplateInputV2] = Field(
        min_length=1,
        max_length=100,
    )
    maximum_exhaustive_candidate_count: int = Field(gt=0)


class CommitMatchJudgmentCommandV2(OperatorCommandV2):
    kind: Literal[OperatorCommandKind.COMMIT_MATCH_JUDGMENT]
    task_key: str = Field(pattern=r"^(?:jczq:\d{4}-\d{2}-\d{2}|zucai:\d{5})$")
    official_match_no: str = Field(min_length=1, max_length=20)
    market_code: str = Field(min_length=1, max_length=100)
    belief: list[FaceProbabilityInputV2] = Field(min_length=2, max_length=100)
    factors: list[FactorAdjustmentInputV2] = Field(max_length=100)
    expression_bundles: list[FaceBundleInputV2] = Field(min_length=1, max_length=100)
    rule_ids: list[str] = Field(max_length=100)
    evidence_ref_tokens: list[str] = Field(max_length=500)
    falsifier: str = Field(min_length=1, max_length=4000)
    rationale: str = Field(min_length=1, max_length=4000)


class FreezeJudgmentPrescriptionCommandV2(OperatorCommandV2):
    kind: Literal[OperatorCommandKind.FREEZE_JUDGMENT_PRESCRIPTION]
    task_key: str = Field(pattern=r"^(?:jczq:\d{4}-\d{2}-\d{2}|zucai:\d{5})$")
    judgment_revision_tokens: list[str] = Field(min_length=1, max_length=100)


class RequestCandidateGenerationCommandV2(OperatorCommandV2):
    kind: Literal[OperatorCommandKind.REQUEST_CANDIDATE_GENERATION]
    task_key: str = Field(pattern=r"^(?:jczq:\d{4}-\d{2}-\d{2}|zucai:\d{5})$")
    market_prior_baseline_token: str = Field(min_length=1, max_length=8192)
    baseline_envelope_token: str = Field(min_length=1, max_length=8192)
    judgment_prescription_token: str = Field(min_length=1, max_length=8192)


class SelectTicketCandidateCommandV2(OperatorCommandV2):
    kind: Literal[OperatorCommandKind.SELECT_CANDIDATE]
    task_key: str = Field(pattern=r"^(?:jczq:\d{4}-\d{2}-\d{2}|zucai:\d{5})$")
    candidate_token: str = Field(min_length=1, max_length=8192)
    reason: str = Field(min_length=1, max_length=4000)


class RecordNoTicketCommandV2(OperatorCommandV2):
    kind: Literal[OperatorCommandKind.RECORD_NO_TICKET]
    task_key: str = Field(pattern=r"^(?:jczq:\d{4}-\d{2}-\d{2}|zucai:\d{5})$")
    reason_code: Literal[
        "human_all_dice",
        "evidence_incomplete",
        "no_compliant_structure_within_cap",
        "discipline_brake",
        "operator_discretion",
    ]
    reason_basis: Literal["rule_derived", "operator_judgment"]
    reason_text: str = Field(min_length=1, max_length=4000)
    rule_tokens: list[str] = Field(max_length=100)
    comparison_candidate_token: str | None = Field(default=None, max_length=8192)

    @model_validator(mode="after")
    def _rule_derived_has_a_rule(self):
        if self.reason_basis == "rule_derived" and not self.rule_tokens:
            raise ValueError("rule-derived no-ticket requires a named Rule token")
        return self


class SupersedeNoTicketCommandV2(OperatorCommandV2):
    kind: Literal[OperatorCommandKind.SUPERSEDE_NO_TICKET]
    task_key: str = Field(pattern=r"^(?:jczq:\d{4}-\d{2}-\d{2}|zucai:\d{5})$")
    no_ticket_revision_token: str = Field(min_length=1, max_length=8192)
    reason_text: str = Field(min_length=1, max_length=4000)


class CreateTicketBatchCommandV2(OperatorCommandV2):
    kind: Literal[OperatorCommandKind.CREATE_TICKET_BATCH]
    task_key: str = Field(pattern=r"^(?:jczq:\d{4}-\d{2}-\d{2}|zucai:\d{5})$")
    candidate_selection_token: str = Field(min_length=1, max_length=8192)


class AuditWarnAdjudicationInputV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    finding_token: str = Field(min_length=1, max_length=8192)
    reason: str = Field(min_length=1, max_length=4000)
    evidence_rejected_tokens: list[str] = Field(max_length=100)


class AdjudicateAuditWarnCommandV2(OperatorCommandV2):
    kind: Literal[OperatorCommandKind.ADJUDICATE_AUDIT_WARN]
    task_key: str = Field(pattern=r"^(?:jczq:\d{4}-\d{2}-\d{2}|zucai:\d{5})$")
    ticket_batch_token: str = Field(min_length=1, max_length=8192)
    findings: list[AuditWarnAdjudicationInputV2] = Field(min_length=1, max_length=100)


class ApproveTicketBatchCommandV2(OperatorCommandV2):
    kind: Literal[OperatorCommandKind.APPROVE_TICKET_BATCH]
    task_key: str = Field(pattern=r"^(?:jczq:\d{4}-\d{2}-\d{2}|zucai:\d{5})$")
    ticket_batch_token: str = Field(min_length=1, max_length=8192)


class RequestConfirmationCommandV2(OperatorCommandV2):
    kind: Literal[OperatorCommandKind.REQUEST_CONFIRMATION]
    task_key: str = Field(pattern=r"^(?:jczq:\d{4}-\d{2}-\d{2}|zucai:\d{5})$")
    ticket_artifact_token: str = Field(min_length=1, max_length=8192)


class UnavailableOperatorCommandV2(OperatorCommandV2):
    kind: Literal[
        OperatorCommandKind.REQUEST_SETTLEMENT,
        OperatorCommandKind.GRADE_PREDICTION,
        OperatorCommandKind.RECORD_SCOREBOARD_EFFECT_DISPOSITION,
        OperatorCommandKind.RECORD_SCOREBOARD_OBSERVATION,
        OperatorCommandKind.REQUEST_SCOREBOARD_REVIEW_COMPLETION,
    ]


InstalledOperatorCommandV2 = Annotated[
    FreezeEvidenceCommandV2
    | RecordBaselineEnvelopeCommandV2
    | CommitMatchJudgmentCommandV2
    | FreezeJudgmentPrescriptionCommandV2
    | RequestCandidateGenerationCommandV2
    | SelectTicketCandidateCommandV2
    | RecordNoTicketCommandV2
    | SupersedeNoTicketCommandV2
    | CreateTicketBatchCommandV2
    | AdjudicateAuditWarnCommandV2
    | ApproveTicketBatchCommandV2
    | RequestConfirmationCommandV2
    | RebuildScoreboardProjectionCommandV2
    | UnavailableOperatorCommandV2,
    Field(discriminator="kind"),
]


def mount_operator_api(
    app: FastAPI,
    *,
    require_mutation_session: Callable[[Request], Awaitable[None]],
    operator_actions=None,
    actor_id: str | None = None,
) -> None:
    """Mount the sole v2 mutation path without a generic execution fallback."""

    if operator_actions is None:
        @app.post("/api/v2/operator")
        async def unavailable_operator_command(
            request: Request,
            command: OperatorCommandV2,
        ) -> JSONResponse:
            await require_mutation_session(request)
            error = ProductError(
                code="command_unavailable",
                message=f"operator command {command.kind.value} is not installed",
                retryable=False,
            )
            return JSONResponse(status_code=409, content=error.model_dump(mode="json"))

        return

    if actor_id is None or not actor_id.strip():
        raise ValueError("operator API requires one server-owned actor")

    @app.post("/api/v2/operator")
    async def operator_command(
        request: Request,
        command: InstalledOperatorCommandV2,
    ) -> JSONResponse:
        await require_mutation_session(request)
        try:
            if isinstance(command, FreezeEvidenceCommandV2):
                result = operator_actions.request_evidence_freeze(
                    command,
                    actor_id=actor_id,
                    actor_role=ActorRole.JUDGE_OPERATOR,
                )
                status_code = 202
            elif isinstance(command, RecordBaselineEnvelopeCommandV2):
                result = operator_actions.record_baseline_envelope(
                    command,
                    actor_id=actor_id,
                    actor_role=ActorRole.JUDGE_OPERATOR,
                )
                status_code = 200
            elif isinstance(command, CommitMatchJudgmentCommandV2):
                result = operator_actions.commit_match_judgment(
                    command,
                    actor_id=actor_id,
                    actor_role=ActorRole.JUDGE_OPERATOR,
                )
                status_code = 200
            elif isinstance(command, FreezeJudgmentPrescriptionCommandV2):
                result = operator_actions.freeze_judgment_prescription(
                    command,
                    actor_id=actor_id,
                    actor_role=ActorRole.JUDGE_OPERATOR,
                )
                status_code = 200
            elif isinstance(command, RequestCandidateGenerationCommandV2):
                result = operator_actions.request_candidate_generation(
                    command,
                    actor_id=actor_id,
                    actor_role=ActorRole.JUDGE_OPERATOR,
                )
                status_code = 202
            elif isinstance(command, SelectTicketCandidateCommandV2):
                result = operator_actions.select_ticket_candidate(
                    command,
                    actor_id=actor_id,
                    actor_role=ActorRole.JUDGE_OPERATOR,
                )
                status_code = 200
            elif isinstance(command, RecordNoTicketCommandV2):
                result = operator_actions.record_no_ticket(
                    command,
                    actor_id=actor_id,
                    actor_role=ActorRole.JUDGE_OPERATOR,
                )
                status_code = 200
            elif isinstance(command, SupersedeNoTicketCommandV2):
                result = operator_actions.supersede_no_ticket(
                    command,
                    actor_id=actor_id,
                    actor_role=ActorRole.JUDGE_OPERATOR,
                )
                status_code = 200
            elif isinstance(command, CreateTicketBatchCommandV2):
                result = operator_actions.create_ticket_batch(
                    command,
                    actor_id=actor_id,
                    actor_role=ActorRole.JUDGE_OPERATOR,
                )
                status_code = 200
            elif isinstance(command, AdjudicateAuditWarnCommandV2):
                result = operator_actions.adjudicate_audit_warn(
                    command,
                    actor_id=actor_id,
                    actor_role=ActorRole.JUDGE_OPERATOR,
                )
                status_code = 200
            elif isinstance(command, ApproveTicketBatchCommandV2):
                result = operator_actions.approve_ticket_batch(
                    command,
                    actor_id=actor_id,
                    actor_role=ActorRole.JUDGE_OPERATOR,
                )
                status_code = 200
            elif isinstance(command, RequestConfirmationCommandV2):
                result = operator_actions.request_confirmation(
                    command,
                    actor_id=actor_id,
                    actor_role=ActorRole.JUDGE_OPERATOR,
                )
                status_code = 202
            elif isinstance(command, RebuildScoreboardProjectionCommandV2):
                result = operator_actions.rebuild_scoreboard_projection(
                    command,
                    actor_id=actor_id,
                    actor_role=ActorRole.JUDGE_OPERATOR,
                )
                status_code = 200
            else:
                error = ProductError(
                    code="command_unavailable",
                    message=f"operator command {command.kind.value} is not installed",
                    retryable=False,
                )
                return JSONResponse(
                    status_code=409,
                    content=error.model_dump(mode="json"),
                )
        except OperatorSnapshotTokenError as error:
            product_error = ProductError(
                code=error.code,
                message=str(error),
                retryable=False,
                details=(
                    {"recovery_href": "/operator-next"}
                    if error.code == "task_snapshot_changed"
                    else {}
                ),
            )
            return JSONResponse(
                status_code=409 if error.code == "task_snapshot_changed" else 422,
                content=product_error.model_dump(mode="json"),
            )
        receipt = OperatorCommandReceipt.model_validate(result)
        return JSONResponse(
            status_code=status_code,
            content=receipt.model_dump(mode="json"),
        )


__all__ = [
    "AdjudicateAuditWarnCommandV2",
    "ApproveTicketBatchCommandV2",
    "AuditWarnAdjudicationInputV2",
    "CommitMatchJudgmentCommandV2",
    "CreateTicketBatchCommandV2",
    "FaceBundleInputV2",
    "FaceOffsetInputV2",
    "FaceProbabilityInputV2",
    "FactorAdjustmentInputV2",
    "FreezeEvidenceCommandV2",
    "FreezeJudgmentPrescriptionCommandV2",
    "InstalledOperatorCommandV2",
    "OfferConstraintInputV2",
    "OperatorCommandV2",
    "RecordBaselineEnvelopeCommandV2",
    "RecordNoTicketCommandV2",
    "RebuildScoreboardProjectionCommandV2",
    "RequestCandidateGenerationCommandV2",
    "RequestConfirmationCommandV2",
    "SelectTicketCandidateCommandV2",
    "StructureTemplateInputV2",
    "SupersedeNoTicketCommandV2",
    "mount_operator_api",
]
