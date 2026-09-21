"""Frozen structural-candidate input boundary for shadow discovery."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from dataclasses import replace as dataclass_replace
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import create_engine, select

from nutmeg.ontology.discovery.models import canonical_hash
from nutmeg.ontology.repository import schema_decision
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.product.operator_candidates import CandidateGenerationInput


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


def read_structural_input(
    uow: OntologyUnitOfWork,
    generation_request_id: str,
    *,
    cutoff_at: str,
    source_identity: str | None = None,
) -> StructuralInputSnapshot:
    """Read an existing request and verify each source before freezing the snapshot."""
    from nutmeg.product import operator_workers as worker

    generation = uow.operator_decision.candidate_generation_request(generation_request_id)
    if generation is None:
        raise ValueError("candidate generation request is missing")
    requested = datetime.fromisoformat(generation.requested_at)
    cutoff = datetime.fromisoformat(cutoff_at)
    if (
        requested.tzinfo is None
        or cutoff.tzinfo is None
        or requested > cutoff
    ):
        raise ValueError("candidate request exceeds cutoff")
    slate = uow.operator_sale.slate_revision(generation.slate_revision_id)
    prescription = uow.operator_decision.judgment_prescription_revision(
        generation.judgment_prescription_revision_id
    )
    if slate is None or prescription is None:
        raise ValueError("board or committed prescription is missing")
    if (
        prescription.slate_revision_id != generation.slate_revision_id
        or prescription.task_snapshot_hash != generation.task_snapshot_hash
    ):
        raise ValueError("prescription does not match board request")
    candidate_set = uow.operator_result.candidate_set_for_request(
        generation_request_id=generation_request_id, set_kind="judgment_bound"
    )
    if (
        candidate_set is None
        or not candidate_set.audit_policy_version
        or candidate_set.audit_policy_version != worker._CANDIDATE_AUDIT_POLICY_VERSION
    ):
        raise ValueError("registered candidate audit policy is missing or stale")
    if (
        candidate_set.slate_revision_id != generation.slate_revision_id
        or candidate_set.task_snapshot_hash != generation.task_snapshot_hash
    ):
        raise ValueError("candidate set does not belong to frozen request")
    candidate_input, _conditional, audit_offers, _conditional_audit = (
        worker._candidate_generation_inputs(uow, generation)
    )
    references = [
        {
            "kind": "candidate_set",
            "id": candidate_set.candidate_set_revision_id,
            "source_revision": candidate_set.content_hash,
            "captured_at": candidate_set.created_at,
        },
        {
            "kind": "prescription",
            "id": prescription.judgment_prescription_revision_id,
            "source_revision": prescription.content_hash,
            "captured_at": prescription.created_at,
        }
    ]
    for item in uow.operator_decision.judgment_prescription_items(
        generation.judgment_prescription_revision_id
    ):
        judgment = uow.operator_decision.operator_match_judgment_revision(
            item.operator_match_judgment_revision_id
        )
        if judgment is None:
            raise ValueError("committed forecast judgment is missing")
        forecast = (
            uow.connection.execute(
                select(schema_decision.forecast_revisions).where(
                    schema_decision.forecast_revisions.c.forecast_revision_id
                    == judgment.forecast_revision_id
                )
            )
            .mappings()
            .first()
        )
        if forecast is None or forecast["status"] != "committed":
            raise ValueError("committed forecast is missing")
        references.append(
            {
                "kind": "forecast",
                "id": forecast["forecast_revision_id"],
                "source_revision": str(forecast["revision_no"]),
                "captured_at": forecast["made_at"],
            }
        )
    for offer in candidate_input.offers:
        for _face, quote_id in offer.quote_ids_by_face:
            market_quote = uow.market.quote(quote_id)
            if market_quote is None or market_quote.quote_status != "active":
                raise ValueError("candidate quote is missing or stale")
            references.append(
                {
                    "kind": "quote",
                    "id": market_quote.quote_id,
                    "source_revision": market_quote.quote_id,
                    "captured_at": market_quote.captured_at,
                }
            )
    return freeze_structural_input(
        candidate_input=candidate_input,
        references=tuple(references),
        business_date=slate.business_key,
        task_snapshot_hash=generation.task_snapshot_hash,
        slate_revision_id=generation.slate_revision_id,
        board_slate_revision_id=prescription.slate_revision_id,
        cutoff_at=cutoff_at,
        audit_policy_revision=worker._CANDIDATE_AUDIT_POLICY_VERSION,
        audit_offers=audit_offers,
        source_identity=source_identity,
    )


def read_structural_input_from_database(
    database: Path, generation_request_id: str, *, cutoff_at: str
) -> StructuralInputSnapshot:
    """The source database is opened query-only, without initialization or migration."""
    if not database.is_file():
        raise ValueError("source database does not exist")
    uri = f"file:{quote(str(database.resolve()), safe='/')}?mode=ro"

    def connect():
        connection = sqlite3.connect(uri, uri=True)
        connection.execute("PRAGMA query_only=ON")
        return connection

    engine = create_engine("sqlite+pysqlite://", creator=connect)
    try:
        with OntologyUnitOfWork(engine) as uow:
            return read_structural_input(
                uow,
                generation_request_id,
                cutoff_at=cutoff_at,
                source_identity=str(database.resolve()),
            )
    finally:
        engine.dispose()
