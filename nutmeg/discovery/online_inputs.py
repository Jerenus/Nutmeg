"""Frozen structural-candidate input boundary for shadow discovery."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from dataclasses import replace as dataclass_replace
from datetime import datetime

from nutmeg.discovery.candidates import CandidateGenerationInput
from nutmeg.ontology.discovery.models import canonical_hash


@dataclass(frozen=True, slots=True)
class FrozenReference:
    kind: str
    id: str
    source_revision: str
    captured_at: str


@dataclass(frozen=True, slots=True)
class StructuralInputSnapshot:
    candidate_input: CandidateGenerationInput
    references: tuple[FrozenReference, ...]
    audit_offers: tuple[object, ...]
    business_date: str
    task_snapshot_hash: str
    slate_revision_id: str
    cutoff_at: str
    audit_policy_revision: str
    template_ids: tuple[str, ...]
    manifest_hash: str
    source_identity: str | None = None


def snapshot_payload(snapshot: StructuralInputSnapshot) -> dict[str, object]:
    audits = []
    for audit in snapshot.audit_offers:
        item = asdict(audit)
        item["prescribed_face_bundles"] = [
            sorted(bundle) for bundle in audit.prescribed_face_bundles
        ]
        audits.append(item)
    return {
        "candidate_input": asdict(snapshot.candidate_input),
        "references": [asdict(item) for item in snapshot.references],
        "audit_offers": audits,
        "business_date": snapshot.business_date,
        "task_snapshot_hash": snapshot.task_snapshot_hash,
        "slate_revision_id": snapshot.slate_revision_id,
        "cutoff_at": snapshot.cutoff_at,
        "audit_policy_revision": snapshot.audit_policy_revision,
        "template_ids": snapshot.template_ids,
        "source_identity": snapshot.source_identity,
    }


def freeze_structural_input(
    *,
    candidate_input: CandidateGenerationInput,
    references: tuple[dict[str, str], ...],
    business_date: str,
    task_snapshot_hash: str,
    slate_revision_id: str,
    board_slate_revision_id: str,
    cutoff_at: str,
    audit_policy_revision: str,
    audit_offers: tuple[object, ...] = (),
    source_identity: str | None = None,
) -> StructuralInputSnapshot:
    if not slate_revision_id or slate_revision_id != board_slate_revision_id:
        raise ValueError("candidate request does not belong to board")
    if not business_date or not task_snapshot_hash or not audit_policy_revision:
        raise ValueError("snapshot requires task and audit policy revision")
    cutoff = datetime.fromisoformat(cutoff_at)
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("cutoff must be timezone-aware")
    if candidate_input.lane != "jczq" or not candidate_input.templates:
        raise ValueError("structural pilot requires JCZQ templates")
    template_ids = tuple(template.structure_code for template in candidate_input.templates)
    if len(template_ids) != len(set(template_ids)):
        raise ValueError("duplicate template shard")

    frozen = []
    for reference in references:
        try:
            item = FrozenReference(**reference)
            captured = datetime.fromisoformat(item.captured_at)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("reference provenance is incomplete") from exc
        if not item.kind or not item.id or not item.source_revision:
            raise ValueError("reference provenance is incomplete")
        if captured.tzinfo is None or captured.utcoffset() is None:
            raise ValueError("reference provenance requires a timezone")
        if captured > cutoff:
            raise ValueError("reference exceeds cutoff")
        frozen.append(item)
    if not any(item.kind == "forecast" for item in frozen):
        raise ValueError("committed forecast reference is missing")
    if not any(item.kind == "prescription" for item in frozen):
        raise ValueError("committed prescription reference is missing")
    quotes = {item.id for item in frozen if item.kind == "quote"}
    required_quotes = {
        quote_id for offer in candidate_input.offers for _face, quote_id in offer.quote_ids_by_face
    }
    if not required_quotes.issubset(quotes):
        raise ValueError("candidate quote provenance is incomplete")

    frozen_refs = tuple(sorted(frozen, key=lambda item: (item.kind, item.id)))
    snapshot = StructuralInputSnapshot(
        candidate_input=candidate_input,
        references=frozen_refs,
        audit_offers=audit_offers,
        business_date=business_date,
        task_snapshot_hash=task_snapshot_hash,
        slate_revision_id=slate_revision_id,
        cutoff_at=cutoff_at,
        audit_policy_revision=audit_policy_revision,
        template_ids=template_ids,
        manifest_hash="",
        source_identity=source_identity,
    )
    return dataclass_replace(snapshot, manifest_hash=canonical_hash(snapshot_payload(snapshot)))
