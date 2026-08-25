"""Immutable workflow rows shared by Actions and repositories."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import uuid4


class ProposalStatus(StrEnum):
    PENDING = 'pending'
    APPROVED = 'approved'
    REJECTED = 'rejected'
    WITHDRAWN = 'withdrawn'


class PredictionStatus(StrEnum):
    PENDING = 'pending'
    CONFIRMED = 'confirmed'
    REFUTED = 'refuted'
    VOID = 'void'


def mint_workflow_id(prefix: str) -> str:
    return f'{prefix}-{uuid4().hex}'


@dataclass(frozen=True, slots=True)
class AdjudicationRow:
    adjudication_id: str
    subject_type: str
    subject_id: str
    decision: str
    actor_id: str
    reason: str
    evidence_rejected: list[dict[str, str]]
    alternative: dict[str, object]
    created_at: str
    supersedes_adjudication_id: str | None


@dataclass(frozen=True, slots=True)
class FlagInstanceRow:
    flag_instance_id: str
    flag_type: str
    match_id: str
    direction: str | None
    strength: float
    evidence_refs: list[dict[str, str]]
    predicted_face: str | None
    status: str
    created_at: str


@dataclass(frozen=True, slots=True)
class PredictionRow:
    prediction_id: str
    match_id: str
    claim: str
    falsifier: str
    status: PredictionStatus
    outcome: str | None
    registered_at: str
    settled_at: str | None


@dataclass(frozen=True, slots=True)
class PrecedentLinkRow:
    precedent_link_id: str
    subject_type: str
    subject_id: str
    precedent_match_id: str
    scope: str
    evidence_refs: list[dict[str, str]]
    created_at: str


@dataclass(frozen=True, slots=True)
class AgentProposalRow:
    agent_proposal_id: str
    subject_type: str
    subject_id: str
    proposal_type: str
    information_cutoff_at: str | None
    operator_prompt: str | None
    payload: dict[str, object]
    citation_refs: list[dict[str, str]]
    model_name: str
    model_version: str
    status: ProposalStatus
    version: int
    created_at: str
    resolved_at: str | None
    resolved_by_action_id: str | None
