from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest
from sqlalchemy import insert, inspect, select
from sqlalchemy.exc import IntegrityError

from nutmeg.ontology.operator.models import (
    OfficialOfferFamilyRow,
    OfficialOfferRevisionRow,
    OfficialSaleSlateRevisionRow,
    OfficialScheduleCheckReceiptRow,
)
from nutmeg.ontology.repository import schema, schema_identity
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import MIGRATIONS, migration_status, run_migrations
from nutmeg.ontology.repository.operator_sale import OperatorSaleRepository


def _rows() -> tuple[
    OfficialSaleSlateRevisionRow,
    OfficialOfferFamilyRow,
    OfficialOfferRevisionRow,
    OfficialScheduleCheckReceiptRow,
]:
    slate = OfficialSaleSlateRevisionRow(
        slate_revision_id="slate-1",
        slate_family_id="jczq:2026-09-04",
        lane="jczq",
        business_key="2026-09-04",
        revision_no=1,
        source_artifact_retrieval_id="retrieval-1",
        published_at="2026-09-04T08:00:00+08:00",
        retrieved_at="2026-09-04T08:01:00+08:00",
        valid_from="2026-09-04T08:01:00+08:00",
        supersedes_slate_revision_id=None,
        content_hash="a" * 64,
    )
    family = OfficialOfferFamilyRow(
        official_offer_family_id="offer-family-1",
        lane="jczq",
        business_key="2026-09-04",
        official_match_no="周五001",
        match_id="match-1",
        created_at="2026-09-04T08:01:00+08:00",
    )
    offer = OfficialOfferRevisionRow(
        official_offer_revision_id="offer-revision-1",
        official_offer_family_id=family.official_offer_family_id,
        slate_revision_id=slate.slate_revision_id,
        match_id="match-1",
        official_match_no="周五001",
        market_definition_ids=("md-had",),
        sale_opens_at="2026-09-04T08:00:00+08:00",
        sale_deadline_at="2026-09-04T19:00:00+08:00",
        status="on_sale",
    )
    receipt = OfficialScheduleCheckReceiptRow(
        schedule_check_id="check-1",
        action_id="ACT-check-1",
        lane="jczq",
        shanghai_check_date="2026-09-04",
        checked_at="2026-09-04T08:02:00+08:00",
        source_run_id="run-1",
        check_state="slate_imported",
        parser_contract_version="sporttery-official-sale-parser-v1",
        official_source_content_hash="b" * 64,
        official_source_artifact_retrieval_id="retrieval-1",
        observed_business_keys=("2026-09-04",),
        imported_business_keys=("2026-09-04",),
        error_code=None,
    )
    return slate, family, offer, receipt


def _seed_dependencies(connection, *, action_id: str = "ACT-check-1") -> None:
    at = "2026-09-04T08:01:00+08:00"
    connection.execute(
        insert(schema.source_runs).values(
            source_run_id="run-1",
            source_name="sporttery",
            source_type="official_schedule",
            started_at=at,
            finished_at=at,
            status="succeeded",
            error_code=None,
            error_detail=None,
        )
    )
    connection.execute(
        insert(schema.source_artifacts).values(
            artifact_id="artifact-1",
            first_recorded_at=at,
            content_type="application/json",
            storage_path="sha256/operator-sale-fixture",
            byte_size=2,
            content_hash="b" * 64,
        )
    )
    connection.execute(
        insert(schema.artifact_retrievals).values(
            artifact_retrieval_id="retrieval-1",
            artifact_id="artifact-1",
            source_run_id="run-1",
            source_name="sporttery",
            source_type="official_sale_schedule",
            reported_content_type="application/json",
            canonical_url="https://www.sporttery.cn/official-sale.json",
            requested_url="https://www.sporttery.cn/official-sale.json",
            published_at=at,
            retrieved_at=at,
            status="stored",
        )
    )
    connection.execute(
        insert(schema_identity.matches).values(
            match_id="match-1",
            current_revision_id=None,
        )
    )
    connection.execute(
        insert(schema.actions).values(
            action_id=action_id,
            action_type="record_official_schedule_check",
            actor_id="system:official-sale",
            actor_role="deterministic_system",
            requested_at=at,
            idempotency_key=f"operator-sale:{action_id}",
            request_hash="c" * 64,
            expected_versions_json="{}",
            payload_json="{}",
            policy_version="governance-v1",
            status="committed",
            result_refs_json="[]",
            error_code=None,
            error_detail=None,
            committed_at=at,
        )
    )


