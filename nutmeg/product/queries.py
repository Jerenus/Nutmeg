"""Versioned product DTO assembly with explicit information cutoffs."""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from nutmeg.product.contracts import (
    ActionPage,
    ActionView,
    BoardResponse,
    ClaimSummary,
    EventPage,
    EvidenceSummary,
    ForecastSummary,
    HealthResponse,
    LineageEdge,
    LineageResponse,
    MarketSnapshotSummary,
    MatchDetail,
    MatchSummary,
    ObjectRefContract,
    ObservationSummary,
    OutboxEventView,
    WorkflowObjectSummary,
)
from nutmeg.product.errors import ProductNotFoundError
from nutmeg.product.readiness import evaluate_readiness
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

    def match(self, match_id: str, *, as_of: datetime) -> MatchDetail:
        cutoff = _aware(as_of, 'as_of')
        record = self._repository.match(match_id, cutoff.isoformat())
        if record is None:
            raise ProductNotFoundError(f'match {match_id} not found')
        claims = self._repository.claims_for_match(match_id, cutoff.isoformat())
        observations = self._repository.observations_for_match(
            match_id, cutoff.isoformat()
        )
        snapshot = self._repository.latest_snapshot(
            match_id, _DEFAULT_MARKET, cutoff.isoformat()
        )
        summary = self._summary(record, cutoff, snapshot, len(claims) + len(observations))
        forecasts = self._repository.forecasts_for_match(match_id, cutoff.isoformat())
        workflow = self._repository.workflow_for_match(match_id, cutoff.isoformat())
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
                    )
                    for item in observations
                ],
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
        items = [
            ActionView(
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
            for item in records
        ]
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
        return self._summary(record, cutoff, snapshot, len(claims) + len(observations))

    @staticmethod
    def _summary(
        record: dict,
        cutoff: datetime,
        snapshot: dict | None,
        evidence_count: int,
    ) -> MatchSummary:
        snapshot_at = _parse_iso(snapshot['as_of']) if snapshot is not None else None
        readiness = evaluate_readiness(
            identity_resolved=(
                record['home_resolution_status'] == 'resolved'
                and record['away_resolution_status'] == 'resolved'
            ),
            snapshot_at=snapshot_at,
            as_of=cutoff,
            evidence_count=evidence_count,
        )
        return MatchSummary(
            match_id=record['match_id'],
            home_team=record['home_team'],
            away_team=record['away_team'],
            competition=record['competition'],
            kickoff_at=record['scheduled_at'],
            latest_snapshot_at=snapshot['as_of'] if snapshot is not None else None,
            readiness=readiness,
        )

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
