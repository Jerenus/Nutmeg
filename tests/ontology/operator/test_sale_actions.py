from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import func, insert, select

from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.operator.sale_actions import (
    ImportOfficialSaleSlateRequest,
    OfficialOfferManifestV1,
    OfficialSaleSlateManifestV1,
    OfficialScheduleCheckManifestV1,
    RecordOfficialScheduleCheckRequest,
    SaleActions,
)
from nutmeg.ontology.repository import schema, schema_identity
from nutmeg.ontology.repository import schema_operator_sale as sos
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.operator_sale import OperatorSaleRepository
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

AT = datetime(2026, 9, 4, 0, 5, tzinfo=UTC)


def _seed_dependencies(engine) -> None:
    at = "2026-09-04T08:01:00+08:00"
    with engine.begin() as connection:
        connection.execute(
            insert(schema.source_runs).values(
                source_run_id="run-official",
                source_name="sporttery",
                source_type="official_schedule",
                started_at=at,
                finished_at=at,
                status="succeeded",
                error_code=None,
                error_detail=None,
            )
        )
        for suffix, source_name, source_type in (
            ("official", "sporttery", "official_sale_schedule"),
            ("unofficial", "api-football", "fixture"),
        ):
            connection.execute(
                insert(schema.source_artifacts).values(
                    artifact_id=f"artifact-{suffix}",
                    first_recorded_at=at,
                    content_type="application/json",
                    storage_path=f"sha256/{suffix}",
                    byte_size=2,
                    content_hash=("a" if suffix == "official" else "b") * 64,
                )
            )
            connection.execute(
                insert(schema.artifact_retrievals).values(
                    artifact_retrieval_id=f"retrieval-{suffix}",
                    artifact_id=f"artifact-{suffix}",
                    source_run_id="run-official",
                    source_name=source_name,
                    source_type=source_type,
                    reported_content_type="application/json",
                    canonical_url=(
                        f"https://www.sporttery.cn/{suffix}.json"
                        if suffix == "official"
                        else f"https://example.test/{suffix}.json"
                    ),
                    requested_url=(
                        f"https://www.sporttery.cn/{suffix}.json"
                        if suffix == "official"
                        else f"https://example.test/{suffix}.json"
                    ),
                    published_at=at,
                    retrieved_at=at,
                    status="stored",
                )
            )
        connection.execute(
            insert(schema_identity.matches),
            [
                {"match_id": f"match-{number}", "current_revision_id": None}
                for number in range(1, 15)
            ],
        )


def _setup(tmp_path: Path) -> tuple[SaleActions, object]:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    _seed_dependencies(engine)
    actions = SaleActions(ActionService(lambda: OntologyUnitOfWork(engine)))
    return actions, engine


def _add_official_retrieval(
    engine,
    retrieval_id: str,
    *,
    retrieved_at: str,
    hash_character: str,
) -> str:
    content_hash = hash_character * 64
    artifact_id = f"artifact-{retrieval_id}"
    with engine.begin() as connection:
        connection.execute(
            insert(schema.source_artifacts).values(
                artifact_id=artifact_id,
                first_recorded_at=retrieved_at,
                content_type="application/json",
                storage_path=f"sha256/{retrieval_id}",
                byte_size=2,
                content_hash=content_hash,
            )
        )
        connection.execute(
            insert(schema.artifact_retrievals).values(
                artifact_retrieval_id=retrieval_id,
                artifact_id=artifact_id,
                source_run_id="run-official",
                source_name="sporttery",
                source_type="official_sale_schedule",
                reported_content_type="application/json",
                canonical_url=f"https://www.sporttery.cn/{retrieval_id}.json",
                requested_url=f"https://www.sporttery.cn/{retrieval_id}.json",
                published_at="2026-09-04T08:00:00+08:00",
                retrieved_at=retrieved_at,
                status="stored",
            )
        )
    return content_hash


def _offer(number: int = 1, **changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "canonical_match_id": f"match-{number}",
        "official_match_no": f"周五{number:03d}",
        "market_definition_ids": ["md-had"],
        "sale_opens_at": "2026-09-04T08:00:00+08:00",
        "sale_deadline_at": "2026-09-04T19:00:00+08:00",
        "status": "on_sale",
    }
    value.update(changes)
    return value


def _manifest(**changes: object) -> OfficialSaleSlateManifestV1:
    value: dict[str, object] = {
        "schema_version": "official-sale-slate-v1",
        "lane": "jczq",
        "business_key": "2026-09-04",
        "published_at": "2026-09-04T08:00:00+08:00",
        "retrieved_at": "2026-09-04T08:01:00+08:00",
        "parser_contract_version": "sporttery-official-sale-parser-v1",
        "official_source_content_hash": "a" * 64,
        "official_source_artifact_retrieval_id": "retrieval-official",
        "supersedes_slate_revision_id": None,
        "offers": [_offer()],
    }
    value.update(changes)
    return OfficialSaleSlateManifestV1.model_validate(value)