def test_migration_17_applies_fresh_and_from_v16(tmp_path: Path) -> None:
    expected_tables = {
        "official_sale_slate_revisions",
        "official_offer_families",
        "official_offer_revisions",
        "official_schedule_check_receipts",
    }
    for name, initial in (("fresh", MIGRATIONS), ("upgrade", MIGRATIONS[:16])):
        engine = build_ontology_engine(tmp_path / f"{name}.db")
        run_migrations(engine, initial)
        run_migrations(engine)
        assert migration_status(engine).current_version == 17
        assert expected_tables <= set(inspect(engine).get_table_names())
        inspector = inspect(engine)
        schedule_columns = {
            column["name"]: column
            for column in inspector.get_columns("official_schedule_check_receipts")
        }
        assert schedule_columns["source_run_id"]["nullable"] is False
        schedule_unique_keys = {
            tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints(
                "official_schedule_check_receipts"
            )
        }
        assert ("source_run_id", "lane", "shanghai_check_date") in schedule_unique_keys
        with engine.connect() as connection:
            permissions = {
                (row.action_type, row.actor_role)
                for row in connection.execute(
                    select(
                        schema.action_permissions.c.action_type,
                        schema.action_permissions.c.actor_role,
                    ).where(
                        schema.action_permissions.c.action_type.in_(
                            (
                                "import_official_sale_slate",
                                "record_official_schedule_check",
                            )
                        )
                    )
                )
            }
        assert permissions == {
            ("import_official_sale_slate", "deterministic_system"),
            ("record_official_schedule_check", "deterministic_system"),
        }


