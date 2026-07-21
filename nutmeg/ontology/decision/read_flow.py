"""DecisionReadService — the read verb: session -> bundle -> commit.

Chains the belief-layer Actions for one match/market: open a decision session,
freeze a leak-proof evidence bundle at the cutoff, and commit a forecast anchored
to that bundle. ``belief = prior`` is a legal follow-market commit. Idempotency
keys derive from match + cutoff so a rerun replays.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from nutmeg.ontology.actions.bundle_actions import BundleActions, FreezeBundleRequest
from nutmeg.ontology.actions.forecast_actions import (
    CommitForecastRequest,
    FactorInput,
    ForecastActions,
)
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.session_actions import OpenSessionRequest, SessionActions


@dataclass(frozen=True, slots=True)
class ReadMatchRequest:
    match_id: str
    market_definition_id: str
    operator_id: str
    cutoff_at: str
    prior_distribution: dict[str, float]
    belief_distribution: dict[str, float]
    factors: list[FactorInput]
    actor_id: str
    actor_role: ActorRole
    requested_at: datetime
    commitment_tier: str = 'follow'


@dataclass(frozen=True, slots=True)
class ReadMatchResult:
    committed: bool
    forecast_revision_id: str | None
    bundle_id: str


class DecisionReadService:
    def __init__(
        self,
        *,
        session_actions: SessionActions,
        bundle_actions: BundleActions,
        forecast_actions: ForecastActions,
    ) -> None:
        self._session_actions = session_actions
        self._bundle_actions = bundle_actions
        self._forecast_actions = forecast_actions

    def read_match(self, request: ReadMatchRequest) -> ReadMatchResult:
        key = f'{request.match_id}:{request.cutoff_at}'
        session = self._session_actions.open_session(
            OpenSessionRequest(
                operator_id=request.operator_id,
                cutoff_at=request.cutoff_at,
                scope={'matches': [request.match_id]},
                actor_id=request.actor_id,
                actor_role=request.actor_role,
                idempotency_key=f'sess:{key}',
                requested_at=request.requested_at,
            )
        )
        session_id = session.result_refs[0].object_id
        bundle = self._bundle_actions.freeze_bundle(
            FreezeBundleRequest(
                match_id=request.match_id,
                decision_session_id=session_id,
                cutoff_at=request.cutoff_at,
                market_snapshot_id=None,
                prior_distribution=request.prior_distribution,
                candidate_observation_ids=[],
                caveat_claim_ids=[],
                actor_id='system:freeze',
                actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                idempotency_key=f'bundle:{key}',
                requested_at=request.requested_at,
            )
        )
        bundle_id = bundle.result_refs[0].object_id
        forecast = self._forecast_actions.commit_forecast(
            CommitForecastRequest(
                match_id=request.match_id,
                market_definition_id=request.market_definition_id,
                decision_session_id=session_id,
                prior_distribution=request.prior_distribution,
                belief_distribution=request.belief_distribution,
                factors=request.factors,
                commitment_tier=request.commitment_tier,
                evidence_bundle_id=bundle_id,
                prior_snapshot_id=None,
                falsifier=None,
                actor_id=request.actor_id,
                actor_role=request.actor_role,
                idempotency_key=f'commit:{key}',
                requested_at=request.requested_at,
            )
        )
        committed = forecast.status is ActionStatus.COMMITTED
        return ReadMatchResult(
            committed=committed,
            forecast_revision_id=forecast.result_refs[0].object_id if committed else None,
            bundle_id=bundle_id,
        )
