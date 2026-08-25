"""Versioned product DTO assembly with explicit information cutoffs."""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from nutmeg.ontology.actions.protected_ticket_actions import ticket_audit_finding_id
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.product.contracts import (
    ActionPage,
    ActionView,
    AdjudicationSummary,
    AgentProposalSummary,
    AlertSeverity,
    AlertSummary,
    BoardResponse,
    CalibrationResponse,
    ClaimSummary,
    CommandCenterResponse,
    CounterfactualReplaySummary,
    EventPage,
    EvidenceBundleSummary,
    EvidenceSpanSummary,
    EvidenceSummary,
    FactorEstimateSummary,
    FlagInstanceSummary,
    ForecastSummary,
    HealthResponse,
    IdentityQueueItem,
    LifecycleProposalSummary,
    LineageEdge,
    LineageResponse,
    MarketSnapshotSummary,
    MatchContextSummary,
    MatchDetail,
    MatchSummary,
    MetricSummary,
    ObjectRefContract,
    ObservationSummary,
    OntologyObjectDetail,
    OntologyObjectPage,
    OntologyObjectSummary,
    OperationsMetrics,
    OperationsResponse,
    OutboxEventView,
    PrecedentLinkSummary,
    PredictionSummary,
    ProjectionHealth,
    ReadinessLevel,
    RegimeSummary,
    ReleaseApprovalSummary,
    ReleaseBackupRestoreSummary,
    ReleaseGateSummary,
    ReleasePerformanceSummary,
    ReleaseResponse,
    ReleaseSchedulerSummary,
    ReliabilityEvidenceSummary,
    ReliabilityMetricsResponse,
    ReviewResponse,
    RouteMetricSummary,
    ScoreboardAuthoritySummary,
    ScoreboardResponse,
    ScorePlaneSummary,
    SettlementSummary,
    SoakCoverageSummary,
    SourceHealthSummary,
    TicketArtifactDetail,
    TicketAuditFindingSummary,
    TicketBatchHistoryResponse,
    TicketBatchRevisionSummary,
    TicketLegCommand,
    TicketSelection,
    TicketWorkbenchMatch,
    TicketWorkbenchResponse,
    WorkflowObjectSummary,
)
from nutmeg.product.errors import ProductNotFoundError
from nutmeg.product.readiness import (
    classify_claim_conflicts,
    evaluate_forecast_readiness,
    evaluate_readiness,
)
from nutmeg.product.repository import ProductReadRepository
from nutmeg.reliability.contracts import PERFORMANCE_BUDGETS_MS
from nutmeg.reliability.metrics import RouteMetricSnapshot
from nutmeg.reliability.release import ReleaseEvaluator

_SHANGHAI = ZoneInfo('Asia/Shanghai')
_DEFAULT_MARKET = 'md-had'


