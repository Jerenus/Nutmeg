"""Candidate audit policy for the structural discovery pilot.

Moved verbatim from ``nutmeg.product.operator_workers`` on 2026-09-23: the
audit policy version, the supported settlement markets, the operator-registered
audit offer, the canonical digest, and ``_audit_candidate`` itself.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal

from nutmeg.decision.legs_audit import Leg, audit_legs
from nutmeg.discovery.candidates import CandidateAuditFinding, CandidateDraft
from nutmeg.ontology.actions.models import canonical_json

_CANDIDATE_AUDIT_POLICY_VERSION = "operator-candidate-audit-v1"
_SUPPORTED_SETTLEMENT_MARKETS = {
    "jczq": frozenset({"md-had", "md-hhad", "md-ttg", "md-crs"}),
    "zucai": frozenset({"md-had"}),
}


@dataclass(frozen=True, slots=True)
class _CandidateAuditOffer:
    official_match_no: str
    market_definition_id: str
    belief: tuple[tuple[str, str], ...]
    prior: tuple[tuple[str, str], ...]
    prescribed_face_bundles: tuple[frozenset[str], ...]
    rule_ids: tuple[str, ...]
    # 操作员登记的结构事实。C5/C7/C13/C14 只读这两项；缺省的 "unknown"/() 不是
    # "没问题",而是"没登记"——昂贵排除因此仍然亮 WARN。
    anchor_integrity: str = "unknown"
    face_precedents: tuple[tuple[str, str, str], ...] = ()


def _digest(document: object) -> str:
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


def _audit_candidate(
    draft: CandidateDraft,
    *,
    lane: str,
    offers: tuple[_CandidateAuditOffer, ...],
    capital_cap_minor: int,
):
    by_match_no = {offer.official_match_no: offer for offer in offers}
    findings: list[CandidateAuditFinding] = []
    supported = _SUPPORTED_SETTLEMENT_MARKETS.get(lane, frozenset())
    unsupported = {
        (leg.official_match_no, leg.market_definition_id)
        for ticket in draft.tickets
        for leg in ticket.legs
        if leg.market_definition_id not in supported
    }
    findings.extend(
        CandidateAuditFinding(
            finding_id="unsupported-settlement-" + _digest([match_no, market_id]),
            code="unsupported_settlement_market",
            severity="ERROR",
            message=(
                f"{match_no} {market_id} has no registered deterministic settlement grader"
            ),
            audit_kind="deployment",
            official_match_no=match_no,
        )
        for match_no, market_id in sorted(unsupported)
    )
    if len(draft.tickets) > 1:
        ticket_legs = [
            {
                (leg.official_match_no, leg.market_definition_id): frozenset(
                    leg.selection_codes
                )
                for leg in ticket.legs
            }
            for ticket in draft.tickets
        ]
        common_keys = set.intersection(*(set(legs) for legs in ticket_legs))
        for match_no, market_id in sorted(common_keys):
            if market_id not in {"md-had", "md-hhad"}:
                continue
            covered = set().union(*(legs[(match_no, market_id)] for legs in ticket_legs))
            for dead_face in sorted({"3", "1", "0"} - covered):
                findings.append(
                    CandidateAuditFinding(
                        finding_id="cross-ticket-exposure-"
                        + _digest(
                            [
                                draft.composition_hash,
                                match_no,
                                market_id,
                                dead_face,
                            ]
                        ),
                        code="shared_dead_face_exposure",
                        severity="WARN",
                        message=(
                            f"all tickets share dead face {dead_face} at {match_no} "
                            f"{market_id}"
                        ),
                        audit_kind="deployment",
                        official_match_no=match_no,
                    )
                )
    if draft.stake_minor > capital_cap_minor:
        findings.append(
            CandidateAuditFinding(
                finding_id="candidate-budget-"
                + _digest(
                    [draft.composition_hash, draft.stake_minor, capital_cap_minor]
                ),
                code="capital_cap_exceeded",
                severity="ERROR",
                message=(
                    f"candidate stake {draft.stake_minor} exceeds capital cap "
                    f"{capital_cap_minor}"
                ),
                audit_kind="budget",
            )
        )
    for ticket in draft.tickets:
        ticket_legs = {leg.official_match_no: leg for leg in ticket.legs}
        for audit_offer in offers:
            leg = ticket_legs.get(audit_offer.official_match_no)
            candidate_faces = (
                frozenset() if leg is None else frozenset(leg.selection_codes)
            )
            if candidate_faces in audit_offer.prescribed_face_bundles:
                continue
            if not audit_offer.rule_ids:
                raise ValueError(
                    "candidate prescription deviation has no named Rule ID"
                )
            findings.append(
                CandidateAuditFinding(
                    finding_id="prescription-difference-"
                    + _digest(
                        [
                            ticket.composition_hash,
                            audit_offer.official_match_no,
                            sorted(candidate_faces),
                            audit_offer.rule_ids[0],
                        ]
                    ),
                    code="candidate_differs_from_prescription",
                    severity="WARN",
                    message=(
                        f"{audit_offer.official_match_no} candidate faces differ from "
                        "the committed prescription"
                    ),
                    audit_kind="prescription_difference",
                    official_match_no=audit_offer.official_match_no,
                    rule_id=audit_offer.rule_ids[0],
                )
            )
    for ticket in draft.tickets:
        audit_legs_input: list[Leg] = []
        official_numbers: list[str] = []
        for leg_index, ticket_leg in enumerate(ticket.legs):
            context = by_match_no.get(ticket_leg.official_match_no)
            if (
                context is None
                or context.market_definition_id not in {"md-had", "md-hhad"}
                or {face for face, _value in context.belief} != {"3", "1", "0"}
            ):
                continue
            belief = dict(context.belief)
            prior = dict(context.prior)
            audit_legs_input.append(
                Leg(
                    match_no=leg_index + 1,
                    name=f"场 {context.official_match_no}",
                    faces="".join(ticket_leg.selection_codes),
                    fair={
                        "home": float(Decimal(belief["3"])),
                        "draw": float(Decimal(belief["1"])),
                        "away": float(Decimal(belief["0"])),
                    },
                    confidence=5,
                    prior={
                        "home": float(Decimal(prior["3"])),
                        "draw": float(Decimal(prior["1"])),
                        "away": float(Decimal(prior["0"])),
                    },
                    anchor_integrity=context.anchor_integrity,
                    precedents=context.face_precedents,
                )
            )
            official_numbers.append(context.official_match_no)
        for finding in audit_legs(audit_legs_input):
            # INFO 是随票打印的参考表（对位机制 / 排面分级 / ttg 锚），不是治理级 finding：
            # 候选审计契约只登记 WARN 与 ERROR。把 INFO 也塞进去会让每一张带双选的候选
            # 都因"severity 未注册"而整条动作失败——参考信息不该有阻断能力。
            if finding.level == "INFO":
                continue
            official_match_no = (
                None
                if finding.match_no is None
                else official_numbers[finding.match_no - 1]
            )
            findings.append(
                CandidateAuditFinding(
                    finding_id="leg-audit-"
                    + _digest(
                        [
                            ticket.composition_hash,
                            finding.code,
                            official_match_no,
                            finding.message,
                        ]
                    ),
                    code=finding.code,
                    severity=finding.level,
                    message=finding.message,
                    audit_kind="legs",
                    official_match_no=official_match_no,
                )
            )
    return tuple(findings)
