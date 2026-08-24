"""Read-only temporal queries over Ontology Kernel v2."""
from __future__ import annotations

import json
from collections.abc import Iterable

from sqlalchemy import Engine, and_, func, or_, select

from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository import schema_decision as sd
from nutmeg.ontology.repository import schema_evidence as se
from nutmeg.ontology.repository import schema_finance as sf
from nutmeg.ontology.repository import schema_identity as si
from nutmeg.ontology.repository import schema_market as sm
from nutmeg.ontology.repository import schema_workflow as sw
from nutmeg.ontology.repository.outbox import OutboxEventRow, OutboxRepository

LineageTuple = tuple[str, str, str, str, str]


class ProductReadRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

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
                home_team.c.resolution_status.label('home_resolution_status'),
                away_team.c.resolution_status.label('away_resolution_status'),
                si.competitions.c.name.label('competition'),
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
                        sm.market_snapshots.c.as_of <= as_of,
                    )
                    .order_by(sm.market_snapshots.c.as_of.desc())
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
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(se.claims)
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
        return [self._decode_json(row, ('value_json',)) for row in rows]

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
        return [self._decode_json(row, ('value_json', 'quality_json')) for row in rows]

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

    def lineage(self, object_type: str, object_id: str) -> list[LineageTuple] | None:
        with self._engine.connect() as connection:
            edges = self._lineage_for_object(connection, object_type, object_id)
            if edges is None:
                return None
            action_rows = connection.execute(
                select(schema.actions.c.action_id, schema.actions.c.result_refs_json)
            ).all()
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
