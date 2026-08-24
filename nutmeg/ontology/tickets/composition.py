"""Thin adapter over Nutmeg's authoritative ticket and C0-C7 functions."""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from nutmeg.decision.express import compose_tickets, load_budget
from nutmeg.decision.legs_audit import audit_legs
from nutmeg.ontology.actions.models import canonical_json
from nutmeg.ontology.tickets.models import (
    AuditFindingRecord,
    BatchComposition,
    ComposedTicket,
    TicketLegDraft,
)


def canonical_bytes(value: object) -> bytes:
    return canonical_json(value).encode("utf-8")


def canonical_digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def compose_batch(
    legs: list[TicketLegDraft],
    *,
    channel: str,
    made_at: datetime,
    budget: dict[str, object] | None = None,
) -> BatchComposition:
    if made_at.tzinfo is None or made_at.utcoffset() is None:
        raise ValueError("made_at must be timezone-aware")
    if not channel.strip():
        raise ValueError("channel is required")

    summary = compose_tickets(
        [leg.express_dict() for leg in legs],
        budget or load_budget(),
        channel=channel,
        made_at=made_at.astimezone(UTC).isoformat(),
        store=None,
    )
    findings = audit_legs([leg.audit_leg() for leg in legs])
    return BatchComposition(
        channel=str(summary["channel"]),
        period_cap_yuan=(
            int(summary["period_cap_yuan"])
            if summary["period_cap_yuan"] is not None
            else None
        ),
        total_stake_yuan=int(summary["total_stake_yuan"]),
        scaled=bool(summary["scaled"]),
        tickets=tuple(_ticket(item) for item in summary["tickets"]),
        by_bucket={
            str(bucket): {str(key): int(value) for key, value in values.items()}
            for bucket, values in summary["by_bucket"].items()
        },
        findings=tuple(
            AuditFindingRecord(
                level=finding.level,
                code=finding.code,
                match_no=finding.match_no,
                message=finding.message,
                since=finding.since,
            )
            for finding in findings
        ),
    )


def _ticket(item: dict[str, object]) -> ComposedTicket:
    raw_legs = item.get("legs")
    if not isinstance(raw_legs, list):
        raise ValueError("composed ticket legs must be a list")
    return ComposedTicket(
        ticket_id=str(item["ticket_id"]),
        bucket=str(item["bucket"]),
        budget_bucket=str(item["budget_bucket"]),
        structure=str(item["structure"]),
        stake_yuan=int(item["stake_yuan"]),
        combined_odds=float(item["combined_odds"]),
        n_legs=int(item["n_legs"]),
        computed_hit_prob=(
            float(item["computed_hit_prob"])
            if item.get("computed_hit_prob") is not None
            else None
        ),
        legs=tuple({str(key): value for key, value in leg.items()} for leg in raw_legs),
    )
