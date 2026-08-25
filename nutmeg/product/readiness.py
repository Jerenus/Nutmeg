"""Pure readiness policy for product-visible next actions."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

from nutmeg.product.contracts import (
    EvidenceConflictSummary,
    ReadinessIssue,
    ReadinessLevel,
    ReadinessState,
)

_MAX_MARKET_AGE = timedelta(hours=6)
_HARD_ISSUES = {'identity_unresolved', 'market_anchor_missing'}


def evaluate_readiness(
    *,
    identity_resolved: bool,
    snapshot_at: datetime | None,
    as_of: datetime,
    evidence_count: int,
) -> ReadinessState:
    """Return every issue while applying deterministic severity precedence."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError('as_of must be timezone-aware')
    if snapshot_at is not None and (
        snapshot_at.tzinfo is None or snapshot_at.utcoffset() is None
    ):
        raise ValueError('snapshot_at must be timezone-aware')
    if evidence_count < 0:
        raise ValueError('evidence_count cannot be negative')

    issues: list[ReadinessIssue] = []
    if not identity_resolved:
        issues.append(
            ReadinessIssue(
                code='identity_unresolved',
                message='cross-source match identity is unresolved',
            )
        )
    if snapshot_at is None:
        issues.append(
            ReadinessIssue(
                code='market_anchor_missing',
                message='required market anchor is missing',
            )
        )
    elif as_of - snapshot_at > _MAX_MARKET_AGE:
        issues.append(
            ReadinessIssue(
                code='market_anchor_stale',
                message='market anchor is older than six hours',
                observed_at=snapshot_at,
            )
        )
    if evidence_count == 0:
        issues.append(
            ReadinessIssue(
                code='evidence_empty',
                message='no eligible evidence is available at this cutoff',
            )
        )

    if any(issue.code in _HARD_ISSUES for issue in issues):
        level = ReadinessLevel.BLOCKED
    elif issues:
        level = ReadinessLevel.DEGRADED
    else:
        level = ReadinessLevel.READY
    return ReadinessState(level=level, issues=issues)


def evaluate_forecast_readiness(
    base: ReadinessState,
    *,
    blocking_conflicts: int,
    provisional_conflicts: int = 0,
) -> ReadinessState:
    if blocking_conflicts < 0 or provisional_conflicts < 0:
        raise ValueError('conflict counts cannot be negative')

    issues = list(base.issues)
    if blocking_conflicts:
        issues.append(
            ReadinessIssue(
                code='source_conflict_unresolved',
                message=(
                    f'{blocking_conflicts} verified source conflict(s) '
                    'require adjudication'
                ),
            )
        )
        level = ReadinessLevel.BLOCKED
    elif provisional_conflicts:
        issues.append(
            ReadinessIssue(
                code='source_conflict_provisional',
                message=(
                    f'{provisional_conflicts} provisional source conflict(s) '
                    'remain visible'
                ),
            )
        )
        level = (
            ReadinessLevel.DEGRADED
            if base.level is ReadinessLevel.READY
            else base.level
        )
    else:
        level = base.level
    return ReadinessState(level=level, issues=issues)


def classify_claim_conflicts(claims: list[dict]) -> list[EvidenceConflictSummary]:
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
