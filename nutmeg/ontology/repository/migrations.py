"""Explicit, numbered schema migrations with drift detection.

Migrations are ordinary Python callables carrying a stable ``fingerprint``. The
runner records a SHA-256 checksum of ``version:name:fingerprint`` per applied
migration and refuses to run again if a previously applied migration's checksum
changed — a change to already-shipped DDL is a drift bug, not a silent upgrade.
Each migration's schema/data change and its ``schema_migrations`` row commit in
one transaction, so a partially applied migration cannot survive a crash.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Connection, Engine, delete, func, insert, inspect, select

from nutmeg.ontology.errors import MigrationDriftError
from nutmeg.ontology.identity.models import EntityType, TeamKind, mint_id
from nutmeg.ontology.repository import (
    schema,
    schema_context,
    schema_decision,
    schema_evidence,
    schema_finance,
    schema_identity,
    schema_market,
    schema_reliability,
    schema_scoreboard,
    schema_tickets,
    schema_workflow,
)


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    fingerprint: str
    apply: Callable[[Connection], None]

    @property
    def checksum(self) -> str:
        material = f'{self.version}:{self.name}:{self.fingerprint}'
        return hashlib.sha256(material.encode('utf-8')).hexdigest()


@dataclass(frozen=True, slots=True)
class MigrationReport:
    applied_versions: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class MigrationStatus:
    current_version: int
    applied_versions: tuple[int, ...]


def _canonical_json(document: dict[str, object]) -> str:
    return json.dumps(document, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def _apply_governance_kernel(connection: Connection) -> None:
    # Foreign-key order: policy_versions before actions/action_permissions.
    schema.policy_versions.create(connection)
    schema.actions.create(connection)
    schema.action_permissions.create(connection)

    now = datetime.now(UTC).isoformat()
    connection.execute(
        insert(schema.policy_versions).values(
            policy_version_id='governance-v1',
            policy_kind='governance',
            version=1,
            payload_json=_canonical_json({'name': 'kernel-default'}),
            status='active',
            effective_at=now,
            created_at=now,
        )
    )
    # Seed after all three tables exist so action_permissions FK resolves.
    permissions = (
        ('ingest_artifact', 'connector'),
        ('ingest_artifact', 'judge_operator'),
        ('change_policy', 'judge_operator'),
    )
    connection.execute(
        insert(schema.action_permissions),
        [
            {
                'policy_version_id': 'governance-v1',
                'action_type': action_type,
                'actor_role': actor_role,
            }
            for action_type, actor_role in permissions
        ],
    )


def _apply_evidence_kernel(connection: Connection) -> None:
    # Foreign-key order: source_runs + source_artifacts before artifact_retrievals.
    schema.source_runs.create(connection)
    schema.source_artifacts.create(connection)
    schema.artifact_retrievals.create(connection)


def _load_team_alias_seed() -> dict[tuple[str, str], set[str]]:
    """Curated `{chinese_alias: english_canonical}` files -> {(canonical, kind): aliases}."""
    root = Path(__file__).resolve().parents[2] / 'data'
    seed: dict[tuple[str, str], set[str]] = {}
    for filename, kind in (
        ('jczq_club_team_aliases.json', TeamKind.CLUB.value),
        ('jczq_national_team_aliases.json', TeamKind.NATIONAL.value),
    ):
        raw = json.loads((root / filename).read_text(encoding='utf-8'))
        for alias, canonical in raw.items():
            if alias == '_comment' or not isinstance(canonical, str):
                continue
            aliases = seed.setdefault((canonical, kind), set())
            aliases.add(alias.strip().casefold())
            aliases.add(canonical.strip().casefold())
    return seed


_IDENTITY_ACTION_PERMISSIONS = (
    ('upsert_provisional_entity', 'connector'),
    ('upsert_provisional_entity', 'deterministic_system'),
    ('link_external_identifier', 'connector'),
    ('link_external_identifier', 'deterministic_system'),
    ('propose_identity_link', 'connector'),
    ('propose_identity_link', 'ai_extractor'),
    ('merge_entity', 'judge_operator'),
    ('record_match', 'connector'),
    ('record_match', 'deterministic_system'),
)


def _apply_football_identity(connection: Connection) -> None:
    # Foreign-key order.
    for table in (
        schema_identity.competitions,
        schema_identity.competition_editions,
        schema_identity.teams,
        schema_identity.venues,
        schema_identity.matches,
        schema_identity.match_revisions,
        schema_identity.team_appearances,
        schema_identity.external_identifiers,
        schema_identity.entity_aliases,
        schema_identity.entity_merges,
    ):
        table.create(connection)

    now = datetime.now(UTC).isoformat()
    team_rows: list[dict[str, object]] = []
    alias_rows: list[dict[str, object]] = []
    for (canonical, kind), aliases in _load_team_alias_seed().items():
        team_id = mint_id(EntityType.TEAM)
        team_rows.append({
            'team_id': team_id, 'team_kind': kind, 'canonical_name': canonical,
            'country': None, 'resolution_status': 'provisional', 'created_at': now,
        })
        for alias in sorted(aliases):
            alias_rows.append({
                'entity_id': team_id, 'entity_type': EntityType.TEAM.value,
                'normalized_alias': alias, 'language': None, 'provider': None,
            })
    if team_rows:
        connection.execute(insert(schema_identity.teams), team_rows)
    if alias_rows:
        connection.execute(insert(schema_identity.entity_aliases), alias_rows)

    connection.execute(
        insert(schema.action_permissions),
        [
            {
                'policy_version_id': 'governance-v1',
                'action_type': action_type,
                'actor_role': actor_role,
            }
            for action_type, actor_role in _IDENTITY_ACTION_PERMISSIONS
        ],
    )


_CRS_SELECTIONS: list[tuple[str, str, str | None]] = [
    (f'sel-crs-{home}-{away}', f'{home}:{away}', None)
    for home in range(4)
    for away in range(4)
] + [('sel-crs-other', 'other', None)]

_MARKET_SEED: dict[str, dict[str, object]] = {
    'md-had': {
        'market_kind': 'had', 'settlement_scope': 'regular_time', 'ordered': 0, 'line_schema': None,
        'selections': [
            ('sel-had-home', 'home', None),
            ('sel-had-draw', 'draw', None),
            ('sel-had-away', 'away', None),
        ],
    },
    'md-hhad': {
        'market_kind': 'hhad', 'settlement_scope': 'regular_time', 'ordered': 0,
        'line_schema': 'integer_handicap',
        'selections': [
            ('sel-hhad-home', 'home', None),
            ('sel-hhad-draw', 'draw', None),
            ('sel-hhad-away', 'away', None),
        ],
    },
    'md-ttg': {
        'market_kind': 'ttg', 'settlement_scope': 'regular_time', 'ordered': 1, 'line_schema': None,
        'selections': [(f'sel-ttg-{n}', f'total_{n}', None) for n in range(8)],
    },
    'md-crs': {
        'market_kind': 'crs', 'settlement_scope': 'regular_time', 'ordered': 0, 'line_schema': None,
        'selections': _CRS_SELECTIONS,
    },
}

_MARKET_ACTION_PERMISSIONS = (
    ('record_market_quote', 'connector'),
    ('build_market_snapshot', 'deterministic_system'),
)


def _apply_market(connection: Connection) -> None:
    for table in (
        schema_market.market_definitions,
        schema_market.selection_definitions,
        schema_market.market_quotes,
        schema_market.market_snapshots,
        schema_market.market_snapshot_quotes,
    ):
        table.create(connection)

    for market_definition_id, spec in _MARKET_SEED.items():
        connection.execute(
            insert(schema_market.market_definitions).values(
                market_definition_id=market_definition_id,
                market_kind=spec['market_kind'],
                settlement_scope=spec['settlement_scope'],
                ordered=spec['ordered'],
                line_schema=spec['line_schema'],
                outcome_schema_version='1',
            )
        )
        connection.execute(
            insert(schema_market.selection_definitions),
            [
                {
                    'selection_id': selection_id,
                    'market_definition_id': market_definition_id,
                    'outcome_key': outcome_key,
                    'line': line,
                }
                for selection_id, outcome_key, line in spec['selections']
            ],
        )

    connection.execute(
        insert(schema.action_permissions),
        [
            {
                'policy_version_id': 'governance-v1',
                'action_type': action_type,
                'actor_role': actor_role,
            }
            for action_type, actor_role in _MARKET_ACTION_PERMISSIONS
        ],
    )


def _apply_context(connection: Connection) -> None:
    for table in (
        schema_context.persons,
        schema_context.role_assignments,
        schema_context.person_match_statuses,
        schema_context.lineup_entries,
    ):
        table.create(connection)


# Graded write-back (design §2.4): AI extractors write only provisional claims and
# can never record a verified fact or adjudicate one.
_EVIDENCE_ACTION_PERMISSIONS = (
    ('upsert_person', 'connector'),
    ('upsert_person', 'deterministic_system'),
    ('record_observation', 'connector'),
    ('record_observation', 'deterministic_system'),
    ('record_person_match_status', 'connector'),
    ('record_person_match_status', 'deterministic_system'),
    ('record_lineup_entry', 'connector'),
    ('record_lineup_entry', 'deterministic_system'),
    ('extract_claim', 'ai_extractor'),
    ('verify_claim', 'deterministic_system'),
    ('verify_claim', 'judge_operator'),
    ('dispute_claim', 'judge_operator'),
    ('retract_claim', 'judge_operator'),
)


def _apply_evidence(connection: Connection) -> None:
    for table in (
        schema_evidence.claims,
        schema_evidence.claim_status_events,
        schema_evidence.claim_evidence_spans,
        schema_evidence.observations,
        schema_evidence.observation_sources,
        schema_evidence.observation_claims,
    ):
        table.create(connection)

    connection.execute(
        insert(schema.action_permissions),
        [
            {
                'policy_version_id': 'governance-v1',
                'action_type': action_type,
                'actor_role': actor_role,
            }
            for action_type, actor_role in _EVIDENCE_ACTION_PERMISSIONS
        ],
    )


_DECISION_ACTION_PERMISSIONS = (
    ('open_decision_session', 'judge_operator'),
    ('open_decision_session', 'deterministic_system'),
    ('freeze_evidence_bundle', 'deterministic_system'),
    ('draft_forecast', 'ai_analyst'),
    ('draft_forecast', 'judge_operator'),
    ('commit_forecast', 'judge_operator'),
    ('revise_forecast', 'judge_operator'),
    ('withdraw_forecast', 'judge_operator'),
    ('propose_factor_status', 'ai_analyst'),
    ('propose_factor_status', 'judge_operator'),
    ('apply_factor_status', 'judge_operator'),
)


def _apply_decision(connection: Connection) -> None:
    for table in (
        schema_decision.decision_sessions,
        schema_decision.evidence_bundles,
        schema_decision.evidence_bundle_items,
        schema_decision.forecast_series,
        schema_decision.factor_families,
        schema_decision.factor_definitions,
        schema_decision.forecast_revisions,
        schema_decision.factor_applications,
        schema_decision.scenarios,
    ):
        table.create(connection)

    connection.execute(
        insert(schema.action_permissions),
        [
            {
                'policy_version_id': 'governance-v1',
                'action_type': action_type,
                'actor_role': actor_role,
            }
            for action_type, actor_role in _DECISION_ACTION_PERMISSIONS
        ],
    )


_FINANCE_ACTION_PERMISSIONS = (
    ('change_budget_policy', 'judge_operator'),
    ('propose_ticket', 'ai_analyst'),
    ('propose_ticket', 'judge_operator'),
    ('approve_ticket', 'judge_operator'),
    ('record_cash_transaction', 'deterministic_system'),
    ('record_cash_transaction', 'judge_operator'),
    ('record_outcome', 'deterministic_system'),
    ('correct_outcome', 'deterministic_system'),
    ('settle_ticket', 'deterministic_system'),
)


def _apply_finance(connection: Connection) -> None:
    for table in (
        schema_finance.cash_accounts,
        schema_finance.budget_policies,
        schema_finance.ticket_proposals,
        schema_finance.tickets,
        schema_finance.bet_legs,
        schema_finance.cash_transactions,
        schema_finance.match_outcomes,
        schema_finance.bet_leg_settlements,
        schema_finance.ticket_settlements,
    ):
        table.create(connection)

    connection.execute(
        insert(schema.action_permissions),
        [
            {
                'policy_version_id': 'governance-v1',
                'action_type': action_type,
                'actor_role': actor_role,
            }
            for action_type, actor_role in _FINANCE_ACTION_PERMISSIONS
        ],
    )


def _apply_finance_entry_odds(connection: Connection) -> None:
    """Add ``bet_legs.entry_odds`` (booking-time decimal odds — the settlement price).

    Fresh databases already get the column from migration 8's ``table.create`` (the
    Table definition carries it), so this ALTER is guarded by a PRAGMA check and only
    fires when upgrading a store created before this migration.
    """
    columns = {
        row[1] for row in connection.exec_driver_sql('PRAGMA table_info(bet_legs)').fetchall()
    }
    if 'entry_odds' not in columns:
        connection.exec_driver_sql('ALTER TABLE bet_legs ADD COLUMN entry_odds REAL')


_WORKFLOW_ACTION_PERMISSIONS = (
    ('record_adjudication', 'judge_operator'),
    ('record_flag_instance', 'judge_operator'),
    ('record_flag_instance', 'deterministic_system'),
    ('register_prediction', 'ai_analyst'),
    ('register_prediction', 'judge_operator'),
    ('link_precedent', 'judge_operator'),
    ('link_precedent', 'deterministic_system'),
    ('create_agent_proposal', 'ai_analyst'),
    ('create_agent_proposal', 'judge_operator'),
    ('resolve_agent_proposal', 'judge_operator'),
)


def _apply_product_workflow(connection: Connection) -> None:
    for table in (
        schema_workflow.adjudications,
        schema_workflow.flag_instances,
        schema_workflow.predictions,
        schema_workflow.precedent_links,
        schema_workflow.agent_proposals,
        schema_workflow.outbox_events,
    ):
        table.create(connection)

    connection.execute(
        insert(schema.action_permissions),
        [
            {
                'policy_version_id': 'governance-v1',
                'action_type': action_type,
                'actor_role': actor_role,
            }
            for action_type, actor_role in _WORKFLOW_ACTION_PERMISSIONS
        ],
    )


def _apply_m3_proposal_citations(connection: Connection) -> None:
    columns = {
        row[1]
        for row in connection.exec_driver_sql(
            'PRAGMA table_info(agent_proposals)'
        ).fetchall()
    }
    if 'information_cutoff_at' not in columns:
        connection.exec_driver_sql(
            'ALTER TABLE agent_proposals ADD COLUMN information_cutoff_at TEXT'
        )
    if 'operator_prompt' not in columns:
        connection.exec_driver_sql(
            'ALTER TABLE agent_proposals ADD COLUMN operator_prompt TEXT'
        )
    connection.execute(
        delete(schema.action_permissions).where(
            schema.action_permissions.c.policy_version_id == 'governance-v1',
            schema.action_permissions.c.action_type == 'create_agent_proposal',
            schema.action_permissions.c.actor_role == 'judge_operator',
        )
    )


_PROTECTED_TICKET_PERMISSIONS = (
    ("create_ticket_batch", "judge_operator"),
    ("remove_ticket_leg", "judge_operator"),
    ("approve_ticket_batch", "judge_operator"),
    ("issue_ticket_confirmation", "judge_operator"),
    ("confirm_ticket_placement", "judge_operator"),
)


def _apply_protected_tickets(connection: Connection) -> None:
    for table in (
        schema_tickets.ticket_batch_revisions,
        schema_tickets.audited_ticket_artifacts,
        schema_tickets.ticket_confirmation_challenges,
        schema_tickets.ticket_placements,
    ):
        table.create(connection)
    connection.execute(
        insert(schema.action_permissions),
        [
            {
                "policy_version_id": "governance-v1",
                "action_type": action_type,
                "actor_role": actor_role,
            }
            for action_type, actor_role in _PROTECTED_TICKET_PERMISSIONS
        ],
    )


_SCOREBOARD_PERMISSIONS = (
    ("record_scoreboard_observation", "judge_operator"),
    ("approve_scoreboard_cutover", "judge_operator"),
    ("record_scoreboard_shadow_review", "deterministic_system"),
    ("record_scoreboard_export", "deterministic_system"),
)


def _apply_scoreboard_authority(connection: Connection) -> None:
    for table in (
        schema_scoreboard.scoreboard_observations,
        schema_scoreboard.scoreboard_shadow_reviews,
        schema_scoreboard.scoreboard_authority,
    ):
        table.create(connection)
    connection.execute(
        insert(schema_scoreboard.scoreboard_authority).values(
            authority_id="primary",
            state="legacy",
            projection_version=None,
            source_high_watermark=None,
            legacy_sha256=None,
            shadow_review_id=None,
            compatibility_export_sha256=None,
            approved_at=None,
            approved_by_action_id=None,
            version=1,
        )
    )
    connection.execute(
        insert(schema.action_permissions),
        [
            {
                "policy_version_id": "governance-v1",
                "action_type": action_type,
                "actor_role": actor_role,
            }
            for action_type, actor_role in _SCOREBOARD_PERMISSIONS
        ],
    )


_RELIABILITY_PERMISSIONS = (
    ("record_reliability_evidence", "deterministic_system"),
    ("record_reliability_evidence", "judge_operator"),
    ("approve_release", "judge_operator"),
)


def _apply_reliability_governance(connection: Connection) -> None:
    for table in (
        schema_reliability.reliability_evidence,
        schema_reliability.release_approvals,
    ):
        table.create(connection)
    connection.execute(
        insert(schema.action_permissions),
        [
            {
                "policy_version_id": "governance-v1",
                "action_type": action_type,
                "actor_role": actor_role,
            }
            for action_type, actor_role in _RELIABILITY_PERMISSIONS
        ],
    )


_PREDICTION_GRADE_PERMISSIONS = (
    ('grade_prediction', 'judge_operator'),
)


def _apply_prediction_subjects(connection: Connection) -> None:
    """Widen predictions to subject scope (issue-level rx predictions) + grade permission.

    Fresh databases already get ``subject_type``/``subject_id`` and the nullable
    ``match_id`` from migration 10's ``table.create`` (the Table definition carries
    them), so the rebuild is guarded by a PRAGMA check and only fires when upgrading
    a store created before this migration. SQLite cannot relax NOT NULL in place, so
    the upgrade path rebuilds the table (12-step simplified; pre-v15 production
    tables are empty or tiny). ``RENAME TO`` keeps the old table's indexes under
    their original names, so the stale index is dropped before ``create`` re-makes it.
    """
    cols = {row[1] for row in connection.exec_driver_sql('PRAGMA table_info(predictions)')}
    if 'subject_type' not in cols:
        connection.exec_driver_sql('ALTER TABLE predictions RENAME TO predictions_v14')
        connection.exec_driver_sql('DROP INDEX IF EXISTS ix_predictions_match_id')
        schema_workflow.predictions.create(connection)
        connection.exec_driver_sql(
            'INSERT INTO predictions (prediction_id, match_id, subject_type, subject_id,'
            ' claim, falsifier, status, outcome, registered_at, settled_at)'
            " SELECT prediction_id, match_id, 'match', match_id,"
            ' claim, falsifier, status, outcome, registered_at, settled_at'
            ' FROM predictions_v14'
        )
        connection.exec_driver_sql('DROP TABLE predictions_v14')
    # Permission insert sits outside the rebuild guard (fresh stores skip the rebuild
    # but still need the grant) behind its own COUNT guard so it lands exactly once.
    granted = connection.exec_driver_sql(
        "SELECT COUNT(*) FROM action_permissions WHERE action_type='grade_prediction'"
    ).scalar_one()
    if granted == 0:
        connection.execute(
            insert(schema.action_permissions),
            [
                {
                    'policy_version_id': 'governance-v1',
                    'action_type': action_type,
                    'actor_role': actor_role,
                }
                for action_type, actor_role in _PREDICTION_GRADE_PERMISSIONS
            ],
        )


def _apply_ticket_shadows(connection: Connection) -> None:
    schema_tickets.ticket_shadow_records.create(connection, checkfirst=True)
    granted = connection.execute(
        select(func.count())
        .select_from(schema.action_permissions)
        .where(
            schema.action_permissions.c.policy_version_id == "governance-v1",
            schema.action_permissions.c.action_type == "mark_ticket_shadow",
            schema.action_permissions.c.actor_role == "deterministic_system",
        )
    ).scalar_one()
    if granted == 0:
        connection.execute(
            insert(schema.action_permissions).values(
                policy_version_id="governance-v1",
                action_type="mark_ticket_shadow",
                actor_role="deterministic_system",
            )
        )


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=1,
        name='governance_kernel',
        fingerprint='policy_versions+actions+action_permissions+seed(governance-v1)',
        apply=_apply_governance_kernel,
    ),
    Migration(
        version=2,
        name='evidence_kernel',
        fingerprint='source_runs+source_artifacts+artifact_retrievals',
        apply=_apply_evidence_kernel,
    ),
    Migration(
        version=3,
        name='football_identity',
        fingerprint='competitions..entity_merges+team_alias_seed+identity_permissions',
        apply=_apply_football_identity,
    ),
    Migration(
        version=4,
        name='market_definitions',
        fingerprint='market_defs+selection_defs(had,hhad,ttg,crs)+market_permissions',
        apply=_apply_market,
    ),
    Migration(
        version=5,
        name='football_context',
        fingerprint='persons+role_assignments+person_match_statuses+lineup_entries',
        apply=_apply_context,
    ),
    Migration(
        version=6,
        name='football_evidence',
        fingerprint='claims..observation_claims+evidence_permissions',
        apply=_apply_evidence,
    ),
    Migration(
        version=7,
        name='decision',
        fingerprint='decision_sessions..scenarios+decision_permissions',
        apply=_apply_decision,
    ),
    Migration(
        version=8,
        name='finance',
        fingerprint='budget_policies..ticket_settlements+finance_permissions',
        apply=_apply_finance,
    ),
    Migration(
        version=9,
        name='finance_entry_odds',
        fingerprint='bet_legs+entry_odds(guarded_alter)',
        apply=_apply_finance_entry_odds,
    ),
    Migration(
        version=10,
        name='product_workflow',
        fingerprint=(
            'adjudications+flags+predictions+precedents+agent_proposals+'
            'outbox+workflow_permissions'
        ),
        apply=_apply_product_workflow,
    ),
    Migration(
        version=11,
        name='m3_proposal_citations',
        fingerprint='agent_proposals+cutoff+prompt+ai_only_create',
        apply=_apply_m3_proposal_citations,
    ),
    Migration(
        version=12,
        name="protected_ticket_workbench",
        fingerprint=(
            "ticket_batch_revisions+audited_ticket_artifacts+"
            "ticket_confirmation_challenges+ticket_placements+judge_only_permissions"
        ),
        apply=_apply_protected_tickets,
    ),
    Migration(
        version=13,
        name="scoreboard_authority",
        fingerprint=(
            "scoreboard_observations+scoreboard_shadow_reviews+"
            "scoreboard_authority+role_separated_permissions"
        ),
        apply=_apply_scoreboard_authority,
    ),
    Migration(
        version=14,
        name="reliability_governance",
        fingerprint=(
            "reliability_evidence+release_approvals+role_separated_permissions"
        ),
        apply=_apply_reliability_governance,
    ),
    Migration(
        version=15,
        name='prediction_subjects',
        fingerprint='predictions+subject_type+subject_id+match_nullable+grade_permission',
        apply=_apply_prediction_subjects,
    ),
    Migration(
        version=16,
        name="ticket_shadows",
        fingerprint="ticket_shadow_records+deterministic_system_permission",
        apply=_apply_ticket_shadows,
    ),
)


def _validate_sequence(migrations: tuple[Migration, ...]) -> None:
    versions = [migration.version for migration in migrations]
    if versions != list(range(1, len(versions) + 1)):
        raise MigrationDriftError(
            f'migration versions must be a gap-free ascending sequence from 1, got {versions}'
        )


def _applied_checksums(connection: Connection) -> dict[int, str]:
    rows = connection.execute(
        select(schema.schema_migrations.c.version, schema.schema_migrations.c.checksum)
    ).all()
    return {row.version: row.checksum for row in rows}


def run_migrations(
    engine: Engine,
    migrations: tuple[Migration, ...] = MIGRATIONS,
) -> MigrationReport:
    _validate_sequence(migrations)
    applied: list[int] = []
    with engine.begin() as connection:
        schema.schema_migrations.create(connection, checkfirst=True)
        existing = _applied_checksums(connection)
        for migration in migrations:
            recorded = existing.get(migration.version)
            if recorded is not None:
                if recorded != migration.checksum:
                    raise MigrationDriftError(
                        f'migration {migration.version} checksum drift'
                    )
                continue
            migration.apply(connection)
            connection.execute(
                insert(schema.schema_migrations).values(
                    version=migration.version,
                    name=migration.name,
                    checksum=migration.checksum,
                    applied_at=datetime.now(UTC).isoformat(),
                )
            )
            applied.append(migration.version)
    return MigrationReport(applied_versions=tuple(applied))


def migration_status(engine: Engine) -> MigrationStatus:
    if not inspect(engine).has_table('schema_migrations'):
        return MigrationStatus(current_version=0, applied_versions=())
    with engine.connect() as connection:
        versions = tuple(
            sorted(connection.execute(select(schema.schema_migrations.c.version)).scalars().all())
        )
    current = versions[-1] if versions else 0
    return MigrationStatus(current_version=current, applied_versions=versions)