def _request(
    manifest: OfficialSaleSlateManifestV1,
    *,
    key: str = "official-sale:1",
    role: ActorRole = ActorRole.DETERMINISTIC_SYSTEM,
) -> ImportOfficialSaleSlateRequest:
    return ImportOfficialSaleSlateRequest(
        manifest=manifest,
        actor_id="system:official-sale",
        actor_role=role,
        idempotency_key=key,
        requested_at=AT,
    )


@pytest.mark.parametrize(
    "mutation",
    (
        {"unexpected": True},
        {"published_at": "2026-09-04T08:00:00"},
        {"retrieved_at": "2026-09-04T08:01:00"},
        {"offers": [_offer(sale_deadline_at="2026-09-04T08:00:00+08:00")]},
        {"offers": [_offer(), _offer(2, official_match_no="周五001")]},
        {"offers": [_offer(), _offer(1, official_match_no="周五002")]},
        {"offers": [_offer(status="mystery")]},
    ),
)
def test_sale_manifest_is_closed_and_time_aware(mutation: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _manifest(**mutation)


def test_offer_manifest_rejects_unknown_fields_and_duplicate_markets() -> None:
    with pytest.raises(ValidationError):
        OfficialOfferManifestV1.model_validate({**_offer(), "odds": {"home": "2.0"}})
    with pytest.raises(ValidationError):
        OfficialOfferManifestV1.model_validate(_offer(market_definition_ids=["md-had", "md-had"]))


def test_sale_manifest_accepts_the_approved_minimal_v1_contract() -> None:
    document = {
        "schema_version": "official-sale-slate-v1",
        "lane": "jczq",
        "business_key": "2026-09-04",
        "published_at": "2026-09-04T08:00:00+08:00",
        "retrieved_at": "2026-09-04T08:01:00+08:00",
        "official_source_artifact_retrieval_id": "retrieval-official",
        "supersedes_slate_revision_id": None,
        "offers": [_offer()],
    }

    parsed = OfficialSaleSlateManifestV1.model_validate(document)

    assert parsed.official_source_artifact_retrieval_id == "retrieval-official"


@pytest.mark.parametrize(
    ("model", "document", "field"),
    (
        (
            OfficialOfferManifestV1,
            _offer(sale_opens_at=1_788_480_000),
            "sale_opens_at",
        ),
        (
            OfficialSaleSlateManifestV1,
            {
                "schema_version": "official-sale-slate-v1",
                "lane": "jczq",
                "business_key": "2026-09-04",
                "published_at": 1_788_480_000,
                "retrieved_at": "2026-09-04T08:01:00+08:00",
                "official_source_artifact_retrieval_id": "retrieval-official",
                "supersedes_slate_revision_id": None,
                "offers": [_offer()],
            },
            "published_at",
        ),
        (
            OfficialScheduleCheckManifestV1,
            {
                "schema_version": "official-schedule-check-v1",
                "lane": "jczq",
                "shanghai_check_date": "2026-09-04",
                "checked_at": 1_788_480_000,
                "source_run_id": "run-official",
                "check_state": "failed",
                "parser_contract_version": None,
                "official_source_content_hash": None,
                "official_source_artifact_retrieval_id": None,
                "observed_business_keys": [],
                "imported_business_keys": [],
                "error_code": "network_error",
            },
            "checked_at",
        ),
    ),
)
def test_manifest_datetimes_reject_numeric_epoch_values(model, document, field: str) -> None:
    with pytest.raises(ValidationError, match=field):
        model.model_validate(document)


def test_imports_jczq_slate_atomically_with_exact_counts(tmp_path: Path) -> None:
    actions, engine = _setup(tmp_path)
    manifest = _manifest(offers=[_offer(1), _offer(2)])

    result = actions.import_official_sale_slate(_request(manifest))

    assert result.outcome.status is ActionStatus.COMMITTED
    assert result.slate.lane == "jczq"
    assert result.slate.business_key == "2026-09-04"
    assert result.counts.slate_revision_count == 1
    assert result.counts.offer_family_count == 2
    assert result.counts.offer_revision_count == 2
    assert len(result.offers) == 2
    assert len(result.outcome.result_refs) == 4
    with engine.connect() as connection:
        assert (
            connection.scalar(select(func.count()).select_from(sos.official_sale_slate_revisions))
            == 1
        )
        assert connection.scalar(select(func.count()).select_from(sos.official_offer_families)) == 2
        assert (
            connection.scalar(select(func.count()).select_from(sos.official_offer_revisions)) == 2
        )


def test_nullable_manifest_fields_must_still_be_explicit() -> None:
    sale = {
        "schema_version": "official-sale-slate-v1",
        "lane": "jczq",
        "business_key": "2026-09-04",
        "published_at": "2026-09-04T08:00:00+08:00",
        "retrieved_at": "2026-09-04T08:01:00+08:00",
        "official_source_artifact_retrieval_id": "retrieval-official",
        "offers": [_offer()],
    }
    with pytest.raises(ValidationError, match="supersedes_slate_revision_id"):
        OfficialSaleSlateManifestV1.model_validate(sale)

    check = {
        "schema_version": "official-schedule-check-v1",
        "lane": "jczq",
        "shanghai_check_date": "2026-09-04",
        "checked_at": "2026-09-04T08:02:00+08:00",
        "check_state": "failed",
        "imported_business_keys": [],
        "error_code": "network_error",
    }
    with pytest.raises(ValidationError, match="source_run_id"):
        OfficialScheduleCheckManifestV1.model_validate(check)


def test_zucai_requires_exact_ordered_fourteen(tmp_path: Path) -> None:
    actions, _engine = _setup(tmp_path)
    offers = [
        _offer(number, official_match_no=str(number), market_definition_ids=["md-had"])
        for number in range(1, 15)
    ]

    result = actions.import_official_sale_slate(
        _request(
            _manifest(lane="zucai", business_key="26120", offers=offers),
            key="official-sale:zucai",
        )
    )

    assert result.outcome.status is ActionStatus.COMMITTED
    assert tuple(offer.official_match_no for offer in result.offers) == tuple(
        str(number) for number in range(1, 15)
    )


def test_sale_manifest_enforces_lane_business_key_and_market_contract() -> None:
    zucai_offers = [
        _offer(number, official_match_no=str(number), market_definition_ids=["md-had"])
        for number in range(1, 15)
    ]
    invalid_zucai_market = list(zucai_offers)
    invalid_zucai_market[-1] = _offer(
        14,
        official_match_no="14",
        market_definition_ids=["md-hhad"],
    )

    with pytest.raises(ValidationError, match="JCZQ business key"):
        _manifest(business_key="26120")
    with pytest.raises(ValidationError, match="Zucai business key"):
        _manifest(lane="zucai", business_key="2026-09-04", offers=zucai_offers)
    with pytest.raises(ValidationError, match="Zucai market"):
        _manifest(lane="zucai", business_key="26120", offers=invalid_zucai_market)
    with pytest.raises(ValidationError, match="fourteen"):
        _manifest(lane="zucai", business_key="26121", offers=zucai_offers[:-1])
    with pytest.raises(ValidationError, match="ordered"):
        _manifest(
            lane="zucai",
            business_key="26121",
            offers=[
                {**offer, "official_match_no": str(15 - index)}
                for index, offer in enumerate(zucai_offers)
            ],
        )


@pytest.mark.parametrize(
    ("label", "changes", "message"),
    (
        ("unresolved", {"offers": [_offer(canonical_match_id="match-missing")]}, "match"),
        ("market", {"offers": [_offer(market_definition_ids=["md-missing"])]}, "market"),
        (
            "source",
            {"official_source_artifact_retrieval_id": "retrieval-unofficial"},
            "official",
        ),
    ),
)
def test_import_rejects_invalid_references_without_partial_slate(
    tmp_path: Path,
    label: str,
    changes: dict[str, object],
    message: str,
) -> None:
    actions, engine = _setup(tmp_path)

    with pytest.raises(ValueError, match=message):
        actions.import_official_sale_slate(
            _request(_manifest(**changes), key=f"official-sale:invalid:{label}")
        )

    with engine.connect() as connection:
        assert (
            connection.scalar(select(func.count()).select_from(sos.official_sale_slate_revisions))
            == 0
        )
        assert connection.scalar(select(func.count()).select_from(sos.official_offer_families)) == 0
        assert (
            connection.scalar(select(func.count()).select_from(sos.official_offer_revisions)) == 0
        )


def test_import_rolls_back_if_a_later_offer_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actions, engine = _setup(tmp_path)
    original = OperatorSaleRepository.insert_offer_revision
    calls = 0

    def fail_second(repository, row):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected second-offer failure")
        return original(repository, row)

    monkeypatch.setattr(OperatorSaleRepository, "insert_offer_revision", fail_second)

    with pytest.raises(RuntimeError, match="second-offer"):
        actions.import_official_sale_slate(
            _request(
                _manifest(offers=[_offer(1), _offer(2)]),
                key="official-sale:mid-transaction-failure",
            )
        )

    with engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(sos.official_sale_slate_revisions)
        ) == 0
        assert connection.scalar(
            select(func.count()).select_from(sos.official_offer_families)
        ) == 0
        assert connection.scalar(
            select(func.count()).select_from(sos.official_offer_revisions)
        ) == 0
        failed = connection.execute(
            select(schema.actions.c.status, schema.actions.c.error_detail).where(
                schema.actions.c.action_type == "import_official_sale_slate"
            )
        ).one()
        assert failed.status == "failed"
        assert "second-offer" in failed.error_detail


