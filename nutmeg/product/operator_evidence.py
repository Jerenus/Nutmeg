"""Deterministic E1-E6b/EC evidence policy for operator task snapshots."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Literal

from sqlalchemy import func, select

from nutmeg.ontology.actions.models import canonical_json
from nutmeg.ontology.repository import schema_identity
from nutmeg.product.operator_lanes import JczqLaneAdapter, ZucaiLaneAdapter

if TYPE_CHECKING:
    from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
    from nutmeg.product.repository import ProductReadRepository

RequirementId = Literal["E1", "E2", "E3", "E4", "E5", "E6a", "E6b", "EC"]
_REQUIREMENT_IDS: tuple[RequirementId, ...] = (
    "E1",
    "E2",
    "E3",
    "E4",
    "E5",
    "E6a",
    "E6b",
    "EC",
)


class EvidenceState(StrEnum):
    COMPLETE = "complete"
    MISSING = "missing"
    STALE = "stale"
    CONFLICT = "conflict"


class EvidenceObservationKind(StrEnum):
    PERSON_AVAILABILITY = "person_availability"
    AVAILABILITY_CLEAR = "availability_clear"
    RECENT_FORM = "recent_form"
    STRUCTURAL_CONTEXT = "structural_context"


class EvidenceClaimKind(StrEnum):
    AVAILABILITY = "availability"
    STRUCTURAL_CONTEXT = "structural_context"


@dataclass(frozen=True, slots=True)
class IdentityEvidence:
    match_revision_ref_token: str | None
    match_revision_current: bool
    team_ids: tuple[str, ...]
    team_resolution_states: tuple[str, ...]
    unresolved_alias_ref_tokens: tuple[str, ...]
    ambiguous_alias_ref_tokens: tuple[str, ...]
    merged_away_ref_tokens: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OfficialOfferEvidence:
    ref_token: str
    current: bool
    source_official: bool
    valid_from: datetime
    valid_to: datetime | None
    competition_revision_id: str | None
    official_match_no: str | None
    kickoff_at: datetime | None
    sale_deadline_at: datetime | None
    market_definition_ids: tuple[str, ...]
    source_status: str = "on_sale"

    def __post_init__(self) -> None:
        _aware(self.valid_from, "offer valid_from")
        if self.valid_to is not None:
            _aware(self.valid_to, "offer valid_to")
        if self.kickoff_at is not None:
            _aware(self.kickoff_at, "offer kickoff_at")
        if self.sale_deadline_at is not None:
            _aware(self.sale_deadline_at, "offer sale_deadline_at")


@dataclass(frozen=True, slots=True)
class MarketEvidence:
    ref_token: str
    market_definition_id: str
    source_kind: Literal["sporttery_official", "international_market"]
    observed_at: datetime
    resolved_identity: bool

    def __post_init__(self) -> None:
        _aware(self.observed_at, "market observed_at")


@dataclass(frozen=True, slots=True)
class ObservationEvidence:
    ref_token: str
    kind: EvidenceObservationKind
    team_id: str
    observed_at: datetime
    valid_from: datetime
    valid_to: datetime | None
    verification_method: str
    source_kinds: tuple[str, ...]
    authoritative_sample_ref_tokens: tuple[str, ...]
    value_fingerprint: str
    conflict_scope: str | None = None
    adjudication_ref_tokens: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _aware(self.observed_at, "observation observed_at")
        _aware(self.valid_from, "observation valid_from")
        if self.valid_to is not None:
            _aware(self.valid_to, "observation valid_to")


@dataclass(frozen=True, slots=True)
class ClaimEvidence:
    ref_token: str
    kind: EvidenceClaimKind
    team_id: str
    predicate: str
    conflict_scope: str
    value_fingerprint: str
    status: str
    valid_from: datetime
    valid_to: datetime | None
    source_kinds: tuple[str, ...]
    observed_at: datetime
    source_retrieval_ids: tuple[str, ...] = ()
    source_identity_tokens: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.conflict_scope.strip():
            raise ValueError("claim conflict_scope is required")
        _aware(self.valid_from, "claim valid_from")
        if self.valid_to is not None:
            _aware(self.valid_to, "claim valid_to")
        _aware(self.observed_at, "claim observed_at")


@dataclass(frozen=True, slots=True)
class EvidenceCoverage:
    requirement_id: RequirementId
    subject_scope: str
    evidence_ref_tokens: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MatchEvidenceSnapshot:
    match_id: str
    official_match_no: str
    required_for_evidence: bool
    identity: IdentityEvidence
    offer: OfficialOfferEvidence | None
    required_market_definition_ids: tuple[str, ...]
    markets: tuple[MarketEvidence, ...]
    observations: tuple[ObservationEvidence, ...]
    claims: tuple[ClaimEvidence, ...]
    coverage_ref_tokens: tuple[str, ...] = ()
    coverage: tuple[EvidenceCoverage, ...] | None = None


@dataclass(frozen=True, slots=True)
class TaskEvidenceSnapshot:
    lane: Literal["jczq", "zucai"]
    matches: tuple[MatchEvidenceSnapshot, ...]


@dataclass(frozen=True, slots=True)
class RequirementStatus:
    requirement_id: RequirementId
    state: EvidenceState
    evidence_ref_tokens: tuple[str, ...] = ()
    missing_ref_tokens: tuple[str, ...] = ()
    stale_ref_tokens: tuple[str, ...] = ()
    conflict_ref_tokens: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MatchEvidenceStatus:
    match_id: str
    complete: bool
    requirements: tuple[RequirementStatus, ...]


@dataclass(frozen=True, slots=True)
class TaskEvidenceStatus:
    ready: bool
    complete_match_count: int
    required_match_count: int
    matches: tuple[MatchEvidenceStatus, ...]


class OperatorEvidenceService:
    """Load strict ontology evidence into typed snapshots before evaluation."""

    def __init__(
        self,
        *,
        repository: ProductReadRepository,
        unit_of_work_factory: Callable[[], OntologyUnitOfWork],
    ) -> None:
        self._repository = repository
        self._unit_of_work_factory = unit_of_work_factory

    def load_task_snapshot(
        self,
        *,
        lane: Literal["jczq", "zucai"],
        business_key: str,
        as_of: datetime,
    ) -> TaskEvidenceSnapshot:
        _aware(as_of, "as_of")
        slate = next(
            (
                item
                for item in self._repository.operator_sale_slates(
                    as_of=as_of.isoformat()
                )
                if item.lane.value == lane and item.business_key == business_key
            ),
            None,
        )
        if slate is None:
            raise ValueError("operator evidence task has no current official slate")
        adapter = JczqLaneAdapter() if lane == "jczq" else ZucaiLaneAdapter()
        required_offer_ids = set(adapter.evidence_offer_ids(slate, as_of))
        matches = tuple(
            self._load_match_snapshot(
                offer=offer,
                required=offer.official_offer_revision_id in required_offer_ids,
                as_of=as_of,
                source_official=slate.source_official,
            )
            for offer in slate.offers
        )
        return TaskEvidenceSnapshot(lane=lane, matches=matches)

    def evaluate_task(
        self,
        *,
        lane: Literal["jczq", "zucai"],
        business_key: str,
        as_of: datetime,
    ) -> TaskEvidenceStatus:
        snapshot = self.load_task_snapshot(
            lane=lane,
            business_key=business_key,
            as_of=as_of,
        )
        cutoff = as_of if lane == "jczq" else _zucai_issue_cutoff(snapshot)
        return evaluate_task_evidence(snapshot, cutoff=cutoff)

    def _load_match_snapshot(
        self,
        *,
        offer,
        required: bool,
        as_of: datetime,
        source_official: bool,
    ):
        record = self._repository.match(offer.match_id, as_of.isoformat())
        team_ids = () if record is None else (
            str(record["home_team_id"]),
            str(record["away_team_id"]),
        )
        team_states = () if record is None else (
            str(record["home_resolution_status"]),
            str(record["away_resolution_status"]),
        )
        unresolved_aliases, ambiguous_aliases, merged_aliases = (
            self._load_identity_alias_issues(team_ids, as_of)
        )
        identity = IdentityEvidence(
            match_revision_ref_token=(
                None if record is None else str(record["match_revision_id"])
            ),
            match_revision_current=record is not None,
            team_ids=team_ids,
            team_resolution_states=team_states,
            unresolved_alias_ref_tokens=unresolved_aliases,
            ambiguous_alias_ref_tokens=ambiguous_aliases,
            merged_away_ref_tokens=tuple(sorted({
                *merged_aliases,
                *(
                    team_id
                    for team_id, state in zip(team_ids, team_states, strict=True)
                    if state == "merged"
                ),
            })),
        )
        official_offer = OfficialOfferEvidence(
            ref_token=offer.official_offer_revision_id,
            current=True,
            source_official=source_official,
            valid_from=offer.sale_opens_at,
            valid_to=offer.sale_deadline_at,
            competition_revision_id=(
                None if record is None else record.get("competition_edition_id")
            ),
            official_match_no=offer.official_match_no,
            kickoff_at=(
                None
                if record is None or record.get("scheduled_at") is None
                else datetime.fromisoformat(str(record["scheduled_at"]))
            ),
            sale_deadline_at=offer.sale_deadline_at,
            market_definition_ids=offer.market_definition_ids,
            source_status=offer.source_status,
        )
        metadata, coverage = self._intake_metadata(offer.match_id, as_of)
        coverage_ref_tokens = tuple(
            sorted(
                {
                    ref
                    for receipt in coverage
                    for ref in receipt.evidence_ref_tokens
                }
            )
        )
        return MatchEvidenceSnapshot(
            match_id=offer.match_id,
            official_match_no=offer.official_match_no,
            required_for_evidence=required,
            identity=identity,
            offer=official_offer,
            required_market_definition_ids=offer.market_definition_ids,
            markets=self._load_markets(offer.match_id, offer.market_definition_ids, as_of),
            observations=self._load_observations(offer.match_id, metadata, as_of),
            claims=self._load_claims(offer.match_id, metadata, as_of),
            coverage_ref_tokens=coverage_ref_tokens,
            coverage=coverage,
        )

    def _load_identity_alias_issues(
        self,
        team_ids: tuple[str, ...],
        as_of: datetime,
    ) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        if not team_ids:
            return (), (), ()
        with self._unit_of_work_factory() as uow:
            merge_rows = uow.connection.execute(
                select(
                    schema_identity.entity_merges.c.from_id,
                    schema_identity.entity_merges.c.into_id,
                ).where(
                    schema_identity.entity_merges.c.entity_type == "team",
                    func.julianday(schema_identity.entity_merges.c.at)
                    <= func.julianday(as_of.isoformat()),
                )
            ).all()
            redirects = {str(row.from_id): str(row.into_id) for row in merge_rows}

            def redirect(team_id: str) -> str:
                current = team_id
                seen = {current}
                while current in redirects and redirects[current] not in seen:
                    current = redirects[current]
                    seen.add(current)
                return current

            relevant_ids = {
                *team_ids,
                *(
                    source_id
                    for source_id in redirects
                    if redirect(source_id) in team_ids
                ),
            }
            relevant_alias_rows = uow.connection.execute(
                select(
                    schema_identity.entity_aliases.c.entity_id,
                    schema_identity.entity_aliases.c.normalized_alias,
                ).where(
                    schema_identity.entity_aliases.c.entity_type == "team",
                    schema_identity.entity_aliases.c.entity_id.in_(relevant_ids),
                )
            ).all()
            alias_names = {str(row.normalized_alias) for row in relevant_alias_rows}
            all_alias_rows = (
                uow.connection.execute(
                    select(
                        schema_identity.entity_aliases.c.entity_id,
                        schema_identity.entity_aliases.c.normalized_alias,
                    ).where(
                        schema_identity.entity_aliases.c.entity_type == "team",
                        schema_identity.entity_aliases.c.normalized_alias.in_(alias_names),
                    )
                ).all()
                if alias_names
                else ()
            )
            entity_ids = {str(row.entity_id) for row in relevant_alias_rows}
            statuses = {
                str(row.team_id): str(row.resolution_status)
                for row in uow.connection.execute(
                    select(
                        schema_identity.teams.c.team_id,
                        schema_identity.teams.c.resolution_status,
                    ).where(schema_identity.teams.c.team_id.in_(entity_ids))
                ).all()
            }

        def token(alias: str) -> str:
            return f"alias:team:{alias}"
        unresolved = {
            token(str(row.normalized_alias))
            for row in relevant_alias_rows
            if str(row.entity_id) in team_ids
            and statuses.get(str(row.entity_id)) not in {"resolved", "merged"}
        }
        merged = {
            token(str(row.normalized_alias))
            for row in relevant_alias_rows
            if statuses.get(str(row.entity_id)) == "merged"
            or (
                str(row.entity_id) not in team_ids
                and redirect(str(row.entity_id)) in team_ids
            )
        }
        direct_aliases = {
            str(row.normalized_alias)
            for row in relevant_alias_rows
            if str(row.entity_id) in team_ids
        }
        targets_by_alias: dict[str, set[str]] = {}
        for row in all_alias_rows:
            alias = str(row.normalized_alias)
            targets_by_alias.setdefault(alias, set()).add(redirect(str(row.entity_id)))
        ambiguous = {
            token(alias)
            for alias in direct_aliases
            if len(targets_by_alias.get(alias, ())) > 1
        }
        return tuple(sorted(unresolved)), tuple(sorted(ambiguous)), tuple(sorted(merged))

    def _intake_metadata(self, match_id: str, as_of: datetime):
        with self._unit_of_work_factory() as uow:
            rows = uow.operator_decision.evidence_intake_objects_for_match(
                match_id,
                as_of=as_of.isoformat(),
            )
            coverage_rows = uow.operator_decision.evidence_coverage_receipts_for_match(
                match_id,
                as_of=as_of.isoformat(),
            )
            coverage = tuple(
                EvidenceCoverage(
                    requirement_id=row.requirement_id,
                    subject_scope=row.subject_scope,
                    evidence_ref_tokens=row.evidence_ref_tokens,
                )
                for row in coverage_rows
            )
            metadata = {row.object_id: row for row in rows}
            missing_refs = tuple(
                sorted(
                    {
                        token
                        for receipt in coverage
                        for token in receipt.evidence_ref_tokens
                        if token not in metadata
                    }
                )
            )
            for row in uow.operator_decision.evidence_lineage_for_refs(
                match_id,
                missing_refs,
                as_of=as_of.isoformat(),
            ):
                metadata[row.object_id] = row
        return metadata, coverage

    def _load_markets(
        self,
        match_id: str,
        market_definition_ids: tuple[str, ...],
        as_of: datetime,
    ) -> tuple[MarketEvidence, ...]:
        facts: list[MarketEvidence] = []
        for market_id in market_definition_ids:
            for record in self._repository.market_timeline(
                match_id,
                market_id,
                as_of.isoformat(),
            ):
                for source_kind in _market_source_kinds(record):
                    facts.append(
                        MarketEvidence(
                            ref_token=str(record["market_snapshot_id"]),
                            market_definition_id=market_id,
                            source_kind=source_kind,
                            observed_at=datetime.fromisoformat(str(record["as_of"])),
                            resolved_identity=True,
                        )
                    )
        return tuple(sorted(facts, key=lambda item: item.ref_token))

    def _load_observations(self, match_id: str, metadata, as_of: datetime):
        kinds = {
            "person_availability_v1": EvidenceObservationKind.PERSON_AVAILABILITY,
            "team_availability_clear_v1": EvidenceObservationKind.AVAILABILITY_CLEAR,
            "recent_form_v1": EvidenceObservationKind.RECENT_FORM,
            "structural_context_v1": EvidenceObservationKind.STRUCTURAL_CONTEXT,
        }
        facts: list[ObservationEvidence] = []
        for record in self._repository.observations_for_match(
            match_id,
            as_of.isoformat(),
        ):
            link = metadata.get(str(record["observation_id"]))
            kind = kinds.get(str(record["observation_type"]))
            value = record.get("value") or {}
            if link is None or kind is None or not isinstance(value, dict):
                continue
            facts.append(
                ObservationEvidence(
                    ref_token=str(record["observation_id"]),
                    kind=kind,
                    team_id=str(value.get("team_token", "")),
                    observed_at=datetime.fromisoformat(str(record["observed_at"])),
                    valid_from=datetime.fromisoformat(str(record["valid_from"])),
                    valid_to=(
                        None
                        if record.get("valid_to") is None
                        else datetime.fromisoformat(str(record["valid_to"]))
                    ),
                    verification_method=str(record["verification_method"]),
                    source_kinds=link.source_kinds,
                    authoritative_sample_ref_tokens=tuple(
                        str(token) for token in value.get("sample_match_tokens", ())
                    ),
                    value_fingerprint=_semantic_value_fingerprint(value),
                    conflict_scope=_observation_conflict_scope(kind, value),
                    adjudication_ref_tokens=tuple(
                        str(token)
                        for token in record.get("adjudication_ref_tokens", ())
                    ),
                )
            )
        return tuple(facts)

    def _load_claims(self, match_id: str, metadata, as_of: datetime):
        kinds = {
            "availability_claim_v1": EvidenceClaimKind.AVAILABILITY,
            "structural_context_claim_v1": EvidenceClaimKind.STRUCTURAL_CONTEXT,
        }
        facts: list[ClaimEvidence] = []
        for record in self._repository.claims_for_match(match_id, as_of.isoformat()):
            link = metadata.get(str(record["claim_id"]))
            value = record.get("value") or {}
            kind = kinds.get(str(value.get("kind"))) if isinstance(value, dict) else None
            if link is None or kind is None:
                continue
            team_id = str(value.get("team_token", ""))
            conflict_scope = (
                f"person:{value.get('person_token', '')}:availability"
                if kind is EvidenceClaimKind.AVAILABILITY
                else f"team:{team_id}:structure:{value.get('context_kind', '')}"
            )
            facts.append(
                ClaimEvidence(
                    ref_token=str(record["claim_id"]),
                    kind=kind,
                    team_id=team_id,
                    predicate=str(record["predicate"]),
                    conflict_scope=conflict_scope,
                    value_fingerprint=_semantic_value_fingerprint(value),
                    status=str(record["status"]),
                    valid_from=datetime.fromisoformat(str(record["valid_from"])),
                    valid_to=(
                        None
                        if record.get("valid_to") is None
                        else datetime.fromisoformat(str(record["valid_to"]))
                    ),
                    source_kinds=link.source_kinds,
                    observed_at=datetime.fromisoformat(link.observed_at),
                    source_retrieval_ids=link.source_retrieval_ids,
                    source_identity_tokens=link.source_identities,
                )
            )
        return tuple(facts)


def _aware(value: datetime, name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _market_source_kinds(
    record: dict[str, object],
) -> tuple[Literal["sporttery_official", "international_market"], ...]:
    kinds: set[Literal["sporttery_official", "international_market"]] = set()
    lineage = record.get("quote_lineage")
    if not isinstance(lineage, list):
        return ()
    for source in lineage:
        if not isinstance(source, dict) or source.get("artifact_retrieval_id") is None:
            continue
        if source.get("retrieval_status") != "stored":
            continue
        if source.get("run_status") not in {None, "succeeded"}:
            continue
        provider = source.get("provider")
        source_name = source.get("source_name")
        if provider in {"sporttery", "zucai"} and source_name == provider:
            kinds.add("sporttery_official")
        elif provider == "intl" and source_name == provider:
            kinds.add("international_market")
    return tuple(sorted(kinds))


def _semantic_value_fingerprint(value: dict[str, object]) -> str:
    return canonical_json({key: item for key, item in value.items() if key != "kind"})


def _observation_conflict_scope(
    kind: EvidenceObservationKind,
    value: dict[str, object],
) -> str:
    team_id = str(value.get("team_token", ""))
    if kind is EvidenceObservationKind.PERSON_AVAILABILITY:
        return f"person:{value.get('person_token', '')}:availability"
    if kind is EvidenceObservationKind.AVAILABILITY_CLEAR:
        return f"team:{team_id}:availability_clear"
    if kind is EvidenceObservationKind.RECENT_FORM:
        return f"team:{team_id}:recent_form"
    return f"team:{team_id}:structure:{value.get('context_kind', '')}"


def _inside_interval(
    cutoff: datetime,
    valid_from: datetime,
    valid_to: datetime | None,
) -> bool:
    return valid_from <= cutoff and (valid_to is None or cutoff <= valid_to)


def _fresh(observed_at: datetime, cutoff: datetime, maximum_age: timedelta) -> bool:
    return observed_at <= cutoff and cutoff - observed_at <= maximum_age


def _zucai_issue_cutoff(snapshot: TaskEvidenceSnapshot) -> datetime:
    required = tuple(match for match in snapshot.matches if match.required_for_evidence)
    deadlines = tuple(
        match.offer.sale_deadline_at
        for match in required
        if match.offer is not None and match.offer.sale_deadline_at is not None
    )
    if len(deadlines) != len(required) or not deadlines:
        raise ValueError("required Zucai offer is missing its sale deadline")
    return min(deadlines)


def _complete(
    requirement_id: RequirementId,
    refs: tuple[str, ...] = (),
) -> RequirementStatus:
    return RequirementStatus(
        requirement_id=requirement_id,
        state=EvidenceState.COMPLETE,
        evidence_ref_tokens=tuple(sorted(set(refs))),
    )


def _blocked(
    requirement_id: RequirementId,
    *,
    missing: tuple[str, ...] = (),
    stale: tuple[str, ...] = (),
    conflict: tuple[str, ...] = (),
) -> RequirementStatus:
    if conflict:
        state = EvidenceState.CONFLICT
    elif missing:
        state = EvidenceState.MISSING
    else:
        state = EvidenceState.STALE
    return RequirementStatus(
        requirement_id=requirement_id,
        state=state,
        missing_ref_tokens=tuple(sorted(set(missing))),
        stale_ref_tokens=tuple(sorted(set(stale))),
        conflict_ref_tokens=tuple(sorted(set(conflict))),
    )


def _evaluate_identity(snapshot: MatchEvidenceSnapshot) -> RequirementStatus:
    identity = snapshot.identity
    missing: list[str] = []
    if not identity.match_revision_ref_token or not identity.match_revision_current:
        missing.append(f"match-current:{snapshot.match_id}")
    if len(identity.team_ids) != 2 or len(identity.team_resolution_states) != 2:
        missing.append(f"canonical-teams:{snapshot.match_id}")
    for index, state in enumerate(identity.team_resolution_states):
        if state != "resolved":
            token = identity.team_ids[index] if index < len(identity.team_ids) else str(index)
            missing.append(f"identity:{token}:{state}")
    missing.extend(identity.unresolved_alias_ref_tokens)
    missing.extend(identity.ambiguous_alias_ref_tokens)
    missing.extend(identity.merged_away_ref_tokens)
    if missing:
        return _blocked("E1", missing=tuple(missing))
    refs = (identity.match_revision_ref_token, *identity.team_ids)
    return _complete("E1", tuple(ref for ref in refs if ref is not None))


def _evaluate_offer(snapshot: MatchEvidenceSnapshot, cutoff: datetime) -> RequirementStatus:
    offer = snapshot.offer
    if offer is None:
        return _blocked("E2", missing=(f"official-offer:{snapshot.match_id}",))
    required_fields_present = (
        offer.competition_revision_id is not None
        and bool(offer.official_match_no)
        and offer.kickoff_at is not None
        and offer.sale_deadline_at is not None
        and bool(offer.market_definition_ids)
    )
    if not offer.current or not offer.source_official or not required_fields_present:
        return _blocked("E2", missing=(offer.ref_token,))
    if not _inside_interval(cutoff, offer.valid_from, offer.valid_to):
        return _blocked("E2", stale=(offer.ref_token,))
    return _complete("E2", (offer.ref_token,))


def _evaluate_markets(
    requirement_id: Literal["E3", "E4"],
    snapshot: MatchEvidenceSnapshot,
    cutoff: datetime,
) -> RequirementStatus:
    source_kind = (
        "sporttery_official" if requirement_id == "E3" else "international_market"
    )
    eligible = [
        fact
        for fact in snapshot.markets
        if fact.source_kind == source_kind and fact.resolved_identity
    ]
    if requirement_id == "E4":
        fresh = [
            fact
            for fact in eligible
            if _fresh(fact.observed_at, cutoff, timedelta(hours=6))
        ]
        if fresh:
            return _complete(
                "E4",
                (sorted(fresh, key=lambda item: item.ref_token)[0].ref_token,),
            )
        if eligible:
            return _blocked("E4", stale=tuple(fact.ref_token for fact in eligible))
        return _blocked("E4", missing=(f"international_market:{snapshot.match_id}",))

    refs: list[str] = []
    missing: list[str] = []
    stale: list[str] = []
    for market_id in snapshot.required_market_definition_ids:
        candidates = [fact for fact in eligible if fact.market_definition_id == market_id]
        fresh = [
            fact
            for fact in candidates
            if _fresh(fact.observed_at, cutoff, timedelta(hours=6))
        ]
        if fresh:
            refs.append(sorted(fresh, key=lambda item: item.ref_token)[0].ref_token)
        elif candidates:
            stale.extend(fact.ref_token for fact in candidates)
        else:
            missing.append(f"{source_kind}:{snapshot.match_id}:{market_id}")
    if missing or stale:
        return _blocked(requirement_id, missing=tuple(missing), stale=tuple(stale))
    return _complete(requirement_id, tuple(refs))


def _eligible_observation(
    fact: ObservationEvidence,
    cutoff: datetime,
    maximum_age: timedelta,
) -> bool:
    return _inside_interval(cutoff, fact.valid_from, fact.valid_to) and _fresh(
        fact.observed_at,
        cutoff,
        maximum_age,
    )


_OFFICIAL_SOURCE_KINDS = frozenset(
    {"sporttery_official", "club_official", "league_official"}
)


def _verified_observation(fact: ObservationEvidence) -> bool:
    if fact.verification_method == "official":
        return bool(_OFFICIAL_SOURCE_KINDS.intersection(fact.source_kinds))
    if fact.verification_method == "adjudicated":
        return bool(fact.adjudication_ref_tokens)
    return False


def _claim_fresh_and_valid(
    fact: ClaimEvidence,
    cutoff: datetime,
    maximum_age: timedelta,
) -> bool:
    if not _inside_interval(cutoff, fact.valid_from, fact.valid_to):
        return False
    return _fresh(fact.observed_at, cutoff, maximum_age)


def _evaluate_team_requirement(
    requirement_id: Literal["E5", "E6a", "E6b"],
    snapshot: MatchEvidenceSnapshot,
    cutoff: datetime,
) -> RequirementStatus:
    config = {
        "E5": (EvidenceObservationKind.AVAILABILITY_CLEAR, timedelta(hours=24)),
        "E6a": (EvidenceObservationKind.RECENT_FORM, timedelta(hours=72)),
        "E6b": (EvidenceObservationKind.STRUCTURAL_CONTEXT, timedelta(hours=72)),
    }
    expected_kind, maximum_age = config[requirement_id]
    refs: list[str] = []
    missing: list[str] = []
    stale: list[str] = []
    for team_id in snapshot.identity.team_ids:
        registered_refs = _registered_coverage_refs(snapshot, requirement_id, team_id)
        observations = [
            fact
            for fact in snapshot.observations
            if fact.team_id == team_id
            and (
                fact.kind is expected_kind
                or (
                    requirement_id == "E5"
                    and fact.kind is EvidenceObservationKind.PERSON_AVAILABILITY
                )
            )
            and (registered_refs is None or fact.ref_token in registered_refs)
        ]
        valid_observations = [
            fact
            for fact in observations
            if _eligible_observation(fact, cutoff, maximum_age)
            and (
                (
                    requirement_id == "E6a"
                    and fact.verification_method == "deterministic"
                    and bool(fact.authoritative_sample_ref_tokens)
                    and "authoritative_results" in fact.source_kinds
                )
                or (
                    requirement_id != "E6a"
                    and _verified_observation(fact)
                )
            )
        ]
        valid_claims: list[ClaimEvidence] = []
        if requirement_id in {"E5", "E6b"}:
            expected_claim_kind = (
                EvidenceClaimKind.AVAILABILITY
                if requirement_id == "E5"
                else EvidenceClaimKind.STRUCTURAL_CONTEXT
            )
            valid_claims = [
                fact
                for fact in snapshot.claims
                if fact.team_id == team_id
                and fact.kind is expected_claim_kind
                and (registered_refs is None or fact.ref_token in registered_refs)
                and fact.status in {"verified", "corroborated"}
                and len(set(fact.source_identity_tokens)) >= 2
                and _claim_fresh_and_valid(fact, cutoff, maximum_age)
            ]
        candidates: list[ObservationEvidence | ClaimEvidence] = [
            *valid_observations,
            *valid_claims,
        ]
        if candidates:
            refs.append(sorted(candidates, key=lambda item: item.ref_token)[0].ref_token)
        elif observations or any(
            fact.team_id == team_id
            and (registered_refs is None or fact.ref_token in registered_refs)
            for fact in snapshot.claims
        ):
            stale.extend(
                fact.ref_token
                for fact in (*observations, *snapshot.claims)
                if fact.team_id == team_id
            )
        else:
            missing.append(f"{requirement_id}:{snapshot.match_id}:{team_id}")
    if missing or stale:
        return _blocked(requirement_id, missing=tuple(missing), stale=tuple(stale))
    return _complete(requirement_id, tuple(refs))


def _registered_coverage_refs(
    snapshot: MatchEvidenceSnapshot,
    requirement_id: RequirementId,
    subject_scope: str,
) -> frozenset[str] | None:
    if snapshot.coverage is None:
        return None
    return frozenset(
        ref
        for receipt in snapshot.coverage
        if receipt.requirement_id == requirement_id and receipt.subject_scope == subject_scope
        for ref in receipt.evidence_ref_tokens
    )


def _evaluate_conflicts(
    snapshot: MatchEvidenceSnapshot,
    cutoff: datetime,
) -> RequirementStatus:
    groups: dict[str, list[ObservationEvidence | ClaimEvidence]] = {}
    for observation in snapshot.observations:
        if not _inside_interval(cutoff, observation.valid_from, observation.valid_to):
            continue
        if observation.observed_at > cutoff:
            continue
        scope = observation.conflict_scope or (
            f"team:{observation.team_id}:{observation.kind.value}"
        )
        groups.setdefault(scope, []).append(observation)
    for claim in snapshot.claims:
        if claim.status in {"retracted", "expired"}:
            continue
        if not _inside_interval(cutoff, claim.valid_from, claim.valid_to):
            continue
        groups.setdefault(claim.conflict_scope, []).append(claim)
    conflict_refs: list[str] = []
    for facts in groups.values():
        if len({_conflict_value(fact) for fact in facts}) > 1:
            conflict_refs.extend(fact.ref_token for fact in facts)
    conflict_refs.extend(_availability_clear_conflicts(snapshot, cutoff))
    if conflict_refs:
        return _blocked("EC", conflict=tuple(conflict_refs))
    return _complete("EC")


def _conflict_value(fact: ObservationEvidence | ClaimEvidence) -> str:
    """Discard collection lineage from facts that make the same semantic assertion."""
    try:
        value = json.loads(fact.value_fingerprint)
    except (TypeError, json.JSONDecodeError):
        return fact.value_fingerprint
    if not isinstance(value, dict):
        return fact.value_fingerprint
    if isinstance(fact, ObservationEvidence):
        if fact.kind is EvidenceObservationKind.AVAILABILITY_CLEAR:
            return "availability-clear"
        if fact.kind is EvidenceObservationKind.RECENT_FORM:
            keys = ("team_token", "wins", "draws", "losses", "goals_for", "goals_against")
            return canonical_json({key: value.get(key) for key in keys})
    return canonical_json(value)


def _availability_clear_conflicts(
    snapshot: MatchEvidenceSnapshot,
    cutoff: datetime,
) -> tuple[str, ...]:
    clears_by_team: dict[str, list[ObservationEvidence]] = {}
    negatives_by_team: dict[str, list[ObservationEvidence | ClaimEvidence]] = {}
    for observation in snapshot.observations:
        if not _inside_interval(cutoff, observation.valid_from, observation.valid_to):
            continue
        if observation.observed_at > cutoff:
            continue
        if observation.kind is EvidenceObservationKind.AVAILABILITY_CLEAR:
            clears_by_team.setdefault(observation.team_id, []).append(observation)
        elif observation.kind is EvidenceObservationKind.PERSON_AVAILABILITY and _is_unavailable(
            observation
        ):
            negatives_by_team.setdefault(observation.team_id, []).append(observation)
    for claim in snapshot.claims:
        if claim.status in {"retracted", "expired"}:
            continue
        if not _inside_interval(cutoff, claim.valid_from, claim.valid_to):
            continue
        if claim.kind is EvidenceClaimKind.AVAILABILITY and _is_unavailable(claim):
            negatives_by_team.setdefault(claim.team_id, []).append(claim)
    return tuple(
        sorted(
            {
                fact.ref_token
                for team_id, clears in clears_by_team.items()
                if team_id in negatives_by_team
                for fact in (*clears, *negatives_by_team[team_id])
            }
        )
    )


def _is_unavailable(fact: ObservationEvidence | ClaimEvidence) -> bool:
    try:
        value = json.loads(fact.value_fingerprint)
    except (TypeError, json.JSONDecodeError):
        unavailable_states = ("doubtful", "out", "suspended")
        return any(
            f":{status}:" in fact.value_fingerprint for status in unavailable_states
        )
    return isinstance(value, dict) and value.get("availability") in {
        "doubtful",
        "out",
        "suspended",
    }


def evaluate_requirement(
    requirement_id: RequirementId,
    snapshot: MatchEvidenceSnapshot,
    *,
    cutoff: datetime,
) -> RequirementStatus:
    """Evaluate one closed policy requirement with actionable diagnostics."""
    _aware(cutoff, "cutoff")
    if requirement_id == "E1":
        return _evaluate_identity(snapshot)
    if requirement_id == "E2":
        return _evaluate_offer(snapshot, cutoff)
    if requirement_id in {"E3", "E4"}:
        return _evaluate_markets(requirement_id, snapshot, cutoff)
    if requirement_id in {"E5", "E6a", "E6b"}:
        return _evaluate_team_requirement(requirement_id, snapshot, cutoff)
    if requirement_id == "EC":
        return _evaluate_conflicts(snapshot, cutoff)
    raise ValueError(f"unknown evidence requirement {requirement_id}")


def evaluate_match_requirements(
    snapshot: MatchEvidenceSnapshot,
    *,
    cutoff: datetime,
) -> dict[RequirementId, RequirementStatus]:
    """Evaluate the complete closed requirement set for one match."""
    return {
        requirement_id: evaluate_requirement(
            requirement_id,
            snapshot,
            cutoff=cutoff,
        )
        for requirement_id in _REQUIREMENT_IDS
    }


def evaluate_task_evidence(
    snapshot: TaskEvidenceSnapshot,
    *,
    cutoff: datetime,
) -> TaskEvidenceStatus:
    """Apply the whole-task gate to 14-leg Zucai or current-open JCZQ scope."""
    _aware(cutoff, "cutoff")
    required_matches = tuple(
        match
        for match in snapshot.matches
        if match.required_for_evidence
        and (
            snapshot.lane == "zucai"
            and match.offer is not None
            and match.offer.source_status != "cancelled"
            or (
                snapshot.lane == "jczq"
                and match.offer is not None
                and match.offer.current
                and match.offer.sale_deadline_at is not None
                and cutoff < match.offer.sale_deadline_at
            )
        )
    )
    match_statuses: list[MatchEvidenceStatus] = []
    for match in required_matches:
        match_cutoff = (
            match.offer.sale_deadline_at
            if snapshot.lane == "jczq" and match.offer is not None
            else cutoff
        )
        if match_cutoff is None:
            raise ValueError("required JCZQ offer is missing its sale deadline")
        statuses = evaluate_match_requirements(match, cutoff=match_cutoff)
        rows = tuple(statuses[requirement_id] for requirement_id in _REQUIREMENT_IDS)
        match_statuses.append(
            MatchEvidenceStatus(
                match_id=match.match_id,
                complete=all(row.state is EvidenceState.COMPLETE for row in rows),
                requirements=rows,
            )
    )
    complete_count = sum(status.complete for status in match_statuses)
    required_count = (
        14
        if snapshot.lane == "zucai" and len(snapshot.matches) != 14
        else len(required_matches)
    )
    normal_zucai_offer_count = snapshot.lane != "zucai" or len(snapshot.matches) == 14
    ready = (
        bool(required_count)
        and normal_zucai_offer_count
        and len(required_matches) == required_count
        and complete_count == required_count
    )
    return TaskEvidenceStatus(
        ready=ready,
        complete_match_count=complete_count,
        required_match_count=required_count,
        matches=tuple(match_statuses),
    )


__all__ = [
    "ClaimEvidence",
    "EvidenceCoverage",
    "EvidenceClaimKind",
    "EvidenceObservationKind",
    "EvidenceState",
    "IdentityEvidence",
    "MarketEvidence",
    "MatchEvidenceSnapshot",
    "MatchEvidenceStatus",
    "ObservationEvidence",
    "OfficialOfferEvidence",
    "RequirementStatus",
    "TaskEvidenceSnapshot",
    "TaskEvidenceStatus",
    "evaluate_match_requirements",
    "evaluate_requirement",
    "evaluate_task_evidence",
]
