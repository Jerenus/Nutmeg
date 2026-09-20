"""Replay-only adjudication of historical draft JCZQ Reads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from nutmeg.ontology.actions.bundle_actions import BundleActions, FreezeBundleRequest
from nutmeg.ontology.actions.forecast_actions import CommitForecastRequest, ForecastActions
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.actions.workflow_actions import (
    CreateAgentProposalRequest,
    RecordAdjudicationRequest,
    ResolveAgentProposalRequest,
    WorkflowActions,
)
from nutmeg.ontology.workflow.models import ProposalStatus


@dataclass(frozen=True, slots=True)
class ReplayAdjudicationInput:
    read_id: str
    match_id: str
    made_at: datetime
    origin: str
    branch: str
    reason: str
    market_definition_id: str
    market_snapshot_id: str
    prior_distribution: dict[str, float]
    belief_distribution: dict[str, float]
    revised_belief_distribution: dict[str, float]
    citation_refs: tuple[dict[str, str], ...]
    candidate_observation_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.branch not in {"approve", "revise", "reject"}:
            raise ValueError("replay adjudication branch is invalid")
        if self.made_at.tzinfo is None or self.made_at.utcoffset() is None:
            raise ValueError("made_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ReplayAdjudicationResult:
    read_id: str
    branch: str
    original_proposal_id: str
    committed_proposal_id: str
    adjudication_id: str
    evidence_bundle_id: str
    forecast_revision_id: str


class ReplayAdjudicator:
    def __init__(self, action_service: ActionService, *, replay_run_id: str) -> None:
        self._workflow = WorkflowActions(action_service)
        self._bundles = BundleActions(action_service)
        self._forecasts = ForecastActions(action_service)
        self._run_id = replay_run_id
        self._actor_id = f"replay:{replay_run_id}:adjudicator"

    def adjudicate(
        self, inputs: tuple[ReplayAdjudicationInput, ...]
    ) -> tuple[ReplayAdjudicationResult, ...]:
        return tuple(self._adjudicate_one(item) for item in inputs)

    def _create_proposal(
        self,
        item: ReplayAdjudicationInput,
        *,
        suffix: str,
        origin: str,
        belief: dict[str, float],
    ) -> str:
        outcome = self._workflow.create_agent_proposal(
            CreateAgentProposalRequest(
                subject_type="match",
                subject_id=item.match_id,
                proposal_type="forecast_draft",
                information_cutoff_at=item.made_at.isoformat(),
                operator_prompt="JCZQ historical replay proposal",
                payload={
                    "read_id": item.read_id,
                    "status": "draft",
                    "historical_replay": True,
                    "prospective": False,
                    "origin": origin,
                    "prior_distribution": item.prior_distribution,
                    "belief_distribution": belief,
                },
                citation_refs=list(item.citation_refs),
                model_name=origin,
                model_version="historical-replay-v1",
                actor_id=self._actor_id,
                actor_role=ActorRole.REPLAY_ADJUDICATOR,
                idempotency_key=f"replay:{self._run_id}:proposal:{item.read_id}:{suffix}",
                requested_at=item.made_at,
            )
        )
        return outcome.result_refs[0].object_id

    def _resolve(
        self,
        proposal_id: str,
        resolution: ProposalStatus,
        item: ReplayAdjudicationInput,
        suffix: str,
    ) -> None:
        self._workflow.resolve_agent_proposal(
            ResolveAgentProposalRequest(
                agent_proposal_id=proposal_id,
                resolution=resolution,
                expected_version=1,
                actor_id=self._actor_id,
                actor_role=ActorRole.REPLAY_ADJUDICATOR,
                idempotency_key=f"replay:{self._run_id}:resolve:{item.read_id}:{suffix}",
                requested_at=item.made_at,
            )
        )

    def _adjudicate_one(self, item: ReplayAdjudicationInput) -> ReplayAdjudicationResult:
        original_id = self._create_proposal(
            item,
            suffix="original",
            origin=item.origin,
            belief=item.belief_distribution,
        )
        committed_id = original_id
        committed_belief = item.belief_distribution
        if item.branch != "approve":
            committed_belief = (
                item.revised_belief_distribution
                if item.branch == "revise"
                else item.prior_distribution
            )
            committed_id = self._create_proposal(
                item,
                suffix="replacement",
                origin=("replay-revision" if item.branch == "revise" else "market-anchor"),
                belief=committed_belief,
            )

        adjudication = self._workflow.record_adjudication(
            RecordAdjudicationRequest(
                subject_type="agent_proposal",
                subject_id=original_id,
                decision=item.branch,
                reason=item.reason,
                evidence_rejected=(
                    [] if item.branch == "approve" else list(item.citation_refs)
                ),
                alternative=(
                    {} if committed_id == original_id else {"proposal_id": committed_id}
                ),
                supersedes_adjudication_id=None,
                actor_id=self._actor_id,
                actor_role=ActorRole.REPLAY_ADJUDICATOR,
                idempotency_key=f"replay:{self._run_id}:adjudicate:{item.read_id}",
                requested_at=item.made_at,
            )
        )
        adjudication_id = adjudication.result_refs[0].object_id
        self._resolve(
            original_id,
            ProposalStatus.APPROVED if item.branch == "approve" else ProposalStatus.REJECTED,
            item,
            "original",
        )
        if committed_id != original_id:
            self._workflow.record_adjudication(
                RecordAdjudicationRequest(
                    subject_type="agent_proposal",
                    subject_id=committed_id,
                    decision="approve_replacement",
                    reason=f"replacement after replay {item.branch}",
                    evidence_rejected=[],
                    alternative={},
                    supersedes_adjudication_id=None,
                    actor_id=self._actor_id,
                    actor_role=ActorRole.REPLAY_ADJUDICATOR,
                    idempotency_key=(
                        f"replay:{self._run_id}:adjudicate:{item.read_id}:replacement"
                    ),
                    requested_at=item.made_at,
                )
            )
            self._resolve(committed_id, ProposalStatus.APPROVED, item, "replacement")

        bundle = self._bundles.freeze_bundle(
            FreezeBundleRequest(
                match_id=item.match_id,
                decision_session_id=None,
                cutoff_at=item.made_at.isoformat(),
                market_snapshot_id=item.market_snapshot_id,
                prior_distribution=item.prior_distribution,
                candidate_observation_ids=list(item.candidate_observation_ids),
                caveat_claim_ids=[],
                actor_id=self._actor_id,
                actor_role=ActorRole.REPLAY_ADJUDICATOR,
                idempotency_key=f"replay:{self._run_id}:bundle:{item.read_id}",
                requested_at=item.made_at,
            )
        )
        bundle_id = bundle.result_refs[0].object_id
        forecast = self._forecasts.commit_forecast(
            CommitForecastRequest(
                match_id=item.match_id,
                market_definition_id=item.market_definition_id,
                decision_session_id=None,
                prior_distribution=item.prior_distribution,
                belief_distribution=committed_belief,
                factors=[],
                commitment_tier="historical_replay_only",
                evidence_bundle_id=bundle_id,
                prior_snapshot_id=item.market_snapshot_id,
                falsifier=None,
                actor_id=self._actor_id,
                actor_role=ActorRole.REPLAY_ADJUDICATOR,
                idempotency_key=f"replay:{self._run_id}:forecast:{item.read_id}",
                requested_at=item.made_at,
                information_cutoff_at=item.made_at.isoformat(),
                expected_current_revision_no=0,
            )
        )
        return ReplayAdjudicationResult(
            read_id=item.read_id,
            branch=item.branch,
            original_proposal_id=original_id,
            committed_proposal_id=committed_id,
            adjudication_id=adjudication_id,
            evidence_bundle_id=bundle_id,
            forecast_revision_id=forecast.result_refs[0].object_id,
        )


__all__ = ["ReplayAdjudicationInput", "ReplayAdjudicationResult", "ReplayAdjudicator"]