def test_revision_preserves_families_and_requires_current_supersession(tmp_path: Path) -> None:
    actions, engine = _setup(tmp_path)
    first = actions.import_official_sale_slate(_request(_manifest(offers=[_offer(1), _offer(2)])))
    family_ids = {offer.official_match_no: offer.official_offer_family_id for offer in first.offers}
    second_hash = _add_official_retrieval(
        engine,
        "retrieval-official-revision-2",
        retrieved_at="2026-09-04T08:02:00+08:00",
        hash_character="c",
    )
    revision = _manifest(
        supersedes_slate_revision_id=first.slate.slate_revision_id,
        retrieved_at="2026-09-04T08:02:00+08:00",
        official_source_artifact_retrieval_id="retrieval-official-revision-2",
        official_source_content_hash=second_hash,
        offers=[_offer(1, status="sale_closed")],
    )

    second = actions.import_official_sale_slate(_request(revision, key="official-sale:revision:2"))

    assert second.slate.revision_no == 2
    assert second.offers[0].official_offer_family_id == family_ids["周五001"]
    assert second.counts.offer_family_count == 1
    assert second.counts.created_slate_revision_count == 1
    assert second.counts.created_offer_family_count == 0
    assert second.counts.created_offer_revision_count == 1
    with OntologyUnitOfWork(engine) as uow:
        assert uow.operator_sale.current_offer_by_family(family_ids["周五002"]) is None

    third_hash = _add_official_retrieval(
        engine,
        "retrieval-official-revision-3",
        retrieved_at="2026-09-04T08:03:00+08:00",
        hash_character="d",
    )
    bad = _manifest(
        retrieved_at="2026-09-04T08:03:00+08:00",
        official_source_artifact_retrieval_id="retrieval-official-revision-3",
        official_source_content_hash=third_hash,
        offers=[_offer(1, status="cancelled")],
    )
    with pytest.raises(ValueError, match="supersede"):
        actions.import_official_sale_slate(_request(bad, key="official-sale:bad-supersession"))


