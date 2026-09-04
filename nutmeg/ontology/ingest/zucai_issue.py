"""Ingest one 传统足彩 (zucai) issue into typed identity + market facts.

The zucai lane is the second live channel next to the jczq market day: one issue is
14 matches with a single 1X2 book. Each match enters through the same typed Actions
as the market day — upsert_team → record_match → build_snapshot — with idempotency
keys derived from ``issue`` + ``match_no`` so a rerun commits nothing new.

**Identity**: matches are keyed ``provider='zucai-canonical'`` with
``external_id = canonical_match_id(home, away, match_date)`` — the same identity
function the legacy store used, so replays and cross-issue duplicates collapse.
Cross-channel unification with the sporttery board (which keys matches by its own
provider ids) is a documented follow-on, not attempted here: a real-world match that
appears on both boards is two kernel matches until an alignment pass links them.

A match without a full 1X2 book or without its own ``match_date`` is skipped and
counted (never a fabricated snapshot, never an issue-level single-date fallback —
one issue routinely spans multiple days).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from nutmeg.ontology.actions.artifact_ingest import ArtifactIngestRequest, ArtifactIngestService
from nutmeg.ontology.actions.entity_actions import EntityActions, UpsertTeamRequest
from nutmeg.ontology.actions.market_actions import MarketActions
from nutmeg.ontology.actions.match_actions import MatchActions, MatchSideRef, RecordMatchRequest
from nutmeg.ontology.actions.models import ActionStatus, ActorRole, canonical_json
from nutmeg.ontology.errors import IdempotencyConflictError
from nutmeg.ontology.identity.models import MatchSide, MatchStatus, TeamKind
from nutmeg.ontology.ingest.competition import resolve_competition_edition
from nutmeg.ontology.market.models import QuoteInput, SnapshotBuildRequest


@dataclass(frozen=True, slots=True)
class ZucaiMarketSource:
    provider: str
    value: dict
    retrieved_at: datetime

    def __post_init__(self) -> None:
        if self.provider not in {"zucai", "intl"}:
            raise ValueError("Zucai market source provider must be zucai or intl")
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("Zucai market source retrieved_at must be timezone-aware")

_HAD = "md-had"
_OUTCOMES = ("home", "draw", "away")


def _content_key(value: dict) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True, slots=True)
class ZucaiRow:
    """One board slot: identity + its 1X2 decimal odds (``None`` odds → skipped)."""

    match_no: int
    home: str
    away: str
    competition: str
    match_date: str | None
    odds: dict | None


@dataclass(frozen=True, slots=True)
class ZucaiIssueIngestRequest:
    issue: str
    rows: tuple[ZucaiRow, ...]
    actor_id: str
    actor_role: ActorRole
    requested_at: datetime
    snapshot_kind: str = "read_time"
    market_sources: tuple[ZucaiMarketSource, ...] = ()

    def __post_init__(self) -> None:
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError("requested_at must be timezone-aware")
        if not self.issue.strip():
            raise ValueError("issue is required")


@dataclass(frozen=True, slots=True)
class ZucaiIssueIngestResult:
    matches: int
    snapshots: int
    teams: int
    skipped: tuple[str, ...] = field(default=())


class ZucaiIssueIngestService:
    def __init__(
        self,
        *,
        entity_actions: EntityActions,
        match_actions: MatchActions,
        market_actions: MarketActions,
        artifact_ingest: ArtifactIngestService | None = None,
        snapshot_probe: Callable[[str, str, str], bool] | None = None,
    ) -> None:
        self._entity_actions = entity_actions
        self._match_actions = match_actions
        self._market_actions = market_actions
        self._artifact_ingest = artifact_ingest
        self._snapshot_probe = snapshot_probe

    def ingest(self, request: ZucaiIssueIngestRequest) -> ZucaiIssueIngestResult:
        from nutmeg.decision.identity import canonical_match_id

        source_markets = tuple(
            (
                source,
                self._market_odds(request.issue, source.value),
                self._ingest_artifact(request, source),
            )
            for source in request.market_sources
        )
        match_ids: set[str] = set()
        team_ids: set[str] = set()
        snapshots = 0
        skipped: list[str] = []

        for row in request.rows:
            odds = row.odds or {}
            source_rows = tuple(
                (source, by_match_no.get(row.match_no), retrieval_id)
                for source, by_match_no, retrieval_id in source_markets
                if self._complete_odds(by_match_no.get(row.match_no))
            )
            if not source_rows and not self._complete_odds(odds):
                skipped.append(f"{request.issue}-{row.match_no}:no_odds")
                continue
            if not row.match_date:
                skipped.append(f"{request.issue}-{row.match_no}:no_date")
                continue

            home_id = self._upsert_team(request, row.home)
            away_id = self._upsert_team(request, row.away)
            team_ids.update((home_id, away_id))

            canonical = canonical_match_id(row.home, row.away, row.match_date)
            competition_edition = resolve_competition_edition(row.competition)
            outcome = self._match_actions.record_match(
                RecordMatchRequest(
                    provider="zucai-canonical",
                    external_id=canonical,
                    scheduled_at=row.match_date,
                    schedule_status="scheduled",
                    status=MatchStatus.SCHEDULED,
                    home=MatchSideRef(team_id=home_id, side=MatchSide.HOME),
                    away=MatchSideRef(team_id=away_id, side=MatchSide.AWAY),
                    actor_id=request.actor_id,
                    actor_role=request.actor_role,
                    idempotency_key=(
                        f"zucai:match:v2:{request.issue}:{row.match_no}:"
                        f"{competition_edition.competition_edition_id}"
                        if competition_edition
                        else f"zucai:match:v2:{request.issue}:{row.match_no}:unresolved"
                    ),
                    requested_at=request.requested_at,
                    competition_edition=competition_edition,
                )
            )
            match_id = outcome.result_refs[0].object_id
            match_ids.add(match_id)

            builds = source_rows or (
                (
                    ZucaiMarketSource(
                        provider="zucai",
                        value={},
                        retrieved_at=request.requested_at,
                    ),
                    odds,
                    None,
                ),
            )
            for source, source_odds, retrieval_id in builds:
                as_of = source.retrieved_at.astimezone(UTC).isoformat()
                if self._snapshot_probe is not None and self._snapshot_probe(
                    match_id, source.provider, as_of
                ):
                    skipped.append(
                        f"{request.issue}-{row.match_no}:{source.provider}_snapshot_replayed"
                    )
                    continue
                outcome = self._build_snapshot(
                    request=request,
                    row=row,
                    match_id=match_id,
                    source=source,
                    odds=source_odds,
                    artifact_retrieval_id=retrieval_id,
                )
                if outcome is None:
                    skipped.append(
                        f"{request.issue}-{row.match_no}:{source.provider}_snapshot_key_conflict"
                    )
                elif outcome.status is ActionStatus.COMMITTED:
                    snapshots += 1
                else:
                    # 拒绝/失败不是入库(26110-26111 曾把 rejected 计成 14 Snapshot)
                    code = f":{outcome.error_code}" if outcome.error_code else ""
                    skipped.append(
                        f"{request.issue}-{row.match_no}:{source.provider}_snapshot_"
                        f"{outcome.status.value}{code}"
                    )

        return ZucaiIssueIngestResult(
            matches=len(match_ids),
            snapshots=snapshots,
            teams=len(team_ids),
            skipped=tuple(skipped),
        )

    @staticmethod
    def _complete_odds(odds: dict | None) -> bool:
        return bool(odds) and all(odds.get(key) for key in _OUTCOMES)

    @staticmethod
    def _market_odds(issue: str, value: dict) -> dict[int, dict[str, float]]:
        source_issue = str(value.get("issue_id") or value.get("issue") or "")
        if source_issue and source_issue != issue:
            raise ValueError(
                f"Zucai market artifact issue {source_issue} does not match {issue}"
            )
        markets: dict[int, dict[str, float]] = {}
        for item in value.get("matches") or []:
            try:
                match_no = int(item["match_no"])
                odds = {key: float(item[key]) for key in _OUTCOMES}
            except (KeyError, TypeError, ValueError):
                continue
            if all(decimal > 1.0 for decimal in odds.values()):
                markets[match_no] = odds
        return markets

    def _ingest_artifact(
        self,
        request: ZucaiIssueIngestRequest,
        source: ZucaiMarketSource,
    ) -> str:
        if self._artifact_ingest is None:
            raise ValueError("artifact_ingest is required for Zucai market sources")
        captured_at = source.retrieved_at.astimezone(UTC).isoformat()
        outcome = self._artifact_ingest.ingest(
            ArtifactIngestRequest(
                content=canonical_json(source.value).encode("utf-8"),
                content_type="application/json",
                source_name=source.provider,
                source_type="api",
                actor_id=request.actor_id,
                actor_role=request.actor_role,
                idempotency_key=(
                    f"zucai:{request.issue}:{source.provider}:{request.snapshot_kind}:"
                    f"{captured_at}:{_content_key(source.value)}"
                ),
                retrieved_at=source.retrieved_at,
            )
        )
        for ref in outcome.result_refs:
            if ref.object_type == "artifact_retrieval":
                return ref.object_id
        raise ValueError("Zucai market artifact did not produce a retrieval")

    def _build_snapshot(
        self,
        *,
        request: ZucaiIssueIngestRequest,
        row: ZucaiRow,
        match_id: str,
        source: ZucaiMarketSource,
        odds: dict,
        artifact_retrieval_id: str | None,
    ):
        as_of = source.retrieved_at.astimezone(UTC).isoformat()
        try:
            return self._market_actions.build_snapshot(
                SnapshotBuildRequest(
                    match_id=match_id,
                    market_definition_id=_HAD,
                    snapshot_kind=request.snapshot_kind,
                    as_of=as_of,
                    provider=source.provider,
                    quotes=[
                        QuoteInput(_HAD, f"sel-had-{key}", float(odds[key]))
                        for key in _OUTCOMES
                    ],
                    actor_id=request.actor_id,
                    # 快照是确定性算术产物，由 deterministic_system 执行。
                    actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                    idempotency_key=(
                        f"zucai:snapshot:{request.issue}:{row.match_no}:"
                        f"{source.provider}:{request.snapshot_kind}:"
                        f"{artifact_retrieval_id or as_of}"
                    ),
                    requested_at=request.requested_at,
                    artifact_retrieval_id=artifact_retrieval_id,
                )
            )
        except IdempotencyConflictError:
            return None

    def _upsert_team(self, request: ZucaiIssueIngestRequest, name: str) -> str:
        outcome = self._entity_actions.upsert_team(
            UpsertTeamRequest(
                canonical_name=name,
                team_kind=TeamKind.CLUB,
                country=None,
                provider=None,
                external_id=None,
                actor_id=request.actor_id,
                actor_role=request.actor_role,
                idempotency_key=f"team:zucai:{request.issue}:{name.casefold()}",
                requested_at=request.requested_at,
            )
        )
        return outcome.result_refs[0].object_id