def test_repository_returns_frozen_current_rows_and_stable_family(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    slate, family, offer, receipt = _rows()
    with engine.begin() as connection:
        _seed_dependencies(connection)
        repository = OperatorSaleRepository(connection)
        repository.insert_slate_revision(slate)
        repository.insert_offer_family(family)
        repository.insert_offer_revision(offer)
        repository.insert_schedule_check(receipt)
    with engine.connect() as connection:
        repository = OperatorSaleRepository(connection)
        assert repository.current_slate("jczq", "2026-09-04") == slate
        assert repository.slate_revision("slate-1") == slate
        assert repository.offer_revisions_for_slate("slate-1") == (offer,)
        assert repository.current_offer_by_family("offer-family-1") == offer
        assert repository.latest_schedule_check("jczq", "2026-09-04") == receipt
        with pytest.raises(FrozenInstanceError):
            slate.revision_no = 9  # type: ignore[misc]


def test_repository_tracks_one_linear_current_leaf_and_removed_offers(
    tmp_path: Path,
) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    slate, family, offer, _receipt = _rows()
    second_slate = replace(
        slate,
        slate_revision_id="slate-2",
        revision_no=2,
        supersedes_slate_revision_id=slate.slate_revision_id,
        content_hash="d" * 64,
    )
    second_offer = replace(
        offer,
        official_offer_revision_id="offer-revision-2",
        slate_revision_id=second_slate.slate_revision_id,
        status="sale_closed",
    )
    with engine.begin() as connection:
        _seed_dependencies(connection)
        repository = OperatorSaleRepository(connection)
        repository.insert_slate_revision(slate)
        repository.insert_offer_family(family)
        repository.insert_offer_revision(offer)
        repository.insert_slate_revision(second_slate)
        repository.insert_offer_revision(second_offer)

    with engine.connect() as connection:
        repository = OperatorSaleRepository(connection)
        assert repository.current_slate("jczq", "2026-09-04") == second_slate
        assert repository.current_offer_by_family(family.official_offer_family_id) == second_offer

    with pytest.raises(IntegrityError, match="supersedes_slate_revision_id"):
        with engine.begin() as connection:
            OperatorSaleRepository(connection).insert_slate_revision(
                replace(
                    second_slate,
                    slate_revision_id="slate-branch",
                    revision_no=3,
                    supersedes_slate_revision_id=slate.slate_revision_id,
                    content_hash="e" * 64,
                )
            )

    with pytest.raises(IntegrityError, match="slate_family_id"):
        with engine.begin() as connection:
            OperatorSaleRepository(connection).insert_slate_revision(
                replace(
                    slate,
                    slate_revision_id="slate-parallel-root",
                    revision_no=4,
                    supersedes_slate_revision_id=None,
                    content_hash="9" * 64,
                )
            )

    with pytest.raises(IntegrityError, match="same slate family"):
        with engine.begin() as connection:
            OperatorSaleRepository(connection).insert_slate_revision(
                replace(
                    slate,
                    slate_revision_id="other-family-child",
                    slate_family_id="jczq:2026-09-05",
                    business_key="2026-09-05",
                    revision_no=3,
                    supersedes_slate_revision_id=second_slate.slate_revision_id,
                    content_hash="8" * 64,
                )
            )

    with pytest.raises(IntegrityError, match="revision_no"):
        with engine.begin() as connection:
            OperatorSaleRepository(connection).insert_slate_revision(
                replace(
                    second_slate,
                    slate_revision_id="slate-skipped-revision",
                    revision_no=5,
                    supersedes_slate_revision_id=second_slate.slate_revision_id,
                    content_hash="7" * 64,
                )
            )

    third_slate = replace(
        second_slate,
        slate_revision_id="slate-3",
        revision_no=3,
        supersedes_slate_revision_id=second_slate.slate_revision_id,
        content_hash="f" * 64,
    )
    with engine.begin() as connection:
        OperatorSaleRepository(connection).insert_slate_revision(third_slate)
    with engine.connect() as connection:
        repository = OperatorSaleRepository(connection)
        assert repository.current_slate("jczq", "2026-09-04") == third_slate
        assert repository.current_offer_by_family(family.official_offer_family_id) is None


def test_sale_uniqueness_and_foreign_keys_are_enforced(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    slate, family, offer, _receipt = _rows()
    with pytest.raises(IntegrityError, match="lane, business_key, revision_no"):
        with engine.begin() as connection:
            _seed_dependencies(connection)
            repository = OperatorSaleRepository(connection)
            repository.insert_slate_revision(slate)
            repository.insert_slate_revision(replace(slate, slate_revision_id="slate-duplicate"))
    with pytest.raises(IntegrityError, match="FOREIGN KEY"):
        with engine.begin() as connection:
            repository = OperatorSaleRepository(connection)
            repository.insert_offer_family(family)
            repository.insert_offer_revision(offer)


def test_root_slate_revision_must_start_at_one(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    slate, _family, _offer, _receipt = _rows()

    with pytest.raises(IntegrityError, match="root revision_no"):
        with engine.begin() as connection:
            _seed_dependencies(connection)
            OperatorSaleRepository(connection).insert_slate_revision(
                replace(slate, revision_no=2)
            )


def test_one_schedule_check_receipt_per_action(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    _slate, _family, _offer, receipt = _rows()
    with pytest.raises(IntegrityError, match="action_id"):
        with engine.begin() as connection:
            _seed_dependencies(connection)
            repository = OperatorSaleRepository(connection)
            repository.insert_schedule_check(receipt)
            repository.insert_schedule_check(replace(receipt, schedule_check_id="check-2"))