def test_same_business_content_retrieval_and_jczq_order_reuse_current_revision(
    tmp_path: Path,
) -> None:
    actions, engine = _setup(tmp_path)
    first = actions.import_official_sale_slate(
        _request(_manifest(offers=[_offer(1), _offer(2)]), key="official-sale:content:first")
    )
    with engine.begin() as connection:
        connection.execute(
            insert(schema.artifact_retrievals).values(
                artifact_retrieval_id="retrieval-official-2",
                artifact_id="artifact-official",
                source_run_id="run-official",
                source_name="sporttery",
                source_type="official_sale_schedule",
                reported_content_type="application/json",
                canonical_url="https://www.sporttery.cn/official-2.json",
                requested_url="https://www.sporttery.cn/official-2.json",
                published_at="2026-09-04T08:00:00+08:00",
                retrieved_at="2026-09-04T08:03:00+08:00",
                status="stored",
            )
        )
    repeated = _manifest(
        official_source_artifact_retrieval_id="retrieval-official-2",
        supersedes_slate_revision_id=first.slate.slate_revision_id,
        retrieved_at="2026-09-04T08:03:00+08:00",
        offers=[_offer(2), _offer(1)],
    )

    second = actions.import_official_sale_slate(
        _request(repeated, key="official-sale:content:second")
    )

    assert second.slate.slate_revision_id == first.slate.slate_revision_id
    assert second.slate.content_hash == first.slate.content_hash
    assert second.counts.created_slate_revision_count == 0
    assert second.counts.created_offer_family_count == 0
    assert second.counts.created_offer_revision_count == 0
    assert second.counts.offer_family_count == 2
    check = actions.record_official_schedule_check(
        _check_request(
                _check_manifest(
                    official_source_artifact_retrieval_id="retrieval-official-2",
                    checked_at="2026-09-04T08:04:00+08:00",
                ),
            key="official-check:content:second",
        )
    )
    assert check.status is ActionStatus.COMMITTED
    with engine.connect() as connection:
        assert (
            connection.scalar(select(func.count()).select_from(sos.official_sale_slate_revisions))
            == 1
        )


def test_same_idempotency_key_replays_same_import_without_duplicate_rows(tmp_path: Path) -> None:
    actions, engine = _setup(tmp_path)
    request = _request(_manifest())

    first = actions.import_official_sale_slate(request)
    replay = actions.import_official_sale_slate(request)

    assert replay == first
    with engine.connect() as connection:
        assert (
            connection.scalar(select(func.count()).select_from(sos.official_sale_slate_revisions))
            == 1
        )
        assert (
            connection.scalar(select(func.count()).select_from(sos.official_offer_revisions)) == 1
        )


