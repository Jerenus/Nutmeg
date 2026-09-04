"""Typed persistence for official operator sale revisions."""

from __future__ import annotations

import json

from sqlalchemy import Connection, func, insert, select

from nutmeg.ontology.actions.models import canonical_json
from nutmeg.ontology.operator.models import (
    OfficialOfferFamilyRow,
    OfficialOfferRevisionRow,
    OfficialSaleSlateRevisionRow,
    OfficialScheduleCheckReceiptRow,
)
from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository import schema_operator_sale as sos


class OperatorSaleRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def insert_slate_revision(self, row: OfficialSaleSlateRevisionRow) -> None:
        self._connection.execute(
            insert(sos.official_sale_slate_revisions).values(**row_fields(row))
        )

    def insert_offer_family(self, row: OfficialOfferFamilyRow) -> None:
        self._connection.execute(insert(sos.official_offer_families).values(**row_fields(row)))

    def offer_family(self, family_id: str) -> OfficialOfferFamilyRow | None:
        row = (
            self._connection.execute(
                select(sos.official_offer_families).where(
                    sos.official_offer_families.c.official_offer_family_id == family_id
                )
            )
            .mappings()
            .first()
        )
        return OfficialOfferFamilyRow(**dict(row)) if row is not None else None

    def insert_offer_revision(self, row: OfficialOfferRevisionRow) -> None:
        values = row_fields(row)
        values["market_definition_ids_json"] = canonical_json(list(row.market_definition_ids))
        values.pop("market_definition_ids")
        self._connection.execute(insert(sos.official_offer_revisions).values(**values))

    def insert_schedule_check(self, row: OfficialScheduleCheckReceiptRow) -> None:
        values = row_fields(row)
        values["observed_business_keys_json"] = canonical_json(
            list(row.observed_business_keys)
        )
        values.pop("observed_business_keys")
        values["imported_business_keys_json"] = canonical_json(list(row.imported_business_keys))
        values.pop("imported_business_keys")
        self._connection.execute(insert(sos.official_schedule_check_receipts).values(**values))

    def current_slate(self, lane: str, business_key: str) -> OfficialSaleSlateRevisionRow | None:
        row = (
            self._connection.execute(
                select(sos.official_sale_slate_revisions)
                .where(
                    sos.official_sale_slate_revisions.c.lane == lane,
                    sos.official_sale_slate_revisions.c.business_key == business_key,
                )
                .order_by(sos.official_sale_slate_revisions.c.revision_no.desc())
                .limit(1)
            )
            .mappings()
            .first()
        )
        return self._slate(row) if row is not None else None

    def slate_revision(self, slate_revision_id: str) -> OfficialSaleSlateRevisionRow | None:
        row = (
            self._connection.execute(
                select(sos.official_sale_slate_revisions).where(
                    sos.official_sale_slate_revisions.c.slate_revision_id == slate_revision_id
                )
            )
            .mappings()
            .first()
        )
        return self._slate(row) if row is not None else None

    def offer_revisions_for_slate(
        self, slate_revision_id: str
    ) -> tuple[OfficialOfferRevisionRow, ...]:
        rows = (
            self._connection.execute(
                select(sos.official_offer_revisions)
                .where(sos.official_offer_revisions.c.slate_revision_id == slate_revision_id)
            )
            .mappings()
            .all()
        )
        ordered = sorted(rows, key=self._official_offer_order)
        return tuple(self._offer(row) for row in ordered)

    def offer_revision(
        self, official_offer_revision_id: str
    ) -> OfficialOfferRevisionRow | None:
        row = (
            self._connection.execute(
                select(sos.official_offer_revisions).where(
                    sos.official_offer_revisions.c.official_offer_revision_id
                    == official_offer_revision_id
                )
            )
            .mappings()
            .first()
        )
        return self._offer(row) if row is not None else None

    def current_offer_by_family(self, family_id: str) -> OfficialOfferRevisionRow | None:
        family = (
            self._connection.execute(
                select(
                    sos.official_offer_families.c.lane,
                    sos.official_offer_families.c.business_key,
                ).where(sos.official_offer_families.c.official_offer_family_id == family_id)
            )
            .mappings()
            .first()
        )
        if family is None:
            return None
        current_slate = self.current_slate(family["lane"], family["business_key"])
        if current_slate is None:
            return None
        row = (
            self._connection.execute(
                select(sos.official_offer_revisions)
                .where(
                    sos.official_offer_revisions.c.official_offer_family_id == family_id,
                    sos.official_offer_revisions.c.slate_revision_id
                    == current_slate.slate_revision_id,
                )
                .limit(1)
            )
            .mappings()
            .first()
        )
        return self._offer(row) if row is not None else None

    def latest_schedule_check(
        self, lane: str, shanghai_date: str
    ) -> OfficialScheduleCheckReceiptRow | None:
        row = (
            self._connection.execute(
                select(sos.official_schedule_check_receipts)
                .where(
                    sos.official_schedule_check_receipts.c.lane == lane,
                    sos.official_schedule_check_receipts.c.shanghai_check_date == shanghai_date,
                )
                .order_by(
                    sos.official_schedule_check_receipts.c.checked_at.desc(),
                    sos.official_schedule_check_receipts.c.schedule_check_id.desc(),
                )
                .limit(1)
            )
            .mappings()
            .first()
        )
        return self._schedule_check(row) if row is not None else None

    def schedule_check_for_run_scope(
        self,
        source_run_id: str,
        lane: str,
        shanghai_date: str,
    ) -> OfficialScheduleCheckReceiptRow | None:
        row = (
            self._connection.execute(
                select(sos.official_schedule_check_receipts).where(
                    sos.official_schedule_check_receipts.c.source_run_id == source_run_id,
                    sos.official_schedule_check_receipts.c.lane == lane,
                    sos.official_schedule_check_receipts.c.shanghai_check_date == shanghai_date,
                )
            )
            .mappings()
            .first()
        )
        return self._schedule_check(row) if row is not None else None

    def business_keys_for_source_run(
        self,
        lane: str,
        source_run_id: str,
    ) -> tuple[str, ...]:
        rows = self._connection.execute(
            select(sos.official_sale_slate_revisions.c.business_key)
            .select_from(
                sos.official_sale_slate_revisions.join(
                    schema.artifact_retrievals,
                    sos.official_sale_slate_revisions.c.source_artifact_retrieval_id
                    == schema.artifact_retrievals.c.artifact_retrieval_id,
                )
            )
            .where(
                sos.official_sale_slate_revisions.c.lane == lane,
                schema.artifact_retrievals.c.source_run_id == source_run_id,
            )
            .distinct()
            .order_by(sos.official_sale_slate_revisions.c.business_key)
        ).scalars()
        business_keys = set(rows)
        retrieval_ids = set(
            self._connection.execute(
                select(schema.artifact_retrievals.c.artifact_retrieval_id).where(
                    schema.artifact_retrievals.c.source_run_id == source_run_id
                )
            ).scalars()
        )
        action_payloads = self._connection.execute(
            select(schema.actions.c.payload_json).where(
                schema.actions.c.action_type == "import_official_sale_slate",
                schema.actions.c.status == "committed",
            )
        ).scalars()
        for payload_json in action_payloads:
            payload = json.loads(payload_json)
            if (
                isinstance(payload, dict)
                and payload.get("lane") == lane
                and payload.get("official_source_artifact_retrieval_id") in retrieval_ids
                and isinstance(payload.get("business_key"), str)
            ):
                business_keys.add(payload["business_key"])
        return tuple(sorted(business_keys))

    def persisted_counts_for_slate(self, slate_revision_id: str) -> tuple[int, int, int]:
        slate_count = self._connection.execute(
            select(func.count())
            .select_from(sos.official_sale_slate_revisions)
            .where(sos.official_sale_slate_revisions.c.slate_revision_id == slate_revision_id)
        ).scalar_one()
        offer_count = self._connection.execute(
            select(func.count())
            .select_from(sos.official_offer_revisions)
            .where(sos.official_offer_revisions.c.slate_revision_id == slate_revision_id)
        ).scalar_one()
        family_count = self._connection.execute(
            select(
                func.count(func.distinct(sos.official_offer_revisions.c.official_offer_family_id))
            ).where(sos.official_offer_revisions.c.slate_revision_id == slate_revision_id)
        ).scalar_one()
        return int(slate_count), int(family_count), int(offer_count)

    @staticmethod
    def _slate(row) -> OfficialSaleSlateRevisionRow:
        return OfficialSaleSlateRevisionRow(**dict(row))

    @staticmethod
    def _offer(row) -> OfficialOfferRevisionRow:
        values = dict(row)
        values["market_definition_ids"] = tuple(
            json.loads(values.pop("market_definition_ids_json"))
        )
        return OfficialOfferRevisionRow(**values)

    @staticmethod
    def _official_offer_order(row) -> tuple[int, int | str]:
        official_match_no = row["official_match_no"]
        if official_match_no.isdigit():
            return 0, int(official_match_no)
        return 1, official_match_no

    @staticmethod
    def _schedule_check(row) -> OfficialScheduleCheckReceiptRow:
        values = dict(row)
        values["observed_business_keys"] = tuple(
            json.loads(values.pop("observed_business_keys_json"))
        )
        values["imported_business_keys"] = tuple(
            json.loads(values.pop("imported_business_keys_json"))
        )
        return OfficialScheduleCheckReceiptRow(**values)


def row_fields(row) -> dict[str, object]:
    return {name: getattr(row, name) for name in row.__dataclass_fields__}


__all__ = ["OperatorSaleRepository"]
