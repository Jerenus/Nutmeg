"""Forecast Actions: draft / commit / revise / withdraw a belief.

A forecast anchors ``prior`` to the market and records ``belief`` with a per-factor
delta decomposition validated to reconstruct ``belief − prior`` exactly (the only
place an edge may come from). ``belief = prior`` is a legal "follow the market"
commit. Drafts are ai_analyst-writable; commit/revise/withdraw are judge_operator
only and keep a single current committed revision per series via optimistic
concurrency (the Action envelope's expected_versions).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from nutmeg.ontology.actions.models import (
    ActionCommand,
    ActionOutcome,
    ActorRole,
    ObjectRef,
)
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.decision.distributions import reconstructs_belief, validate_simplex
from nutmeg.ontology.decision.models import ForecastStatus, mint_decision_id
from nutmeg.ontology.repository.decision import FactorApplicationRow, ForecastRevisionRow


@dataclass(frozen=True, slots=True)
class FactorInput:
    factor_definition_id: str
    delta: dict[str, float]
    scope_entity_ids: list[str]
    supporting_observation_ids: list[str]
    note: str | None


@dataclass(frozen=True, slots=True)
class DraftForecastRequest:
    match_id: str
    market_definition_id: str
    decision_session_id: str | None
    prior_distribution: dict[str, float]
    belief_distribution: dict[str, float]
    factors: list[FactorInput]
    commitment_tier: str
    evidence_bundle_id: str | None
    prior_snapshot_id: str | None
    falsifier: str | None
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class CommitForecastRequest:
    match_id: str
    market_definition_id: str
    decision_session_id: str | None
    prior_distribution: dict[str, float]
    belief_distribution: dict[str, float]
    factors: list[FactorInput]
    commitment_tier: str
    evidence_bundle_id: str | None
    prior_snapshot_id: str | None
    falsifier: str | None
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class WithdrawForecastRequest:
    match_id: str
    market_definition_id: str
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime


def _validate_forecast(
    prior: dict[str, float], belief: dict[str, float], factors: list[FactorInput]
) -> None:
    validate_simplex(prior)
    validate_simplex(belief)
    if factors and not reconstructs_belief(prior, [f.delta for f in factors], belief):
        raise ValueError('factor delta must reconstruct belief-prior')


class ForecastActions:
    def __init__(self, action_service: ActionService) -> None:
        self._action_service = action_service

    def draft_forecast(self, request: DraftForecastRequest) -> ActionOutcome:
        _validate_forecast(
            request.prior_distribution, request.belief_distribution, request.factors
        )
        command = ActionCommand.create(
            action_type='draft_forecast',
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload={
                'match_id': request.match_id,
                'market_definition_id': request.market_definition_id,
                'commitment_tier': request.commitment_tier,
            },
            requested_at=request.requested_at,
        )

        def handler(uow, _command) -> tuple[ObjectRef, ...]:
            series_id = uow.decision.ensure_series(
                request.match_id, request.market_definition_id
            )
            revision_no = uow.decision.max_revision_no(series_id) + 1
            revision_id = mint_decision_id('fr')
            uow.decision.insert_revision(
                _revision_row(
                    request, revision_id, series_id, revision_no,
                    ForecastStatus.DRAFT.value, None, command.policy_version,
                )
            )
            _insert_factor_applications(uow, revision_id, request.factors)
            return (ObjectRef('forecast_revision', revision_id),)

        return self._action_service.execute(command, handler)

    def commit_forecast(self, request: CommitForecastRequest) -> ActionOutcome:
        return self._commit(request, 'commit_forecast', require_current=False)

    def revise_forecast(self, request: CommitForecastRequest) -> ActionOutcome:
        return self._commit(request, 'revise_forecast', require_current=True)

    def withdraw_forecast(self, request: WithdrawForecastRequest) -> ActionOutcome:
        command = ActionCommand.create(
            action_type='withdraw_forecast',
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload={
                'match_id': request.match_id,
                'market_definition_id': request.market_definition_id,
            },
            requested_at=request.requested_at,
        )

        def handler(uow, _command) -> tuple[ObjectRef, ...]:
            series_id = uow.decision.ensure_series(
                request.match_id, request.market_definition_id
            )
            current = uow.decision.current_committed_revision(series_id)
            if current is None:
                raise ValueError('no committed forecast to withdraw')
            uow.decision.set_revision_status(
                current.forecast_revision_id, ForecastStatus.WITHDRAWN.value
            )
            return (ObjectRef('forecast_revision', current.forecast_revision_id),)

        return self._action_service.execute(command, handler)

    def _commit(
        self, request: CommitForecastRequest, action_type: str, require_current: bool
    ) -> ActionOutcome:
        _validate_forecast(
            request.prior_distribution, request.belief_distribution, request.factors
        )
        command = ActionCommand.create(
            action_type=action_type,
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload={
                'match_id': request.match_id,
                'market_definition_id': request.market_definition_id,
                'commitment_tier': request.commitment_tier,
            },
            requested_at=request.requested_at,
        )

        def handler(uow, _command) -> tuple[ObjectRef, ...]:
            series_id = uow.decision.ensure_series(
                request.match_id, request.market_definition_id
            )
            current = uow.decision.current_committed_revision(series_id)
            if require_current and current is None:
                raise ValueError('no committed forecast to revise')
            revision_no = uow.decision.max_revision_no(series_id) + 1
            revision_id = mint_decision_id('fr')
            supersedes = current.forecast_revision_id if current is not None else None
            uow.decision.insert_revision(
                _revision_row(
                    request, revision_id, series_id, revision_no,
                    ForecastStatus.COMMITTED.value, supersedes, command.policy_version,
                )
            )
            _insert_factor_applications(uow, revision_id, request.factors)
            if current is not None:
                uow.decision.set_revision_status(
                    current.forecast_revision_id, ForecastStatus.SUPERSEDED.value
                )
            return (ObjectRef('forecast_revision', revision_id),)

        return self._action_service.execute(command, handler)


def _revision_row(
    request,
    forecast_revision_id: str,
    forecast_series_id: str,
    revision_no: int,
    status: str,
    supersedes_revision_id: str | None,
    policy_version: str,
) -> ForecastRevisionRow:
    return ForecastRevisionRow(
        forecast_revision_id=forecast_revision_id,
        forecast_series_id=forecast_series_id,
        decision_session_id=request.decision_session_id,
        revision_no=revision_no,
        status=status,
        made_at=request.requested_at.astimezone(UTC).isoformat(),
        information_cutoff_at=None,
        prior_snapshot_id=request.prior_snapshot_id,
        prior_distribution=request.prior_distribution,
        belief_distribution=request.belief_distribution,
        evidence_bundle_id=request.evidence_bundle_id,
        falsifier=request.falsifier,
        actor_id=request.actor_id,
        model_name=None,
        model_version=None,
        policy_version=policy_version,
        commitment_tier=request.commitment_tier,
        evidence_coverage=None,
        evidence_quality=None,
        forecast_stability=None,
        supersedes_revision_id=supersedes_revision_id,
    )


def _insert_factor_applications(uow, revision_id: str, factors: list[FactorInput]) -> None:
    for factor in factors:
        uow.decision.insert_factor_application(
            FactorApplicationRow(
                factor_application_id=mint_decision_id('fa'),
                forecast_revision_id=revision_id,
                factor_definition_id=factor.factor_definition_id,
                scope_entity_ids=factor.scope_entity_ids,
                delta_distribution=factor.delta,
                supporting_observation_ids=factor.supporting_observation_ids,
                note=factor.note,
            )
        )