def test_import_replay_reconciles_every_linked_count_with_persistence(tmp_path: Path) -> None:
    actions, engine = _setup(tmp_path)
    request = _request(_manifest(), key="official-sale:count-reconcile")
    first = actions.import_official_sale_slate(request)
    with engine.begin() as connection:
        refs = json.loads(
            connection.scalar(
                select(schema.actions.c.result_refs_json).where(
                    schema.actions.c.action_id == first.outcome.action_id
                )
            )
        )
        count_ref = next(
            ref for ref in refs if ref["object_type"] == "official_sale_import_count"
        )
        parts = count_ref["object_id"].rsplit(":", 6)
        parts[2] = "99"
        count_ref["object_id"] = ":".join(parts)
        connection.execute(
            schema.actions.update()
            .where(schema.actions.c.action_id == first.outcome.action_id)
            .values(result_refs_json=json.dumps(refs))
        )

    with pytest.raises(ValueError, match="reconciled"):
        actions.import_official_sale_slate(request)


def _check_manifest(**changes: object) -> OfficialScheduleCheckManifestV1:
    value: dict[str, object] = {
        "schema_version": "official-schedule-check-v1",
        "lane": "jczq",
        "shanghai_check_date": "2026-09-04",
        "checked_at": "2026-09-04T08:02:00+08:00",
        "source_run_id": "run-official",
        "check_state": "slate_imported",
        "parser_contract_version": "sporttery-official-sale-parser-v1",
        "official_source_content_hash": "a" * 64,
        "official_source_artifact_retrieval_id": "retrieval-official",
        "observed_business_keys": ["2026-09-04"],
        "imported_business_keys": ["2026-09-04"],
        "error_code": None,
    }
    value.update(changes)
    return OfficialScheduleCheckManifestV1.model_validate(value)


def _check_request(
    manifest: OfficialScheduleCheckManifestV1,
    *,
    key: str = "official-schedule-check:1",
    role: ActorRole = ActorRole.DETERMINISTIC_SYSTEM,
    requested_at: datetime = AT,
) -> RecordOfficialScheduleCheckRequest:
    return RecordOfficialScheduleCheckRequest(
        manifest=manifest,
        actor_id="system:official-sale",
        actor_role=role,
        idempotency_key=key,
        requested_at=requested_at,
    )


