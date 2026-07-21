"""FreezeEvidenceBundle — weld an as-of input set with no future leak.

The bundle freezes the cutoff, the market prior and only the verified observations
whose ``recorded_at <= cutoff`` (a later-recorded observation, even if published
earlier, cannot enter — no future leak). Provisional/disputed claims may enter
only as caveats (risk flags, never a licence to move belief). A content hash over
the frozen inputs proves "same inputs, same bundle". deterministic_system only.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from nutmeg.ontology.actions.models import (
    ActionCommand,
    ActionOutcome,
    ActorRole,
    ObjectRef,
    canonical_json,
)
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.decision.models import mint_decision_id
from nutmeg.ontology.repository.decision import EvidenceBundleRow


@dataclass(frozen=True, slots=True)
class FreezeBundleRequest:
    match_id: str
    decision_session_id: str | None
    cutoff_at: str
    market_snapshot_id: str | None
    prior_distribution: dict[str, float]
    candidate_observation_ids: list[str]
    caveat_claim_ids: list[str]
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError('requested_at must be timezone-aware')
        if not self.match_id.strip() or not self.cutoff_at.strip():
            raise ValueError('match_id and cutoff_at are required')
        if not self.idempotency_key.strip():
            raise ValueError('idempotency_key is required')


class BundleActions:
    def __init__(self, action_service: ActionService) -> None:
        self._action_service = action_service

    def freeze_bundle(self, request: FreezeBundleRequest) -> ActionOutcome:
        command = ActionCommand.create(
            action_type='freeze_evidence_bundle',
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload={
                'match_id': request.match_id,
                'cutoff_at': request.cutoff_at,
                'candidate_count': len(request.candidate_observation_ids),
            },
            requested_at=request.requested_at,
        )

        def handler(uow, _command) -> tuple[ObjectRef, ...]:
            included = [
                observation_id
                for observation_id in request.candidate_observation_ids
                if _recorded_at_or_before(
                    uow.decision.observation_recorded_at(observation_id), request.cutoff_at
                )
            ]
            content_hash = hashlib.sha256(
                canonical_json(
                    {
                        'cutoff': request.cutoff_at,
                        'prior': request.prior_distribution,
                        'observations': sorted(included),
                        'caveats': sorted(request.caveat_claim_ids),
                    }
                ).encode('utf-8')
            ).hexdigest()
            bundle_id = mint_decision_id('eb')
            uow.decision.insert_bundle(
                EvidenceBundleRow(
                    evidence_bundle_id=bundle_id,
                    match_id=request.match_id,
                    decision_session_id=request.decision_session_id,
                    frozen_at=request.requested_at.astimezone(UTC).isoformat(),
                    information_cutoff_at=request.cutoff_at,
                    market_snapshot_id=request.market_snapshot_id,
                    prior_distribution=request.prior_distribution,
                    identity_resolution_version=None,
                    source_coverage={'observations': len(included)},
                    freshness={},
                    content_hash=content_hash,
                )
            )
            for observation_id in included:
                uow.decision.add_bundle_item(
                    bundle_id, 'observation', observation_id=observation_id
                )
            for claim_id in request.caveat_claim_ids:
                uow.decision.add_bundle_item(bundle_id, 'caveat_claim', claim_id=claim_id)
            return (ObjectRef('evidence_bundle', bundle_id),)

        return self._action_service.execute(command, handler)


def _recorded_at_or_before(recorded_at: str | None, cutoff_at: str) -> bool:
    # ISO-8601 strings with the same offset order lexicographically by instant.
    return recorded_at is not None and recorded_at <= cutoff_at
