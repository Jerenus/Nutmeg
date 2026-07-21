"""Decision (belief) persistence: sessions, bundles, series/revisions, factors.

One forecast series per (match, market); revisions are append-only with a single
current committed revision enforced by the application layer. JSON distribution
columns round-trip through the canonical serializer. ``observation_recorded_at``
reads the 2B evidence table so bundle freezing can exclude post-cutoff evidence.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import Connection, func, insert, select, update

from nutmeg.ontology.actions.models import canonical_json
from nutmeg.ontology.decision.models import mint_decision_id
from nutmeg.ontology.repository import schema_decision as sd
from nutmeg.ontology.repository import schema_evidence as se


@dataclass(frozen=True, slots=True)
class SessionRow:
    decision_session_id: str
    opened_at: str
    operator_id: str
    cutoff_at: str
    scope: dict[str, object]
    status: str
    closed_at: str | None


@dataclass(frozen=True, slots=True)
class EvidenceBundleRow:
    evidence_bundle_id: str
    match_id: str
    decision_session_id: str | None
    frozen_at: str
    information_cutoff_at: str
    market_snapshot_id: str | None
    prior_distribution: dict[str, float]
    identity_resolution_version: str | None
    source_coverage: dict[str, object]
    freshness: dict[str, object]
    content_hash: str


@dataclass(frozen=True, slots=True)
class ForecastRevisionRow:
    forecast_revision_id: str
    forecast_series_id: str
    decision_session_id: str | None
    revision_no: int
    status: str
    made_at: str
    information_cutoff_at: str | None
    prior_snapshot_id: str | None
    prior_distribution: dict[str, float]
    belief_distribution: dict[str, float]
    evidence_bundle_id: str | None
    falsifier: str | None
    actor_id: str
    model_name: str | None
    model_version: str | None
    policy_version: str
    commitment_tier: str
    evidence_coverage: float | None
    evidence_quality: float | None
    forecast_stability: float | None
    supersedes_revision_id: str | None


@dataclass(frozen=True, slots=True)
class CommittedRevisionRow:
    forecast_revision_id: str
    match_id: str
    market_definition_id: str
    made_at: str
    prior_distribution: dict[str, float]
    belief_distribution: dict[str, float]
    commitment_tier: str
    actor_id: str
    model_name: str | None
    model_version: str | None


@dataclass(frozen=True, slots=True)
class FactorFamilyRow:
    factor_family_id: str
    name: str
    definition: str | None


@dataclass(frozen=True, slots=True)
class FactorDefinitionRow:
    factor_definition_id: str
    factor_family_id: str
    version: int
    name: str
    definition: str | None
    scope: str | None
    status: str
    born_from_refs: list[str]
    valid_from: str
    valid_to: str | None
    policy_version: str


@dataclass(frozen=True, slots=True)
class FactorApplicationRow:
    factor_application_id: str
    forecast_revision_id: str
    factor_definition_id: str
    scope_entity_ids: list[str]
    delta_distribution: dict[str, float]
    supporting_observation_ids: list[str]
    note: str | None


class DecisionRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    # -- sessions ---------------------------------------------------------
    def insert_session(self, row: SessionRow) -> None:
        self._connection.execute(
            insert(sd.decision_sessions).values(
                decision_session_id=row.decision_session_id,
                opened_at=row.opened_at,
                operator_id=row.operator_id,
                cutoff_at=row.cutoff_at,
                scope_json=canonical_json(row.scope),
                status=row.status,
                closed_at=row.closed_at,
            )
        )

    # -- series / revisions ----------------------------------------------
    def ensure_series(self, match_id: str, market_definition_id: str) -> str:
        existing = self._connection.execute(
            select(sd.forecast_series.c.forecast_series_id).where(
                sd.forecast_series.c.match_id == match_id,
                sd.forecast_series.c.market_definition_id == market_definition_id,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        series_id = mint_decision_id('fs')
        self._connection.execute(
            insert(sd.forecast_series).values(
                forecast_series_id=series_id,
                match_id=match_id,
                market_definition_id=market_definition_id,
            )
        )
        return series_id

    def insert_revision(self, row: ForecastRevisionRow) -> None:
        self._connection.execute(
            insert(sd.forecast_revisions).values(
                forecast_revision_id=row.forecast_revision_id,
                forecast_series_id=row.forecast_series_id,
                decision_session_id=row.decision_session_id,
                revision_no=row.revision_no,
                status=row.status,
                made_at=row.made_at,
                information_cutoff_at=row.information_cutoff_at,
                prior_snapshot_id=row.prior_snapshot_id,
                prior_distribution_json=canonical_json(row.prior_distribution),
                belief_distribution_json=canonical_json(row.belief_distribution),
                evidence_bundle_id=row.evidence_bundle_id,
                falsifier=row.falsifier,
                actor_id=row.actor_id,
                model_name=row.model_name,
                model_version=row.model_version,
                policy_version=row.policy_version,
                commitment_tier=row.commitment_tier,
                evidence_coverage=row.evidence_coverage,
                evidence_quality=row.evidence_quality,
                forecast_stability=row.forecast_stability,
                supersedes_revision_id=row.supersedes_revision_id,
            )
        )

    def set_revision_status(self, forecast_revision_id: str, status: str) -> None:
        self._connection.execute(
            update(sd.forecast_revisions)
            .where(sd.forecast_revisions.c.forecast_revision_id == forecast_revision_id)
            .values(status=status)
        )

    def max_revision_no(self, forecast_series_id: str) -> int:
        value = self._connection.execute(
            select(func.max(sd.forecast_revisions.c.revision_no)).where(
                sd.forecast_revisions.c.forecast_series_id == forecast_series_id
            )
        ).scalar_one_or_none()
        return int(value) if value is not None else 0

    def current_committed_revision(self, forecast_series_id: str) -> ForecastRevisionRow | None:
        row = (
            self._connection.execute(
                select(sd.forecast_revisions)
                .where(
                    sd.forecast_revisions.c.forecast_series_id == forecast_series_id,
                    sd.forecast_revisions.c.status == 'committed',
                )
                .order_by(sd.forecast_revisions.c.revision_no.desc())
                .limit(1)
            )
            .mappings()
            .first()
        )
        return self._to_revision(row) if row is not None else None

    def count_committed_revisions(self) -> int:
        return self._connection.execute(
            select(func.count()).select_from(sd.forecast_revisions).where(
                sd.forecast_revisions.c.status == 'committed'
            )
        ).scalar_one()

    def iter_committed_revisions(self) -> list[CommittedRevisionRow]:
        rows = (
            self._connection.execute(
                select(
                    sd.forecast_revisions.c.forecast_revision_id,
                    sd.forecast_series.c.match_id,
                    sd.forecast_series.c.market_definition_id,
                    sd.forecast_revisions.c.made_at,
                    sd.forecast_revisions.c.prior_distribution_json,
                    sd.forecast_revisions.c.belief_distribution_json,
                    sd.forecast_revisions.c.commitment_tier,
                    sd.forecast_revisions.c.actor_id,
                    sd.forecast_revisions.c.model_name,
                    sd.forecast_revisions.c.model_version,
                )
                .select_from(
                    sd.forecast_revisions.join(
                        sd.forecast_series,
                        sd.forecast_revisions.c.forecast_series_id
                        == sd.forecast_series.c.forecast_series_id,
                    )
                )
                .where(sd.forecast_revisions.c.status == 'committed')
                .order_by(sd.forecast_revisions.c.forecast_revision_id)
            )
            .mappings()
            .all()
        )
        return [
            CommittedRevisionRow(
                forecast_revision_id=row['forecast_revision_id'],
                match_id=row['match_id'],
                market_definition_id=row['market_definition_id'],
                made_at=row['made_at'],
                prior_distribution=json.loads(row['prior_distribution_json']),
                belief_distribution=json.loads(row['belief_distribution_json']),
                commitment_tier=row['commitment_tier'],
                actor_id=row['actor_id'],
                model_name=row['model_name'],
                model_version=row['model_version'],
            )
            for row in rows
        ]

    # -- bundles ----------------------------------------------------------
    def insert_bundle(self, row: EvidenceBundleRow) -> None:
        self._connection.execute(
            insert(sd.evidence_bundles).values(
                evidence_bundle_id=row.evidence_bundle_id,
                match_id=row.match_id,
                decision_session_id=row.decision_session_id,
                frozen_at=row.frozen_at,
                information_cutoff_at=row.information_cutoff_at,
                market_snapshot_id=row.market_snapshot_id,
                prior_distribution_json=canonical_json(row.prior_distribution),
                identity_resolution_version=row.identity_resolution_version,
                source_coverage_json=canonical_json(row.source_coverage),
                freshness_json=canonical_json(row.freshness),
                content_hash=row.content_hash,
            )
        )

    def add_bundle_item(
        self,
        evidence_bundle_id: str,
        item_type: str,
        observation_id: str | None = None,
        claim_id: str | None = None,
    ) -> None:
        self._connection.execute(
            insert(sd.evidence_bundle_items).values(
                item_id=mint_decision_id('ebi'),
                evidence_bundle_id=evidence_bundle_id,
                item_type=item_type,
                observation_id=observation_id,
                claim_id=claim_id,
            )
        )

    def bundle_item_ids(self, evidence_bundle_id: str) -> tuple[str, ...]:
        rows = self._connection.execute(
            select(
                sd.evidence_bundle_items.c.observation_id,
                sd.evidence_bundle_items.c.claim_id,
            ).where(sd.evidence_bundle_items.c.evidence_bundle_id == evidence_bundle_id)
        ).all()
        return tuple(observation_id or claim_id for observation_id, claim_id in rows)

    def count_bundles(self) -> int:
        return self._connection.execute(
            select(func.count()).select_from(sd.evidence_bundles)
        ).scalar_one()

    def observation_recorded_at(self, observation_id: str) -> str | None:
        return self._connection.execute(
            select(se.observations.c.recorded_at).where(
                se.observations.c.observation_id == observation_id
            )
        ).scalar_one_or_none()

    # -- factors ----------------------------------------------------------
    def insert_factor_family(self, row: FactorFamilyRow) -> None:
        self._connection.execute(
            insert(sd.factor_families).values(
                factor_family_id=row.factor_family_id, name=row.name, definition=row.definition
            )
        )

    def insert_factor_definition(self, row: FactorDefinitionRow) -> None:
        self._connection.execute(
            insert(sd.factor_definitions).values(
                factor_definition_id=row.factor_definition_id,
                factor_family_id=row.factor_family_id,
                version=row.version,
                name=row.name,
                definition=row.definition,
                scope=row.scope,
                status=row.status,
                born_from_refs_json=canonical_json(row.born_from_refs),
                valid_from=row.valid_from,
                valid_to=row.valid_to,
                policy_version=row.policy_version,
            )
        )

    def set_factor_status(self, factor_definition_id: str, status: str) -> None:
        self._connection.execute(
            update(sd.factor_definitions)
            .where(sd.factor_definitions.c.factor_definition_id == factor_definition_id)
            .values(status=status)
        )

    def factor_status(self, factor_definition_id: str) -> str | None:
        return self._connection.execute(
            select(sd.factor_definitions.c.status).where(
                sd.factor_definitions.c.factor_definition_id == factor_definition_id
            )
        ).scalar_one_or_none()

    def insert_factor_application(self, row: FactorApplicationRow) -> None:
        self._connection.execute(
            insert(sd.factor_applications).values(
                factor_application_id=row.factor_application_id,
                forecast_revision_id=row.forecast_revision_id,
                factor_definition_id=row.factor_definition_id,
                scope_entity_ids_json=canonical_json(row.scope_entity_ids),
                delta_distribution_json=canonical_json(row.delta_distribution),
                supporting_observation_ids_json=canonical_json(row.supporting_observation_ids),
                note=row.note,
            )
        )

    @staticmethod
    def _to_revision(row) -> ForecastRevisionRow:
        return ForecastRevisionRow(
            forecast_revision_id=row['forecast_revision_id'],
            forecast_series_id=row['forecast_series_id'],
            decision_session_id=row['decision_session_id'],
            revision_no=row['revision_no'],
            status=row['status'],
            made_at=row['made_at'],
            information_cutoff_at=row['information_cutoff_at'],
            prior_snapshot_id=row['prior_snapshot_id'],
            prior_distribution=json.loads(row['prior_distribution_json']),
            belief_distribution=json.loads(row['belief_distribution_json']),
            evidence_bundle_id=row['evidence_bundle_id'],
            falsifier=row['falsifier'],
            actor_id=row['actor_id'],
            model_name=row['model_name'],
            model_version=row['model_version'],
            policy_version=row['policy_version'],
            commitment_tier=row['commitment_tier'],
            evidence_coverage=row['evidence_coverage'],
            evidence_quality=row['evidence_quality'],
            forecast_stability=row['forecast_stability'],
            supersedes_revision_id=row['supersedes_revision_id'],
        )
