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

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from nutmeg.ontology.actions.entity_actions import EntityActions, UpsertTeamRequest
from nutmeg.ontology.actions.market_actions import MarketActions
from nutmeg.ontology.actions.match_actions import MatchActions, MatchSideRef, RecordMatchRequest
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.errors import IdempotencyConflictError
from nutmeg.ontology.identity.models import MatchSide, MatchStatus, TeamKind
from nutmeg.ontology.market.models import QuoteInput, SnapshotBuildRequest

_HAD = "md-had"
_OUTCOMES = ("home", "draw", "away")


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
        snapshot_probe: Callable[[str], bool] | None = None,
    ) -> None:
        self._entity_actions = entity_actions
        self._match_actions = match_actions
        self._market_actions = market_actions
        # 首个 read_time 锚保持:probe 报告该场已有 zucai 快照 → 不再建新的
        # (判读时的价是锚,盘中位移不覆盖)。
        self._snapshot_probe = snapshot_probe

    def ingest(self, request: ZucaiIssueIngestRequest) -> ZucaiIssueIngestResult:
        from nutmeg.decision.identity import canonical_match_id

        match_ids: set[str] = set()
        team_ids: set[str] = set()
        snapshots = 0
        skipped: list[str] = []

        for row in request.rows:
            odds = row.odds or {}
            if not all(odds.get(key) for key in _OUTCOMES):
                skipped.append(f"{request.issue}-{row.match_no}:no_odds")
                continue
            if not row.match_date:
                skipped.append(f"{request.issue}-{row.match_no}:no_date")
                continue

            home_id = self._upsert_team(request, row.home)
            away_id = self._upsert_team(request, row.away)
            team_ids.update((home_id, away_id))

            canonical = canonical_match_id(row.home, row.away, row.match_date)
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
                    idempotency_key=f"zucai:match:{request.issue}:{row.match_no}",
                    requested_at=request.requested_at,
                )
            )
            match_id = outcome.result_refs[0].object_id
            match_ids.add(match_id)

            if self._snapshot_probe is not None and self._snapshot_probe(match_id):
                # 盘中赔率已动的重跑:保留首个 read_time 锚(判读时的价),可见跳过
                skipped.append(f"{request.issue}-{row.match_no}:first_anchor_kept")
                continue

            as_of = request.requested_at.astimezone(UTC).isoformat()
            try:
                outcome = self._market_actions.build_snapshot(
                    SnapshotBuildRequest(
                        match_id=match_id,
                        market_definition_id=_HAD,
                        snapshot_kind=request.snapshot_kind,
                        as_of=as_of,
                        provider="zucai",
                        quotes=[
                            QuoteInput(_HAD, f"sel-had-{key}", float(odds[key]))
                            for key in _OUTCOMES
                        ],
                        actor_id=request.actor_id,
                        # 与 market_day 同一治理约定:快照是确定性算术产物,
                        # 由 deterministic_system 执行(connector 无此授权)。
                        actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                        idempotency_key=(
                            f"zucai:snapshot:{request.issue}:{row.match_no}"
                            f":{request.snapshot_kind}:{as_of}"
                        ),
                        requested_at=request.requested_at,
                    )
                )
            except IdempotencyConflictError:
                skipped.append(f"{request.issue}-{row.match_no}:snapshot_key_conflict")
                continue
            if outcome.status is ActionStatus.COMMITTED:
                snapshots += 1
            else:
                # 拒绝/失败不是入库(26110-26111 曾把 rejected 计成 14 Snapshot)
                code = f":{outcome.error_code}" if outcome.error_code else ""
                skipped.append(
                    f"{request.issue}-{row.match_no}"
                    f":snapshot_{outcome.status.value}{code}"
                )

        return ZucaiIssueIngestResult(
            matches=len(match_ids),
            snapshots=snapshots,
            teams=len(team_ids),
            skipped=tuple(skipped),
        )

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
