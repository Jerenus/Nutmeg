"""Ingest one market day into typed identity + market facts.

Orchestrates the Package 2A Actions end to end: IngestArtifact the raw payloads
to CAS, then for each parsed sporttery match upsert its teams, record the match
(real schedule, opaque id), and de-vig its had snapshot; finally align the
international book's quotes to the same opaque match by sporttery match number and
record their snapshot. Every step's idempotency key is derived deterministically
from the business date + provider ids, so a rerun commits nothing new.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

from nutmeg.ontology.actions.artifact_ingest import ArtifactIngestRequest, ArtifactIngestService
from nutmeg.ontology.actions.entity_actions import EntityActions, UpsertTeamRequest
from nutmeg.ontology.actions.market_actions import MarketActions
from nutmeg.ontology.actions.match_actions import MatchActions, MatchSideRef, RecordMatchRequest
from nutmeg.ontology.actions.models import ActorRole, canonical_json
from nutmeg.ontology.errors import IdempotencyConflictError
from nutmeg.ontology.identity.models import MatchSide, MatchStatus, TeamKind
from nutmeg.ontology.ingest.intl_odds import ParsedIntlQuote, parse_bold_odds
from nutmeg.ontology.ingest.sporttery import ParsedMatch, ParsedQuote, parse_sporttery_markets
from nutmeg.ontology.market.models import QuoteInput, SnapshotBuildRequest

_HAD = "md-had"


def _content_key(value: dict) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True, slots=True)
class MarketDayIngestRequest:
    business_date: str
    sporttery_value: dict
    actor_id: str
    actor_role: ActorRole
    requested_at: datetime
    intl_value: dict | None = None
    snapshot_kind: str = "read_time"
    sporttery_snapshots: bool = True

    def __post_init__(self) -> None:
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError("requested_at must be timezone-aware")
        if not self.business_date.strip():
            raise ValueError("business_date is required")


@dataclass(frozen=True, slots=True)
class MarketDayIngestResult:
    matches: int
    snapshots: int
    teams: int


class MarketDayIngestService:
    def __init__(
        self,
        *,
        artifact_ingest: ArtifactIngestService,
        entity_actions: EntityActions,
        match_actions: MatchActions,
        market_actions: MarketActions,
    ) -> None:
        self._artifact_ingest = artifact_ingest
        self._entity_actions = entity_actions
        self._match_actions = match_actions
        self._market_actions = market_actions

    def ingest(self, request: MarketDayIngestRequest) -> MarketDayIngestResult:
        kind = request.snapshot_kind
        sporttery_retrieval = self._ingest_artifact(
            request,
            request.sporttery_value,
            "sporttery",
            f"sporttery:{kind}:{request.business_date}:{_content_key(request.sporttery_value)}",
        )
        intl_retrieval = None
        if request.intl_value is not None:
            intl_retrieval = self._ingest_artifact(
                request,
                request.intl_value,
                "intl",
                f"intl:{kind}:{request.business_date}:{_content_key(request.intl_value)}",
            )

        match_ids: set[str] = set()
        team_ids: set[str] = set()
        snapshots = 0
        match_no_to_id: dict[str, str] = {}

        for parsed in parse_sporttery_markets(
            request.sporttery_value, business_date=request.business_date
        ):
            home_id = self._upsert_team(request, parsed.home_name)
            away_id = self._upsert_team(request, parsed.away_name)
            team_ids.update((home_id, away_id))
            match_id = self._record_match(request, parsed, home_id, away_id)
            match_ids.add(match_id)
            match_no_to_id[parsed.match_no] = match_id
            had = [quote for quote in parsed.quotes if quote.market_kind == "had"]
            if had and request.sporttery_snapshots:
                try:
                    self._build_had_snapshot(
                        request,
                        match_id,
                        parsed.match_no,
                        "sporttery",
                        parsed.scheduled_at,
                        had,
                        sporttery_retrieval,
                    )
                    snapshots += 1
                except IdempotencyConflictError:
                    pass  # 盘中赔率已动:保留早盘 read_time 锚(判读时的价),不覆盖

        if request.intl_value is not None:
            by_match_no: dict[str, list[ParsedIntlQuote]] = defaultdict(list)
            for quote in parse_bold_odds(request.intl_value):
                by_match_no[quote.align_match_no].append(quote)
            for match_no, quotes in by_match_no.items():
                match_id = match_no_to_id.get(match_no)
                if match_id is None:
                    continue
                had = [quote for quote in quotes if quote.market_kind == "had"]
                if had:
                    try:
                        self._build_had_snapshot(
                            request, match_id, match_no, "intl", None, had, intl_retrieval
                        )
                        snapshots += 1
                    except IdempotencyConflictError:
                        pass  # 同上:保留已存锚

        return MarketDayIngestResult(
            matches=len(match_ids), snapshots=snapshots, teams=len(team_ids)
        )

    def _ingest_artifact(
        self, request: MarketDayIngestRequest, value: dict, source_name: str, key: str
    ) -> str | None:
        try:
            return self._ingest_artifact_once(request, value, source_name, key)
        except IdempotencyConflictError:
            return None  # 同内容重放(requested_at 不同):既有 artifact 已在库,静默跳过

    def _ingest_artifact_once(
        self, request: MarketDayIngestRequest, value: dict, source_name: str, key: str
    ) -> str | None:
        outcome = self._artifact_ingest.ingest(
            ArtifactIngestRequest(
                content=canonical_json(value).encode("utf-8"),
                content_type="application/json",
                source_name=source_name,
                source_type="api",
                actor_id=request.actor_id,
                actor_role=request.actor_role,
                idempotency_key=key,
                retrieved_at=request.requested_at,
            )
        )
        for ref in outcome.result_refs:
            if ref.object_type == "artifact_retrieval":
                return ref.object_id
        return None

    def _upsert_team(self, request: MarketDayIngestRequest, name: str) -> str:
        outcome = self._entity_actions.upsert_team(
            UpsertTeamRequest(
                canonical_name=name,
                team_kind=TeamKind.CLUB,
                country=None,
                provider=None,
                external_id=None,
                actor_id=request.actor_id,
                actor_role=request.actor_role,
                idempotency_key=f"team:{request.business_date}:{name.casefold()}",
                requested_at=request.requested_at,
            )
        )
        return outcome.result_refs[0].object_id

    def _record_match(
        self, request: MarketDayIngestRequest, parsed: ParsedMatch, home_id: str, away_id: str
    ) -> str:
        outcome = self._match_actions.record_match(
            RecordMatchRequest(
                provider=parsed.provider,
                external_id=parsed.external_id,
                scheduled_at=parsed.scheduled_at,
                schedule_status=parsed.schedule_status,
                status=MatchStatus.SCHEDULED,
                home=MatchSideRef(team_id=home_id, side=MatchSide.HOME),
                away=MatchSideRef(team_id=away_id, side=MatchSide.AWAY),
                actor_id=request.actor_id,
                actor_role=request.actor_role,
                idempotency_key=f"match:{request.business_date}:{parsed.external_id}",
                requested_at=request.requested_at,
            )
        )
        return outcome.result_refs[0].object_id

    def _build_had_snapshot(
        self,
        request: MarketDayIngestRequest,
        match_id: str,
        match_no: str,
        channel: str,
        scheduled_at: str | None,
        had_quotes: list[ParsedQuote] | list[ParsedIntlQuote],
        artifact_retrieval_id: str | None,
    ) -> None:
        as_of = scheduled_at or request.requested_at.astimezone(UTC).isoformat()
        kind = request.snapshot_kind
        self._market_actions.build_snapshot(
            SnapshotBuildRequest(
                match_id=match_id,
                market_definition_id=_HAD,
                snapshot_kind=kind,
                as_of=as_of,
                provider=channel,
                quotes=[
                    QuoteInput(
                        market_definition_id=_HAD,
                        selection_id=f"sel-had-{quote.outcome_key}",
                        decimal_odds=quote.decimal_odds,
                    )
                    for quote in had_quotes
                ],
                actor_id="system:devig",
                actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                idempotency_key=f"snap:{channel}:{kind}:{request.business_date}:{match_no}:had",
                requested_at=request.requested_at,
                artifact_retrieval_id=artifact_retrieval_id,
            )
        )
