"""Typed persistence for scoreboard observations, reviews, and authority."""
from __future__ import annotations

import json
from dataclasses import asdict

from sqlalchemy import Connection, func, insert, select, update

from nutmeg.ontology.actions.models import canonical_json
from nutmeg.ontology.errors import OptimisticConcurrencyError
from nutmeg.ontology.repository import schema_scoreboard as ss
from nutmeg.ontology.scoreboard.models import (
    ScoreboardAuthorityRow,
    ScoreboardObservationRow,
    ScoreboardShadowReviewRow,
)


class ScoreboardRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def insert_observation(self, row: ScoreboardObservationRow) -> None:
        values = asdict(row)
        values["evidence_refs_json"] = canonical_json(values.pop("evidence_refs"))
        self._connection.execute(insert(ss.scoreboard_observations).values(**values))

    def observation(self, observation_id: str) -> ScoreboardObservationRow | None:
        row = (
            self._connection.execute(
                select(ss.scoreboard_observations).where(
                    ss.scoreboard_observations.c.scoreboard_observation_id
                    == observation_id
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else self._observation_row(row)

    def latest_observations(self, as_of: str) -> list[ScoreboardObservationRow]:
        rows = (
            self._connection.execute(
                select(ss.scoreboard_observations)
                .where(
                    ss.scoreboard_observations.c.effective_at <= as_of,
                    ss.scoreboard_observations.c.recorded_at <= as_of,
                )
                .order_by(
                    ss.scoreboard_observations.c.recorded_at,
                    ss.scoreboard_observations.c.scoreboard_observation_id,
                )
            )
            .mappings()
            .all()
        )
        latest: dict[tuple[str, str], ScoreboardObservationRow] = {}
        for raw in rows:
            row = self._observation_row(raw)
            latest[(row.group_key, row.metric_key)] = row
        return [latest[key] for key in sorted(latest)]

    def current_observation(
        self, group_key: str, metric_key: str
    ) -> ScoreboardObservationRow | None:
        rows = (
            self._connection.execute(
                select(ss.scoreboard_observations)
                .where(
                    ss.scoreboard_observations.c.group_key == group_key,
                    ss.scoreboard_observations.c.metric_key == metric_key,
                )
                .order_by(
                    ss.scoreboard_observations.c.recorded_at,
                    ss.scoreboard_observations.c.scoreboard_observation_id,
                )
            )
            .mappings()
            .all()
        )
        if not rows:
            return None
        superseded_ids = {
            str(row["supersedes_observation_id"])
            for row in rows
            if row["supersedes_observation_id"] is not None
        }
        leaves = [
            row
            for row in rows
            if row["scoreboard_observation_id"] not in superseded_ids
        ]
        if len(leaves) != 1:
            raise ValueError(
                f"scoreboard observation chain {group_key}/{metric_key} is ambiguous"
            )
        return self._observation_row(leaves[0])

    def insert_shadow_review(self, row: ScoreboardShadowReviewRow) -> None:
        values = asdict(row)
        values["classification_json"] = canonical_json(values.pop("classification"))
        self._connection.execute(insert(ss.scoreboard_shadow_reviews).values(**values))

    def shadow_review(self, review_id: str) -> ScoreboardShadowReviewRow | None:
        row = (
            self._connection.execute(
                select(ss.scoreboard_shadow_reviews).where(
                    ss.scoreboard_shadow_reviews.c.scoreboard_shadow_review_id
                    == review_id
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else self._review_row(row)

    def latest_shadow_review(self) -> ScoreboardShadowReviewRow | None:
        row = (
            self._connection.execute(
                select(ss.scoreboard_shadow_reviews)
                .order_by(
                    ss.scoreboard_shadow_reviews.c.reviewed_at.desc(),
                    ss.scoreboard_shadow_reviews.c.scoreboard_shadow_review_id.desc(),
                )
                .limit(1)
            )
            .mappings()
            .first()
        )
        return None if row is None else self._review_row(row)

    def authority(self) -> ScoreboardAuthorityRow:
        row = self._connection.execute(
            select(ss.scoreboard_authority).where(
                ss.scoreboard_authority.c.authority_id == "primary"
            )
        ).mappings().one()
        return ScoreboardAuthorityRow(**dict(row))

    def approve_authority(
        self,
        *,
        expected_version: int,
        review_id: str,
        projection_version: str,
        source_high_watermark: int,
        legacy_sha256: str,
        approved_at: str,
        action_id: str,
    ) -> ScoreboardAuthorityRow:
        result = self._connection.execute(
            update(ss.scoreboard_authority)
            .where(
                ss.scoreboard_authority.c.authority_id == "primary",
                ss.scoreboard_authority.c.version == expected_version,
            )
            .values(
                state="ontology",
                projection_version=projection_version,
                source_high_watermark=source_high_watermark,
                legacy_sha256=legacy_sha256,
                shadow_review_id=review_id,
                compatibility_export_sha256=None,
                approved_at=approved_at,
                approved_by_action_id=action_id,
                version=expected_version + 1,
            )
        )
        if result.rowcount != 1:
            current = self.authority()
            raise OptimisticConcurrencyError(
                f"scoreboard authority is at version {current.version}, "
                f"expected {expected_version}"
            )
        return self.authority()

    def record_export(
        self,
        *,
        expected_version: int,
        export_sha256: str,
        projection_version: str,
        source_high_watermark: int,
        action_id: str,
    ) -> ScoreboardAuthorityRow:
        del action_id  # The generation Action is retained in the immutable Actions table.
        result = self._connection.execute(
            update(ss.scoreboard_authority)
            .where(
                ss.scoreboard_authority.c.authority_id == "primary",
                ss.scoreboard_authority.c.version == expected_version,
                ss.scoreboard_authority.c.state == "ontology",
            )
            .values(
                compatibility_export_sha256=export_sha256,
                projection_version=projection_version,
                source_high_watermark=source_high_watermark,
                version=expected_version + 1,
            )
        )
        if result.rowcount != 1:
            current = self.authority()
            raise OptimisticConcurrencyError(
                f"scoreboard authority is at version {current.version}, "
                f"expected {expected_version} in ontology state"
            )
        return self.authority()

    def count_observations(self) -> int:
        return int(
            self._connection.execute(
                select(func.count()).select_from(ss.scoreboard_observations)
            ).scalar_one()
        )

    def count_shadow_reviews(self) -> int:
        return int(
            self._connection.execute(
                select(func.count()).select_from(ss.scoreboard_shadow_reviews)
            ).scalar_one()
        )

    @staticmethod
    def _observation_row(row) -> ScoreboardObservationRow:
        values = dict(row)
        values["evidence_refs"] = json.loads(values.pop("evidence_refs_json"))
        return ScoreboardObservationRow(**values)

    @staticmethod
    def _review_row(row) -> ScoreboardShadowReviewRow:
        values = dict(row)
        values["classification"] = json.loads(values.pop("classification_json"))
        return ScoreboardShadowReviewRow(**values)
