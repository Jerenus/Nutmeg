"""Pure readiness policy for product-visible next actions."""
from __future__ import annotations

from datetime import datetime, timedelta

from nutmeg.product.contracts import ReadinessIssue, ReadinessLevel, ReadinessState

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
