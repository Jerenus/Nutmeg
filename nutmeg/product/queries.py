"""Versioned product DTO assembly with explicit information cutoffs."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from nutmeg.product.contracts import (
    ActionPage,
    ActionView,
    AdjudicationSummary,
    AgentProposalSummary,
    AlertSeverity,
    AlertSummary,
    BoardResponse,
    ClaimSummary,
    CommandCenterResponse,
    EventPage,
    EvidenceBundleSummary,
    EvidenceConflictSummary,
    EvidenceSpanSummary,
    EvidenceSummary,
    FlagInstanceSummary,
    ForecastSummary,
    HealthResponse,
    IdentityQueueItem,
    LineageEdge,
    LineageResponse,
    MarketSnapshotSummary,
    MatchContextSummary,
    MatchDetail,
    MatchSummary,
    ObjectRefContract,
    ObservationSummary,
    OperationsMetrics,
    OperationsResponse,
    OutboxEventView,
    PrecedentLinkSummary,
    PredictionSummary,
    ReadinessLevel,
    SourceHealthSummary,
    WorkflowObjectSummary,
)
from nutmeg.product.errors import ProductNotFoundError
from nutmeg.product.readiness import evaluate_forecast_readiness, evaluate_readiness
from nutmeg.product.repository import ProductReadRepository

_SHANGHAI = ZoneInfo('Asia/Shanghai')
_DEFAULT_MARKET = 'md-had'


class ProductQueryService:
    def __init__(self, repository: ProductReadRepository, kernel) -> None:
        self._repository = repository
        self._kernel = kernel

    def board(self, day: date, *, as_of: datetime) -> BoardResponse:
        cutoff = _aware(as_of, 'as_of')
        start = datetime.combine(day, time.min, tzinfo=_SHANGHAI).astimezone(UTC)
        end = start + timedelta(days=1)
        records = self._repository.board_matches(
            start.isoformat(), end.isoformat(), cutoff.isoformat()
        )
        return BoardResponse(
            date=day,
            as_of=cutoff,
            matches=[self._match_summary(record, cutoff) for record in records],
        )

    def command_center(
        self,
        day: date,
        *,
        as_of: datetime,
        readiness: ReadinessLevel | None = None,
        competition: str | None = None,
        query: str | None = None,
    ) -> CommandCenterResponse:
        unfiltered = self.board(day, as_of=as_of)
        counts = {level.value: 0 for level in ReadinessLevel}
        for match in unfiltered.matches:
            counts[match.readiness.level.value] += 1

        query_text = (query or '').strip().casefold()
        competition_text = (competition or '').strip().casefold()
        filtered = [
            match
            for match in unfiltered.matches
            if (readiness is None or match.readiness.level is readiness)
            and (
                not competition_text
                or (match.competition or '').casefold() == competition_text
            )
            and (
                not query_text
                or query_text in match.home_team.casefold()
                or query_text in match.away_team.casefold()
                or query_text in (match.competition or '').casefold()
            )
        ]
        cutoff = _aware(as_of, 'as_of')
        return CommandCenterResponse(
            board=BoardResponse(date=day, as_of=cutoff, matches=filtered),
            health=self.health(),
            alerts=self._board_alerts(unfiltered, cutoff),
            readiness_counts=counts,
            pending_workflow_count=self._repository.pending_workflow_count(
                as_of=cutoff.isoformat()
            ),
        )

    def operations(
        self,
        *,
        as_of: datetime,
        identity_limit: int = 100,
    ) -> OperationsResponse:
        cutoff = _aware(as_of, 'as_of')
        source_rows = self._repository.source_health(cutoff.isoformat())
        sources: list[SourceHealthSummary] = []
        alerts: list[AlertSummary] = []
        for row in source_rows:
            retrieved_at = (
                _parse_iso(row['latest_retrieved_at'])
                if row['latest_retrieved_at'] is not None
                else None
            )
            age_seconds = (
                max(0, int((cutoff - retrieved_at).total_seconds()))
                if retrieved_at is not None
                else None
            )
            source = SourceHealthSummary(**row, age_seconds=age_seconds)
            sources.append(source)
            if age_seconds is not None and age_seconds > 6 * 60 * 60:
                alerts.append(
                    _alert(
                        severity=AlertSeverity.WARN,
                        code='source_stale',
                        title=f'{source.source_name} source is stale',
                        detail=f'latest retrieval is {age_seconds} seconds old',
                        observed_at=cutoff,
                        object_ref=ObjectRefContract(
                            object_type='source', object_id=source.source_name
                        ),
                        href='/operations',
                    )
                )

        identities = [
            IdentityQueueItem(**row)
            for row in self._repository.identity_queue(limit=identity_limit)
        ]
        unresolved_count = self._repository.unresolved_identity_count()
        if unresolved_count:
            alerts.append(
                _alert(
                    severity=AlertSeverity.WARN,
                    code='identity_unresolved',
                    title='Identity queue requires review',
                    detail=f'{unresolved_count} provisional teams remain unresolved',
                    observed_at=cutoff,
                    href='/operations#identity-queue',
                )
            )

        failures = [
            self._action_contract(row)
            for row in self._repository.failed_actions(limit=20)
        ]
        for action in failures:
            alerts.append(
                _alert(
                    severity=(
                        AlertSeverity.ERROR
                        if action.status == 'failed'
                        else AlertSeverity.WARN
                    ),
                    code='action_failed',
                    title=f'Action {action.status}: {action.action_type}',
                    detail=action.error_code or 'formal Action did not commit',
                    observed_at=_parse_iso(action.requested_at),
                    object_ref=ObjectRefContract(
                        object_type='action', object_id=action.action_id
                    ),
                    href='/operations#action-failures',
                )
            )

        status = self._kernel.status()
        if status.integrity_check != 'ok' or status.pending_migrations:
            alerts.append(
                _alert(
                    severity=AlertSeverity.ERROR,
                    code='ontology_unhealthy',
                    title='Ontology health gate is blocked',
                    detail=(
                        f'integrity={status.integrity_check}; '
                        f'pending={list(status.pending_migrations)}'
                    ),
                    observed_at=cutoff,
                    href='/operations',
                )
            )
        alerts.append(
            _alert(
                severity=AlertSeverity.WARN,
                code='schedule_visibility_missing',
                title='Schedule state is not instrumented',
                detail='M2 does not infer scheduler health from absent ontology facts',
                observed_at=cutoff,
                href='/operations',
            )
        )
        return OperationsResponse(
            as_of=cutoff,
            sources=sources,
            identities=identities,
            recent_failures=failures,
            alerts=_sort_alerts(alerts),
            metrics=OperationsMetrics(
                ontology_integrity=status.integrity_check,
                ontology_schema_version=status.schema_version,
                action_high_watermark=self._repository.action_high_watermark(),
                outbox_high_watermark=status.outbox_latest_sequence,
                projection_run_count=status.projection_run_count,
                unresolved_identity_count=unresolved_count,
            ),
        )

    def match(self, match_id: str, *, as_of: datetime) -> MatchDetail:
        cutoff = _aware(as_of, 'as_of')
        record = self._repository.match(match_id, cutoff.isoformat())
        if record is None:
            raise ProductNotFoundError(f'match {match_id} not found')
        claims = self._repository.claims_for_match(match_id, cutoff.isoformat())
        observations = self._repository.observations_for_match(
            match_id, cutoff.isoformat()
        )
        conflicts = _classify_conflicts(claims)
        snapshot = self._repository.latest_snapshot(
            match_id, _DEFAULT_MARKET, cutoff.isoformat()
        )
        summary = self._summary(
            record,
            cutoff,
            snapshot,
            len(claims) + len(observations),
            blocking_conflicts=sum(item.blocking for item in conflicts),
            provisional_conflicts=sum(not item.blocking for item in conflicts),
        )
        forecasts = self._repository.forecasts_for_match(match_id, cutoff.isoformat())
        workflow = self._repository.workflow_for_match(match_id, cutoff.isoformat())
        timeline = self._repository.market_timeline(
            match_id, _DEFAULT_MARKET, cutoff.isoformat()
        )
        bundles = self._repository.evidence_bundles_for_match(
            match_id, cutoff.isoformat()
        )
        flags = self._repository.flag_instances_for_match(
            match_id, cutoff.isoformat()
        )
        predictions = self._repository.predictions_for_match(
            match_id, cutoff.isoformat()
        )
        precedents = self._repository.precedents_for_match(
            match_id, cutoff.isoformat()
        )
        adjudications = self._repository.adjudications_for_match(
            match_id, cutoff.isoformat()
        )
        proposals = self._repository.agent_proposals_for_match(
            match_id, cutoff.isoformat()
        )
        eligible_refs = {
            ('claim', item['claim_id']) for item in claims
        } | {
            ('observation', item['observation_id']) for item in observations
        }
        return MatchDetail(
            match=summary,
            market_snapshot=self._snapshot_contract(snapshot),
            evidence=EvidenceSummary(
                claims=[
                    ClaimSummary(
                        claim_id=item['claim_id'],
                        subject_type=item['subject_type'],
                        subject_id=item['subject_id'],
                        predicate=item['predicate'],
                        value=item['value'],
                        status=item['status'],
                        created_at=item['created_at'],
                        spans=[EvidenceSpanSummary(**span) for span in item['spans']],
                    )
                    for item in claims
                ],
                observations=[
                    ObservationSummary(
                        observation_id=item['observation_id'],
                        observation_type=item['observation_type'],
                        subject_type=item['subject_type'],
                        subject_id=item['subject_id'],
                        value=item['value'],
                        observed_at=item['observed_at'],
                        recorded_at=item['recorded_at'],
                        verification_method=item['verification_method'],
                        source_retrieval_ids=item['source_retrieval_ids'],
                    )
                    for item in observations
                ],
                conflicts=conflicts,
            ),
            forecasts=[self._forecast_contract(item) for item in forecasts],
            workflow=[
                WorkflowObjectSummary(
                    object_ref=ObjectRefContract(
                        object_type=item['object_type'], object_id=item['object_id']
                    ),
                    workflow_type=item['object_type'],
                    status=item['status'],
                    created_at=item['created_at'],
                )
                for item in workflow
            ],
            as_of=cutoff,
            context=MatchContextSummary(
                match_revision_id=record['match_revision_id'],
                competition_id=record['competition_id'],
                competition_edition_id=record['competition_edition_id'],
                competition=record['competition'],
                round_label=record['round_label'],
                venue_id=record['venue_id'],
                scheduled_at=record['scheduled_at'],
                schedule_status=record['schedule_status'],
                status=record['status'],
                home_team_id=record['home_team_id'],
                home_team=record['home_team'],
                away_team_id=record['away_team_id'],
                away_team=record['away_team'],
            ),
            market_timeline=[
                self._snapshot_contract(item) for item in timeline
            ],
            evidence_bundles=[
                EvidenceBundleSummary(
                    evidence_bundle_id=item['evidence_bundle_id'],
                    frozen_at=item['frozen_at'],
                    information_cutoff_at=item['information_cutoff_at'],
                    market_snapshot_id=item['market_snapshot_id'],
                    prior_distribution=item['prior_distribution'],
                    identity_resolution_version=item['identity_resolution_version'],
                    source_coverage=item['source_coverage'],
                    freshness=item['freshness'],
                    content_hash=item['content_hash'],
                    item_refs=[ObjectRefContract(**ref) for ref in item['item_refs']],
                )
                for item in bundles
            ],
            flag_instances=[
                FlagInstanceSummary(
                    flag_instance_id=item['flag_instance_id'],
                    flag_type=item['flag_type'],
                    match_id=item['match_id'],
                    direction=item['direction'],
                    strength=item['strength'],
                    evidence_refs=[
                        ObjectRefContract(**ref) for ref in item['evidence_refs']
                    ],
                    predicted_face=item['predicted_face'],
                    status=item['status'],
                    created_at=item['created_at'],
                )
                for item in flags
            ],
            predictions=[PredictionSummary(**item) for item in predictions],
            precedent_links=[
                PrecedentLinkSummary(
                    precedent_link_id=item['precedent_link_id'],
                    subject_type=item['subject_type'],
                    subject_id=item['subject_id'],
                    precedent_match_id=item['precedent_match_id'],
                    scope=item['scope'],
                    evidence_refs=[
                        ObjectRefContract(**ref) for ref in item['evidence_refs']
                    ],
                    created_at=item['created_at'],
                )
                for item in precedents
            ],
            adjudications=[
                AdjudicationSummary(
                    adjudication_id=item['adjudication_id'],
                    subject_type=item['subject_type'],
                    subject_id=item['subject_id'],
                    decision=item['decision'],
                    actor_id=item['actor_id'],
                    reason=item['reason'],
                    evidence_rejected=[
                        ObjectRefContract(**ref) for ref in item['evidence_rejected']
                    ],
                    alternative=item['alternative'],
                    created_at=item['created_at'],
                    supersedes_adjudication_id=item['supersedes_adjudication_id'],
                )
                for item in adjudications
            ],
            agent_proposals=[
                _proposal_contract(
                    item,
                    claims=claims,
                    observations=observations,
                    eligible_refs=eligible_refs,
                )
                for item in proposals
            ],
        )

    def lineage(self, object_type: str, object_id: str) -> LineageResponse:
        edges = self._repository.lineage(object_type, object_id)
        if edges is None:
            raise ProductNotFoundError(f'{object_type} {object_id} not found')
        return LineageResponse(
            object_ref=ObjectRefContract(object_type=object_type, object_id=object_id),
            edges=[
                LineageEdge(
                    relation=relation,
                    source=ObjectRefContract(object_type=source_type, object_id=source_id),
                    target=ObjectRefContract(object_type=target_type, object_id=target_id),
                )
                for relation, source_type, source_id, target_type, target_id in edges
            ],
        )

    def actions(self, *, after: str | None = None, limit: int = 100) -> ActionPage:
        records = self._repository.actions(after=after, limit=limit)
        items = [self._action_contract(item) for item in records]
        return ActionPage(items=items, next_cursor=items[-1].action_id if items else None)

    def events(self, *, after: int, limit: int = 100) -> EventPage:
        rows = self._repository.events(after, limit=limit)
        items = [
            OutboxEventView(
                sequence=row.sequence,
                event_id=row.event_id,
                action_id=row.action_id,
                topic=row.topic,
                object_type=row.object_type,
                object_id=row.object_id,
                payload=row.payload,
                occurred_at=row.occurred_at,
            )
            for row in rows
        ]
        return EventPage(items=items, next_cursor=items[-1].sequence if items else after)

    def health(self) -> HealthResponse:
        status = self._kernel.status()
        return HealthResponse(
            initialized=status.initialized,
            ontology_schema_version=status.schema_version,
            integrity_check=status.integrity_check,
            pending_migrations=list(status.pending_migrations),
            action_counts=status.action_counts,
            outbox_event_count=status.outbox_event_count,
            outbox_latest_sequence=status.outbox_latest_sequence,
        )

    def _match_summary(self, record: dict, cutoff: datetime) -> MatchSummary:
        claims = self._repository.claims_for_match(record['match_id'], cutoff.isoformat())
        observations = self._repository.observations_for_match(
            record['match_id'], cutoff.isoformat()
        )
        snapshot = self._repository.latest_snapshot(
            record['match_id'], _DEFAULT_MARKET, cutoff.isoformat()
        )
        conflicts = _classify_conflicts(claims)
        return self._summary(
            record,
            cutoff,
            snapshot,
            len(claims) + len(observations),
            self._repository.flag_count_for_match(
                record['match_id'], as_of=cutoff.isoformat()
            ),
            blocking_conflicts=sum(item.blocking for item in conflicts),
            provisional_conflicts=sum(not item.blocking for item in conflicts),
        )

    @staticmethod
    def _summary(
        record: dict,
        cutoff: datetime,
        snapshot: dict | None,
        evidence_count: int,
        flag_count: int = 0,
        *,
        blocking_conflicts: int = 0,
        provisional_conflicts: int = 0,
    ) -> MatchSummary:
        snapshot_at = _parse_iso(snapshot['as_of']) if snapshot is not None else None
        readiness = evaluate_forecast_readiness(
            evaluate_readiness(
                identity_resolved=(
                    record['home_resolution_status'] == 'resolved'
                    and record['away_resolution_status'] == 'resolved'
                ),
                snapshot_at=snapshot_at,
                as_of=cutoff,
                evidence_count=evidence_count,
            ),
            blocking_conflicts=blocking_conflicts,
            provisional_conflicts=provisional_conflicts,
        )
        workflow_state, next_action = {
            ReadinessLevel.READY: ('inspect', 'open_match'),
            ReadinessLevel.DEGRADED: ('needs_evidence', 'inspect_gaps'),
            ReadinessLevel.BLOCKED: ('blocked', 'resolve_blocker'),
        }[readiness.level]
        return MatchSummary(
            match_id=record['match_id'],
            home_team=record['home_team'],
            away_team=record['away_team'],
            competition=record['competition'],
            kickoff_at=record['scheduled_at'],
            latest_snapshot_at=snapshot['as_of'] if snapshot is not None else None,
            readiness=readiness,
            evidence_count=evidence_count,
            workflow_state=workflow_state,
            next_action=next_action,
            flag_count=flag_count,
        )

    @staticmethod
    def _action_contract(item: dict) -> ActionView:
        return ActionView(
            action_id=item['action_id'],
            action_type=item['action_type'],
            actor_id=item['actor_id'],
            actor_role=item['actor_role'],
            requested_at=item['requested_at'],
            status=item['status'],
            result_refs=[ObjectRefContract(**ref) for ref in item['result_refs']],
            error_code=item['error_code'],
            committed_at=item['committed_at'],
        )

    @staticmethod
    def _board_alerts(board: BoardResponse, cutoff: datetime) -> list[AlertSummary]:
        alerts: list[AlertSummary] = []
        for match in board.matches:
            for issue in match.readiness.issues:
                alerts.append(
                    _alert(
                        severity=(
                            AlertSeverity.ERROR
                            if match.readiness.level is ReadinessLevel.BLOCKED
                            else AlertSeverity.WARN
                        ),
                        code=issue.code,
                        title=f'{match.home_team} v {match.away_team}',
                        detail=issue.message,
                        observed_at=issue.observed_at or cutoff,
                        object_ref=ObjectRefContract(
                            object_type='match', object_id=match.match_id
                        ),
                        href=f'/matches/{match.match_id}?as_of={cutoff.isoformat()}',
                    )
                )
        return _sort_alerts(alerts)

    @staticmethod
    def _snapshot_contract(snapshot: dict | None) -> MarketSnapshotSummary | None:
        if snapshot is None:
            return None
        return MarketSnapshotSummary(
            market_snapshot_id=snapshot['market_snapshot_id'],
            market_definition_id=snapshot['market_definition_id'],
            as_of=snapshot['as_of'],
            devig_distribution=snapshot['fair_distribution'],
        )

    @staticmethod
    def _forecast_contract(item: dict) -> ForecastSummary:
        return ForecastSummary(
            forecast_revision_id=item['forecast_revision_id'],
            forecast_series_id=item['forecast_series_id'],
            revision_no=item['revision_no'],
            status=item['status'],
            made_at=item['made_at'],
            information_cutoff_at=item['information_cutoff_at'],
            prior_snapshot_id=item['prior_snapshot_id'],
            prior_distribution=item['prior_distribution'],
            belief_distribution=item['belief_distribution'],
            evidence_bundle_id=item['evidence_bundle_id'],
            evidence_status=(
                'bundled' if item['evidence_bundle_id'] is not None else 'legacy_unbundled'
            ),
            commitment_tier=item['commitment_tier'],
        )


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f'{name} must be timezone-aware')
    return value.astimezone(UTC)


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return _aware(parsed, 'timestamp')


def _classify_conflicts(claims: list[dict]) -> list[EvidenceConflictSummary]:
    grouped: dict[tuple[str, str, str], dict[str, list[dict]]] = {}
    for claim in claims:
        if claim['status'] == 'retracted':
            continue
        group_key = (
            claim['subject_type'],
            claim['subject_id'],
            claim['predicate'],
        )
        value_key = json.dumps(
            claim['value'], sort_keys=True, separators=(',', ':'), ensure_ascii=False
        )
        grouped.setdefault(group_key, {}).setdefault(value_key, []).append(claim)

    conflicts: list[EvidenceConflictSummary] = []
    for group_key, values in grouped.items():
        if len(values) < 2:
            continue
        claims_in_group = sorted(
            (claim for group in values.values() for claim in group),
            key=lambda item: item['claim_id'],
        )
        verified_values = sum(
            any(claim['status'] == 'verified' for claim in group)
            for group in values.values()
        )
        identity = json.dumps(
            [*group_key, *sorted(values)],
            separators=(',', ':'),
            ensure_ascii=False,
        )
        conflicts.append(
            EvidenceConflictSummary(
                conflict_id=(
                    'conflict-'
                    + hashlib.sha256(identity.encode('utf-8')).hexdigest()[:20]
                ),
                predicate=group_key[2],
                claim_ids=[item['claim_id'] for item in claims_in_group],
                statuses=[item['status'] for item in claims_in_group],
                blocking=verified_values >= 2,
            )
        )
    return sorted(conflicts, key=lambda item: (item.predicate, item.conflict_id))


def _proposal_contract(
    item: dict,
    *,
    claims: list[dict],
    observations: list[dict],
    eligible_refs: set[tuple[str, str]],
) -> AgentProposalSummary:
    claims_by_id = {claim['claim_id']: claim for claim in claims}
    observations_by_id = {
        observation['observation_id']: observation for observation in observations
    }
    citations: list[EvidenceSpanSummary] = []
    cited_refs: set[tuple[str, str]] = set()
    for ref in item['citation_refs']:
        object_type = ref['object_type']
        object_id = ref['object_id']
        cited_refs.add((object_type, object_id))
        if object_type == 'claim' and object_id in claims_by_id:
            spans = claims_by_id[object_id]['spans']
            citations.extend(
                EvidenceSpanSummary(**span) for span in spans
            )
            if spans:
                continue
        if object_type == 'observation' and object_id in observations_by_id:
            retrieval_ids = observations_by_id[object_id]['source_retrieval_ids']
            citations.extend(
                EvidenceSpanSummary(
                    object_type=object_type,
                    object_id=object_id,
                    artifact_retrieval_id=retrieval_id,
                )
                for retrieval_id in retrieval_ids
            )
            if retrieval_ids:
                continue
        citations.append(
            EvidenceSpanSummary(object_type=object_type, object_id=object_id)
        )

    payload = item['payload']
    coverage = (
        len(cited_refs & eligible_refs) / len(eligible_refs)
        if eligible_refs
        else 0.0
    )
    return AgentProposalSummary(
        agent_proposal_id=item['agent_proposal_id'],
        subject_type=item['subject_type'],
        subject_id=item['subject_id'],
        proposal_type=item['proposal_type'],
        status=item['status'],
        version=item['version'],
        information_cutoff_at=item.get('information_cutoff_at'),
        operator_prompt=item.get('operator_prompt'),
        summary=str(
            payload.get('summary')
            or payload.get('note')
            or item['proposal_type']
        ),
        scenarios=payload.get('scenarios', []),
        proposed_belief=payload.get('proposed_belief'),
        factors=payload.get('factors', []),
        falsifier=payload.get('falsifier'),
        citations=citations,
        citation_coverage=coverage,
        conflicts=payload.get('conflicts', []),
        missing_evidence=payload.get('missing_evidence', []),
        model_name=item['model_name'],
        model_version=item['model_version'],
        created_at=item['created_at'],
        resolved_at=item['resolved_at'],
        resolved_by_action_id=item['resolved_by_action_id'],
    )


def _alert(
    *,
    severity: AlertSeverity,
    code: str,
    title: str,
    detail: str,
    observed_at: datetime,
    object_ref: ObjectRefContract | None = None,
    href: str | None = None,
) -> AlertSummary:
    identity = '|'.join(
        (
            code,
            object_ref.object_type if object_ref is not None else '',
            object_ref.object_id if object_ref is not None else '',
            observed_at.isoformat(),
        )
    )
    alert_id = 'alert-' + hashlib.sha256(identity.encode('utf-8')).hexdigest()[:20]
    return AlertSummary(
        alert_id=alert_id,
        severity=severity,
        code=code,
        title=title,
        detail=detail,
        observed_at=observed_at,
        object_ref=object_ref,
        href=href,
    )


def _sort_alerts(alerts: list[AlertSummary]) -> list[AlertSummary]:
    rank = {
        AlertSeverity.ERROR: 0,
        AlertSeverity.WARN: 1,
        AlertSeverity.INFO: 2,
    }
    return sorted(
        alerts,
        key=lambda item: (rank[item.severity], item.observed_at, item.alert_id),
    )
