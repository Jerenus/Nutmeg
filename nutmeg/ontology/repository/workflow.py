"""Typed persistence for governed workflow objects."""
from __future__ import annotations

import json

from sqlalchemy import Connection, func, insert, select, update

from nutmeg.ontology.actions.models import canonical_json
from nutmeg.ontology.errors import OptimisticConcurrencyError
from nutmeg.ontology.repository import schema_workflow as sw
from nutmeg.ontology.workflow.models import (
    AdjudicationRow,
    AgentProposalRow,
    FlagInstanceRow,
    PrecedentLinkRow,
    PredictionRow,
    PredictionStatus,
    ProposalStatus,
)


class WorkflowRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def insert_adjudication(self, row: AdjudicationRow) -> None:
        self._connection.execute(
            insert(sw.adjudications).values(
                adjudication_id=row.adjudication_id,
                subject_type=row.subject_type,
                subject_id=row.subject_id,
                decision=row.decision,
                actor_id=row.actor_id,
                reason=row.reason,
                evidence_rejected_json=canonical_json(row.evidence_rejected),
                alternative_json=canonical_json(row.alternative),
                created_at=row.created_at,
                supersedes_adjudication_id=row.supersedes_adjudication_id,
            )
        )

    def get_adjudication(self, adjudication_id: str) -> AdjudicationRow:
        row = self._connection.execute(
            select(sw.adjudications).where(
                sw.adjudications.c.adjudication_id == adjudication_id
            )
        ).mappings().one()
        return AdjudicationRow(
            adjudication_id=row['adjudication_id'],
            subject_type=row['subject_type'],
            subject_id=row['subject_id'],
            decision=row['decision'],
            actor_id=row['actor_id'],
            reason=row['reason'],
            evidence_rejected=json.loads(row['evidence_rejected_json']),
            alternative=json.loads(row['alternative_json']),
            created_at=row['created_at'],
            supersedes_adjudication_id=row['supersedes_adjudication_id'],
        )

    def count_adjudications(self) -> int:
        return self._connection.execute(
            select(func.count()).select_from(sw.adjudications)
        ).scalar_one()

    def insert_flag_instance(self, row: FlagInstanceRow) -> None:
        self._connection.execute(
            insert(sw.flag_instances).values(
                flag_instance_id=row.flag_instance_id,
                flag_type=row.flag_type,
                match_id=row.match_id,
                direction=row.direction,
                strength=row.strength,
                evidence_refs_json=canonical_json(row.evidence_refs),
                predicted_face=row.predicted_face,
                status=row.status,
                created_at=row.created_at,
            )
        )

    def get_flag_instance(self, flag_instance_id: str) -> FlagInstanceRow:
        row = self._connection.execute(
            select(sw.flag_instances).where(
                sw.flag_instances.c.flag_instance_id == flag_instance_id
            )
        ).mappings().one()
        return FlagInstanceRow(
            flag_instance_id=row['flag_instance_id'],
            flag_type=row['flag_type'],
            match_id=row['match_id'],
            direction=row['direction'],
            strength=row['strength'],
            evidence_refs=json.loads(row['evidence_refs_json']),
            predicted_face=row['predicted_face'],
            status=row['status'],
            created_at=row['created_at'],
        )

    def insert_prediction(self, row: PredictionRow) -> None:
        self._connection.execute(
            insert(sw.predictions).values(
                prediction_id=row.prediction_id,
                match_id=row.match_id,
                claim=row.claim,
                falsifier=row.falsifier,
                status=row.status.value,
                outcome=row.outcome,
                registered_at=row.registered_at,
                settled_at=row.settled_at,
            )
        )

    def get_prediction(self, prediction_id: str) -> PredictionRow:
        row = self._connection.execute(
            select(sw.predictions).where(sw.predictions.c.prediction_id == prediction_id)
        ).mappings().one()
        return PredictionRow(
            prediction_id=row['prediction_id'],
            match_id=row['match_id'],
            claim=row['claim'],
            falsifier=row['falsifier'],
            status=PredictionStatus(row['status']),
            outcome=row['outcome'],
            registered_at=row['registered_at'],
            settled_at=row['settled_at'],
        )

    def insert_precedent_link(self, row: PrecedentLinkRow) -> None:
        self._connection.execute(
            insert(sw.precedent_links).values(
                precedent_link_id=row.precedent_link_id,
                subject_type=row.subject_type,
                subject_id=row.subject_id,
                precedent_match_id=row.precedent_match_id,
                scope=row.scope,
                evidence_refs_json=canonical_json(row.evidence_refs),
                created_at=row.created_at,
            )
        )

    def get_precedent_link(self, precedent_link_id: str) -> PrecedentLinkRow:
        row = self._connection.execute(
            select(sw.precedent_links).where(
                sw.precedent_links.c.precedent_link_id == precedent_link_id
            )
        ).mappings().one()
        return PrecedentLinkRow(
            precedent_link_id=row['precedent_link_id'],
            subject_type=row['subject_type'],
            subject_id=row['subject_id'],
            precedent_match_id=row['precedent_match_id'],
            scope=row['scope'],
            evidence_refs=json.loads(row['evidence_refs_json']),
            created_at=row['created_at'],
        )

    def insert_agent_proposal(self, row: AgentProposalRow) -> None:
        self._connection.execute(
            insert(sw.agent_proposals).values(
                agent_proposal_id=row.agent_proposal_id,
                subject_type=row.subject_type,
                subject_id=row.subject_id,
                proposal_type=row.proposal_type,
                payload_json=canonical_json(row.payload),
                citation_refs_json=canonical_json(row.citation_refs),
                model_name=row.model_name,
                model_version=row.model_version,
                status=row.status.value,
                version=row.version,
                created_at=row.created_at,
                resolved_at=row.resolved_at,
                resolved_by_action_id=row.resolved_by_action_id,
            )
        )

    def get_agent_proposal(self, agent_proposal_id: str) -> AgentProposalRow:
        row = self._connection.execute(
            select(sw.agent_proposals).where(
                sw.agent_proposals.c.agent_proposal_id == agent_proposal_id
            )
        ).mappings().one()
        return AgentProposalRow(
            agent_proposal_id=row['agent_proposal_id'],
            subject_type=row['subject_type'],
            subject_id=row['subject_id'],
            proposal_type=row['proposal_type'],
            payload=json.loads(row['payload_json']),
            citation_refs=json.loads(row['citation_refs_json']),
            model_name=row['model_name'],
            model_version=row['model_version'],
            status=ProposalStatus(row['status']),
            version=row['version'],
            created_at=row['created_at'],
            resolved_at=row['resolved_at'],
            resolved_by_action_id=row['resolved_by_action_id'],
        )

    def resolve_agent_proposal(
        self,
        proposal_id: str,
        status: ProposalStatus,
        expected_version: int,
        at: str,
        action_id: str,
    ) -> None:
        result = self._connection.execute(
            update(sw.agent_proposals)
            .where(
                sw.agent_proposals.c.agent_proposal_id == proposal_id,
                sw.agent_proposals.c.status == ProposalStatus.PENDING.value,
                sw.agent_proposals.c.version == expected_version,
            )
            .values(
                status=status.value,
                version=expected_version + 1,
                resolved_at=at,
                resolved_by_action_id=action_id,
            )
        )
        if result.rowcount != 1:
            raise OptimisticConcurrencyError(
                f'proposal {proposal_id} is absent, resolved, or not at version '
                f'{expected_version}'
            )