@pytest.mark.parametrize(
    "changes",
    (
        {"unexpected": True},
        {"checked_at": "2026-09-04T08:02:00"},
        {"checked_at": "2026-09-04T16:02:00+00:00"},
        {"check_state": "slate_imported", "imported_business_keys": []},
        {"check_state": "slate_imported", "source_run_id": None},
        {"check_state": "confirmed_no_sale", "imported_business_keys": ["26120"]},
        {"check_state": "confirmed_no_sale", "source_run_id": None},
        {"check_state": "confirmed_no_sale", "official_source_artifact_retrieval_id": None},
        {"check_state": "failed", "error_code": None},
        {
            "check_state": "failed",
            "error_code": "made_up_error",
            "official_source_artifact_retrieval_id": None,
            "imported_business_keys": [],
        },
        {"check_state": "failed", "error_code": "network", "imported_business_keys": ["26120"]},
    ),
)
def test_schedule_check_manifest_enforces_cross_field_contract(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        _check_manifest(**changes)


@pytest.mark.parametrize(
    ("state", "changes"),
    (
        ("slate_imported", {}),
        (
            "confirmed_no_sale",
            {
                "check_state": "confirmed_no_sale",
                "observed_business_keys": [],
                "imported_business_keys": [],
            },
        ),
        (
            "failed",
            {
                "check_state": "failed",
                "official_source_artifact_retrieval_id": None,
                "parser_contract_version": None,
                "official_source_content_hash": None,
                "observed_business_keys": [],
                "imported_business_keys": [],
                "error_code": "network_error",
            },
        ),
    ),
)
def test_records_each_schedule_check_state(
    tmp_path: Path,
    state: str,
    changes: dict[str, object],
) -> None:
    actions, engine = _setup(tmp_path)
    if state == "slate_imported":
        actions.import_official_sale_slate(
            _request(_manifest(), key="official-sale:for-schedule-check")
        )
    elif state == "failed":
        with engine.begin() as connection:
            connection.execute(
                schema.source_runs.update()
                .where(schema.source_runs.c.source_run_id == "run-official")
                .values(status="failed", error_code="network_error")
            )

    outcome = actions.record_official_schedule_check(
        _check_request(_check_manifest(**changes), key=f"official-check:{state}")
    )

    assert outcome.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        row = uow.operator_sale.latest_schedule_check("jczq", "2026-09-04")
        assert row is not None
        assert row.action_id == outcome.action_id
        assert row.check_state == state


def test_slate_imported_check_rejects_an_uncommitted_business_key(tmp_path: Path) -> None:
    actions, engine = _setup(tmp_path)

    with pytest.raises(ValueError, match="business key"):
        actions.record_official_schedule_check(
            _check_request(
                _check_manifest(imported_business_keys=["2026-09-05"]),
                key="official-check:missing-business-key",
            )
        )


def test_schedule_check_requires_complete_retrieval_business_key_set(
    tmp_path: Path,
) -> None:
    actions, _engine = _setup(tmp_path)
    actions.import_official_sale_slate(
        _request(_manifest(), key="official-sale:complete-set:first")
    )
    second_hash = _add_official_retrieval(
        _engine,
        "retrieval-official-complete-set-2",
        retrieved_at="2026-09-04T08:02:00+08:00",
        hash_character="c",
    )
    actions.import_official_sale_slate(
        _request(
            _manifest(
                business_key="2026-09-05",
                retrieved_at="2026-09-04T08:02:00+08:00",
                official_source_artifact_retrieval_id=(
                    "retrieval-official-complete-set-2"
                ),
                official_source_content_hash=second_hash,
                offers=[
                    _offer()
                ],
            ),
            key="official-sale:complete-set:second",
        )
    )

    with pytest.raises(ValueError, match="complete business key set"):
        actions.record_official_schedule_check(
            _check_request(
                _check_manifest(),
                key="official-check:incomplete-set",
            )
        )


def test_confirmed_no_sale_rejects_retrieval_that_imported_a_slate(
    tmp_path: Path,
) -> None:
    actions, _engine = _setup(tmp_path)
    actions.import_official_sale_slate(
        _request(_manifest(), key="official-sale:no-sale-conflict")
    )

    with pytest.raises(ValueError, match="no sale"):
        actions.record_official_schedule_check(
            _check_request(
                _check_manifest(
                    check_state="confirmed_no_sale",
                    observed_business_keys=[],
                    imported_business_keys=[],
                ),
                key="official-check:no-sale-conflict",
            )
        )


def test_confirmed_no_sale_rejects_sale_imported_by_another_run_retrieval(
    tmp_path: Path,
) -> None:
    actions, engine = _setup(tmp_path)
    with engine.begin() as connection:
        connection.execute(
            insert(schema.artifact_retrievals).values(
                artifact_retrieval_id="retrieval-official-run-peer",
                artifact_id="artifact-official",
                source_run_id="run-official",
                source_name="sporttery",
                source_type="official_sale_schedule",
                reported_content_type="application/json",
                canonical_url="https://www.sporttery.cn/official-peer.json",
                requested_url="https://www.sporttery.cn/official-peer.json",
                published_at="2026-09-04T08:00:00+08:00",
                retrieved_at="2026-09-04T08:01:00+08:00",
                status="stored",
            )
        )
    actions.import_official_sale_slate(
        _request(
            _manifest(
                official_source_artifact_retrieval_id=(
                    "retrieval-official-run-peer"
                )
            ),
            key="official-sale:run-peer",
        )
    )

    with pytest.raises(ValueError, match="no sale"):
        actions.record_official_schedule_check(
            _check_request(
                _check_manifest(
                    check_state="confirmed_no_sale",
                    observed_business_keys=[],
                    imported_business_keys=[],
                ),
                key="official-check:run-peer-conflict",
            )
        )


def test_schedule_check_is_unique_per_run_lane_and_shanghai_date(
    tmp_path: Path,
) -> None:
    actions, engine = _setup(tmp_path)
    manifest = _check_manifest(
        check_state="confirmed_no_sale",
        observed_business_keys=[],
        imported_business_keys=[],
    )
    actions.record_official_schedule_check(
        _check_request(manifest, key="official-check:unique:first")
    )

    with pytest.raises(ValueError, match="already recorded"):
        actions.record_official_schedule_check(
            _check_request(manifest, key="official-check:unique:second")
        )

    with engine.connect() as connection:
        assert (
            connection.scalar(
                select(func.count()).select_from(sos.official_schedule_check_receipts)
            )
            == 1
        )


def test_sale_retrieval_requires_successful_official_schedule_run(
    tmp_path: Path,
) -> None:
    actions, engine = _setup(tmp_path)
    with engine.begin() as connection:
        connection.execute(
            schema.source_runs.update()
            .where(schema.source_runs.c.source_run_id == "run-official")
            .values(status="failed")
        )

    with pytest.raises(ValueError, match="official schedule source run"):
        actions.import_official_sale_slate(
            _request(_manifest(), key="official-sale:failed-source-run")
        )


def test_sale_manifest_must_bind_exact_official_source_content_and_time(
    tmp_path: Path,
) -> None:
    actions, engine = _setup(tmp_path)

    with pytest.raises(ValueError, match="content hash"):
        actions.import_official_sale_slate(
            _request(
                _manifest(official_source_content_hash="c" * 64),
                key="official-sale:wrong-source-hash",
            )
        )


def test_official_source_times_are_monotonic_and_not_from_the_future(
    tmp_path: Path,
) -> None:
    actions, engine = _setup(tmp_path)
    first = actions.import_official_sale_slate(
        _request(_manifest(), key="official-sale:time:first")
    )
    stale_hash = _add_official_retrieval(
        engine,
        "retrieval-official-stale",
        retrieved_at="2026-09-04T08:00:00+08:00",
        hash_character="e",
    )
    with pytest.raises(ValueError, match="advance monotonically"):
        actions.import_official_sale_slate(
            _request(
                _manifest(
                    retrieved_at="2026-09-04T08:00:00+08:00",
                    official_source_artifact_retrieval_id="retrieval-official-stale",
                    official_source_content_hash=stale_hash,
                    supersedes_slate_revision_id=first.slate.slate_revision_id,
                    offers=[_offer(status="sale_closed")],
                ),
                key="official-sale:time:stale",
            )
        )

    future_hash = _add_official_retrieval(
        engine,
        "retrieval-official-future",
        retrieved_at="2026-09-04T08:06:00+08:00",
        hash_character="f",
    )
    with pytest.raises(ValueError, match="later than the Action"):
        actions.import_official_sale_slate(
            _request(
                _manifest(
                    retrieved_at="2026-09-04T08:06:00+08:00",
                    official_source_artifact_retrieval_id="retrieval-official-future",
                    official_source_content_hash=future_hash,
                    supersedes_slate_revision_id=first.slate.slate_revision_id,
                    offers=[_offer(status="sale_closed")],
                ),
                key="official-sale:time:future",
            )
        )

    with pytest.raises(ValueError, match="check cannot precede"):
        actions.record_official_schedule_check(
            _check_request(
                _check_manifest(
                    checked_at="2026-09-04T08:05:00+08:00",
                    official_source_artifact_retrieval_id="retrieval-official-future",
                    official_source_content_hash=future_hash,
                ),
                key="official-check:time:future",
            )
        )
    with pytest.raises(ValueError, match="retrieved_at"):
        actions.import_official_sale_slate(
            _request(
                _manifest(retrieved_at="2026-09-04T08:02:00+08:00"),
                key="official-sale:wrong-source-time",
            )
        )

    with engine.begin() as connection:
        connection.execute(
            insert(schema.artifact_retrievals).values(
                artifact_retrieval_id="retrieval-false-official-url",
                artifact_id="artifact-official",
                source_run_id="run-official",
                source_name="sporttery",
                source_type="official_sale_schedule",
                reported_content_type="application/json",
                canonical_url="https://www.500.com/error.json",
                requested_url="https://www.500.com/error.json",
                published_at="2026-09-04T08:00:00+08:00",
                retrieved_at="2026-09-04T08:01:00+08:00",
                status="stored",
            )
        )
    with pytest.raises(ValueError, match="official Sporttery URL"):
        actions.import_official_sale_slate(
            _request(
                _manifest(
                    official_source_artifact_retrieval_id=(
                        "retrieval-false-official-url"
                    )
                ),
                key="official-sale:false-official-url",
            )
        )


def test_schedule_check_retrieval_must_belong_to_declared_source_run(
    tmp_path: Path,
) -> None:
    actions, engine = _setup(tmp_path)
    with engine.begin() as connection:
        connection.execute(
            insert(schema.source_runs).values(
                source_run_id="run-other",
                source_name="sporttery",
                source_type="official_schedule",
                started_at="2026-09-04T08:01:00+08:00",
                finished_at="2026-09-04T08:01:00+08:00",
                status="succeeded",
                error_code=None,
                error_detail=None,
            )
        )

    with pytest.raises(ValueError, match="source run"):
        actions.record_official_schedule_check(
            _check_request(
                _check_manifest(
                    source_run_id="run-other",
                    check_state="confirmed_no_sale",
                    observed_business_keys=[],
                    imported_business_keys=[],
                ),
                key="official-check:wrong-source-run",
            )
        )

    with engine.connect() as connection:
        assert (
            connection.scalar(
                select(func.count()).select_from(sos.official_schedule_check_receipts)
            )
            == 0
        )


def test_schedule_check_retrieval_must_match_shanghai_check_date(
    tmp_path: Path,
) -> None:
    actions, engine = _setup(tmp_path)
    next_day = datetime(2026, 9, 5, 0, 5, tzinfo=UTC)

    with pytest.raises(ValueError, match="Shanghai check date"):
        actions.record_official_schedule_check(
            _check_request(
                _check_manifest(
                    shanghai_check_date="2026-09-05",
                    checked_at="2026-09-05T08:02:00+08:00",
                    check_state="confirmed_no_sale",
                    observed_business_keys=[],
                    imported_business_keys=[],
                ),
                key="official-check:wrong-retrieval-date",
                requested_at=next_day,
            )
        )

    actions.import_official_sale_slate(
        _request(_manifest(), key="official-sale:cross-date-check")
    )
    with pytest.raises(ValueError, match="Shanghai check date"):
        actions.record_official_schedule_check(
            _check_request(
                _check_manifest(
                    shanghai_check_date="2026-09-05",
                    checked_at="2026-09-05T08:02:00+08:00",
                ),
                key="official-check:wrong-import-date",
                requested_at=next_day,
            )
        )

    with engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(sos.official_schedule_check_receipts)
        ) == 0