class ProductQueryService:
    def __init__(self, repository: ProductReadRepository, kernel) -> None:
        self._repository = repository
        self._kernel = kernel

    def review(self, *, as_of: datetime) -> ReviewResponse:
        cutoff = _aware(as_of, 'as_of')
        projection = self._repository.scoreboard_projection(
            as_of=cutoff.isoformat()
        )
        counterfactuals = self._repository.projection_rows(
            'counterfactual_replays', as_of=cutoff.isoformat()
        )
        return ReviewResponse(
            as_of=cutoff,
            forecast=self._score_plane('forecast', projection),
            money=self._score_plane('money', projection),
            intervention=self._score_plane('intervention', projection),
            settlements=[
                SettlementSummary(
                    ticket_settlement_id=row['ticket_settlement_id'],
                    ticket_id=row['ticket_id'],
                    status=row['status'],
                    settled_at=row['settled_at'],
                    stake_amount=row['stake_amount'],
                    payout_amount=row['payout_amount'],
                    pnl_amount=row['pnl_amount'],
                    settlement_method_version=row['settlement_method_version'],
                    leg_settlement_ids=row['bet_leg_settlement_ids'],
                )
                for row in self._repository.settlements(as_of=cutoff.isoformat())
            ],
            counterfactuals=[
                CounterfactualReplaySummary(
                    **{
                        key: row[key]
                        for key in CounterfactualReplaySummary.model_fields
                    }
                )
                for row in counterfactuals['rows']
            ],
        )

    def calibration(self, *, as_of: datetime) -> CalibrationResponse:
        cutoff = _aware(as_of, 'as_of')
        estimates = self._repository.projection_rows(
            'factor_estimates', as_of=cutoff.isoformat()
        )
        proposals = self._repository.projection_rows(
            'factor_lifecycle_proposals', as_of=cutoff.isoformat()
        )
        vectors = self._repository.projection_rows(
            'regime_vectors', as_of=cutoff.isoformat()
        )
        labels = self._repository.projection_rows(
            'regime_postmatch_labels', as_of=cutoff.isoformat()
        )
        factors: list[FactorEstimateSummary] = []
        for row in estimates['rows']:
            detail = self._repository.ontology_object(
                'factor_definition',
                str(row['factor_definition_id']),
                as_of=cutoff.isoformat(),
            )
            factors.append(
                FactorEstimateSummary(
                    **{
                        key: row[key]
                        for key in FactorEstimateSummary.model_fields
                        if key != 'current_status'
                    },
                    current_status=(
                        str(detail['properties']['status']) if detail else None
                    ),
                )
            )
        postmatch = {
            str(row['match_id']): _json_value(row['labels_json'], 'labels_json')
            for row in labels['rows']
        }
        regimes = []
        for row in vectors['rows']:
            scope_id = str(row['scope_id'])
            regimes.append(
                RegimeSummary(
                    regime_key=str(row['regime_id']),
                    values={
                        'scope_type': row['scope_type'],
                        'scope_id': scope_id,
                        'as_of': row['as_of'],
                        'axes': _json_value(row['axes_json'], 'axes_json'),
                        'labels': _json_value(row['labels_json'], 'labels_json'),
                        'postmatch_labels': postmatch.get(scope_id),
                    },
                )
            )
        return CalibrationResponse(
            as_of=cutoff,
            health=ProjectionHealth(**estimates['health']),
            factors=factors,
            lifecycle_proposals=[
                LifecycleProposalSummary(
                    proposal_id=row['proposal_id'],
                    factor_definition_id=row['factor_definition_id'],
                    from_status=row['from_status'],
                    to_status=row['to_status'],
                    rationale=_json_value(row['rationale_json'], 'rationale_json'),
                    policy_version=row['policy_version'],
                )
                for row in proposals['rows']
            ],
            regimes=regimes,
        )

    def ontology_objects(
        self,
        *,
        object_type: str,
        query: str | None,
        after: str | None,
        limit: int,
        as_of: datetime,
    ) -> OntologyObjectPage:
        cutoff = _aware(as_of, 'as_of')
        result = self._repository.ontology_objects(
            object_type=object_type,
            query=query,
            after=after,
            limit=limit,
            as_of=cutoff.isoformat(),
        )
        return OntologyObjectPage(
            object_type=object_type,
            as_of=cutoff,
            items=[OntologyObjectSummary(**item) for item in result['items']],
            next_cursor=result['next_cursor'],
        )

    def ontology_object(
        self, object_type: str, object_id: str, *, as_of: datetime
    ) -> OntologyObjectDetail:
        cutoff = _aware(as_of, 'as_of')
        result = self._repository.ontology_object(
            object_type, object_id, as_of=cutoff.isoformat()
        )
        if result is None:
            raise ProductNotFoundError(f'{object_type} {object_id} not found')
        return OntologyObjectDetail(
            object_type=result['object_type'],
            object_id=result['object_id'],
            as_of=cutoff,
            properties=result['properties'],
            links=[LineageEdge(**item) for item in result['links']],
            versions=result['versions'],
            actions=[self._action_contract(item) for item in result['actions']],
        )

    def scoreboard(self, *, as_of: datetime) -> ScoreboardResponse:
        cutoff = _aware(as_of, 'as_of')
        projection = self._repository.scoreboard_projection(
            as_of=cutoff.isoformat()
        )
        with OntologyUnitOfWork(self._kernel.engine) as uow:
            authority = uow.scoreboard.authority()
        return ScoreboardResponse(
            as_of=cutoff,
            authority=ScoreboardAuthoritySummary(
                state=authority.state,
                version=authority.version,
                projection_version=authority.projection_version,
                source_high_watermark=authority.source_high_watermark,
                legacy_sha256=authority.legacy_sha256,
                shadow_review_id=authority.shadow_review_id,
                compatibility_export_sha256=authority.compatibility_export_sha256,
                approved_at=authority.approved_at,
                approved_by_action_id=authority.approved_by_action_id,
            ),
            health=ProjectionHealth(**projection['health']),
            planes=[
                self._score_plane(plane, projection)
                for plane in (
                    'forecast',
                    'money',
                    'intervention',
                    'lifecycle',
                    'manual',
                )
            ],
        )

    @staticmethod
    def _score_plane(plane: str, projection: dict) -> ScorePlaneSummary:
        return ScorePlaneSummary(
            plane=plane,
            health=ProjectionHealth(**projection['health']),
            metrics=[
                MetricSummary(
                    **{key: row[key] for key in MetricSummary.model_fields}
                )
                for row in projection['rows']
                if row['plane'] == plane
            ],
        )

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
        conflicts = classify_claim_conflicts(claims)
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

    def ticket_workbench(
        self, day: date, *, as_of: datetime
    ) -> TicketWorkbenchResponse:
        cutoff = _aware(as_of, 'as_of')
        start = datetime.combine(day, time.min, tzinfo=_SHANGHAI).astimezone(UTC)
        end = start + timedelta(days=1)
        records = self._repository.board_matches(
            start.isoformat(), end.isoformat(), cutoff.isoformat()
        )
        matches: list[TicketWorkbenchMatch] = []
        for match_no, record in enumerate(records, start=1):
            forecast = self._repository.ticket_forecast_at(
                record['match_id'], _DEFAULT_MARKET, cutoff.isoformat()
            )
            selection_rows = self._repository.ticket_selections_at(
                record['match_id'], _DEFAULT_MARKET, cutoff.isoformat()
            )
            selections: list[TicketSelection] = []
            for row in selection_rows:
                reasons: list[str] = []
                if forecast is None:
                    reasons.append('no_committed_forecast')
                if row['quote_id'] is None:
                    reasons.append('no_active_quote')
                selections.append(
                    TicketSelection(
                        market_definition_id=row['market_definition_id'],
                        selection_id=row['selection_id'],
                        outcome_key=row['outcome_key'],
                        line=row['line'],
                        quote_id=row['quote_id'],
                        odds=row['decimal_odds'],
                        captured_at=row['captured_at'],
                        provider=row['provider'],
                        eligible=not reasons,
                        block_reasons=reasons,
                    )
                )
            block_reasons: list[str] = []
            if forecast is None:
                block_reasons.append('no_committed_forecast')
            if not any(row['quote_id'] is not None for row in selection_rows):
                block_reasons.append('no_active_quote')
            matches.append(
                TicketWorkbenchMatch(
                    match_id=record['match_id'],
                    match_revision_id=record['match_revision_id'],
                    match_no=match_no,
                    home_team=record['home_team'],
                    away_team=record['away_team'],
                    competition=record['competition'],
                    kickoff_at=record['scheduled_at'],
                    market_definition_id=_DEFAULT_MARKET,
                    forecast_revision_id=(
                        forecast['forecast_revision_id'] if forecast else None
                    ),
                    forecast_revision_no=(
                        forecast['revision_no'] if forecast else None
                    ),
                    belief_distribution=(
                        forecast['belief_distribution'] if forecast else None
                    ),
                    selections=selections,
                    eligible=not block_reasons,
                    block_reasons=block_reasons,
                )
            )
        batch_rows = self._repository.current_ticket_batches(
            day.isoformat(), cutoff.isoformat()
        )
        return TicketWorkbenchResponse(
            date=day,
            as_of=cutoff,
            matches=matches,
            batch_revisions=self._ticket_batch_summaries(batch_rows),
        )

    def ticket_batch(self, ticket_batch_id: str) -> TicketBatchHistoryResponse:
        rows = self._repository.ticket_batch_history(ticket_batch_id)
        if not rows:
            raise ProductNotFoundError(f'ticket batch {ticket_batch_id} not found')
        return TicketBatchHistoryResponse(
            ticket_batch_id=ticket_batch_id,
            revisions=self._ticket_batch_summaries(rows),
        )

    def ticket_artifact(
        self, ticket_artifact_id: str, *, as_of: datetime | None = None
    ) -> TicketArtifactDetail:
        row = self._repository.ticket_artifact(ticket_artifact_id)
        if row is None:
            raise ProductNotFoundError(
                f'ticket artifact {ticket_artifact_id} not found'
            )
        cutoff = _aware(as_of or datetime.now(UTC), 'as_of')
        confirmation = self._repository.latest_confirmation(ticket_artifact_id)
        if confirmation is None:
            confirmation_state = 'not_issued'
        elif confirmation['consumed_at'] is not None:
            confirmation_state = 'consumed'
        elif _parse_iso(confirmation['expires_at']) < cutoff:
            confirmation_state = 'expired'
        else:
            confirmation_state = 'open'
        placed = row['ticket_placement_id'] is not None
        return TicketArtifactDetail(
            ticket_artifact_id=row['ticket_artifact_id'],
            ticket_batch_revision_id=row['ticket_batch_revision_id'],
            ticket_index=row['ticket_index'],
            ticket_hash=row['ticket_hash'],
            source_artifact_id=row['source_artifact_id'],
            amount=row['amount'],
            currency=row['currency'],
            channel=row['channel'],
            deadline_at=row['deadline_at'],
            payload=row['payload'],
            approved_at=row['approved_at'],
            approved_by_action_id=row['approved_by_action_id'],
            confirmation_state=confirmation_state,
            confirmation_id=(
                confirmation['confirmation_id'] if confirmation else None
            ),
            confirmation_expires_at=(
                confirmation['expires_at'] if confirmation else None
            ),
            placement_state='placed' if placed else 'unplaced',
            ticket_placement_id=row['ticket_placement_id'],
            ticket_id=row['ticket_id'],
            placement_mode=row['placement_mode'],
            external_reference=row['external_reference'],
            receipt_artifact_id=row['receipt_artifact_id'],
            receipt_retrieval_id=row['receipt_retrieval_id'],
            placed_at=row['placed_at'],
        )

    def _ticket_batch_summaries(
        self, rows: list[dict]
    ) -> list[TicketBatchRevisionSummary]:
        revision_ids = [row['ticket_batch_revision_id'] for row in rows]
        artifact_ids = self._repository.ticket_artifact_ids_for_revisions(
            revision_ids
        )
        finding_ids = [
            ticket_audit_finding_id(row['ticket_batch_revision_id'], finding)
            for row in rows
            for finding in row['audit_findings']
            if finding['level'] == 'WARN'
        ]
        adjudications = self._repository.ticket_warning_adjudications(finding_ids)
        result: list[TicketBatchRevisionSummary] = []
        previous_by_batch: dict[str, dict[str, dict[str, object]]] = {}
        for row in rows:
            current_legs = {
                str(leg['leg_key']): leg for leg in row['input_legs']
            }
            previous_legs = previous_by_batch.get(row['ticket_batch_id'], {})
            added = sorted(current_legs.keys() - previous_legs.keys())
            removed = sorted(previous_legs.keys() - current_legs.keys())
            changed = sorted(
                key
                for key in current_legs.keys() & previous_legs.keys()
                if current_legs[key] != previous_legs[key]
            )
            findings: list[TicketAuditFindingSummary] = []
            for finding in row['audit_findings']:
                finding_id = ticket_audit_finding_id(
                    row['ticket_batch_revision_id'], finding
                )
                adjudication = adjudications.get(finding_id)
                findings.append(
                    TicketAuditFindingSummary(
                        finding_id=finding_id,
                        level=finding['level'],
                        code=finding['code'],
                        match_no=finding['match_no'],
                        message=finding['message'],
                        since=finding['since'],
                        adjudication_id=(
                            adjudication['adjudication_id']
                            if adjudication
                            else None
                        ),
                        adjudication_decision=(
                            adjudication['decision'] if adjudication else None
                        ),
                    )
                )
            levels = {finding.level for finding in findings}
            audit_state = (
                'error' if 'ERROR' in levels else 'warn' if 'WARN' in levels else 'clean'
            )
            revision_id = row['ticket_batch_revision_id']
            result.append(
                TicketBatchRevisionSummary(
                    ticket_batch_revision_id=revision_id,
                    ticket_batch_id=row['ticket_batch_id'],
                    revision_no=row['revision_no'],
                    supersedes_revision_id=row['supersedes_revision_id'],
                    run_date=row['run_date'],
                    channel=row['channel'],
                    account_id=row['account_id'],
                    currency=row['currency'],
                    deadline_at=row['deadline_at'],
                    state=row['state'],
                    content_hash=row['content_hash'],
                    source_artifact_id=row['source_artifact_id'],
                    created_at=row['created_at'],
                    created_by_action_id=row['created_by_action_id'],
                    legs=[TicketLegCommand(**leg) for leg in row['input_legs']],
                    composition=row['composition'],
                    audit_state=audit_state,
                    audit_findings=findings,
                    artifact_ids=artifact_ids.get(revision_id, []),
                    added_leg_keys=added,
                    removed_leg_keys=removed,
                    changed_leg_keys=changed,
                )
            )
            previous_by_batch[row['ticket_batch_id']] = current_legs
        return result

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

    def release(
        self,
        *,
        release_version: str,
        candidate_commit: str,
        evaluated_at: datetime,
    ) -> ReleaseResponse:
        cutoff = _aware(evaluated_at, 'evaluated_at')
        with OntologyUnitOfWork(self._kernel.engine) as uow:
            evaluation = ReleaseEvaluator(uow.reliability).evaluate(
                release_version,
                candidate_commit=candidate_commit,
                evaluated_at=cutoff,
            )
            approval = uow.reliability.approval_for_release(release_version)
        approval_summary = None
        if approval is not None:
            approval_summary = ReleaseApprovalSummary(
                release_approval_id=approval.release_approval_id,
                release_version=approval.release_version,
                evidence_snapshot_sha256=approval.evidence_snapshot_sha256,
                policy_version=approval.policy_version,
                reason=approval.reason,
                approved_at=approval.approved_at,
                status=evaluation.approval_status,
            )
        selected_by_kind = {
            row.evidence_kind: row for row in evaluation.selected_evidence
        }
        scheduler_row = selected_by_kind.get('scheduler_authority')
        backup_row = selected_by_kind.get('backup_restore')
        performance_row = selected_by_kind.get('performance')
        return ReleaseResponse(
            release_version=evaluation.release_version,
            candidate_commit=evaluation.candidate_commit,
            policy_version=evaluation.policy_version,
            evaluated_at=evaluation.evaluated_at,
            ready=evaluation.ready,
            gates=[
                ReleaseGateSummary(**gate.to_dict())
                for gate in evaluation.gates.values()
            ],
            evidence=[self._reliability_evidence(row) for row in evaluation.selected_evidence],
            soak_coverage=[
                SoakCoverageSummary(**coverage.to_dict())
                for coverage in evaluation.soak_coverage.values()
            ],
            evidence_snapshot_sha256=evaluation.evidence_snapshot_sha256,
            approval_status=evaluation.approval_status,
            approval=approval_summary,
            scheduler_authority=(
                self._release_scheduler_summary(scheduler_row)
                if scheduler_row is not None
                else None
            ),
            backup_restore=(
                self._release_backup_summary(backup_row)
                if backup_row is not None
                else None
            ),
            performance=(
                self._release_performance_summary(performance_row)
                if performance_row is not None
                else []
            ),
        )

    def reliability_metrics(
        self,
        *,
        as_of: datetime,
        routes: Iterable[RouteMetricSnapshot] = (),
    ) -> ReliabilityMetricsResponse:
        cutoff = _aware(as_of, 'as_of')
        status = self._kernel.status()
        with OntologyUnitOfWork(self._kernel.engine) as uow:
            rows = uow.reliability.list_evidence(recorded_to=cutoff.isoformat())
            authority = uow.scoreboard.authority().state
        freshness: dict[str, datetime | None] = {}
        for row in rows:
            if row.evidence_kind not in freshness:
                freshness[row.evidence_kind] = _parse_iso(row.recorded_at)
        last_restore = next(
            (
                row
                for row in rows
                if row.evidence_kind == 'backup_restore' and row.status == 'passed'
            ),
            None,
        )
        projection = self._repository.scoreboard_projection(as_of=cutoff.isoformat())
        action_high_watermark = self._repository.action_high_watermark()
        return ReliabilityMetricsResponse(
            as_of=cutoff,
            routes=[
                RouteMetricSummary(
                    route_template=row.route_template,
                    method=row.method,
                    request_count=row.request_count,
                    error_count=row.error_count,
                    p95_ms=row.p95_ms,
                )
                for row in routes
            ],
            action_status_counts=status.action_counts,
            action_high_watermark=action_high_watermark,
            outbox_high_watermark=status.outbox_latest_sequence,
            outbox_lag=max(0, action_high_watermark - status.outbox_latest_sequence),
            projection_state=projection['health']['state'],
            authority_state=authority,
            evidence_freshness=freshness,
            last_restore_drill=(
                self._reliability_evidence(last_restore)
                if last_restore is not None
                else None
            ),
        )

    @staticmethod
    def _reliability_evidence(row) -> ReliabilityEvidenceSummary:
        return ReliabilityEvidenceSummary(
            reliability_evidence_id=row.reliability_evidence_id,
            evidence_kind=row.evidence_kind,
            workflow=row.workflow,
            business_date=row.business_date,
            observed_from=row.observed_from,
            observed_to=row.observed_to,
            status=row.status,
            content_hash=row.content_hash,
            recorded_at=row.recorded_at,
        )

    @staticmethod
    def _release_scheduler_summary(row) -> ReleaseSchedulerSummary:
        summary = row.report.get('summary')
        summary = summary if isinstance(summary, dict) else {}
        stages = summary.get('stages')
        stages = stages if isinstance(stages, list) else []
        configured = sum(
            1
            for stage in stages
            if isinstance(stage, dict) and stage.get('configured') is True
        )
        loaded = sum(
            1
            for stage in stages
            if isinstance(stage, dict) and stage.get('loaded') is True
        )
        authority = summary.get('scoreboard_authority')
        return ReleaseSchedulerSummary(
            reliability_evidence_id=row.reliability_evidence_id,
            status=row.status,
            observed_to=row.observed_to,
            ontology_v2=(
                summary.get('ontology_v2')
                if isinstance(summary.get('ontology_v2'), bool)
                else None
            ),
            scoreboard_authority=(
                authority if authority in {'legacy', 'ontology'} else None
            ),
            sop_ready=(
                summary.get('sop_ready')
                if isinstance(summary.get('sop_ready'), bool)
                else None
            ),
            configured_stages=configured,
            loaded_stages=loaded,
        )

    @staticmethod
    def _release_backup_summary(row) -> ReleaseBackupRestoreSummary:
        summary = row.report.get('summary')
        summary = summary if isinstance(summary, dict) else {}

        def non_negative_int(name: str) -> int | None:
            value = summary.get(name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                return None
            return value

        digest = summary.get('source_manifest_sha256')
        if not (
            isinstance(digest, str)
            and len(digest) == 64
            and all(char in '0123456789abcdef' for char in digest)
        ):
            digest = None
        integrity = summary.get('sqlite_integrity')
        return ReleaseBackupRestoreSummary(
            reliability_evidence_id=row.reliability_evidence_id,
            status=row.status,
            observed_to=row.observed_to,
            sqlite_integrity=integrity if isinstance(integrity, str) else None,
            schema_version=non_negative_int('schema_version'),
            action_high_watermark=non_negative_int('action_high_watermark'),
            outbox_cursor=non_negative_int('outbox_cursor'),
            projection_high_watermark=non_negative_int(
                'projection_high_watermark'
            ),
            source_manifest_sha256=digest,
        )

    @staticmethod
    def _release_performance_summary(row) -> list[ReleasePerformanceSummary]:
        metrics = row.report.get('metrics')
        if not isinstance(metrics, dict):
            return []
        summaries: list[ReleasePerformanceSummary] = []
        for name, budget in PERFORMANCE_BUDGETS_MS.items():
            raw = metrics.get(name)
            if not isinstance(raw, dict):
                continue
            p95 = raw.get('p95_ms')
            samples = raw.get('sample_count')
            if (
                isinstance(p95, bool)
                or not isinstance(p95, (int, float))
                or not math.isfinite(float(p95))
                or float(p95) < 0
                or isinstance(samples, bool)
                or not isinstance(samples, int)
                or samples <= 0
            ):
                continue
            summaries.append(
                ReleasePerformanceSummary(
                    metric=name,
                    p95_ms=float(p95),
                    budget_ms=budget,
                    sample_count=samples,
                    passed=row.status == 'passed' and float(p95) <= budget,
                )
            )
        return summaries

    def _match_summary(self, record: dict, cutoff: datetime) -> MatchSummary:
        claims = self._repository.claims_for_match(record['match_id'], cutoff.isoformat())
        observations = self._repository.observations_for_match(
            record['match_id'], cutoff.isoformat()
        )
        snapshot = self._repository.latest_snapshot(
            record['match_id'], _DEFAULT_MARKET, cutoff.isoformat()
        )
        conflicts = classify_claim_conflicts(claims)
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


def _json_value(value: str, name: str) -> dict | list:
    decoded = json.loads(value)
    if not isinstance(decoded, (dict, list)):
        raise ValueError(f'{name} must contain an object or list')
    return decoded


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
