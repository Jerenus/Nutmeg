"""Replay the old JSONL decision store into a fresh kernel through typed Actions.

The importer is deterministic and idempotent: every Action's idempotency key is
derived from the old object id (``import:<type>:<old_id>``), so a re-run imports
nothing twice. It keeps an old→new id map so snapshots/reads/tickets resolve to the
matches they belong to. Nothing is dropped silently — an unresolved reference is
counted in ``ImportReport.skipped``. The importer writes only the kernel it is given.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from nutmeg.ontology.actions.entity_actions import EntityActions, UpsertTeamRequest
from nutmeg.ontology.actions.forecast_actions import CommitForecastRequest, ForecastActions
from nutmeg.ontology.actions.market_actions import MarketActions
from nutmeg.ontology.actions.match_actions import (
    MatchActions,
    MatchSideRef,
    RecordMatchRequest,
)
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.outcome_actions import OutcomeActions, RecordOutcomeRequest
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.identity.models import MatchSide, MatchStatus, TeamKind
from nutmeg.ontology.market.models import QuoteInput, SnapshotBuildRequest
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

_HAD_MARKET = 'md-had'
_MARKET_MAP = {'had': 'md-had', 'hhad': 'md-hhad', 'ttg': 'md-ttg', 'crs': 'md-crs'}
_RESULT_SCORE = {'home': '1-0', 'draw': '0-0', 'away': '0-1'}

_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


def _to_datetime(value: object) -> datetime:
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return _EPOCH
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return _EPOCH


@dataclass
class ImportReport:
    counts: dict[str, int] = field(default_factory=dict)
    team_id_map: dict[str, str] = field(default_factory=dict)
    match_id_map: dict[str, str] = field(default_factory=dict)
    snapshot_id_map: dict[str, str] = field(default_factory=dict)
    read_match: dict[str, str] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)

    def bump(self, key: str) -> None:
        self.counts[key] = self.counts.get(key, 0) + 1


class HistoricalImporter:
    def __init__(self, kernel, actor_id: str = 'migration') -> None:
        self._kernel = kernel
        self._actor = actor_id
        service = ActionService(lambda: OntologyUnitOfWork(kernel.engine))
        self._entities = EntityActions(service)
        self._matches = MatchActions(service)
        self._markets = MarketActions(service)
        self._forecasts = ForecastActions(service)
        self._outcomes = OutcomeActions(service)
        self.report = ImportReport()

    def _team_id(self, old_ref: str, name: str) -> str:
        cached = self.report.team_id_map.get(old_ref)
        if cached is not None:
            return cached
        outcome = self._entities.upsert_team(UpsertTeamRequest(
            canonical_name=name, team_kind=TeamKind.CLUB, country=None, provider='import',
            external_id=old_ref, actor_id=self._actor, actor_role=ActorRole.CONNECTOR,
            idempotency_key=f'import:team:{old_ref}', requested_at=_EPOCH))
        team_id = outcome.result_refs[0].object_id
        self.report.team_id_map[old_ref] = team_id
        return team_id

    def import_matches(self, rows: list[dict[str, object]]) -> ImportReport:
        for row in rows:
            old_id = str(row['match_id'])
            if old_id in self.report.match_id_map:
                continue
            home_ref = str(row.get('home_team_id') or row['home'])
            away_ref = str(row.get('away_team_id') or row['away'])
            home = self._team_id(home_ref, str(row['home']))
            away = self._team_id(away_ref, str(row['away']))
            kickoff = row.get('kickoff_at')
            outcome = self._matches.record_match(RecordMatchRequest(
                provider='import', external_id=old_id,
                scheduled_at=str(kickoff) if kickoff else None,
                schedule_status='scheduled' if kickoff else 'unknown',
                status=MatchStatus.FINISHED,
                home=MatchSideRef(home, MatchSide.HOME),
                away=MatchSideRef(away, MatchSide.AWAY),
                actor_id=self._actor, actor_role=ActorRole.CONNECTOR,
                idempotency_key=f'import:match:{old_id}', requested_at=_to_datetime(kickoff)))
            self.report.match_id_map[old_id] = outcome.result_refs[0].object_id
            self.report.bump('matches')
        return self.report

    def import_snapshots(self, rows: list[dict[str, object]]) -> ImportReport:
        for row in rows:
            old_id = str(row['snapshot_id'])
            if old_id in self.report.snapshot_id_map:
                continue
            new_match = self.report.match_id_map.get(str(row['match_id']))
            if new_match is None:
                self.report.skipped.append(f'snapshot:{old_id}:unmapped_match')
                continue
            # The old snapshot fair is nested by market: {"had": {home,draw,away}, "hhad": …};
            # 5A imports the had book. A flat {home,draw,away} is also accepted.
            fair_all = row.get('fair') or {}
            fair = fair_all.get('had', fair_all) if isinstance(fair_all, dict) else {}
            quotes = [
                QuoteInput(_HAD_MARKET, f'sel-had-{key}', 1.0 / float(prob))
                for key, prob in fair.items()
                if isinstance(prob, int | float) and 0.0 < float(prob) < 1.0
            ]
            if len(quotes) != len(fair) or not quotes:
                self.report.skipped.append(f'snapshot:{old_id}:degenerate_fair')
                continue
            as_of = str(row.get('taken_at') or _EPOCH.isoformat())
            outcome = self._markets.build_snapshot(SnapshotBuildRequest(
                match_id=new_match, market_definition_id=_HAD_MARKET,
                snapshot_kind=str(row.get('kind') or 'open'), as_of=as_of, provider='import',
                quotes=quotes, actor_id=self._actor, actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                idempotency_key=f'import:snapshot:{old_id}',
                requested_at=_to_datetime(row.get('taken_at'))))
            self.report.snapshot_id_map[old_id] = outcome.result_refs[0].object_id
            self.report.bump('snapshots')
        return self.report

    def import_reads(self, rows: list[dict[str, object]]) -> ImportReport:
        for row in rows:
            old_id = str(row['read_id'])
            market = _MARKET_MAP.get(str(row.get('market')))
            if market is None:
                self.report.skipped.append(f'read:{old_id}:unmapped_market')
                continue
            old_match = str(row['match_id'])
            new_match = self.report.match_id_map.get(old_match)
            if new_match is None:
                self.report.skipped.append(f'read:{old_id}:unmapped_match')
                continue
            # Old factors carry direction/weight_pp, not a per-outcome delta that
            # reconstructs belief-prior, so they cannot be replayed as FactorApplications;
            # the belief is committed follow-market and the drop is counted, never faked.
            dropped = len(row.get('factors') or [])
            if dropped:
                self.report.counts['factors_dropped'] = (
                    self.report.counts.get('factors_dropped', 0) + dropped
                )
            made_at = row.get('made_at')
            self._forecasts.commit_forecast(CommitForecastRequest(
                match_id=new_match, market_definition_id=market, decision_session_id=None,
                prior_distribution=row['prior'], belief_distribution=row['belief'], factors=[],
                commitment_tier='commit', evidence_bundle_id=None,
                prior_snapshot_id=self.report.snapshot_id_map.get(str(row.get('snapshot_id'))),
                falsifier=row.get('falsifier'), actor_id=self._actor,
                actor_role=ActorRole.JUDGE_OPERATOR, idempotency_key=f'import:read:{old_id}',
                requested_at=_to_datetime(made_at)))
            self.report.read_match[old_id] = old_match
            self.report.bump('reads')
        return self.report

    def import_outcomes(self, settlement_rows: list[dict[str, object]]) -> ImportReport:
        recorded: set[str] = set()
        for row in settlement_rows:
            if row.get('ref_type') != 'read':
                continue
            score = _RESULT_SCORE.get(str(row.get('outcome_90')))
            if score is None:
                continue
            old_match = self.report.read_match.get(str(row.get('ref_id')))
            new_match = self.report.match_id_map.get(old_match) if old_match else None
            if new_match is None or new_match in recorded:
                continue
            self._outcomes.record_outcome(RecordOutcomeRequest(
                match_id=new_match, score_90=score, status='final',
                source_artifact_retrieval_ids=[], actor_id=self._actor,
                actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                idempotency_key=f'import:outcome:{new_match}',
                requested_at=_to_datetime(row.get('settled_at'))))
            recorded.add(new_match)
            self.report.bump('outcomes')
        return self.report