def test_failed_schedule_check_requires_official_run_on_check_date(
    tmp_path: Path,
) -> None:
    actions, engine = _setup(tmp_path)
    with engine.begin() as connection:
        connection.execute(
            insert(schema.source_runs),
            [
                {
                    "source_run_id": "run-unofficial",
                    "source_name": "api-football",
                    "source_type": "fixture",
                    "started_at": "2026-09-04T08:01:00+08:00",
                    "finished_at": "2026-09-04T08:01:00+08:00",
                    "status": "succeeded",
                    "error_code": None,
                    "error_detail": None,
                },
                {
                    "source_run_id": "run-official-previous-day",
                    "source_name": "sporttery",
                    "source_type": "official_schedule",
                    "started_at": "2026-09-03T08:01:00+08:00",
                    "finished_at": "2026-09-03T08:01:00+08:00",
                    "status": "failed",
                    "error_code": "network_error",
                    "error_detail": "fixture",
                },
            ],
        )

    failed = {
        "check_state": "failed",
        "parser_contract_version": None,
        "official_source_content_hash": None,
        "official_source_artifact_retrieval_id": None,
        "observed_business_keys": [],
        "imported_business_keys": [],
        "error_code": "network_error",
    }
    with pytest.raises(ValueError, match="official schedule source run"):
        actions.record_official_schedule_check(
            _check_request(
                _check_manifest(source_run_id="run-unofficial", **failed),
                key="official-check:failed-unofficial-run",
            )
        )
    with pytest.raises(ValueError, match="failed source run status"):
        actions.record_official_schedule_check(
            _check_request(
                _check_manifest(source_run_id="run-official", **failed),
                key="official-check:failed-successful-run",
            )
        )
    with pytest.raises(ValueError, match="Shanghai check date"):
        actions.record_official_schedule_check(
            _check_request(
                _check_manifest(
                    source_run_id="run-official-previous-day",
                    **failed,
                ),
                key="official-check:failed-wrong-date",
            )
        )


