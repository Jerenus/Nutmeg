"""Read-only temporal queries over Ontology Kernel v2."""
from __future__ import annotations

import base64
import json
from collections.abc import Iterable
from pathlib import Path

from sqlalchemy import Engine, and_, case, func, or_, select

from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository import schema_context as sc
from nutmeg.ontology.repository import schema_decision as sd
from nutmeg.ontology.repository import schema_evidence as se
from nutmeg.ontology.repository import schema_finance as sf
from nutmeg.ontology.repository import schema_identity as si
from nutmeg.ontology.repository import schema_market as sm
from nutmeg.ontology.repository import schema_tickets as st
from nutmeg.ontology.repository import schema_workflow as sw
from nutmeg.ontology.repository.outbox import OutboxEventRow, OutboxRepository

LineageTuple = tuple[str, str, str, str, str]


class ProductReadRepository:
    def __init__(self, engine: Engine, analytics_path: Path | None = None) -> None:
        self._engine = engine
        self._analytics_path = Path(analytics_path) if analytics_path is not None else None

    def scoreboard_projection(self, *, as_of: str) -> dict:
        result = self._projection_rows("scoreboard_metrics", as_of=as_of)
        if result["rows"]:
            for row in result["rows"]:
                row["source_refs"] = json.loads(row.pop("source_refs_json"))
        return result

    def projection_rows(self, table: str, *, as_of: str) -> dict:
        allowed = {
            "counterfactual_replays",
            "factor_estimates",
            "factor_lifecycle_proposals",
            "regime_vectors",
            "regime_postmatch_labels",
        }
        if table not in allowed:
            raise ValueError(f"projection table {table} is not allowlisted")
        return self._projection_rows(table, as_of=as_of)

    def _projection_rows(self, table: str, *, as_of: str) -> dict:
        path = self._analytics_path
        unavailable = {
            "health": {
                "state": "unavailable",
                "code": "projection_unavailable",
                "instruction": "run `nutmeg ontology calibrate`",
                "projection_version": None,
                "source_high_watermark": None,
                "built_at": None,
                "cohort_definition_version": None,
                "metric_version": None,
            },
            "rows": [],
        }
        if path is None or not path.is_file():
            return unavailable
        import duckdb

        with duckdb.connect(str(path), read_only=True) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT table_name FROM information_schema.tables"
                ).fetchall()
            }
            if table not in tables:
                return unavailable
            cursor = connection.execute(f'SELECT * FROM "{table}" ORDER BY 1, 2')
            columns = [item[0] for item in cursor.description]
            rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
        if not rows:
            projection_names = {
                "counterfactual_replays": "intervention_quality",
                "factor_estimates": "factor_estimates",
                "factor_lifecycle_proposals": "factor_lifecycle_proposals",
                "regime_vectors": "regime_vectors",
                "regime_postmatch_labels": "regime_postmatch_labels",
                "scoreboard_metrics": "scoreboard",
            }
            projection_name = projection_names[table]
            with duckdb.connect(str(path), read_only=True) as connection:
                run = connection.execute(
                    "SELECT projection_version, source_high_watermark, finished_at "
                    "FROM projection_runs WHERE projection_name = ? "
                    "AND status = 'succeeded' ORDER BY finished_at DESC, run_id DESC LIMIT 1",
                    [projection_name],
                ).fetchone()
            if run is None:
                return unavailable
            version, watermark, built_at = run
            stale = int(watermark) < self.action_high_watermark()
            return {
                "health": {
                    "state": "stale" if stale else "available",
                    "code": "projection_stale" if stale else None,
                    "instruction": (
                        "run `nutmeg ontology calibrate`" if stale else None
                    ),
                    "projection_version": str(version),
                    "source_high_watermark": int(watermark),
                    "built_at": str(built_at),
                    "cohort_definition_version": None,
                    "metric_version": None,
                },
                "rows": [],
            }
        identities = {
            (
                str(row["projection_version"]),
                int(row["source_high_watermark"]),
                str(row["built_at"]),
                str(row["cohort_definition_version"]),
                str(row["metric_version"]),
            )
            for row in rows
        }
        if len(identities) != 1:
            raise ValueError(f"projection {table} has ambiguous provenance")
        version, watermark, built_at, cohort_version, metric_version = identities.pop()
        stale = watermark < self.action_high_watermark()
        return {
            "health": {
                "state": "stale" if stale else "available",
                "code": "projection_stale" if stale else None,
                "instruction": "run `nutmeg ontology calibrate`" if stale else None,
                "projection_version": version,
                "source_high_watermark": watermark,
                "built_at": built_at,
                "cohort_definition_version": cohort_version,
                "metric_version": metric_version,
            },
            "rows": rows,
        }

    def settlements(self, *, as_of: str) -> list[dict]:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(sf.ticket_settlements)
                    .where(sf.ticket_settlements.c.settled_at <= as_of)
                    .order_by(
                        sf.ticket_settlements.c.settled_at.desc(),
                        sf.ticket_settlements.c.ticket_settlement_id,
                    )
                )
                .mappings()
                .all()
            )
        return [
            self._decode_json(row, ("bet_leg_settlement_ids_json",)) for row in rows
        ]

    def ontology_objects(
        self,
        *,
        object_type: str,
        query: str | None,
        after: str | None,
        limit: int,
        as_of: str,
    ) -> dict:
        if not 1 <= limit <= 1000:
            raise ValueError("ontology object limit must be between 1 and 1000")
        items = self._ontology_summaries(object_type, as_of)
        query_text = (query or "").strip().casefold()
        if query_text:
            items = [
                item
                for item in items
                if query_text in item["object_id"].casefold()
                or query_text in item["label"].casefold()
            ]
        if after is not None:
            cursor = self._decode_ontology_cursor(after)
            items = [item for item in items if self._ontology_sort_key(item) > cursor]
        page = items[: limit + 1]
        has_more = len(page) > limit
        page = page[:limit]
        return {
            "items": page,
            "next_cursor": (
                self._encode_ontology_cursor(self._ontology_sort_key(page[-1]))
                if has_more and page
                else None
            ),
        }

    def ontology_object(
        self, object_type: str, object_id: str, *, as_of: str
    ) -> dict | None:
        if object_type == "match":
            with self._engine.connect() as connection:
                versions = (
                    connection.execute(
                        select(si.match_revisions)
                        .where(
                            si.match_revisions.c.match_id == object_id,
                            si.match_revisions.c.recorded_at <= as_of,
                        )
                        .order_by(
                            si.match_revisions.c.recorded_at,
                            si.match_revisions.c.version,
                        )
                    )
                    .mappings()
                    .all()
                )
            if not versions:
                return None
            public_versions = [dict(row) for row in versions]
            properties = {
                "match_id": object_id,
                "current_revision_id": public_versions[-1]["match_revision_id"],
                "status": public_versions[-1]["status"],
                "scheduled_at": public_versions[-1]["scheduled_at"],
            }
        else:
            specification = self._ontology_spec(object_type)
            table, id_name, label_name, status_name, recorded_name, json_columns = specification
            statement = select(table).where(table.c[id_name] == object_id)
            if recorded_name is not None:
                statement = statement.where(table.c[recorded_name] <= as_of)
            with self._engine.connect() as connection:
                row = connection.execute(statement).mappings().first()
            if row is None:
                return None
            properties = self._public_object_properties(
                object_type, row, json_columns
            )
            public_versions = [dict(properties)]
            del label_name, status_name
        lineage = self.lineage(object_type, object_id, as_of=as_of) or []
        return {
            "object_type": object_type,
            "object_id": object_id,
            "properties": properties,
            "versions": public_versions,
            "links": [
                {
                    "relation": relation,
                    "source": {"object_type": source_type, "object_id": source_id},
                    "target": {"object_type": target_type, "object_id": target_id},
                }
                for relation, source_type, source_id, target_type, target_id in lineage
            ],
            "actions": self._object_action_history(object_type, object_id, as_of),
        }

    def _ontology_summaries(self, object_type: str, as_of: str) -> list[dict]:
        if object_type == "match":
            with self._engine.connect() as connection:
                rows = (
                    connection.execute(
                        select(si.match_revisions).where(
                            si.match_revisions.c.recorded_at <= as_of
                        )
                    )
                    .mappings()
                    .all()
                )
            current: dict[str, dict] = {}
            for row in rows:
                item = dict(row)
                prior = current.get(item["match_id"])
                if prior is None or (item["recorded_at"], item["version"]) > (
                    prior["recorded_at"],
                    prior["version"],
                ):
                    current[item["match_id"]] = item
            items = [
                {
                    "object_type": "match",
                    "object_id": match_id,
                    "label": match_id,
                    "status": row["status"],
                    "recorded_at": row["recorded_at"],
                }
                for match_id, row in current.items()
            ]
        else:
            table, id_name, label_name, status_name, recorded_name, _json = (
                self._ontology_spec(object_type)
            )
            statement = select(table)
            if recorded_name is not None:
                statement = statement.where(table.c[recorded_name] <= as_of)
            with self._engine.connect() as connection:
                rows = connection.execute(statement).mappings().all()
            items = [
                {
                    "object_type": object_type,
                    "object_id": str(row[id_name]),
                    "label": str(row[label_name] or row[id_name]),
                    "status": (
                        str(row[status_name])
                        if status_name is not None and row[status_name] is not None
                        else None
                    ),
                    "recorded_at": (
                        str(row[recorded_name])
                        if recorded_name is not None and row[recorded_name] is not None
                        else None
                    ),
                }
                for row in rows
            ]
        return sorted(items, key=self._ontology_sort_key)

    @staticmethod
    def _ontology_spec(object_type: str):
        specifications = {
            "team": (
                si.teams,
                "team_id",
                "canonical_name",
                "resolution_status",
                "created_at",
                (),
            ),
            "competition": (
                si.competitions,
                "competition_id",
                "name",
                None,
                None,
                (),
            ),
            "person": (
                sc.persons,
                "person_id",
                "canonical_name",
                "resolution_status",
                "created_at",
                (),
            ),
            "claim": (
                se.claims,
                "claim_id",
                "predicate",
                "status",
                "created_at",
                ("value_json",),
            ),
            "observation": (
                se.observations,
                "observation_id",
                "observation_type",
                "verification_method",
                "recorded_at",
                ("value_json", "quality_json"),
            ),
            "market_snapshot": (
                sm.market_snapshots,
                "market_snapshot_id",
                "market_definition_id",
                "snapshot_kind",
                "as_of",
                (
                    "fair_distribution_json",
                    "source_coverage_json",
                    "freshness_json",
                    "disagreement_json",
                ),
            ),
            "forecast_revision": (
                sd.forecast_revisions,
                "forecast_revision_id",
                "forecast_revision_id",
                "status",
                "made_at",
                ("prior_distribution_json", "belief_distribution_json"),
            ),
            "factor_definition": (
                sd.factor_definitions,
                "factor_definition_id",
                "name",
                "status",
                "valid_from",
                ("born_from_refs_json",),
            ),
            "ticket": (sf.tickets, "ticket_id", "structure", "status", "approved_at", ()),
            "outcome": (
                sf.match_outcomes,
                "outcome_id",
                "match_id",
                "status",
                "recorded_at",
                ("source_artifact_retrieval_ids_json",),
            ),
            "settlement": (
                sf.ticket_settlements,
                "ticket_settlement_id",
                "ticket_id",
                "status",
                "settled_at",
                ("bet_leg_settlement_ids_json",),
            ),
            "adjudication": (
                sw.adjudications,
                "adjudication_id",
                "decision",
                "decision",
                "created_at",
                ("evidence_rejected_json", "alternative_json"),
            ),
            "flag_instance": (
                sw.flag_instances,
                "flag_instance_id",
                "flag_type",
                "status",
                "created_at",
                ("evidence_refs_json",),
            ),
            "prediction": (sw.predictions, "prediction_id", "claim", "status", "registered_at", ()),
            "action": (
                schema.actions,
                "action_id",
                "action_type",
                "status",
                "requested_at",
                ("result_refs_json",),
            ),
        }
        try:
            return specifications[object_type]
        except KeyError as error:
            raise ValueError(
                f"ontology object type {object_type} is not allowlisted"
            ) from error

    @staticmethod
    def _public_object_properties(object_type: str, row, json_columns) -> dict:
        properties = dict(row)
        for column in json_columns:
            properties[column.removesuffix("_json")] = json.loads(
                properties.pop(column)
            )
        if object_type == "action":
            for field in (
                "payload_json",
                "request_hash",
                "expected_versions_json",
                "idempotency_key",
                "error_detail",
            ):
                properties.pop(field, None)
        return properties

    def _object_action_history(
        self, object_type: str, object_id: str, as_of: str
    ) -> list[dict]:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(
                        schema.actions.c.action_id,
                        schema.actions.c.action_type,
                        schema.actions.c.actor_id,
                        schema.actions.c.actor_role,
                        schema.actions.c.requested_at,
                        schema.actions.c.status,
                        schema.actions.c.result_refs_json,
                        schema.actions.c.error_code,
                        schema.actions.c.committed_at,
                    )
                    .where(schema.actions.c.requested_at <= as_of)
                    .order_by(schema.actions.c.requested_at, schema.actions.c.action_id)
                )
                .mappings()
                .all()
            )
        history: list[dict] = []
        for row in rows:
            refs = json.loads(row["result_refs_json"])
            if not any(
                ref.get("object_type") == object_type
                and ref.get("object_id") == object_id
                for ref in refs
            ):
                continue
            item = dict(row)
            item.pop("result_refs_json")
            item["result_refs"] = refs
            history.append(item)
        return history

    @staticmethod
    def _ontology_sort_key(item: dict) -> tuple[str, str]:
        return str(item.get("recorded_at") or ""), str(item["object_id"])

    @staticmethod
    def _encode_ontology_cursor(cursor: tuple[str, str]) -> str:
        return base64.urlsafe_b64encode(
            json.dumps(cursor, separators=(",", ":")).encode("utf-8")
        ).decode("ascii")

    @staticmethod
    def _decode_ontology_cursor(value: str) -> tuple[str, str]:
        try:
            decoded = json.loads(base64.urlsafe_b64decode(value.encode("ascii")))
        except (ValueError, json.JSONDecodeError) as error:
            raise ValueError("ontology cursor is invalid") from error
        if not isinstance(decoded, list) or len(decoded) != 2:
            raise ValueError("ontology cursor is invalid")
        return str(decoded[0]), str(decoded[1])

    def board_matches(self, start_at: str, end_at: str, as_of: str) -> list[dict]:
        statement = self._match_statement(as_of).where(
            si.match_revisions.c.scheduled_at >= start_at,
            si.match_revisions.c.scheduled_at < end_at,
        )
        with self._engine.connect() as connection:
            return [dict(row) for row in connection.execute(statement).mappings().all()]

    def match(self, match_id: str, as_of: str) -> dict | None:
        statement = self._match_statement(as_of).where(si.matches.c.match_id == match_id)
        with self._engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        return dict(row) if row is not None else None

    @staticmethod
    def _match_statement(as_of: str):
        home_appearance = si.team_appearances.alias('home_appearance')
        away_appearance = si.team_appearances.alias('away_appearance')
        home_team = si.teams.alias('home_team')
        away_team = si.teams.alias('away_team')
        current_at_cutoff = (
            select(si.match_revisions.c.match_revision_id)
            .where(
                si.match_revisions.c.match_id == si.matches.c.match_id,
                si.match_revisions.c.recorded_at <= as_of,
            )
            .order_by(
                si.match_revisions.c.recorded_at.desc(),
                si.match_revisions.c.version.desc(),
            )
            .limit(1)
            .correlate(si.matches)
            .scalar_subquery()
        )
        return (
            select(
                si.matches.c.match_id,
                si.match_revisions.c.match_revision_id,
                si.match_revisions.c.scheduled_at,
                si.match_revisions.c.status,
                si.match_revisions.c.schedule_status,
                home_team.c.canonical_name.label('home_team'),
                away_team.c.canonical_name.label('away_team'),
                home_team.c.team_id.label('home_team_id'),
                away_team.c.team_id.label('away_team_id'),
                home_team.c.resolution_status.label('home_resolution_status'),
                away_team.c.resolution_status.label('away_resolution_status'),
                si.competitions.c.competition_id,
                si.competition_editions.c.competition_edition_id,
                si.competitions.c.name.label('competition'),
                si.match_revisions.c.round_label,
                si.match_revisions.c.venue_id,
            )
            .select_from(
                si.matches.join(
                    si.match_revisions,
                    si.match_revisions.c.match_revision_id == current_at_cutoff,
                )
                .join(
                    home_appearance,
                    and_(
                        home_appearance.c.match_id == si.matches.c.match_id,
                        home_appearance.c.side.in_(['home', 'neutral_designated_home']),
                    ),
                )
                .join(home_team, home_team.c.team_id == home_appearance.c.team_id)
                .join(
                    away_appearance,
                    and_(
                        away_appearance.c.match_id == si.matches.c.match_id,
                        away_appearance.c.side.in_(['away', 'neutral_designated_away']),
                    ),
                )
                .join(away_team, away_team.c.team_id == away_appearance.c.team_id)
                .outerjoin(
                    si.competition_editions,
                    si.competition_editions.c.competition_edition_id
                    == si.match_revisions.c.competition_edition_id,
                )
                .outerjoin(
                    si.competitions,
                    si.competitions.c.competition_id
                    == si.competition_editions.c.competition_id,
                )
            )
            .order_by(si.match_revisions.c.scheduled_at, si.matches.c.match_id)
        )

    def latest_snapshot(
        self, match_id: str, market_definition_id: str, as_of: str
    ) -> dict | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(sm.market_snapshots)
                    .where(
                        sm.market_snapshots.c.match_id == match_id,
                        sm.market_snapshots.c.market_definition_id
                        == market_definition_id,
                        func.julianday(sm.market_snapshots.c.as_of)
                        <= func.julianday(as_of),
                    )
                    .order_by(
                        func.julianday(sm.market_snapshots.c.as_of).desc(),
                        sm.market_snapshots.c.market_snapshot_id.desc(),
                    )
                    .limit(1)
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        result = dict(row)
        result['fair_distribution'] = json.loads(result.pop('fair_distribution_json'))
        return result

    def claims_for_match(self, match_id: str, as_of: str) -> list[dict]:
        status_at_cutoff = (
            select(se.claim_status_events.c.to_status)
            .where(
                se.claim_status_events.c.claim_id == se.claims.c.claim_id,
                se.claim_status_events.c.at <= as_of,
            )
            .order_by(
                se.claim_status_events.c.at.desc(),
                se.claim_status_events.c.claim_status_event_id.desc(),
            )
            .limit(1)
            .correlate(se.claims)
            .scalar_subquery()
        )
        has_status_history = (
            select(se.claim_status_events.c.claim_status_event_id)
            .where(se.claim_status_events.c.claim_id == se.claims.c.claim_id)
            .correlate(se.claims)
            .exists()
        )
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(
                        se.claims,
                        case(
                            (has_status_history, status_at_cutoff),
                            else_=se.claims.c.status,
                        ).label('status_at_cutoff'),
                    )
                    .where(
                        se.claims.c.created_at <= as_of,
                        (
                            (se.claims.c.scope_match_id == match_id)
                            | and_(
                                se.claims.c.subject_type == 'match',
                                se.claims.c.subject_id == match_id,
                            )
                        ),
                    )
                    .order_by(se.claims.c.created_at, se.claims.c.claim_id)
                )
                .mappings()
                .all()
            )
            claim_ids = [row['claim_id'] for row in rows]
            span_rows = (
                connection.execute(
                    select(se.claim_evidence_spans)
                    .where(se.claim_evidence_spans.c.claim_id.in_(claim_ids))
                    .order_by(
                        se.claim_evidence_spans.c.claim_id,
                        se.claim_evidence_spans.c.claim_evidence_span_id,
                    )
                )
                .mappings()
                .all()
                if claim_ids
                else []
            )
        spans_by_claim: dict[str, list[dict]] = {claim_id: [] for claim_id in claim_ids}
        for span in span_rows:
            spans_by_claim[span['claim_id']].append(
                {
                    'object_type': 'claim',
                    'object_id': span['claim_id'],
                    'artifact_id': span['artifact_id'],
                    'artifact_retrieval_id': span['artifact_retrieval_id'],
                    'quote': span['quote'],
                    'locator': span['locator'],
                }
            )
        result: list[dict] = []
        for row in rows:
            item = self._decode_json(row, ('value_json',))
            item['status'] = item.pop('status_at_cutoff')
            item['spans'] = spans_by_claim[item['claim_id']]
            result.append(item)
        return result

    def claim(self, claim_id: str) -> dict | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(se.claims).where(se.claims.c.claim_id == claim_id)
            ).mappings().first()
        if row is None:
            return None
        return self._decode_json(row, ('value_json',))

    def observations_for_match(self, match_id: str, as_of: str) -> list[dict]:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(se.observations)
                    .where(
                        se.observations.c.recorded_at <= as_of,
                        (
                            (se.observations.c.scope_match_id == match_id)
                            | and_(
                                se.observations.c.subject_type == 'match',
                                se.observations.c.subject_id == match_id,
                            )
                        ),
                    )
                    .order_by(se.observations.c.recorded_at, se.observations.c.observation_id)
                )
                .mappings()
                .all()
            )
            observation_ids = [row['observation_id'] for row in rows]
            source_rows = (
                connection.execute(
                    select(se.observation_sources)
                    .where(se.observation_sources.c.observation_id.in_(observation_ids))
                    .order_by(
                        se.observation_sources.c.observation_id,
                        se.observation_sources.c.artifact_retrieval_id,
                    )
                )
                .mappings()
                .all()
                if observation_ids
                else []
            )
        sources_by_observation: dict[str, list[str]] = {
            observation_id: [] for observation_id in observation_ids
        }
        for source in source_rows:
            sources_by_observation[source['observation_id']].append(
                source['artifact_retrieval_id']
            )
        result = [
            self._decode_json(row, ('value_json', 'quality_json')) for row in rows
        ]
        for item in result:
            item['source_retrieval_ids'] = sources_by_observation[item['observation_id']]
        return result

    def market_timeline(
        self, match_id: str, market_definition_id: str, as_of: str
    ) -> list[dict]:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(sm.market_snapshots)
                    .where(
                        sm.market_snapshots.c.match_id == match_id,
                        sm.market_snapshots.c.market_definition_id
                        == market_definition_id,
                        func.julianday(sm.market_snapshots.c.as_of)
                        <= func.julianday(as_of),
                    )
                    .order_by(
                        func.julianday(sm.market_snapshots.c.as_of),
                        sm.market_snapshots.c.market_snapshot_id,
                    )
                )
                .mappings()
                .all()
            )
        return [
            self._decode_json(
                row,
                (
                    'fair_distribution_json',
                    'source_coverage_json',
                    'freshness_json',
                    'disagreement_json',
                ),
            )
            for row in rows
        ]

    def evidence_bundles_for_match(self, match_id: str, as_of: str) -> list[dict]:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(sd.evidence_bundles)
                    .where(
                        sd.evidence_bundles.c.match_id == match_id,
                        sd.evidence_bundles.c.frozen_at <= as_of,
                    )
                    .order_by(
                        sd.evidence_bundles.c.frozen_at,
                        sd.evidence_bundles.c.evidence_bundle_id,
                    )
                )
                .mappings()
                .all()
            )
            bundle_ids = [row['evidence_bundle_id'] for row in rows]
            item_rows = (
                connection.execute(
                    select(sd.evidence_bundle_items)
                    .where(sd.evidence_bundle_items.c.evidence_bundle_id.in_(bundle_ids))
                    .order_by(
                        sd.evidence_bundle_items.c.evidence_bundle_id,
                        sd.evidence_bundle_items.c.item_type,
                        sd.evidence_bundle_items.c.item_id,
                    )
                )
                .mappings()
                .all()
                if bundle_ids
                else []
            )
        items_by_bundle: dict[str, list[dict[str, str]]] = {
            bundle_id: [] for bundle_id in bundle_ids
        }
        for item in item_rows:
            if item['observation_id'] is not None:
                object_type = 'observation'
                object_id = item['observation_id']
            else:
                object_type = 'claim'
                object_id = item['claim_id']
            items_by_bundle[item['evidence_bundle_id']].append(
                {'object_type': object_type, 'object_id': object_id}
            )
        result = [
            self._decode_json(
                row,
                (
                    'prior_distribution_json',
                    'source_coverage_json',
                    'freshness_json',
                ),
            )
            for row in rows
        ]
        for item in result:
            item['item_refs'] = items_by_bundle[item['evidence_bundle_id']]
        return result

    def agent_proposals_for_match(self, match_id: str, as_of: str) -> list[dict]:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(sw.agent_proposals)
                    .where(
                        sw.agent_proposals.c.subject_type == 'match',
                        sw.agent_proposals.c.subject_id == match_id,
                        sw.agent_proposals.c.created_at <= as_of,
                    )
                    .order_by(
                        sw.agent_proposals.c.created_at,
                        sw.agent_proposals.c.agent_proposal_id,
                    )
                )
                .mappings()
                .all()
            )
        return [
            self._decode_json(row, ('payload_json', 'citation_refs_json'))
            for row in rows
        ]

    def agent_proposal(self, proposal_id: str) -> dict | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(sw.agent_proposals).where(
                    sw.agent_proposals.c.agent_proposal_id == proposal_id
                )
            ).mappings().first()
        if row is None:
            return None
        return self._decode_json(row, ('payload_json', 'citation_refs_json'))

    def flag_instances_for_match(self, match_id: str, as_of: str) -> list[dict]:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(sw.flag_instances)
                    .where(
                        sw.flag_instances.c.match_id == match_id,
                        sw.flag_instances.c.created_at <= as_of,
                    )
                    .order_by(
                        sw.flag_instances.c.created_at,
                        sw.flag_instances.c.flag_instance_id,
                    )
                )
                .mappings()
                .all()
            )
        return [self._decode_json(row, ('evidence_refs_json',)) for row in rows]

    def predictions_for_match(self, match_id: str, as_of: str) -> list[dict]:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(sw.predictions)
                    .where(
                        sw.predictions.c.match_id == match_id,
                        sw.predictions.c.registered_at <= as_of,
                    )
                    .order_by(
                        sw.predictions.c.registered_at,
                        sw.predictions.c.prediction_id,
                    )
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    def precedents_for_match(self, match_id: str, as_of: str) -> list[dict]:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(sw.precedent_links)
                    .where(
                        sw.precedent_links.c.subject_type == 'match',
                        sw.precedent_links.c.subject_id == match_id,
                        sw.precedent_links.c.created_at <= as_of,
                    )
                    .order_by(
                        sw.precedent_links.c.created_at,
                        sw.precedent_links.c.precedent_link_id,
                    )
                )
                .mappings()
                .all()
            )
        return [self._decode_json(row, ('evidence_refs_json',)) for row in rows]

    def adjudications_for_match(self, match_id: str, as_of: str) -> list[dict]:
        claim_ids = select(se.claims.c.claim_id).where(
            or_(
                se.claims.c.scope_match_id == match_id,
                and_(
                    se.claims.c.subject_type == 'match',
                    se.claims.c.subject_id == match_id,
                ),
            )
        )
        observation_ids = select(se.observations.c.observation_id).where(
            or_(
                se.observations.c.scope_match_id == match_id,
                and_(
                    se.observations.c.subject_type == 'match',
                    se.observations.c.subject_id == match_id,
                ),
            )
        )
        proposal_ids = select(sw.agent_proposals.c.agent_proposal_id).where(
            sw.agent_proposals.c.subject_type == 'match',
            sw.agent_proposals.c.subject_id == match_id,
        )
        forecast_ids = (
            select(sd.forecast_revisions.c.forecast_revision_id)
            .select_from(
                sd.forecast_revisions.join(
                    sd.forecast_series,
                    sd.forecast_revisions.c.forecast_series_id
                    == sd.forecast_series.c.forecast_series_id,
                )
            )
            .where(sd.forecast_series.c.match_id == match_id)
        )
        subject_matches = or_(
            and_(
                sw.adjudications.c.subject_type == 'match',
                sw.adjudications.c.subject_id == match_id,
            ),
            and_(
                sw.adjudications.c.subject_type == 'claim',
                sw.adjudications.c.subject_id.in_(claim_ids),
            ),
            and_(
                sw.adjudications.c.subject_type == 'observation',
                sw.adjudications.c.subject_id.in_(observation_ids),
            ),
            and_(
                sw.adjudications.c.subject_type == 'agent_proposal',
                sw.adjudications.c.subject_id.in_(proposal_ids),
            ),
            and_(
                sw.adjudications.c.subject_type == 'forecast_revision',
                sw.adjudications.c.subject_id.in_(forecast_ids),
            ),
        )
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(sw.adjudications)
                    .where(
                        subject_matches,
                        sw.adjudications.c.created_at <= as_of,
                    )
                    .order_by(
                        sw.adjudications.c.created_at,
                        sw.adjudications.c.adjudication_id,
                    )
                )
                .mappings()
                .all()
            )
        return [
            self._decode_json(
                row, ('evidence_rejected_json', 'alternative_json')
            )
            for row in rows
        ]

    def forecasts_for_match(self, match_id: str, as_of: str) -> list[dict]:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(sd.forecast_revisions, sd.forecast_series.c.market_definition_id)
                    .select_from(
                        sd.forecast_revisions.join(
                            sd.forecast_series,
                            sd.forecast_revisions.c.forecast_series_id
                            == sd.forecast_series.c.forecast_series_id,
                        )
                    )
                    .where(
                        sd.forecast_series.c.match_id == match_id,
                        sd.forecast_revisions.c.made_at <= as_of,
                    )
                    .order_by(
                        sd.forecast_revisions.c.made_at,
                        sd.forecast_revisions.c.revision_no,
                    )
                )
                .mappings()
                .all()
            )
        return [
            self._decode_json(
                row, ('prior_distribution_json', 'belief_distribution_json')
            )
            for row in rows
        ]

    def workflow_for_match(self, match_id: str, as_of: str) -> list[dict]:
        specifications = (
            (
                sw.adjudications,
                sw.adjudications.c.adjudication_id,
                'adjudication',
                sw.adjudications.c.decision,
                sw.adjudications.c.created_at,
                and_(
                    sw.adjudications.c.subject_type == 'match',
                    sw.adjudications.c.subject_id == match_id,
                ),
            ),
            (
                sw.flag_instances,
                sw.flag_instances.c.flag_instance_id,
                'flag_instance',
                sw.flag_instances.c.status,
                sw.flag_instances.c.created_at,
                sw.flag_instances.c.match_id == match_id,
            ),
            (
                sw.predictions,
                sw.predictions.c.prediction_id,
                'prediction',
                sw.predictions.c.status,
                sw.predictions.c.registered_at,
                sw.predictions.c.match_id == match_id,
            ),
            (
                sw.precedent_links,
                sw.precedent_links.c.precedent_link_id,
                'precedent_link',
                None,
                sw.precedent_links.c.created_at,
                and_(
                    sw.precedent_links.c.subject_type == 'match',
                    sw.precedent_links.c.subject_id == match_id,
                ),
            ),
            (
                sw.agent_proposals,
                sw.agent_proposals.c.agent_proposal_id,
                'agent_proposal',
                sw.agent_proposals.c.status,
                sw.agent_proposals.c.created_at,
                and_(
                    sw.agent_proposals.c.subject_type == 'match',
                    sw.agent_proposals.c.subject_id == match_id,
                ),
            ),
        )
        objects: list[dict] = []
        with self._engine.connect() as connection:
            for (
                table,
                id_column,
                object_type,
                status_column,
                at_column,
                condition,
            ) in specifications:
                selected = [id_column.label('object_id'), at_column.label('created_at')]
                if status_column is not None:
                    selected.append(status_column.label('status'))
                rows = connection.execute(
                    select(*selected)
                    .select_from(table)
                    .where(condition, at_column <= as_of)
                ).mappings()
                for row in rows:
                    objects.append(
                        {
                            'object_type': object_type,
                            'object_id': row['object_id'],
                            'status': row.get('status') or 'linked',
                            'created_at': row['created_at'],
                        }
                    )
        return sorted(objects, key=lambda item: (item['created_at'], item['object_id']))

    def actions(self, *, after: str | None, limit: int) -> list[dict]:
        with self._engine.connect() as connection:
            statement = select(schema.actions)
            if after is not None:
                cursor = connection.execute(
                    select(schema.actions.c.requested_at, schema.actions.c.action_id).where(
                        schema.actions.c.action_id == after
                    )
                ).first()
                if cursor is None:
                    return []
                statement = statement.where(
                    or_(
                        schema.actions.c.requested_at > cursor.requested_at,
                        and_(
                            schema.actions.c.requested_at == cursor.requested_at,
                            schema.actions.c.action_id > cursor.action_id,
                        ),
                    )
                )
            rows = (
                connection.execute(
                    statement.order_by(
                        schema.actions.c.requested_at, schema.actions.c.action_id
                    ).limit(limit)
                )
                .mappings()
                .all()
            )
        return [self._decode_json(row, ('result_refs_json',)) for row in rows]

    def events(self, after: int, *, limit: int) -> list[OutboxEventRow]:
        with self._engine.connect() as connection:
            return OutboxRepository(connection).after(after, limit=limit)

    def source_health(self, as_of: str) -> list[dict]:
        with self._engine.connect() as connection:
            retrievals = connection.execute(
                select(schema.artifact_retrievals)
                .where(schema.artifact_retrievals.c.retrieved_at <= as_of)
                .order_by(
                    schema.artifact_retrievals.c.source_name,
                    schema.artifact_retrievals.c.source_type,
                    schema.artifact_retrievals.c.retrieved_at.desc(),
                )
            ).mappings().all()
            runs = connection.execute(
                select(schema.source_runs)
                .where(schema.source_runs.c.started_at <= as_of)
                .order_by(
                    schema.source_runs.c.source_name,
                    schema.source_runs.c.started_at.desc(),
                )
            ).mappings().all()

        latest_runs: dict[str, dict] = {}
        for row in runs:
            latest_runs.setdefault(row['source_name'], dict(row))
        grouped: dict[tuple[str, str], dict] = {}
        for row in retrievals:
            key = (row['source_name'], row['source_type'])
            if key not in grouped:
                run = latest_runs.get(row['source_name'])
                grouped[key] = {
                    'source_name': row['source_name'],
                    'source_type': row['source_type'],
                    'status': run['status'] if run is not None else row['status'],
                    'retrieval_count': 0,
                    'latest_retrieved_at': row['retrieved_at'],
                    'error_code': run['error_code'] if run is not None else None,
                    'error_detail': run['error_detail'] if run is not None else None,
                }
            grouped[key]['retrieval_count'] += 1
        return [grouped[key] for key in sorted(grouped)]

    def identity_queue(self, *, limit: int) -> list[dict]:
        with self._engine.connect() as connection:
            ids = connection.execute(
                select(si.teams.c.team_id)
                .where(si.teams.c.resolution_status == 'provisional')
                .order_by(si.teams.c.created_at.desc(), si.teams.c.team_id)
                .limit(limit)
            ).scalars().all()
        return [
            item
            for entity_id in ids
            if (item := self.identity_item('team', entity_id)) is not None
        ]

    def unresolved_identity_count(self) -> int:
        with self._engine.connect() as connection:
            value = connection.execute(
                select(func.count()).select_from(si.teams).where(
                    si.teams.c.resolution_status == 'provisional'
                )
            ).scalar_one()
        return int(value)

    def identity_item(self, entity_type: str, entity_id: str) -> dict | None:
        if entity_type != 'team':
            return None
        with self._engine.connect() as connection:
            row = connection.execute(
                select(si.teams).where(si.teams.c.team_id == entity_id)
            ).mappings().first()
            if row is None:
                return None
            external = connection.execute(
                select(
                    si.external_identifiers.c.provider,
                    si.external_identifiers.c.external_id,
                )
                .where(
                    si.external_identifiers.c.entity_type == 'team',
                    si.external_identifiers.c.entity_id == entity_id,
                )
                .order_by(
                    si.external_identifiers.c.provider,
                    si.external_identifiers.c.external_id,
                )
            ).all()
            aliases = connection.execute(
                select(si.entity_aliases.c.normalized_alias)
                .where(
                    si.entity_aliases.c.entity_type == 'team',
                    si.entity_aliases.c.entity_id == entity_id,
                )
                .order_by(si.entity_aliases.c.normalized_alias)
            ).scalars().all()
        return {
            'entity_type': 'team',
            'entity_id': row['team_id'],
            'canonical_name': row['canonical_name'],
            'resolution_status': row['resolution_status'],
            'country': row['country'],
            'created_at': row['created_at'],
            'external_identifiers': [
                f'{provider}:{external_id}' for provider, external_id in external
            ],
            'aliases': list(aliases),
        }

    def failed_actions(self, *, limit: int) -> list[dict]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(schema.actions)
                .where(schema.actions.c.status.in_(('failed', 'rejected')))
                .order_by(
                    schema.actions.c.requested_at.desc(),
                    schema.actions.c.action_id.desc(),
                )
                .limit(limit)
            ).mappings().all()
        return [self._decode_json(row, ('result_refs_json',)) for row in rows]

    def action_high_watermark(self) -> int:
        with self._engine.connect() as connection:
            value = connection.exec_driver_sql(
                'SELECT COALESCE(MAX(rowid), 0) FROM actions'
            ).scalar_one()
        return int(value)

    def actions_after_high_watermark(self, watermark: int) -> list[dict]:
        if watermark < 0:
            raise ValueError('action high-watermark cannot be negative')
        with self._engine.connect() as connection:
            rows = connection.exec_driver_sql(
                'SELECT rowid, action_id, action_type, status, result_refs_json '
                'FROM actions WHERE rowid > ? ORDER BY rowid',
                (watermark,),
            ).mappings().all()
        return [
            {
                'rowid': int(row['rowid']),
                'action_id': str(row['action_id']),
                'action_type': str(row['action_type']),
                'status': str(row['status']),
                'result_refs': json.loads(row['result_refs_json']),
            }
            for row in rows
        ]

    def pending_workflow_count(self, *, as_of: str) -> int:
        with self._engine.connect() as connection:
            proposals = connection.execute(
                select(func.count()).select_from(sw.agent_proposals).where(
                    sw.agent_proposals.c.status == 'pending',
                    sw.agent_proposals.c.created_at <= as_of,
                )
            ).scalar_one()
            predictions = connection.execute(
                select(func.count()).select_from(sw.predictions).where(
                    sw.predictions.c.status == 'pending',
                    sw.predictions.c.registered_at <= as_of,
                )
            ).scalar_one()
        return int(proposals) + int(predictions)

    def flag_count_for_match(self, match_id: str, *, as_of: str) -> int:
        with self._engine.connect() as connection:
            value = connection.execute(
                select(func.count()).select_from(sw.flag_instances).where(
                    sw.flag_instances.c.match_id == match_id,
                    sw.flag_instances.c.created_at <= as_of,
                )
            ).scalar_one()
        return int(value)

    def ticket_forecast_at(
        self, match_id: str, market_definition_id: str, as_of: str
    ) -> dict | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(
                        sd.forecast_revisions,
                        sd.forecast_series.c.market_definition_id,
                    )
                    .select_from(
                        sd.forecast_revisions.join(
                            sd.forecast_series,
                            sd.forecast_revisions.c.forecast_series_id
                            == sd.forecast_series.c.forecast_series_id,
                        )
                    )
                    .where(
                        sd.forecast_series.c.match_id == match_id,
                        sd.forecast_series.c.market_definition_id
                        == market_definition_id,
                        sd.forecast_revisions.c.status.in_(
                            ('committed', 'superseded')
                        ),
                        func.julianday(sd.forecast_revisions.c.made_at)
                        <= func.julianday(as_of),
                    )
                    .order_by(
                        func.julianday(sd.forecast_revisions.c.made_at).desc(),
                        sd.forecast_revisions.c.revision_no.desc(),
                    )
                    .limit(1)
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return self._decode_json(
            row, ('prior_distribution_json', 'belief_distribution_json')
        )

    def ticket_selections_at(
        self, match_id: str, market_definition_id: str, as_of: str
    ) -> list[dict]:
        latest_quote_id = (
            select(sm.market_quotes.c.quote_id)
            .where(
                sm.market_quotes.c.match_id == match_id,
                sm.market_quotes.c.market_definition_id == market_definition_id,
                sm.market_quotes.c.selection_id
                == sm.selection_definitions.c.selection_id,
                sm.market_quotes.c.quote_status == 'active',
                func.julianday(sm.market_quotes.c.captured_at)
                <= func.julianday(as_of),
            )
            .order_by(
                func.julianday(sm.market_quotes.c.captured_at).desc(),
                sm.market_quotes.c.quote_id.desc(),
            )
            .limit(1)
            .correlate(sm.selection_definitions)
            .scalar_subquery()
        )
        statement = (
            select(
                sm.selection_definitions.c.market_definition_id,
                sm.selection_definitions.c.selection_id,
                sm.selection_definitions.c.outcome_key,
                sm.selection_definitions.c.line,
                sm.market_quotes.c.quote_id,
                sm.market_quotes.c.decimal_odds,
                sm.market_quotes.c.captured_at,
                sm.market_quotes.c.provider,
                sm.market_quotes.c.bookmaker,
            )
            .select_from(
                sm.selection_definitions.outerjoin(
                    sm.market_quotes,
                    sm.market_quotes.c.quote_id == latest_quote_id,
                )
            )
            .where(
                sm.selection_definitions.c.market_definition_id
                == market_definition_id
            )
            .order_by(
                sm.selection_definitions.c.outcome_key,
                sm.selection_definitions.c.selection_id,
            )
        )
        with self._engine.connect() as connection:
            return [
                dict(row) for row in connection.execute(statement).mappings().all()
            ]

    def adjudications_for_subject(
        self, subject_type: str, subject_id: str, as_of: str
    ) -> list[dict]:
        statement = (
            select(sw.adjudications)
            .where(
                sw.adjudications.c.subject_type == subject_type,
                sw.adjudications.c.subject_id == subject_id,
                sw.adjudications.c.created_at <= as_of,
            )
            .order_by(
                sw.adjudications.c.created_at,
                sw.adjudications.c.adjudication_id,
            )
        )
        with self._engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [
            self._decode_json(row, ("evidence_rejected_json", "alternative_json"))
            for row in rows
        ]

    def predictions_for_subject(
        self, subject_type: str, subject_id: str, as_of: str
    ) -> list[dict]:
        statement = (
            select(sw.predictions)
            .where(
                sw.predictions.c.subject_type == subject_type,
                sw.predictions.c.subject_id == subject_id,
                sw.predictions.c.registered_at <= as_of,
            )
            .order_by(
                sw.predictions.c.registered_at,
                sw.predictions.c.prediction_id,
            )
        )
        with self._engine.connect() as connection:
            return [
                dict(row) for row in connection.execute(statement).mappings().all()
            ]

    def operator_ticket_artifacts(self, as_of: str) -> list[dict]:
        batch = st.ticket_batch_revisions.alias("operator_batch")
        candidate = st.ticket_batch_revisions.alias("operator_batch_candidate")
        artifact = st.audited_ticket_artifacts.alias("operator_artifact")
        confirmation = st.ticket_confirmation_challenges.alias("operator_confirmation")
        placement = st.ticket_placements.alias("operator_placement")
        shadow = st.ticket_shadow_records.alias("operator_shadow")
        current_revision_id = (
            select(candidate.c.ticket_batch_revision_id)
            .where(
                candidate.c.ticket_batch_id == batch.c.ticket_batch_id,
                candidate.c.created_at <= as_of,
            )
            .order_by(candidate.c.revision_no.desc())
            .limit(1)
            .correlate(batch)
            .scalar_subquery()
        )
        latest_confirmation_id = (
            select(confirmation.c.confirmation_id)
            .where(
                confirmation.c.ticket_artifact_id == artifact.c.ticket_artifact_id,
                confirmation.c.issued_at <= as_of,
            )
            .order_by(
                confirmation.c.issued_at.desc(),
                confirmation.c.confirmation_id.desc(),
            )
            .limit(1)
            .correlate(artifact)
            .scalar_subquery()
        )
        statement = (
            select(
                batch.c.ticket_batch_revision_id,
                batch.c.ticket_batch_id,
                batch.c.revision_no,
                batch.c.run_date,
                batch.c.channel,
                batch.c.currency.label("batch_currency"),
                batch.c.deadline_at.label("batch_deadline_at"),
                batch.c.state.label("batch_state"),
                batch.c.content_hash,
                batch.c.created_at.label("batch_created_at"),
                artifact.c.ticket_artifact_id,
                artifact.c.ticket_index,
                artifact.c.ticket_hash,
                artifact.c.amount,
                artifact.c.currency,
                artifact.c.deadline_at,
                artifact.c.payload_json,
                artifact.c.approved_at,
                confirmation.c.confirmation_id,
                confirmation.c.issued_at,
                confirmation.c.expires_at,
                confirmation.c.consumed_at,
                placement.c.ticket_placement_id,
                placement.c.ticket_id,
                placement.c.external_reference,
                placement.c.placed_at,
                shadow.c.ticket_shadow_id,
                shadow.c.marked_at.label("shadow_marked_at"),
            )
            .select_from(
                batch.outerjoin(
                    artifact,
                    and_(
                        artifact.c.ticket_batch_revision_id
                        == batch.c.ticket_batch_revision_id,
                        artifact.c.approved_at <= as_of,
                    ),
                )
                .outerjoin(
                    confirmation,
                    confirmation.c.confirmation_id == latest_confirmation_id,
                )
                .outerjoin(
                    placement,
                    and_(
                        placement.c.ticket_artifact_id == artifact.c.ticket_artifact_id,
                        placement.c.placed_at <= as_of,
                    ),
                )
                .outerjoin(
                    shadow,
                    and_(
                        shadow.c.ticket_artifact_id == artifact.c.ticket_artifact_id,
                        shadow.c.marked_at <= as_of,
                    ),
                )
            )
            .where(
                batch.c.ticket_batch_revision_id == current_revision_id,
                batch.c.created_at <= as_of,
            )
            .order_by(batch.c.run_date, batch.c.ticket_batch_id, artifact.c.ticket_index)
        )
        with self._engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        result = []
        for row in rows:
            item = dict(row)
            payload = item.pop("payload_json")
            item["payload"] = json.loads(payload) if payload is not None else None
            result.append(item)
        return result

    def current_ticket_batches(self, run_date: str, as_of: str) -> list[dict]:
        current = st.ticket_batch_revisions.alias('current_ticket_batch')
        candidate = st.ticket_batch_revisions.alias('candidate_ticket_batch')
        current_revision_id = (
            select(candidate.c.ticket_batch_revision_id)
            .where(
                candidate.c.ticket_batch_id == current.c.ticket_batch_id,
                candidate.c.run_date == run_date,
                func.julianday(candidate.c.created_at) <= func.julianday(as_of),
            )
            .order_by(candidate.c.revision_no.desc())
            .limit(1)
            .correlate(current)
            .scalar_subquery()
        )
        statement = (
            select(current)
            .where(
                current.c.run_date == run_date,
                current.c.ticket_batch_revision_id == current_revision_id,
            )
            .order_by(current.c.created_at, current.c.ticket_batch_id)
        )
        with self._engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._ticket_batch_row(row) for row in rows]

    def ticket_batch_history(self, ticket_batch_id: str) -> list[dict]:
        statement = (
            select(st.ticket_batch_revisions)
            .where(st.ticket_batch_revisions.c.ticket_batch_id == ticket_batch_id)
            .order_by(st.ticket_batch_revisions.c.revision_no)
        )
        with self._engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._ticket_batch_row(row) for row in rows]

    def ticket_artifact_ids_for_revisions(
        self, revision_ids: list[str]
    ) -> dict[str, list[str]]:
        if not revision_ids:
            return {}
        statement = (
            select(
                st.audited_ticket_artifacts.c.ticket_batch_revision_id,
                st.audited_ticket_artifacts.c.ticket_artifact_id,
            )
            .where(
                st.audited_ticket_artifacts.c.ticket_batch_revision_id.in_(
                    revision_ids
                )
            )
            .order_by(
                st.audited_ticket_artifacts.c.ticket_batch_revision_id,
                st.audited_ticket_artifacts.c.ticket_index,
            )
        )
        result = {revision_id: [] for revision_id in revision_ids}
        with self._engine.connect() as connection:
            for revision_id, artifact_id in connection.execute(statement):
                result[revision_id].append(artifact_id)
        return result

    def ticket_artifact(self, ticket_artifact_id: str) -> dict | None:
        statement = (
            select(
                st.audited_ticket_artifacts,
                st.ticket_placements.c.ticket_placement_id,
                st.ticket_placements.c.ticket_id,
                st.ticket_placements.c.placement_mode,
                st.ticket_placements.c.external_reference,
                st.ticket_placements.c.receipt_artifact_id,
                st.ticket_placements.c.receipt_retrieval_id,
                st.ticket_placements.c.placed_at,
            )
            .select_from(
                st.audited_ticket_artifacts.outerjoin(
                    st.ticket_placements,
                    st.ticket_placements.c.ticket_artifact_id
                    == st.audited_ticket_artifacts.c.ticket_artifact_id,
                )
            )
            .where(
                st.audited_ticket_artifacts.c.ticket_artifact_id
                == ticket_artifact_id
            )
        )
        with self._engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        if row is None:
            return None
        return self._decode_json(row, ('payload_json',))

    def latest_confirmation(self, ticket_artifact_id: str) -> dict | None:
        statement = (
            select(
                st.ticket_confirmation_challenges.c.confirmation_id,
                st.ticket_confirmation_challenges.c.ticket_artifact_id,
                st.ticket_confirmation_challenges.c.issued_at,
                st.ticket_confirmation_challenges.c.expires_at,
                st.ticket_confirmation_challenges.c.consumed_at,
                st.ticket_confirmation_challenges.c.consumed_by_action_id,
            )
            .where(
                st.ticket_confirmation_challenges.c.ticket_artifact_id
                == ticket_artifact_id
            )
            .order_by(
                func.julianday(
                    st.ticket_confirmation_challenges.c.issued_at
                ).desc(),
                st.ticket_confirmation_challenges.c.confirmation_id.desc(),
            )
            .limit(1)
        )
        with self._engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        return dict(row) if row is not None else None

    def ticket_warning_adjudications(
        self, finding_ids: list[str]
    ) -> dict[str, dict]:
        if not finding_ids:
            return {}
        statement = (
            select(sw.adjudications)
            .where(
                sw.adjudications.c.subject_type == 'ticket_audit_finding',
                sw.adjudications.c.subject_id.in_(finding_ids),
            )
            .order_by(
                sw.adjudications.c.subject_id,
                func.julianday(sw.adjudications.c.created_at),
                sw.adjudications.c.adjudication_id,
            )
        )
        with self._engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        result: dict[str, dict] = {}
        for row in rows:
            result[row['subject_id']] = self._decode_json(
                row, ('evidence_rejected_json', 'alternative_json')
            )
        return result

    def lineage(
        self, object_type: str, object_id: str, *, as_of: str | None = None
    ) -> list[LineageTuple] | None:
        with self._engine.connect() as connection:
            edges = self._lineage_for_object(connection, object_type, object_id)
            if edges is None:
                return None
            action_statement = select(
                schema.actions.c.action_id, schema.actions.c.result_refs_json
            )
            if as_of is not None:
                action_statement = action_statement.where(
                    schema.actions.c.requested_at <= as_of
                )
            action_rows = connection.execute(action_statement).all()
        for action_id, result_refs_json in action_rows:
            if any(
                item.get('object_type') == object_type and item.get('object_id') == object_id
                for item in json.loads(result_refs_json)
            ):
                edges.append(
                    ('created_by_action', object_type, object_id, 'action', action_id)
                )
        return edges

    @staticmethod
    def _lineage_for_object(connection, object_type: str, object_id: str):
        if object_type == 'artifact_retrieval':
            artifact_id = connection.execute(
                select(schema.artifact_retrievals.c.artifact_id).where(
                    schema.artifact_retrievals.c.artifact_retrieval_id == object_id
                )
            ).scalar_one_or_none()
            if artifact_id is None:
                return None
            return [
                ('retrieval_of', object_type, object_id, 'source_artifact', artifact_id)
            ]
        if object_type == 'source_artifact':
            exists = connection.execute(
                select(schema.source_artifacts.c.artifact_id).where(
                    schema.source_artifacts.c.artifact_id == object_id
                )
            ).scalar_one_or_none()
            if exists is None:
                return None
            retrieval_ids = connection.execute(
                select(schema.artifact_retrievals.c.artifact_retrieval_id).where(
                    schema.artifact_retrievals.c.artifact_id == object_id
                )
            ).scalars()
            return [
                (
                    'artifact_has_retrieval',
                    object_type,
                    object_id,
                    'artifact_retrieval',
                    retrieval_id,
                )
                for retrieval_id in retrieval_ids
            ]
        if object_type == 'market_snapshot':
            row = connection.execute(
                select(sm.market_snapshots.c.match_id).where(
                    sm.market_snapshots.c.market_snapshot_id == object_id
                )
            ).first()
            if row is None:
                return None
            edges: list[LineageTuple] = [
                ('snapshot_for_match', object_type, object_id, 'match', row.match_id)
            ]
            quote_ids = connection.execute(
                select(sm.market_snapshot_quotes.c.quote_id).where(
                    sm.market_snapshot_quotes.c.market_snapshot_id == object_id
                )
            ).scalars()
            edges.extend(
                (
                    'snapshot_contains_quote',
                    object_type,
                    object_id,
                    'market_quote',
                    quote_id,
                )
                for quote_id in quote_ids
            )
            return edges
        if object_type in {'observation', 'claim'}:
            table = se.observations if object_type == 'observation' else se.claims
            id_column = (
                se.observations.c.observation_id
                if object_type == 'observation'
                else se.claims.c.claim_id
            )
            row = connection.execute(
                select(table.c.scope_match_id).where(id_column == object_id)
            ).first()
            if row is None:
                return None
            if row.scope_match_id is None:
                return []
            return [
                (
                    f'{object_type}_for_match',
                    object_type,
                    object_id,
                    'match',
                    row.scope_match_id,
                )
            ]
        if object_type == 'team':
            exists = connection.execute(
                select(si.teams.c.team_id).where(si.teams.c.team_id == object_id)
            ).scalar_one_or_none()
            if exists is None:
                return None
            identifiers = connection.execute(
                select(
                    si.external_identifiers.c.provider,
                    si.external_identifiers.c.external_id,
                ).where(
                    si.external_identifiers.c.entity_type == 'team',
                    si.external_identifiers.c.entity_id == object_id,
                )
            ).all()
            return [
                (
                    'team_has_external_id',
                    object_type,
                    object_id,
                    'external_identifier',
                    f'{provider}:{external_id}',
                )
                for provider, external_id in identifiers
            ]
        if object_type == 'forecast_revision':
            row = connection.execute(
                select(
                    sd.forecast_series.c.match_id,
                    sd.forecast_revisions.c.evidence_bundle_id,
                    sd.forecast_revisions.c.prior_snapshot_id,
                )
                .select_from(
                    sd.forecast_revisions.join(
                        sd.forecast_series,
                        sd.forecast_revisions.c.forecast_series_id
                        == sd.forecast_series.c.forecast_series_id,
                    )
                )
                .where(sd.forecast_revisions.c.forecast_revision_id == object_id)
            ).first()
            if row is None:
                return None
            edges: list[LineageTuple] = [
                ('forecast_for_match', object_type, object_id, 'match', row.match_id)
            ]
            if row.evidence_bundle_id:
                edges.append(
                    (
                        'forecast_uses_bundle',
                        object_type,
                        object_id,
                        'evidence_bundle',
                        row.evidence_bundle_id,
                    )
                )
            if row.prior_snapshot_id:
                edges.append(
                    (
                        'forecast_uses_snapshot',
                        object_type,
                        object_id,
                        'market_snapshot',
                        row.prior_snapshot_id,
                    )
                )
            return edges
        if object_type == 'match':
            exists = connection.execute(
                select(si.matches.c.match_id).where(si.matches.c.match_id == object_id)
            ).scalar_one_or_none()
            if exists is None:
                return None
            team_ids = connection.execute(
                select(si.team_appearances.c.team_id).where(
                    si.team_appearances.c.match_id == object_id
                )
            ).scalars()
            return [
                ('match_has_team', 'match', object_id, 'team', team_id)
                for team_id in team_ids
            ]
        if object_type == 'evidence_bundle':
            row = connection.execute(
                select(sd.evidence_bundles).where(
                    sd.evidence_bundles.c.evidence_bundle_id == object_id
                )
            ).mappings().first()
            if row is None:
                return None
            edges = [('bundle_for_match', object_type, object_id, 'match', row['match_id'])]
            if row['market_snapshot_id']:
                edges.append(
                    (
                        'bundle_uses_snapshot',
                        object_type,
                        object_id,
                        'market_snapshot',
                        row['market_snapshot_id'],
                    )
                )
            return edges
        if object_type == 'ticket':
            exists = connection.execute(
                select(sf.tickets.c.ticket_id).where(sf.tickets.c.ticket_id == object_id)
            ).scalar_one_or_none()
            if exists is None:
                return None
            legs = connection.execute(
                select(sf.bet_legs.c.forecast_revision_id).where(
                    sf.bet_legs.c.ticket_id == object_id
                )
            ).scalars()
            return [
                ('ticket_uses_forecast', 'ticket', object_id, 'forecast_revision', revision_id)
                for revision_id in legs
            ]
        if object_type == 'audited_ticket_artifact':
            row = connection.execute(
                select(
                    st.audited_ticket_artifacts.c.ticket_batch_revision_id,
                    st.audited_ticket_artifacts.c.source_artifact_id,
                    st.ticket_placements.c.ticket_placement_id,
                    st.ticket_placements.c.ticket_id,
                )
                .select_from(
                    st.audited_ticket_artifacts.outerjoin(
                        st.ticket_placements,
                        st.ticket_placements.c.ticket_artifact_id
                        == st.audited_ticket_artifacts.c.ticket_artifact_id,
                    )
                )
                .where(
                    st.audited_ticket_artifacts.c.ticket_artifact_id == object_id
                )
            ).first()
            if row is None:
                return None
            edges = [
                (
                    'ticket_artifact_for_batch_revision',
                    object_type,
                    object_id,
                    'ticket_batch_revision',
                    row.ticket_batch_revision_id,
                ),
                (
                    'ticket_artifact_stored_as_source',
                    object_type,
                    object_id,
                    'source_artifact',
                    row.source_artifact_id,
                ),
            ]
            if row.ticket_placement_id is not None:
                edges.extend(
                    (
                        (
                            'ticket_artifact_has_placement',
                            object_type,
                            object_id,
                            'ticket_placement',
                            row.ticket_placement_id,
                        ),
                        (
                            'ticket_artifact_placed_as_ticket',
                            object_type,
                            object_id,
                            'ticket',
                            row.ticket_id,
                        ),
                    )
                )
            return edges
        if object_type in {'settlement', 'ticket_settlement'}:
            row = connection.execute(
                select(sf.ticket_settlements.c.ticket_id).where(
                    sf.ticket_settlements.c.ticket_settlement_id == object_id
                )
            ).first()
            if row is None:
                return None
            return [('settlement_for_ticket', object_type, object_id, 'ticket', row.ticket_id)]
        workflow_specs = {
            'adjudication': (sw.adjudications, sw.adjudications.c.adjudication_id),
            'flag_instance': (sw.flag_instances, sw.flag_instances.c.flag_instance_id),
            'prediction': (sw.predictions, sw.predictions.c.prediction_id),
            'precedent_link': (sw.precedent_links, sw.precedent_links.c.precedent_link_id),
            'agent_proposal': (sw.agent_proposals, sw.agent_proposals.c.agent_proposal_id),
        }
        specification = workflow_specs.get(object_type)
        if specification is None:
            return None
        table, id_column = specification
        exists = connection.execute(select(id_column).where(id_column == object_id)).first()
        return [] if exists is not None else None

    @staticmethod
    def _decode_json(row, columns: Iterable[str]) -> dict:
        result = dict(row)
        for column in columns:
            result[column.removesuffix('_json')] = json.loads(result.pop(column))
        return result

    @classmethod
    def _ticket_batch_row(cls, row) -> dict:
        return cls._decode_json(
            row,
            ('input_legs_json', 'composition_json', 'audit_findings_json'),
        )