@pytest.mark.parametrize("state", ("slate_imported", "confirmed_no_sale"))
def test_successful_schedule_receipts_require_succeeded_official_run(
    tmp_path: Path,
    state: str,
) -> None:
    actions, engine = _setup(tmp_path)
    if state == "slate_imported":
        actions.import_official_sale_slate(
            _request(_manifest(), key="official-sale:before-failed-run")
        )
        changes: dict[str, object] = {}
    else:
        changes = {
            "observed_business_keys": [],
            "imported_business_keys": [],
        }
    with engine.begin() as connection:
        connection.execute(
            schema.source_runs.update()
            .where(schema.source_runs.c.source_run_id == "run-official")
            .values(status="failed")
        )

    with pytest.raises(ValueError, match="succeeded source run status"):
        actions.record_official_schedule_check(
            _check_request(
                _check_manifest(check_state=state, **changes),
                key=f"official-check:{state}:failed-run",
            )
        )


def test_equivalent_timezone_sale_content_reuses_current_revision(
    tmp_path: Path,
) -> None:
    actions, engine = _setup(tmp_path)
    first = actions.import_official_sale_slate(
        _request(_manifest(), key="official-sale:timezone:first")
    )
    second_hash = _add_official_retrieval(
        engine,
        "retrieval-official-timezone",
        retrieved_at="2026-09-04T00:02:00+00:00",
        hash_character="c",
    )
    equivalent = _manifest(
        published_at="2026-09-04T00:00:00+00:00",
        retrieved_at="2026-09-04T00:02:00+00:00",
        official_source_artifact_retrieval_id="retrieval-official-timezone",
        official_source_content_hash=second_hash,
        supersedes_slate_revision_id=first.slate.slate_revision_id,
        offers=[
            _offer(
                sale_opens_at="2026-09-04T00:00:00+00:00",
                sale_deadline_at="2026-09-04T11:00:00+00:00",
            )
        ],
    )

    repeated = actions.import_official_sale_slate(
        _request(equivalent, key="official-sale:timezone:equivalent")
    )

    assert repeated.slate.slate_revision_id == first.slate.slate_revision_id
    assert repeated.slate.content_hash == first.slate.content_hash
    assert repeated.counts.created_slate_revision_count == 0


def test_browser_role_cannot_import_or_record_checks(tmp_path: Path) -> None:
    actions, engine = _setup(tmp_path)

    imported = actions.import_official_sale_slate(
        _request(_manifest(), key="official-sale:judge-denied", role=ActorRole.JUDGE_OPERATOR)
    )
    checked = actions.record_official_schedule_check(
        _check_request(
            _check_manifest(),
            key="official-check:judge-denied",
            role=ActorRole.JUDGE_OPERATOR,
        )
    )

    assert imported.outcome.status is ActionStatus.REJECTED
    assert checked.status is ActionStatus.REJECTED
    with engine.connect() as connection:
        assert (
            connection.scalar(select(func.count()).select_from(sos.official_sale_slate_revisions))
            == 0
        )
        assert (
            connection.scalar(
                select(func.count()).select_from(sos.official_schedule_check_receipts)
            )
            == 0
        )
